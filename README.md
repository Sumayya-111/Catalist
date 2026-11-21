# Meeting Memory Agent

An agent that answers questions about team meetings and backs every answer
with exact quotes from the transcripts. It also writes a pre-meeting brief for
Team TS3012. Built for the Catalist Media Agentic AI Intern build test.

**Data:** 138 AMI meeting transcripts, 35 teams (3 to 4 meetings each),
48,148 speaker turns, in `data/transcripts/`.

## How it works

1. **Ingest (code):** `build_memory.py` splits every transcript into speaker
   turns and stores them in SQLite (`storage/memory.db`) with meeting ID, team,
   speaker, time and text, plus an FTS5 keyword index with Porter stemming
   ("decide" matches "decided").
2. **Retrieve (code):** `retrieval.py` and `agent.py` search each meeting of the
   team separately, so later meetings are not crowded out. The question becomes
   a keyword query (question-shaped words and single letters removed; LCD, TV
   and DVD are also searched in spelled-out form, because the index splits
   "L_C_D_" into letters). A broad OR query and a strict AND query are merged
   with reciprocal rank fusion. The top 8 turns per meeting are kept, up to 2
   short neighbouring turns on each side are added (so replies like "No."
   come along), and the evidence goes to the model in meeting and time order.
3. **Answer (model):** a Groq model (`openai/gpt-oss-120b`) writes a 1 to 3
   sentence answer with 1 to 3 quotes. The prompt tells it to separate
   suggestions from decisions, use time order, and say when something is not
   established.
4. **Verify (code):** every quote must be at least 6 words (my own safeguard;
   the brief only asks for exact words) and appear exactly, ignoring case and
   spacing, inside one speaker turn of the cited meeting. If a quote fails, the
   model is told which one and gets one retry.
5. **Export (code):** `export_answers.py` re-checks every quote against the
   database, leaves out any that fail, and writes `answers.json` with the brief.
6. **Brief (`brief.py`):** for TS3012 it uses meetings a to c only (d is the
   meeting the brief prepares for). Code pulls relevant turns per meeting; the
   model lists decisions, changes, actions and disagreements; code drops items
   whose quote does not verify; the model writes the brief from the verified
   items; code drops any bullet without a valid citation; a model judge then
   drops bullets the cited turns do not support.

**Model vs code:** the model only reads evidence and writes language. Storage,
search, ordering, quote checking and the final file are code.

**Why keyword search and not embeddings:** the corpus is small (7.7 MB), answers
need exact quotes, and FTS5 needs no extra service or cost and is easy to
explain. The price is that it matches words, not meaning (see limits).

## Setup (Windows PowerShell)

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and put in your own `GROQ_API_KEY`.
`storage/memory.db` is included. To rebuild it from the transcripts (no API
key needed): `python src\build_memory.py`

## Run

```powershell
python src\agent.py          # answers the 25 questions, saves data\test_results.json
python src\export_answers.py # writes answers.json with the brief (no API calls)
python src\ask.py TS3006 "Who suggested dropping speech recognition?"   # one live question
python src\run_eval.py       # my own 10 test questions (evaluations\)
python src\brief.py          # TS3012 brief (reuses data\brief_items.json if present)
```

`agent.py` saves after every question and skips ones already done, so it can be
stopped and resumed. `export_answers.py`, `ask.py` and `run_eval.py` import
`agent.py`, so a `.env` file must exist. `ask.py` needs a team code such as
`TS3006`.

## Files

- `src/`: `build_memory.py`, `retrieval.py`, `agent.py`, `brief.py`,
  `export_answers.py`, `ask.py`, `run_eval.py`, `audit_results.py`
- `data/questions.json`: the 25 questions (unchanged)
- `data/test_results.json`: raw agent output with citation checks
- `data/brief.txt`, `data/brief_items.json`: the TS3012 brief and its items
- `evaluations/`: my 10 questions and the agent's results
- `answers.json`: the submission file (25 answers and the brief)

## Results and honest limits

- **Which version made `answers.json`:** the first version of the pipeline
  (OR search, results in relevance order, no stemming, about 32 turns per
  question, plus the verify-and-retry step). The code in this repo is a later
  version. I ran out of Groq's daily token quota before I could re-run all 25
  with it, so running `agent.py` again will give different answers.
- **Citations:** the first run had 49 of 56 quotes valid. After adding
  verify-and-retry and re-running the 7 flagged questions, 55 of 56 pass. The
  one that fails (Q03, 5 words) is left out of `answers.json`. No hand edits.
- **A valid quote is not a correct answer.** The checker proves the words exist,
  not that they support the claim.
- **My own 10 questions** (teams the company did not use): the first version
  scored 1 right, 5 partly right, 4 wrong. An intermediate version (stemming,
  LCD fix, neighbouring turns) scored 5 right, 4 partly, 1 wrong. I tuned on
  those questions, so that is optimistic, and the current code has not been
  scored.
- **I have not measured accuracy on the 25** (the answers are held back).
  Reading them myself, many multi-part answers are only partly right.
- **Three wrong answers in `answers.json`** (my diagnosis, not fully verified):
  - **Q03** names C as first to propose replacing the titanium; B proposed it
    first (turn 43637). In the first version, turns reached the model ordered
    by relevance, not time.
  - **Q15** says speech recognition was removed. The transcript shows the LCD
    screen was removed and the limit was 12.5. The fix was spread across very
    short turns that single-turn search handles badly, and the model guessed.
  - **Q08** says no health complaint was mentioned. The transcript says
    "repetitive strain injury", and keyword search cannot connect that to
    "health complaint".
- **Other limits:** each question now sends about 5,000 to 7,500 tokens, so on
  Groq's free tier (8,000 tokens per minute, 200,000 per day) expect rate-limit
  errors and wait about a minute between questions. The main call uses
  `max_completion_tokens=1500`; a reasoning model can run out of room and return
  an empty or cut-off reply (this happened for a few questions), and raising it
  could push requests over the per-minute cap. A live question needs a team
  code. Answers change between runs even at temperature 0.1. The 6-word rule
  rejects short but real quotes.