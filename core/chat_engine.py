"""core/chat_engine.py — RAG chat over the lecture library using Claude + vector search."""
import time
from typing import Optional

MAX_CONTEXT_SEGMENTS = 8   # top-k segments to pass as context
MAX_RETRIES          = 3
RETRY_DELAY          = 3.0

CHAT_SYSTEM_PROMPT = """\
אתה עוזר אקדמי חכם שעונה על שאלות על בסיס תמלולי הרצאות.
קיבלת קטעים רלוונטיים מתוך ספריית ההרצאות כהקשר.
ענה בעברית, בצורה ברורה ומדויקת.

כללים:
1. השתמש רק במידע שמופיע בקטעים שניתנו לך.
2. בכל טענה שאתה מביא, ציין את מקורה בפורמט: [שם הקובץ | HH:MM:SS]
3. אם אין מספיק מידע בקטעים כדי לענות — אמור זאת בפירוש.
4. אם שאלת המשך נשאלת, השתמש בהיסטוריית השיחה.
5. אל תמציא מידע שלא מופיע בקטעים.\
"""


def _fmt_time(sec: float) -> str:
    h = int(sec) // 3600
    m = int(sec) // 60 % 60
    s = int(sec) % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _build_context(segments: list[dict]) -> str:
    """Format retrieved segments as a numbered context block."""
    lines = []
    for i, seg in enumerate(segments, 1):
        filename = seg.get("filename", "הרצאה")
        ts       = _fmt_time(seg.get("start_time", 0))
        text     = seg.get("text", "").strip()
        course   = seg.get("course_name", "")
        source   = f"{filename}" + (f" ({course})" if course else "")
        lines.append(f"[{i}] {source} | {ts}\n{text}")
    return "\n\n".join(lines)


def answer(
    question:    str,
    history:     list[dict],   # [{"role": "user"|"assistant", "content": str}]
    api_key:     Optional[str] = None,
    top_k:       int = MAX_CONTEXT_SEGMENTS,
    search_mode: str = "both",
) -> dict:
    """
    Answer a question using RAG over the lecture library.

    Args:
        question:    The user's question.
        history:     Previous turns [{"role": "user"|"assistant", "content": str}].
        api_key:     Anthropic API key (falls back to env).
        top_k:       Number of segments to retrieve.
        search_mode: "semantic", "lexical", or "both".

    Returns:
        dict with keys:
          answer (str)           — Claude's response
          sources (list[dict])   — [{filename, start_time, text, score, course_name}]
          context_used (str)     — The raw context block sent to Claude
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError("pip install anthropic")

    from .config import get_anthropic_key
    key = api_key or get_anthropic_key()
    if not key:
        raise ValueError("חסר מפתח Anthropic API.")

    # ── Retrieve relevant segments ────────────────────────────────────────────
    from .database import semantic_search, lexical_search

    sources: list[dict] = []
    seen_ids: set = set()

    if search_mode in ("semantic", "both"):
        try:
            from .embedder import embed_query
            qvec = embed_query(question)
            for r in semantic_search(qvec, top_k=top_k):
                seen_ids.add(r["id"])
                sources.append(r)
        except Exception as e:
            print(f"  ⚠ semantic retrieval error: {e}", flush=True)

    if search_mode in ("lexical", "both"):
        for r in lexical_search(question, limit=top_k):
            if r["id"] not in seen_ids:
                sources.append(r)
                seen_ids.add(r["id"])

    # Sort by score, take top_k
    sources.sort(key=lambda x: x.get("score", 0), reverse=True)
    sources = sources[:top_k]

    context_used = _build_context(sources)

    # ── Build messages for Claude ─────────────────────────────────────────────
    # Insert context as a system-level note in the first user turn
    context_prefix = (
        f"קטעים רלוונטיים מהספרייה:\n\n{context_used}\n\n---\n\n"
        if context_used
        else "לא נמצאו קטעים רלוונטיים בספרייה.\n\n---\n\n"
    )

    messages = []
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["content"]})

    # Inject context only into the current question
    messages.append({
        "role":    "user",
        "content": context_prefix + question,
    })

    # ── Call Claude ───────────────────────────────────────────────────────────
    client     = anthropic.Anthropic(api_key=key)
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.messages.create(
                model      = "claude-haiku-4-5-20251001",
                max_tokens = 2048,
                system     = CHAT_SYSTEM_PROMPT,
                messages   = messages,
            )
            answer_text = resp.content[0].text.strip()
            return {
                "answer":       answer_text,
                "sources":      sources,
                "context_used": context_used,
            }
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                print(f"  ⚠ chat API error (ניסיון {attempt}/{MAX_RETRIES}): {e}", flush=True)
                time.sleep(RETRY_DELAY)

    raise RuntimeError(f"שגיאת Claude לאחר {MAX_RETRIES} ניסיונות: {last_error}")
