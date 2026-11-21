import json
from pathlib import Path

from agent import answer_question

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "evaluations" / "my_questions.json"
RESULTS = ROOT / "evaluations" / "my_results.json"

questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
results = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else []
done = {r["question_id"] for r in results}

for q in questions:
    if q["question_id"] in done:
        print("Skipping", q["question_id"])
        continue
    try:
        out = answer_question(q)
    except Exception as e:
        print("ERROR", q["question_id"], e)
        continue
    results.append({
        "question_id": q["question_id"],
        "team": q["team"],
        "question": q["question"],
        "my_answer": q["my_answer"],
        "agent_answer": out["answer"],
        "citations": [
            {"meeting_id": c["meeting_id"], "quote": c["quote"], "valid": c["valid"]}
            for c in out.get("citation_validation", [])
        ],
    })
    RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

print()
for r in results:
    print("=" * 70)
    print(r["question_id"], r["question"])
    print("MINE :", r["my_answer"])
    print("AGENT:", r["agent_answer"])
    print("Quotes valid:", sum(c["valid"] for c in r["citations"]), "of", len(r["citations"]))