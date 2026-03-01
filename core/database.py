"""core/database.py — SQLite persistence layer for whisper-hebrew library."""
import json
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

DB_PATH = Path("whisper_library.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init_db() -> None:
    """Create all tables if they don't exist yet."""
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS lectures (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            filename        TEXT    NOT NULL,
            course_name     TEXT    DEFAULT '',
            lecturer        TEXT    DEFAULT '',
            date            TEXT,
            full_raw_text   TEXT,
            full_fixed_text TEXT,
            audio_path      TEXT,
            model           TEXT,
            language        TEXT,
            duration        REAL    DEFAULT 0.0,
            created_at      TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS segments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            lecture_id  INTEGER REFERENCES lectures(id) ON DELETE CASCADE,
            start_time  REAL,
            end_time    REAL,
            speaker_id  TEXT    DEFAULT '',
            text        TEXT,
            words       TEXT,       -- JSON array of word-level timestamps
            embedding   BLOB        -- numpy float32 array serialised as bytes
        );

        CREATE TABLE IF NOT EXISTS insights (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            lecture_id  INTEGER REFERENCES lectures(id) ON DELETE CASCADE,
            summary     TEXT,
            key_terms   TEXT,       -- JSON [{term, definition}]
            anki_cards  TEXT,       -- JSON [{front, back}]
            citations   TEXT,       -- JSON [{author, title, year, context}]
            created_at  TEXT    DEFAULT (datetime('now'))
        );
        """)


# ── Lectures ──────────────────────────────────────────────────────────────────

def save_lecture(
    filename: str,
    course_name: str = "",
    lecturer: str = "",
    date: Optional[str] = None,
    raw_text: str = "",
    fixed_text: str = "",
    audio_path: str = "",
    model: str = "",
    language: str = "he",
    duration: float = 0.0,
) -> int:
    """Insert a lecture row and return its id."""
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO lectures
               (filename, course_name, lecturer, date, full_raw_text,
                full_fixed_text, audio_path, model, language, duration)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (filename, course_name, lecturer, date, raw_text,
             fixed_text, audio_path, model, language, duration),
        )
        return cur.lastrowid


def get_lectures() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, filename, course_name, lecturer, date,
                      duration, model, language, created_at
               FROM lectures ORDER BY created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_lecture(lecture_id: int) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM lectures WHERE id = ?", (lecture_id,)
        ).fetchone()
    return dict(row) if row else None


def update_lecture(lecture_id: int, **fields) -> None:
    allowed = {"course_name", "lecturer", "date", "full_fixed_text"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = ", ".join(f"{k} = ?" for k in updates)
    with _conn() as conn:
        conn.execute(
            f"UPDATE lectures SET {cols} WHERE id = ?",
            (*updates.values(), lecture_id),
        )


def delete_lecture(lecture_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM lectures WHERE id = ?", (lecture_id,))


# ── Segments ──────────────────────────────────────────────────────────────────

def save_segments(lecture_id: int, segments: list[dict]) -> None:
    """
    Each segment dict expected keys:
      start_time, end_time, speaker_id, text, embedding (bytes|None), words (list|None)
    """
    rows = [
        (
            lecture_id,
            s.get("start_time", s.get("start", 0.0)),
            s.get("end_time", s.get("end", 0.0)),
            s.get("speaker_id", ""),
            s.get("text", ""),
            json.dumps(s.get("words") or [], ensure_ascii=False),
            s.get("embedding"),  # raw bytes or None
        )
        for s in segments
    ]
    with _conn() as conn:
        conn.executemany(
            """INSERT INTO segments
               (lecture_id, start_time, end_time, speaker_id, text, words, embedding)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )


def get_segments(lecture_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, lecture_id, start_time, end_time,
                      speaker_id, text, words
               FROM segments WHERE lecture_id = ?
               ORDER BY start_time""",
            (lecture_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["words"] = json.loads(d.get("words") or "[]")
        result.append(d)
    return result


# ── Insights ──────────────────────────────────────────────────────────────────

def save_insights(
    lecture_id: int,
    summary: str,
    key_terms: list,
    anki_cards: list,
    citations: list,
) -> None:
    with _conn() as conn:
        # Replace if exists
        conn.execute("DELETE FROM insights WHERE lecture_id = ?", (lecture_id,))
        conn.execute(
            """INSERT INTO insights
               (lecture_id, summary, key_terms, anki_cards, citations)
               VALUES (?, ?, ?, ?, ?)""",
            (
                lecture_id,
                summary,
                json.dumps(key_terms, ensure_ascii=False),
                json.dumps(anki_cards, ensure_ascii=False),
                json.dumps(citations, ensure_ascii=False),
            ),
        )


def get_insights(lecture_id: int) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM insights WHERE lecture_id = ?", (lecture_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["key_terms"] = json.loads(d.get("key_terms") or "[]")
    d["anki_cards"] = json.loads(d.get("anki_cards") or "[]")
    d["citations"] = json.loads(d.get("citations") or "[]")
    return d


# ── Search ────────────────────────────────────────────────────────────────────

def _all_segments_with_embeddings() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT s.id, s.lecture_id, s.start_time, s.end_time,
                      s.speaker_id, s.text, s.embedding,
                      l.filename, l.course_name
               FROM segments s
               JOIN lectures l ON l.id = s.lecture_id
               WHERE s.embedding IS NOT NULL"""
        ).fetchall()
    return [dict(r) for r in rows]


def semantic_search(
    query_embedding: np.ndarray, top_k: int = 10
) -> list[dict]:
    """Cosine similarity search across all embedded segments."""
    rows = _all_segments_with_embeddings()
    if not rows:
        return []

    results = []
    q_norm = np.linalg.norm(query_embedding) + 1e-8
    for row in rows:
        emb = np.frombuffer(row["embedding"], dtype=np.float32)
        sim = float(np.dot(query_embedding, emb) / (q_norm * (np.linalg.norm(emb) + 1e-8)))
        d = {k: v for k, v in row.items() if k != "embedding"}
        d["score"] = round(sim, 4)
        d["match_type"] = "semantic"
        results.append(d)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def lexical_search(query: str, limit: int = 30) -> list[dict]:
    """LIKE-based full-text search across all segment text."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT s.id, s.lecture_id, s.start_time, s.end_time,
                      s.speaker_id, s.text,
                      l.filename, l.course_name
               FROM segments s
               JOIN lectures l ON l.id = s.lecture_id
               WHERE s.text LIKE ?
               LIMIT ?""",
            (f"%{query}%", limit),
        ).fetchall()
    result = [dict(r) for r in rows]
    for r in result:
        r["score"] = 1.0
        r["match_type"] = "lexical"
    return result
