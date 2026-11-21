import json
import re
from pathlib import Path

from agent import validate_citations

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "test_results.json"
OUTPUT = ROOT / "answers.json"

with open(SOURCE, encoding="utf-8") as f:
    results = json.load(f)

BRIEF_FILE = ROOT / "data" / "brief.txt"
brief = BRIEF_FILE.read_text(encoding="utf-8") if BRIEF_FILE.exists() else ""
if not brief:
    print("WARNING: data/brief.txt not found. Run python src\\brief.py first.")

# Re-check every quote in the brief against the database.
brief_cites = re.findall(r'\[(TS3012[abc]):\s*"([^"]+)"\]', brief)
brief_checked = validate_citations(
    [{"meeting_id": m, "quote": q} for m, q in brief_cites]
)
print(f"Brief citations verified: {sum(c['valid'] for c in brief_checked)} of {len(brief_checked)}")

answers = []
total_kept = 0
total_dropped = 0

for item in sorted(results, key=lambda r: r["question_id"]):
    original = [
        {"meeting_id": c["meeting_id"], "quote": c["quote"]}
        for c in item.get("citations", [])
    ]

    # Re-check every quote against the database, not the saved flags.
    checked = validate_citations(original)
    kept = [
        {"meeting_id": c["meeting_id"], "quote": c["quote"]}
        for c in checked
        if c["valid"]
    ]

    dropped = len(original) - len(kept)
    total_kept += len(kept)
    total_dropped += dropped

    if dropped:
        print(f"{item['question_id']}: left out {dropped} unverified citation(s)")
    if not kept:
        print(f"WARNING {item['question_id']}: no verified citations left")

    answers.append({
        "question_id": item["question_id"],
        "answer": item["answer"],
        "citations": kept,
    })

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump({"answers": answers, "brief": brief}, f, indent=2, ensure_ascii=False)

print(f"Answers written: {len(answers)}")
print(f"Citations kept: {total_kept}, left out: {total_dropped}")
print(f"Saved to: {OUTPUT}")