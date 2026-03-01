"""core/config.py — Project configuration and auto-detection."""
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── ffmpeg ────────────────────────────────────────────────────────────────────
_FFMPEG_FALLBACK = (
    r"C:\Users\Ori-PC\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
)

def get_ffmpeg_path() -> str:
    """Return the ffmpeg executable path, or raise if not found."""
    # 1. Check system PATH
    found = shutil.which("ffmpeg")
    if found:
        return found
    # 2. Check known winget install location
    if Path(_FFMPEG_FALLBACK).exists():
        return _FFMPEG_FALLBACK
    raise FileNotFoundError(
        "ffmpeg not found. Install via: winget install --id Gyan.FFmpeg\n"
        f"Or place ffmpeg.exe at: {_FFMPEG_FALLBACK}"
    )

def setup_ffmpeg_env():
    """Add ffmpeg's directory to PATH so Whisper can find it."""
    ffmpeg = get_ffmpeg_path()
    ffmpeg_dir = str(Path(ffmpeg).parent)
    current = os.environ.get("PATH", "")
    if ffmpeg_dir not in current:
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + current

# ── Paths ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

# ── Model ─────────────────────────────────────────────────────────────────────
DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "small")
SUPPORTED_MODELS = ["tiny", "small", "medium", "large"]

# ── API Keys ──────────────────────────────────────────────────────────────────
def get_anthropic_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY")

def save_anthropic_key(key: str):
    """Persist API key to .env file."""
    env_path = Path(__file__).parent.parent / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("ANTHROPIC_API_KEY="):
            lines[i] = f"ANTHROPIC_API_KEY={key}"
            updated = True
            break
    if not updated:
        lines.append(f"ANTHROPIC_API_KEY={key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key

# ── Audio extensions ──────────────────────────────────────────────────────────
AUDIO_EXTENSIONS = {".mp4", ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".mkv"}
