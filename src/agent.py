
import json
import os
import re
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

from retrieval import search_memory, add_short_replies

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "storage" / "memory.db"

load_dotenv(ROOT / ".env")

MODEL = os.getenv("GROQ_MODEL")
API_KEY = os.getenv("GROQ_API_KEY")

if not API_KEY or not MODEL:
    raise ValueError("Check GROQ_API_KEY and GROQ_MODEL in .env")

client = Groq(api_key=API_KEY)


def get_team_meetings(team):
    """Return all meeting IDs belonging to a team."""
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            """
            SELECT DISTINCT meeting_id
            FROM turns
            WHERE team = ?
            ORDER BY meeting_letter
            """,
            (team,)
        ).fetchall()

    return [row[0] for row in rows]


def retrieve_team_evidence(question, team, per_meeting=8):
    """
    Search each meeting separately so that evidence
    from later meetings is not hidden by earlier results.
    """
    meetings = get_team_meetings(team)
    all_evidence = []

    for meeting_id in meetings:
        results = search_memory(
            question,
            limit=per_meeting,
            team=team,
            meeting_id=meeting_id
        )

        all_evidence.extend(add_short_replies(results))

    return meetings, all_evidence


def normalize(text):
    """Normalize case and whitespace for quote checking."""
    return " ".join(text.lower().split())


def validate_citations(citations):
    """
    Check that every citation quote exists exactly
    within one original speaker turn.
    """
    checked = []

    with sqlite3.connect(DB) as con:
        for citation in citations:
            meeting_id = citation.get("meeting_id", "")
            quote = citation.get("quote", "")

            if len(quote.split()) < 6:
                checked.append({
                    **citation,
                    "valid": False,
                    "reason": "Quote must contain at least six words."
                })
                continue

            rows = con.execute(
                """
                SELECT id, speaker, text
                FROM turns
                WHERE meeting_id = ?
                """,
                (meeting_id,)
            ).fetchall()

            matched = None
            for turn_id, speaker, original_text in rows:
                if normalize(quote) in normalize(original_text):
                    matched = {
                        "turn_id": turn_id,
                        "speaker": speaker
                    }
                    break

            checked.append({
                **citation,
                "valid": matched is not None,
                "speaker": matched["speaker"] if matched else None,
                "turn_id": matched["turn_id"] if matched else None
            })

    return checked


def answer_question(question_data):
    """Retrieve evidence and ask Groq to answer one question."""

    question = question_data["question"]
    team = question_data["team"]
    question_id = question_data["question_id"]

    print(f"\nProcessing {question_id}: {team}")
    print("Question:", question)

    meetings, evidence = retrieve_team_evidence(question, team)

    print("Meetings searched:", meetings)
    print("Evidence passages retrieved:", len(evidence))

    if len(meetings) < 2:
        raise ValueError(
            f"{team} has fewer than two meetings in the database."
        )

    if not evidence:
        return {
            "question_id": question_id,
            "answer": "Insufficient evidence retrieved to answer reliably.",
            "citations": [],
            "citation_validation": [],
            "meetings_searched": meetings
        }

    evidence_text = []

    for item in evidence:
        evidence_text.append(
            f"""
Meeting: {item['meeting_id']}
Speaker: {item['speaker']}
Timestamp: {item['start_time']}
Original turn: {item['text']}
"""
        )

    prompt = f"""
You are a meeting-memory research agent. Your task is to answer questions
accurately using ONLY the supplied transcript evidence.

TEAM: {team}
QUESTION: {question}

MEETINGS SEARCHED: {meetings}

EVIDENCE:
{"".join(evidence_text)}

REASONING INSTRUCTIONS:

1. Understand every part of the question before answering.
2. For multi-part questions, identify each requested element separately.
   For example: person, original proposal, alternative, reason, final decision.
3. Examine evidence chronologically across meetings. Earlier discussions
   may describe proposals, while later discussions may show changes or
   the final decision.
4. Distinguish between suggestions, discussions, agreements and actual
   final decisions. A suggestion alone does not prove it was accepted.
5. Attribute proposals to speakers only when the evidence supports it.
6. If different meetings contradict each other, use chronology to determine
   whether the decision changed.
7. Do not invent facts, names, roles, costs, reasons or conclusions.
8. If a requested part cannot be established from the evidence, clearly
   acknowledge that part is uncertain rather than guessing.
9. Write a concise answer of one to three plain sentences that addresses
   every part of the question.
10. Provide one to three citations supporting the answer.
11. Each citation must contain at least six consecutive, verbatim words
    from ONE supplied original speaker turn.
12. Never combine quotations from multiple turns into one citation.
13. Use the exact meeting ID provided in the evidence.
14. Cite evidence supporting the actual claims in your answer, not merely
    evidence mentioning the same topic.

Return ONLY valid JSON in this format:

{{
  "answer": "Your answer here.",
  "citations": [
    {{
      "meeting_id": "TS3006a",
      "quote": "An exact quotation from one speaker turn"
    }}
  ]
}}
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You answer questions using cited meeting evidence. Never invent citations."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.1,
        max_completion_tokens=1500
    )

    raw_content = response.choices[0].message.content

    if not raw_content or not raw_content.strip():
        raise ValueError(
            f"Groq returned an empty response. "
            f"finish_reason={response.choices[0].finish_reason}, "
            f"usage={response.usage}"
        )

    raw_answer = raw_content.strip()

# Remove Markdown code fences if present.
    raw_answer = re.sub(
    r"^```(?:json)?\s*|\s*```$",
    "",
    raw_answer
).strip()

    try:
        result = json.loads(raw_answer)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Groq returned invalid JSON. "
            f"Error: {e}. Response: {raw_answer[:500]}"
    )

    citations = result.get("citations", [])
    checked = validate_citations(citations)

    # One repair attempt: tell the model which quotes failed verification.
    bad = [c for c in checked if not c["valid"]]
    if bad:
        repair_prompt = (
            "These citation quotes failed verification: "
            + json.dumps(
                [{"meeting_id": c["meeting_id"], "quote": c["quote"]} for c in bad],
                ensure_ascii=False,
            )
            + "\nEach quote must be copied exactly, character for character, "
            "from ONE original turn in the evidence, at least six words long, "
            "with no '...' and no words removed. "
            "Return the full corrected JSON in the same format."
        )
        try:
            retry = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "You answer questions using cited meeting evidence. Never invent citations."},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": raw_answer},
                    {"role": "user", "content": repair_prompt},
                ],
                temperature=0.1,
                max_completion_tokens=3000,
            )
            raw_retry = retry.choices[0].message.content.strip()
            raw_retry = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_retry).strip()
            retry_result = json.loads(raw_retry)
            retry_checked = validate_citations(retry_result.get("citations", []))
            # Keep the retry only if it is at least as good as the first try.
            if sum(c["valid"] for c in retry_checked) >= sum(c["valid"] for c in checked):
                result, checked = retry_result, retry_checked
        except Exception:
            pass  # if the repair fails, keep the original result

    result["question_id"] = question_id
    result["meetings_searched"] = meetings
    result["citation_validation"] = checked

    result["all_citations_valid"] = (
        len(checked) > 0
        and all(item["valid"] for item in checked)
    )

    return result




if __name__ == "__main__":
    questions_file = ROOT / "data" / "questions.json"
    output_file = ROOT / "data" / "test_results.json"
    errors_file = ROOT / "data" / "test_errors.json"

    with open(questions_file, encoding="utf-8") as f:
        data = json.load(f)

    questions = data["questions"]

    # Load previously completed results, if available.
    if output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            results = json.load(f)
    else:
        results = []

    completed_ids = {
        result["question_id"] for result in results
    }

    errors = []

    print(f"Total questions: {len(questions)}")
    print(f"Already completed: {len(completed_ids)}")

    for question in questions:
        question_id = question.get("question_id", "Unknown")

        # Skip questions already completed successfully.
        if question_id in completed_ids:
            print(f"Skipping {question_id} - already completed")
            continue

        print(f"\n{'=' * 60}")
        print(f"Processing {question_id}")
        print(f"{'=' * 60}")

        try:
            result = answer_question(question)
            results.append(result)
            completed_ids.add(question_id)

            # Save immediately after each success.
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

            print(json.dumps(
                result,
                indent=2,
                ensure_ascii=False
            ))

        except Exception as e:
            error_info = {
                "question_id": question_id,
                "error": str(e)
            }
            errors.append(error_info)

            print(f"ERROR processing {question_id}: {e}")

        # Save errors separately.
        with open(errors_file, "w", encoding="utf-8") as f:
            json.dump(errors, f, indent=2, ensure_ascii=False)

    print("\n========== SUMMARY ==========")
    print(f"Completed: {len(completed_ids)}/{len(questions)}")
    print(f"Results saved to: {output_file}")
    print(f"Errors saved to: {errors_file}")
