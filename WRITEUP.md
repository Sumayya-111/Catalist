# Write-up: Meeting Memory Agent

## Architecture
Transcripts become speaker turns in SQLite (138 meetings, 48,148 turns, 7.7 MB)
with an FTS5 keyword index. A question plus a team code triggers per-meeting
search (BM25 keyword query, top 8 turns per meeting plus short following turns,
ordered by meeting and time). A Groq model (`openai/gpt-oss-120b`) writes a 1 to
3 sentence answer with quotes. Code verifies every quote against the database
and writes `answers.json`. The TS3012 brief is built in steps from meetings a to
c only.

## Model vs code
- **Code, never an LLM:** ingestion and turn splitting, indexing, search and
  ranking, evidence ordering, quote verification, the retry decision, export.
  These must be repeatable, and code cannot invent a quote.
- **Model:** reading evidence and writing sentences; in the brief, also
  extracting items and judging whether a bullet is supported.
- **Why:** the model is the part that fails (it tidied quotes, added details and
  misread replies), so code checks it at every step. The model judge in the
  brief lowered errors but did not remove them.
- **Keyword search over embeddings:** small corpus, exact quotes required, no
  extra infrastructure, easy to explain. I accepted its weakness and measured it.

## Memory over time: how the agent knows what is current
Each meeting is searched separately, so a decision in meeting c is not buried
by meeting a. Evidence reaches the model in meeting and time order and the
prompt asks it to compare meetings chronologically and find earlier decisions
and later changes; the brief uses the rule "later meetings override earlier
ones". There is no explicit record of which decision replaced which; the model
infers it from order. That is the main gap: Q03 (titanium) and my test question
M01 (kinetic power) show suggestions and rejections being confused. People
referring back to things without naming them is not handled.

## Tools used and where they broke
- **FTS5/BM25:** the index splits "L_C_D_" into letters, so "LCD" matched 0
  turns and "l c d" matched 711; single letters in questions ("meeting c")
  matched every LCD turn. Short decisive turns ("No.", "stick to plastic")
  rarely share words with the question. Fixes: spelled-out search, dropping
  single letters, stemming, neighbouring turns. Answer-bearing turns reaching
  the model went from 0 of 8 to 4 of 8.
- **The model:** it tidied quotes (7 of 56 failed on the first run), fixed by
  verify-and-retry. As a reasoning model it spent its token budget thinking and
  sometimes returned empty or cut-off JSON.
- **Groq free tier:** 8,000 tokens per minute and 200,000 per day. It stopped my
  re-runs of all 25 answers, so `answers.json` comes from the first version of
  the pipeline.
- **AI coding assistants** helped write the code; I ran and checked each step.
  One late rewrite (rank fusion, wider neighbour window, stricter prompt) made
  results worse: more text sent, fewer answer-bearing turns found, one request
  over the token cap. I measured it with a retrieval check and reverted it.

## Proof: my own questions and failures
I wrote 10 questions on teams the company did not use (ES2012, IS1004, TS3008)
and checked the answers in the transcripts. First version: 1 right, 5 partly,
4 wrong. After the retrieval fixes: 5 right, 4 partly, 1 wrong (tuned on those
questions, so optimistic). Accuracy on the company's 25 is unknown: 55 of 56
quotes verify, but a valid quote can support a wrong claim.

Three wrong answers in `answers.json`:
- **Q03:** names C as first to propose replacing titanium; B did (turn 43637).
  Cause: turns reached the model by relevance, not time.
- **Q15:** says speech recognition was removed; the LCD was, and the limit was
  12.5. Cause: the fix sat in very short turns that search missed, and the model
  guessed instead of saying it did not know.
- **Q08:** says no health complaint came up; the team discussed "repetitive
  strain injury". Cause: word matching cannot link it to "health complaint".

## Scale and cost
Ingestion is plain code: 3.2 seconds for 138 meetings on my laptop, so about 23
seconds for 1,000 and about 4 minutes for 10,000, at $0 in model fees; the
database would be about 56 MB per 1,000 meetings (extrapolated from 7.7 MB).
Per-question cost does not grow with the corpus (search is filtered by team and
the model sees one team's top turns, roughly 3,000 to 6,000 tokens). I did not
measure dollar cost per question.

## What production would need
- Append-only ingestion (mine rebuilds everything) and a store that handles
  concurrent writes.
- Retrieval that finds meaning as well as words (embeddings or model query
  rewriting next to BM25), plus a re-ranking step.
- An explicit decision log: extract each decision once, link it to the one it
  replaces, and answer "what is current" from that log.
- Checking that a quote supports its claim, not only that it exists, and
  answering "not enough evidence" more readily than guessing.
- A scored question set so every retrieval change is measured, which I could
  not finish at the end.
- Rate-limit handling with backoff and queues, caching, monitoring, and access
  control, since meeting transcripts are sensitive.
- Questions without a team code need a routing step.