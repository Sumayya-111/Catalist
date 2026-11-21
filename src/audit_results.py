import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "test_results.json"
QUESTIONS = ROOT / "data" / "questions.json"

with open(RESULTS, encoding="utf-8") as f:
    results = json.load(f)

with open(QUESTIONS, encoding="utf-8") as f:
    questions = json.load(f)["questions"]

question_map = {q["question_id"]: q for q in questions}
result_map = {r["question_id"]: r for r in results}

print("=" * 70)
print("RAG AGENT - RESULTS AUDIT")
print("=" * 70)

print(f"Questions: {len(questions)}")
print(f"Results: {len(results)}")
print(f"Missing: {set(question_map) - set(result_map)}")
print(f"Unexpected: {set(result_map) - set(question_map)}")

total_citations = 0
valid_citations = 0
invalid_citations = 0
no_citation_questions = []
weak_questions = []

for q in questions:
    qid = q["question_id"]
    result = result_map.get(qid)

    if not result:
        continue

    citations = result.get("citations", [])
    validation = result.get("citation_validation", [])

    total_citations += len(citations)
    valid = sum(1 for c in validation if c.get("valid"))
    invalid = sum(1 for c in validation if not c.get("valid"))

    valid_citations += valid
    invalid_citations += invalid

    answer = result.get("answer", "")

    if not citations:
        no_citation_questions.append(qid)

    if invalid or not citations or "insufficient evidence" in answer.lower():
        weak_questions.append(qid)

    print(f"\n{qid}")
    print("Answer:", answer)
    print(f"Citations: {len(citations)} | Valid: {valid} | Invalid: {invalid}")

    for c in validation:
        if not c.get("valid"):
            print("INVALID CITATION:", c)
    
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print("Total citations:", total_citations)
print("Valid citations:", valid_citations)
print("Invalid citations:", invalid_citations)
print("Questions without citations:", no_citation_questions)
print("Questions requiring review:", sorted(set(weak_questions)))
print("Citation validity rate:",
      round(valid_citations / total_citations * 100, 2)
      if total_citations else 0, "%")
