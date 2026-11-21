import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "storage" / "memory.db"


def prepare_search_query(question):
    """Extract searchable words from a question and build an OR query for FTS5."""
    words = re.findall(r"[A-Za-z0-9]+", question.lower())

    # Very common words, plus words that describe the shape of the question
    # rather than its topic.
    stop_words = {
        "what", "when", "where", "who", "why", "how",
        "did", "does", "was", "were", "the", "and",
        "for", "from", "with", "about", "they", "their",
        "them", "that", "this", "have", "has", "had",
        "are", "is", "to", "of", "in", "on", "a", "an",
        "which", "team", "meeting", "meetings", "member", "one", "final",
        "last", "first", "second", "third", "between", "develop", "reasons",
        "given", "plan", "say", "said",
    }
    # Single letters (like the "c" in "meeting c") would match the letters of "L_C_D_".
    words = [word for word in words if word not in stop_words and len(word) > 1]

    # Remove duplicate words while preserving their order.
    words = list(dict.fromkeys(words))

    if not words:
        return ""

    # The transcripts spell "L_C_D_", which the index splits into single letters,
    # so for these abbreviations also search the spelled-out form.
    spelled = {"lcd": "l c d", "tv": "t v", "dvd": "d v d"}
    terms = []
    for word in words:
        if word in spelled:
            terms.append(f'("{word}" OR "{spelled[word]}")')
        else:
            terms.append(f'"{word}"')
    return " OR ".join(terms)


def search_memory(question, limit=10, team=None, meeting_id=None):
    """
    Search stored meeting turns using SQLite FTS5, ranked by BM25.

    Optional filters:
    - team: search only one team
    - meeting_id: search only one meeting
    """
    search_query = prepare_search_query(question)

    if not search_query:
        return []

    sql = """
        SELECT
            turns.id,
            turns.meeting_id,
            turns.team,
            turns.meeting_letter,
            turns.turn_idx,
            turns.start_time,
            turns.speaker,
            turns.text,
            bm25(turns_fts) AS relevance
        FROM turns_fts
        JOIN turns ON turns.id = turns_fts.rowid
        WHERE turns_fts MATCH ?
    """

    params = [search_query]

    if team:
        sql += " AND turns.team = ?"
        params.append(team)

    if meeting_id:
        sql += " AND turns.meeting_id = ?"
        params.append(meeting_id)

    sql += " ORDER BY relevance LIMIT ?"
    params.append(limit)

    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(sql, params).fetchall()

    return [dict(row) for row in rows]


def add_short_replies(results, count=2, max_chars=200):
    """Add the short turns that directly follow each hit (like "No." after a
    suggestion), then return everything ordered by meeting and time."""
    if not results:
        return results
    seen = {r["id"]: r for r in results}
    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        for r in results:
            rows = con.execute(
                "SELECT id, meeting_id, team, meeting_letter, turn_idx, start_time, speaker, text "
                "FROM turns WHERE meeting_id = ? AND turn_idx > ? AND turn_idx <= ? "
                "ORDER BY turn_idx",
                (r["meeting_id"], r["turn_idx"], r["turn_idx"] + count),
            ).fetchall()
            for row in rows:
                if row["id"] not in seen and len(row["text"]) <= max_chars:
                    seen[row["id"]] = dict(row)
    return sorted(seen.values(), key=lambda x: (x["meeting_id"], x["turn_idx"]))


if __name__ == "__main__":
    question = "Who proposed replacing the titanium back and what was the final decision?"
    results = search_memory(question, limit=5)

    print("Search question:", question)
    print("Results found:", len(results))

    for result in results:
        print("\n" + "=" * 60)
        print("Meeting:", result["meeting_id"])
        print("Speaker:", result["speaker"])
        print("Turn:", result["turn_idx"])
        print("Text:", result["text"])