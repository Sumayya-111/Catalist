
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "storage" / "memory.db"


# Words that usually add little to transcript retrieval.
# Keep words such as "first", "final", "proposed", "replaced"
# and "decided", since they can be important for decision questions.
STOP_WORDS = {
    "what", "when", "where", "who", "why", "how",
    "did", "does", "do", "was", "were", "the", "and",
    "for", "from", "with", "about", "they", "their",
    "them", "that", "this", "have", "has", "had",
    "are", "is", "to", "of", "in", "on", "a", "an",
    "which", "team", "teams", "meeting", "meetings",
    "member", "members", "between", "say", "said",
}


def extract_terms(question):
    """Extract useful, deduplicated terms from a question."""
    words = re.findall(r"[A-Za-z0-9]+", question.lower())

    words = [
        word for word in words
        if word not in STOP_WORDS and len(word) > 1
    ]

    return list(dict.fromkeys(words))


def prepare_search_query(question, mode="OR"):
    """
    Build a safe SQLite FTS5 query.

    OR mode: broad retrieval.
    AND mode: stricter retrieval when all terms appear.
    """
    words = extract_terms(question)

    if not words:
        return ""

    spelled = {
        "lcd": "l c d",
        "tv": "t v",
        "dvd": "d v d",
    }

    terms = []

    for word in words:
        if word in spelled:
            terms.append(
                f'("{word}" OR "{spelled[word]}")'
            )
        else:
            terms.append(f'"{word}"')

    if mode == "AND":
        return " AND ".join(terms)

    return " OR ".join(terms)


def _search_query(
    search_query,
    limit=10,
    team=None,
    meeting_id=None
):
    """Execute one FTS5 query and return its ranked results."""
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


def search_memory(question, limit=10, team=None, meeting_id=None):
    """
    Hybrid retrieval:
    1. Retrieve using broad OR matching.
    2. Retrieve using stricter AND matching.
    3. Merge rankings using Reciprocal Rank Fusion (RRF).
    4. Return a deduplicated ranked list.
    """

    or_query = prepare_search_query(question, mode="OR")
    and_query = prepare_search_query(question, mode="AND")

    if not or_query:
        return []

    # Retrieve a larger pool before merging.
    pool_size = max(limit * 3, 30)

    broad_results = _search_query(
        or_query,
        limit=pool_size,
        team=team,
        meeting_id=meeting_id,
    )

    strict_results = _search_query(
        and_query,
        limit=pool_size,
        team=team,
        meeting_id=meeting_id,
    ) if and_query else []

    # Reciprocal Rank Fusion combines ranking positions
    # instead of relying on incomparable raw BM25 scores.
    fused = {}
    rrf_constant = 60

    for results in (broad_results, strict_results):
        for rank, item in enumerate(results, start=1):
            key = item["id"]

            if key not in fused:
                fused[key] = {
                    "item": item,
                    "score": 0.0,
                }

            fused[key]["score"] += (
                1.0 / (rrf_constant + rank)
            )

    ranked = sorted(
        fused.values(),
        key=lambda entry: entry["score"],
        reverse=True,
    )

    output = []

    for entry in ranked[:limit]:
        item = entry["item"].copy()
        item["relevance"] = entry["score"]
        output.append(item)

    return output


def add_short_replies(results, count=2, max_chars=200):
    """
    Expand retrieved hits with neighboring turns.

    Adds up to `count` turns before and after each hit.
    Keeps short replies and conversational context.
    Deduplicates by turn ID.
    """

    if not results:
        return results

    seen = {
        r["id"]: r.copy()
        for r in results
    }

    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row

        for result in results:
            rows = con.execute(
                """
                SELECT
                    id,
                    meeting_id,
                    team,
                    meeting_letter,
                    turn_idx,
                    start_time,
                    speaker,
                    text
                FROM turns
                WHERE meeting_id = ?
                  AND turn_idx BETWEEN ? AND ?
                ORDER BY turn_idx
                """,
                (
                    result["meeting_id"],
                    result["turn_idx"] - count,
                    result["turn_idx"] + count,
                ),
            ).fetchall()

            for row in rows:
                row = dict(row)

                # Preserve the original retrieval result.
                # Add context only when it is reasonably short.
                if row["id"] not in seen:
                    if len(row["text"]) <= max_chars:
                        seen[row["id"]] = row

    # Sort by meeting and chronological turn order.
    return sorted(
        seen.values(),
        key=lambda item: (
            item["meeting_id"],
            item["turn_idx"],
        ),
    )


if __name__ == "__main__":
    question = (
        "Who proposed replacing the titanium back "
        "and what was the final decision?"
    )

    results = search_memory(question, limit=10)

    print("Search question:", question)
    print("Results found:", len(results))

    for result in results:
        print("\n" + "=" * 60)
        print("Meeting:", result["meeting_id"])
        print("Speaker:", result["speaker"])
        print("Turn:", result["turn_idx"])
        print("Timestamp:", result["start_time"])
        print("Score:", result["relevance"])
        print("Text:", result["text"])
