
import json
from agent import answer_question

print("=" * 60)
print("LIVE MEETING MEMORY AGENT DEMO")
print("=" * 60)

team = input("Enter team ID (e.g. TS3010): ").strip()
question = input("Enter your question: ").strip()

question_data = {
    "question_id": "LIVE_DEMO",
    "team": team,
    "question": question
}

print("\nSearching meetings and generating answer...\n")

try:
    result = answer_question(question_data)

    print("\n" + "=" * 60)
    print("FINAL ANSWER")
    print("=" * 60)

    print(result["answer"])

    print("\n" + "=" * 60)
    print("CITATIONS")
    print("=" * 60)

    for i, citation in enumerate(result.get("citations", []), 1):
        print(f"\nCitation {i}")
        print("Meeting:", citation.get("meeting_id"))
        print("Quote:", citation.get("quote"))

    print("\n" + "=" * 60)
    print("CITATION VALIDATION")
    print("=" * 60)

    for citation in result.get("citation_validation", []):
        print("Meeting:", citation.get("meeting_id"))
        print("Valid:", citation.get("valid"))

    print("\nMeetings searched:", result.get("meetings_searched"))
    print("All citations valid:", result.get("all_citations_valid"))

except Exception as e:
    print("Demo failed:", e)
