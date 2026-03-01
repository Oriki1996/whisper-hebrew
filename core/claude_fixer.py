"""core/claude_fixer.py — Post-process Hebrew transcription with Claude."""
import time
from typing import Optional

CHUNK_CHARS = 10_000       # ~2,500 words in Hebrew
CONTEXT_WORDS = 200        # trailing words from previous chunk for continuity
MAX_RETRIES = 3
RETRY_DELAY = 3.0          # seconds between retries

SYSTEM_PROMPT = """\
אתה עורך לשון מומחה לעברית מדוברת אקדמית.
קיבלת מקטע מתוך תמלול אוטומטי (Whisper) של הרצאה אקדמית בעברית.
התמלול מכיל שגיאות הכרה אופייניות: מילים מסולפות, חסרי פיסוק, שמות פרטיים שגויים, ערבוב עברית-אנגלית.

תפקידך:
1. תקן שגיאות הכרה ומילים מסולפות
2. הוסף פיסוק תקין (נקודות, פסיקים, סימני שאלה)
3. כתוב שמות פרטיים ומונחים אקדמיים נכון — שמור על עקביות עם ההקשר הקודם
4. שמור על מבנה הפסקאות המקורי
5. אל תוסיף ואל תמחק תוכן — רק תקן

אם צורף "הקשר קודם" בתחילת ההודעה — השתמש בו לשמירת עקביות בשמות ומונחים.
אל תשכתב את ההקשר הקודם — תקן רק את ה"מקטע לתיקון".
החזר רק את המקטע המתוקן, ללא הסברים."""


def _split_chunks(text: str, chunk_chars: int = CHUNK_CHARS) -> list[str]:
    """
    Split text into chunks of ~chunk_chars characters, breaking on whitespace.
    Avoids cutting in the middle of a word.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_chars
        if end >= len(text):
            chunks.append(text[start:].strip())
            break
        # Walk back to the nearest whitespace to avoid splitting mid-word
        while end > start and text[end] not in (" ", "\n", "\t"):
            end -= 1
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


def _trailing_words(text: str, n: int = CONTEXT_WORDS) -> str:
    """Return the last n words of text as a context snippet."""
    words = text.split()
    return " ".join(words[-n:])


def _call_with_retry(client, chunk: str, context: str, chunk_idx: int, total: int) -> str:
    """Send one chunk to Claude with retry logic. Returns corrected text."""
    if context:
        user_content = (
            f"הקשר קודם (אל תשכתב — לעיון בלבד):\n{context}\n\n"
            f"מקטע לתיקון ({chunk_idx}/{total}):\n{chunk}"
        )
    else:
        user_content = f"מקטע לתיקון ({chunk_idx}/{total}):\n{chunk}"

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            return message.content[0].text.strip()
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                print(f"  ⚠ שגיאת API (ניסיון {attempt}/{MAX_RETRIES}): {e} — מנסה שוב בעוד {RETRY_DELAY}s")
                time.sleep(RETRY_DELAY)

    raise RuntimeError(f"נכשל לאחר {MAX_RETRIES} ניסיונות: {last_error}")


INSIGHTS_SYSTEM_PROMPT = """\
אתה מומחה לניתוח הרצאות אקדמיות בעברית.
קיבלת תמלול של הרצאה אקדמית. נתח אותה לעומק והפק דוח מובנה בפורמט Markdown.

הדוח חייב לכלול את הסעיפים הבאים בדיוק:

## סיכום תמציתי
עיקרי הדברים בהרצאה — עד 5 פסקאות קצרות. כתוב בשפה ברורה ונגישה.

## מושגי מפתח
רשימת המונחים החשובים שהוזכרו בהרצאה, כל אחד עם הסבר קצר של 1-2 משפטים.

## שאלות לתרגול
3-5 שאלות פתוחות שיכולות להופיע במבחן על בסיס החומר. כתוב שאלות מאתגרות שדורשות הבנה ולא שינון.

החזר רק את הדוח בפורמט Markdown תקני, ללא הקדמות.\
"""


def generate_insights(text: str, api_key: Optional[str] = None) -> str:
    """
    Generate academic insights from a Hebrew transcription using Claude.

    Args:
        text: Transcription text (full or truncated).
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Returns:
        Markdown-formatted academic analysis.

    Raises:
        ValueError: If no API key is available.
        RuntimeError: If the API call fails after retries.
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError("pip install anthropic")

    from .config import get_anthropic_key
    key = api_key or get_anthropic_key()
    if not key:
        raise ValueError(
            "חסר מפתח Anthropic API. הגדר ANTHROPIC_API_KEY ב-.env או בהגדרות."
        )

    client = anthropic.Anthropic(api_key=key)

    # Use up to ~80,000 chars (~20,000 Hebrew words) — enough for a full lecture
    truncated = text[:80_000]
    user_content = f"תמלול ההרצאה לניתוח:\n\n{truncated}"

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"מנתח הרצאה עם Claude (ניסיון {attempt})...", flush=True)
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=INSIGHTS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            return message.content[0].text.strip()
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                print(f"  ⚠ שגיאת API (ניסיון {attempt}/{MAX_RETRIES}): {e} — מנסה שוב בעוד {RETRY_DELAY}s")
                time.sleep(RETRY_DELAY)

    raise RuntimeError(f"ניתוח נכשל לאחר {MAX_RETRIES} ניסיונות: {last_error}")


def fix_hebrew(raw_text: str, api_key: Optional[str] = None) -> str:
    """
    Correct Hebrew transcription using Claude, with chunking and context overlap.

    Args:
        raw_text: Raw Whisper transcription text.
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Returns:
        Corrected Hebrew text (all chunks joined).

    Raises:
        ValueError: If no API key is available.
        RuntimeError: If all retry attempts fail for a chunk.
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError("pip install anthropic")

    from .config import get_anthropic_key
    key = api_key or get_anthropic_key()
    if not key:
        raise ValueError(
            "חסר מפתח Anthropic API. הגדר ANTHROPIC_API_KEY ב-.env או בהגדרות."
        )

    client = anthropic.Anthropic(api_key=key)
    chunks = _split_chunks(raw_text)
    total = len(chunks)

    corrected_parts: list[str] = []
    prev_context = ""

    for i, chunk in enumerate(chunks, 1):
        print(f"מעבד מקטע {i} מתוך {total} ב-Claude...", flush=True)
        fixed = _call_with_retry(client, chunk, prev_context, i, total)
        corrected_parts.append(fixed)
        prev_context = _trailing_words(fixed, CONTEXT_WORDS)

    return "\n\n".join(corrected_parts)
