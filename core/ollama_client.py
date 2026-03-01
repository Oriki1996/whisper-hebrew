"""core/ollama_client.py — Local LLM via Ollama for offline Hebrew cleanup."""
import json
import os
import urllib.error
import urllib.request

OLLAMA_BASE = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
TIMEOUT = 90  # seconds

_CLEANUP_SYSTEM = (
    "אתה עוזר לתיקון תמלול אוטומטי בעברית. "
    "קבל את הטקסט הגולמי מהתמלול והחזר אותו עם פיסוק תקין, "
    "הפרדת משפטות, ותיקון שגיאות הגה. "
    "אל תוסיף ואל תמחק תוכן — רק שפר את הניסוח. "
    "החזר רק את הטקסט המתוקן, ללא הסברים."
)


def is_available() -> bool:
    """Return True if the local Ollama server is reachable."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def list_models() -> list[str]:
    """Return list of available model names on the local Ollama server."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def generate(
    prompt: str,
    system: str = "",
    model: str = "",
    temperature: float = 0.2,
) -> str:
    """
    Send a prompt to the local Ollama model and return the response.

    Args:
        prompt:      The user prompt.
        system:      Optional system message.
        model:       Model name (defaults to OLLAMA_MODEL env / 'llama3.2').
        temperature: Sampling temperature (lower = more deterministic).

    Returns:
        Response text string.

    Raises:
        RuntimeError: If Ollama is unreachable or returns an error.
    """
    payload: dict = {
        "model":  model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req  = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("response", "").strip()
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama server not reachable at {OLLAMA_BASE}: {e}")
    except Exception as e:
        raise RuntimeError(f"Ollama error: {e}")


def fix_hebrew_local(text: str, model: str = "") -> str:
    """
    Use the local Ollama model to clean up a Hebrew transcript.

    Much weaker than Claude but works fully offline.
    Raises RuntimeError if Ollama is not available.
    """
    return generate(text, system=_CLEANUP_SYSTEM, model=model)
