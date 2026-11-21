"""Reads every transcript, cuts it into turns, saves them in storage/memory.db.
Also builds a keyword-search index (SQLite FTS5). Plain code, no AI, no API key."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
FOLDER = ROOT / "data" / "transcripts"
DB = ROOT / "storage" / "memory.db"


def split_into_turns(file):
    lines = file.read_text(encoding="utf-8").splitlines()
    turns, current = [], None
    for line in lines:
        parts = line.split()
        is_turn_start = len(parts) == 3 and parts[1] == "Speaker" and ":" in parts[0]
        if is_turn_start:
            current = {"time": parts[0], "speaker": parts[2], "text": ""}
            turns.append(current)
        elif current is not None and line.strip() != "":
            current["text"] += line.strip() + " "
    for t in turns:
        t["text"] = t["text"].strip()
    return turns


def main():
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS turns")
    con.execute("DROP TABLE IF EXISTS turns_fts")
    con.execute("""CREATE TABLE turns (
        id INTEGER PRIMARY KEY, meeting_id TEXT, team TEXT, meeting_letter TEXT,
        turn_idx INTEGER, start_time TEXT, speaker TEXT, text TEXT)""")
    total = 0
    for file in sorted(FOLDER.glob("*.txt")):
        meeting_id = file.stem
        team, letter = meeting_id[:-1], meeting_id[-1]
        for i, t in enumerate(split_into_turns(file)):
            con.execute(
                "INSERT INTO turns (meeting_id, team, meeting_letter, turn_idx, start_time, speaker, text) "
                "VALUES (?,?,?,?,?,?,?)",
                (meeting_id, team, letter, i, t["time"], t["speaker"], t["text"]))
            total += 1
    # keyword search index: lets us find turns containing words, fast
    con.execute("CREATE VIRTUAL TABLE turns_fts USING fts5(text, content='turns', content_rowid='id', tokenize='porter unicode61')")
    con.execute("INSERT INTO turns_fts(rowid, text) SELECT id, text FROM turns")
    con.commit()
    print("Saved", total, "turns into", DB)


if __name__ == "__main__":
    main()