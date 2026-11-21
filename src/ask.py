import sys

from agent import answer_question

if len(sys.argv) < 3:
    print('Usage: python src\\ask.py TEAM "your question"')
    print('Example: python src\\ask.py TS3006 "Who suggested dropping speech recognition?"')
    sys.exit(1)

team = sys.argv[1]
question = " ".join(sys.argv[2:])

result = answer_question({"question_id": "LIVE", "team": team, "question": question})

print("\nANSWER:", result["answer"])
for c in result.get("citation_validation", []):
    status = "OK" if c["valid"] else "UNVERIFIED"
    print(f'  [{status}] {c["meeting_id"]} (speaker {c.get("speaker")}): "{c["quote"]}"')