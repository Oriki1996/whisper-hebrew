"""core/claude_fixer.py — Post-process Hebrew transcription with Claude."""
from typing import Optional

SYSTEM_PROMPT = """\
אתה עורך לשון מומחה לעברית מדוברת אקדמית.
קיבלת תמלול אוטומטי (Whisper) של הרצאה אקדמית בעברית.
התמלול מכיל שגיאות הכרה אופייניות: מילים מסולפות, חסרי פיסוק, שמות פרטיים שגויים, ערבוב עברית-אנגלית.

תפקידך:
1. תקן שגיאות הכרה ומילים מסולפות
2. הוסף פיסוק תקין (נקודות, פסיקים, סימני שאלה)
3. כתוב שמות פרטיים ומונחים אקדמיים נכון
4. שמור על מבנה הפסקאות המקורי
5. אל תוסיף ואל תמחק תוכן — רק תקן

החזר רק את הטקסט המתוקן, ללא הסברים."""


def fix_hebrew(raw_text: str, api_key: Optional[str] = None) -> str:
    """
    Send transcription to Claude for Hebrew correction.

    Args:
        raw_text: Raw Whisper transcription text.
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Returns:
        Corrected Hebrew text.

    Raises:
        ValueError: If no API key is available.
        anthropic.APIError: On API failure.
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

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"תמלול לתיקון:\n\n{raw_text}",
            }
        ],
    )

    return message.content[0].text.strip()
