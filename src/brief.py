import json
import re
from pathlib import Path

import sqlite3
from agent import client, MODEL, DB,validate_citations
from retrieval import search_memory

ROOT = Path(__file__).resolve().parent.parent
ITEMS_FILE = ROOT / "data" / "brief_items.json"
BRIEF_FILE = ROOT / "data" / "brief.txt"

TEAM = "TS3012"
# Meeting d is the final meeting the brief prepares for, so it is excluded.
MEETINGS = ["TS3012a", "TS3012b", "TS3012c"]

TOPICS = {
    "decisions": "decided agreed going with settled final choose go for",
    "changes": "change changed instead switch drop dropped replace rather than",
    "actions": "will need should action look into check find out next meeting",
    "disagreements": "disagree not sure problem worried expensive difficult",
}

CITE = re.compile(r'\[(TS3012[abc]):\s*"([^"]+)"\]')


def call_model(prompt, max_tokens):
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You write meeting briefs from cited evidence. Never invent facts or quotes."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_completion_tokens=max_tokens,
    )
    text = response.choices[0].message.content
    if not text or not text.strip():
        raise ValueError(f"Empty response, finish_reason={response.choices[0].finish_reason}")
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()).strip()


def gather(meeting_id):
    """Code step: pull relevant turns for each topic, de-duplicate, put in time order."""
    seen = {}
    for words in TOPICS.values():
        for row in search_memory(words, limit=10, team=TEAM, meeting_id=meeting_id):
            seen[row["id"]] = row
    return sorted(seen.values(), key=lambda r: r["turn_idx"])


def extract_items(meeting_id, turns):
    """Model step 1: list items from one meeting. Code then verifies every quote."""
    evidence = "\n".join(
        f"[turn {t['turn_idx']}] Speaker {t['speaker']} at {t['start_time']}: {t['text'][:500]}"
        for t in turns
    )
    prompt = f"""
You are reading selected turns from meeting {meeting_id} of a team designing a TV remote.
Extract items of these types:
- decision: something the team decided or agreed
- change: an earlier idea or decision that was replaced or dropped
- action: something a person said they would do, or that still needs doing
- disagreement: people holding conflicting views, or a problem left unresolved

EVIDENCE:
{evidence}

Rules:
1. Use ONLY the evidence above. Do not invent facts, names or reasons.
2. "owner" is the speaker letter responsible, only if the evidence says so, otherwise "unclear".
3. Each item needs a quote of at least six consecutive words copied exactly from ONE turn above.
4. Return at most 12 items. Skip small talk.

Return ONLY valid JSON:
{{"items": [{{"type": "decision", "text": "one short sentence", "owner": "unclear", "quote": "exact words"}}]}}
"""
    data = json.loads(call_model(prompt, 3000))
    verified = []
    for item in data.get("items", []):
        check = validate_citations([{"meeting_id": meeting_id, "quote": item.get("quote", "")}])[0]
        if check["valid"]:
            verified.append({
                "meeting_id": meeting_id,
                "type": item.get("type", ""),
                "text": item.get("text", ""),
                "owner": item.get("owner", "unclear"),
                "said_by": check["speaker"],   # from the database, not the model
                "quote": item["quote"],
            })
    print(f"{meeting_id}: kept {len(verified)} of {len(data.get('items', []))} items")
    return verified


def write_brief(items):
    """Model step 2: write the brief from verified items only."""
    lines = "\n".join(
        f'{i + 1}. [{it["meeting_id"]}] ({it["type"]}, said by {it["said_by"]}, owner {it["owner"]}) '
        f'{it["text"]} | quote: "{it["quote"]}"'
        for i, it in enumerate(items)
    )
    prompt = f"""
Write the brief Team TS3012 should read before their FINAL meeting.
Use ONLY the verified items below, listed in meeting order (a, then b, then c).

ITEMS:
{lines}

Format: four markdown headings in this order:
## Decided
## Changed along the way
## Open actions and owners
## Open disagreements

Rules:
1. Every bullet is one sentence and ends with its citation in exactly this form:
   [TS3012b: "exact quote"]  (quote copied character for character from an item).
2. A bullet may only state what its quote says. The item text is a hint and may
   contain details the quote does not support: leave those details out.
3. Do not turn a statistic, a question, a preference or a suggestion by one person
   into a decision. A decision needs the team to agree or choose.
4. Changed means an earlier choice was replaced or dropped. Say what it was and what
   it became, and cite the quote that shows the change. Do not list ideas that
   were never settled.
5. Mention an owner only under Open actions, and only if the item gives one;
   otherwise write "owner unclear". Elsewhere write nothing about owners.
6. Skip small talk and logistics (for example when the next meeting starts).
7. An action is open unless a later item shows it was done.
8. If a section has nothing supported, write: Nothing found in the evidence.
9. Add nothing that is not in the items.
"""
    return call_model(prompt, 4000)


def verify_brief(brief):
    """Code step: drop any bullet without a citation, or with one that fails the check."""
    kept, dropped = [], 0
    for line in brief.splitlines():
        if line.strip().startswith(("-", "*")):
            cites = [{"meeting_id": m, "quote": q} for m, q in CITE.findall(line)]
            ok = bool(cites) and all(c["valid"] for c in validate_citations(cites))
            if not ok:
                dropped += 1
                continue
        kept.append(line)
    return "\n".join(kept), dropped

def context_for(meeting_id, quote):
    """Code step: the cited turn plus one turn before and two after, from the database."""
    check = validate_citations([{"meeting_id": meeting_id, "quote": quote}])[0]
    if not check["valid"]:
        return None
    turn_id = check["turn_id"]
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            "SELECT id, speaker, text FROM turns "
            "WHERE meeting_id = ? AND id BETWEEN ? AND ? ORDER BY id",
            (meeting_id, turn_id - 1, turn_id + 2),
        ).fetchall()
    out = []
    for tid, sp, text in rows:
        mark = ">>" if tid == turn_id else "  "
        limit = 800 if tid == turn_id else 300
        out.append(f"{mark} Speaker {sp}: {text[:limit]}")
    return "\n".join(out)


def check_support(brief):
    """Model step 3: a strict judge checks each bullet against its cited turn and the
    turns next to it. Code fetches that context and drops every bullet the judge rejects."""
    lines = brief.splitlines()
    numbered = []  # (line index, claim, context)
    for i, line in enumerate(lines):
        if not line.strip().startswith(("-", "*")):
            continue
        cites = CITE.findall(line)
        if not cites:
            continue
        ctx = context_for(*cites[0])
        if ctx is None:
            continue
        numbered.append((i, CITE.sub("", line).strip(" -*"), ctx))

    rejected = {}
    BATCH = 8
    for start in range(0, len(numbered), BATCH):
        chunk = numbered[start:start + BATCH]
        blocks = "\n\n".join(
            f"CLAIM {n}: {claim}\nTRANSCRIPT (>> marks the cited turn):\n{ctx}"
            for n, (_, claim, ctx) in enumerate(chunk, start=1)
        )
        prompt = f"""
You are a strict fact-checker for a meeting brief. Each claim below comes with the
transcript lines around the quote it cites.

A claim is SUPPORTED only if the transcript shown directly says it. Mark it NOT supported if:
1. It adds a detail the transcript does not contain (a name, a unit, a reason, a person).
2. It presents a statistic, a question, a preference or one person's suggestion
   as a team decision or a change.
3. It says two people disagree, but only one side appears in the transcript.
4. The talk is off topic, not about designing the remote control.
5. It names an owner other than the speaker, without the transcript saying so.
When unsure, mark NOT supported.

{blocks}

Return ONLY valid JSON, one verdict per claim:
{{"verdicts": [{{"n": 1, "supported": true, "reason": "short reason"}}]}}
"""
        data = json.loads(call_model(prompt, 3000))
        for v in data.get("verdicts", []):
            n = int(v.get("n", 0))
            if 1 <= n <= len(chunk) and not v.get("supported"):
                rejected[start + n - 1] = v.get("reason", "")

    drop_lines = set()
    for k, reason in rejected.items():
        drop_lines.add(numbered[k][0])
        print(f"  dropped: {numbered[k][1]}\n    why: {reason}")
    kept = [line for i, line in enumerate(lines) if i not in drop_lines]

    # Put a note under any heading that has no bullets left.
    final = []
    for j, line in enumerate(kept):
        final.append(line)
        if line.startswith("## "):
            nxt = next((l for l in kept[j + 1:] if l.strip()), "")
            if not nxt.strip().startswith(("-", "*", "Nothing found")):
                final.append("Nothing found in the evidence.")
    return "\n".join(final), len(drop_lines)


if __name__ == "__main__":
    if ITEMS_FILE.exists():
        items = json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
        print(f"Loaded {len(items)} saved items (delete {ITEMS_FILE.name} to redo step 1)")
    else:
        items = []
        for meeting_id in MEETINGS:
            turns = gather(meeting_id)
            print(f"{meeting_id}: {len(turns)} turns retrieved")
            items.extend(extract_items(meeting_id, turns))
        ITEMS_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

    raw = write_brief(items)
    brief, dropped = verify_brief(raw)
    print("Support check (a judge compares each bullet with the real turns):")
    brief, unsupported = check_support(brief)
    BRIEF_FILE.write_text(brief, encoding="utf-8")

    print("\n" + brief)
    print(f"\nBullets dropped for failing the citation check: {dropped}")
    print(f"Bullets dropped by the support check: {unsupported}")
    print(f"Saved to: {BRIEF_FILE}")