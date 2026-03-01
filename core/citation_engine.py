"""core/citation_engine.py — NER for academic citations using Claude."""
import json
import time
from typing import Optional

MAX_RETRIES  = 3
RETRY_DELAY  = 3.0
# Characters per Claude call — keep under ~6000 tokens
CHUNK_CHARS  = 8000

EXTRACTION_SYSTEM_PROMPT = """\
אתה מנתח ספרותי ואקדמי. קיבלת קטע מתמלול הרצאה בעברית.
עליך לחלץ ישויות אקדמיות מהטקסט וולהחזיר JSON בלבד — ללא הסברים, ללא markdown.

חלץ את הסוגים הבאים:
1. authors   — שמות חוקרים/תיאורטיקנים/פרופסורים (לא סטודנטים)
2. books     — ספרים, מאמרים, כתבי-עת, דוחות
3. laws      — חוקים, תקנות, חקיקה, אמנות, פסיקת חוקה
4. cases     — פסיקות משפטיות, תיקים, פסקי-דין

פורמט JSON:
{
  "authors": [{"name": "...", "field": "...", "context": "..."}],
  "books":   [{"title": "...", "author": "...", "year": "...", "context": "..."}],
  "laws":    [{"name": "...", "year": "...", "jurisdiction": "...", "context": "..."}],
  "cases":   [{"name": "...", "court": "...", "year": "...", "context": "..."}]
}

כללים:
- אם אין ישויות מסוג מסוים — החזר מערך ריק []
- "context" הוא ציטוט קצר (עד 20 מילה) מהטקסט שבו מוזכרת הישות
- אל תמציא — רק מה שמופיע בטקסט
- החזר JSON תקין בלבד\
"""


def _safe_json(text: str) -> dict:
    """Strip markdown fences and parse JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


def _merge_entities(base: dict, chunk: dict) -> dict:
    """Merge two entity dicts, de-duplicating by name/title."""
    for key in ("authors", "books", "laws", "cases"):
        existing = {e.get("name") or e.get("title") for e in base.get(key, [])}
        for item in chunk.get(key, []):
            label = item.get("name") or item.get("title")
            if label and label not in existing:
                base.setdefault(key, []).append(item)
                existing.add(label)
    return base


def _attach_timestamps(entities: dict, segments: list[dict]) -> dict:
    """
    For each entity, scan all segments and attach a list of timestamps
    (segment start_time) where the entity name/title appears.
    """
    for key in ("authors", "books", "laws", "cases"):
        for entity in entities.get(key, []):
            label = (entity.get("name") or entity.get("title") or "").lower()
            if not label or len(label) < 3:
                entity["timestamps"] = []
                continue
            times = []
            for seg in segments:
                if label in seg.get("text", "").lower():
                    times.append(seg.get("start_time", seg.get("start", 0.0)))
            entity["timestamps"] = times
    return entities


def extract_citations(
    text: str,
    segments: Optional[list[dict]] = None,
    api_key: Optional[str] = None,
) -> dict:
    """
    Use Claude NER to extract 4 academic entity types from a transcript.

    Args:
        text:     Full transcript text (fixed or raw).
        segments: Optional list of segment dicts with 'text' and 'start_time'/'start'
                  keys — used to attach timestamps to each extracted entity.
        api_key:  Anthropic API key (falls back to env).

    Returns:
        dict with keys: authors, books, laws, cases
        Each value is a list of entity dicts with a 'timestamps' list added.
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError("pip install anthropic")

    from .config import get_anthropic_key
    key = api_key or get_anthropic_key()
    if not key:
        raise ValueError("חסר מפתח Anthropic API.")

    client = anthropic.Anthropic(api_key=key)

    # Split long texts into overlapping chunks to stay within token limits
    chunks = []
    step = CHUNK_CHARS - 500   # 500-char overlap
    for i in range(0, max(1, len(text)), step):
        chunks.append(text[i: i + CHUNK_CHARS])
        if i + CHUNK_CHARS >= len(text):
            break

    merged: dict = {"authors": [], "books": [], "laws": [], "cases": []}

    for chunk_idx, chunk in enumerate(chunks):
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = client.messages.create(
                    model      = "claude-haiku-4-5-20251001",
                    max_tokens = 1024,
                    system     = EXTRACTION_SYSTEM_PROMPT,
                    messages   = [{"role": "user", "content": chunk}],
                )
                parsed = _safe_json(resp.content[0].text)
                merged = _merge_entities(merged, parsed)
                break
            except json.JSONDecodeError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    print(
                        f"  ⚠ citation JSON parse error chunk {chunk_idx} "
                        f"(attempt {attempt}/{MAX_RETRIES}): {e}",
                        flush=True,
                    )
                    time.sleep(RETRY_DELAY)
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    print(
                        f"  ⚠ citation API error chunk {chunk_idx} "
                        f"(attempt {attempt}/{MAX_RETRIES}): {e}",
                        flush=True,
                    )
                    time.sleep(RETRY_DELAY)
        else:
            print(
                f"  ✗ citation extraction failed for chunk {chunk_idx}: {last_error}",
                flush=True,
            )

    # Attach timestamps from segments
    if segments:
        merged = _attach_timestamps(merged, segments)
    else:
        for key in ("authors", "books", "laws", "cases"):
            for entity in merged.get(key, []):
                entity.setdefault("timestamps", [])

    return merged


def citations_to_markdown(entities: dict) -> str:
    """Convert entities dict to a readable Markdown string."""
    def _fmt_time(sec: float) -> str:
        h = int(sec) // 3600
        m = int(sec) // 60 % 60
        s = int(sec) % 60
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _ts_list(timestamps: list) -> str:
        if not timestamps:
            return ""
        return "  \n  📍 " + " · ".join(_fmt_time(t) for t in timestamps[:6])

    parts = []

    if entities.get("authors"):
        parts.append("## חוקרים ותיאורטיקנים")
        for a in entities["authors"]:
            ts = _ts_list(a.get("timestamps", []))
            field = f" *({a['field']})*" if a.get("field") else ""
            parts.append(f"- **{a['name']}**{field}{ts}")

    if entities.get("books"):
        parts.append("\n## ספרים ומאמרים")
        for b in entities["books"]:
            ts = _ts_list(b.get("timestamps", []))
            author = f" — {b['author']}" if b.get("author") else ""
            year   = f" ({b['year']})" if b.get("year") else ""
            parts.append(f"- *{b['title']}*{author}{year}{ts}")

    if entities.get("laws"):
        parts.append("\n## חקיקה ורגולציה")
        for law in entities["laws"]:
            ts  = _ts_list(law.get("timestamps", []))
            yr  = f" ({law['year']})" if law.get("year") else ""
            jur = f" — {law['jurisdiction']}" if law.get("jurisdiction") else ""
            parts.append(f"- **{law['name']}**{yr}{jur}{ts}")

    if entities.get("cases"):
        parts.append("\n## פסיקה משפטית")
        for c in entities["cases"]:
            ts    = _ts_list(c.get("timestamps", []))
            court = f" ({c['court']})" if c.get("court") else ""
            yr    = f" {c['year']}" if c.get("year") else ""
            parts.append(f"- **{c['name']}**{court}{yr}{ts}")

    return "\n".join(parts) if parts else "*לא נמצאו ישויות אקדמיות בתמלול.*"
