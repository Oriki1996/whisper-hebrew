"""core/config.py — Project configuration and auto-detection."""
import glob
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── ffmpeg ────────────────────────────────────────────────────────────────────
def _find_ffmpeg_candidates() -> list[str]:
    """Return candidate ffmpeg paths to try, in priority order."""
    candidates = []

    # 1. Explicit env var
    env_path = os.getenv("FFMPEG_PATH", "")
    if env_path:
        candidates.append(env_path)

    # 2. Project-local bin/ directory (portable ffmpeg dropped next to project)
    project_bin = Path(__file__).parent.parent / "bin"
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidates.append(str(project_bin / name))

    # 3. winget install — dynamic glob (works for any username and any version)
    winget_pattern = os.path.join(
        os.path.expanduser("~"),
        "AppData", "Local", "Microsoft", "WinGet", "Packages",
        "Gyan.FFmpeg*", "*", "bin", "ffmpeg.exe",
    )
    candidates.extend(sorted(glob.glob(winget_pattern), reverse=True))  # newest first

    # 4. Chocolatey / Scoop / common Windows locations
    candidates += [
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        r"C:\tools\ffmpeg\bin\ffmpeg.exe",
        os.path.join(os.path.expanduser("~"), "scoop", "apps", "ffmpeg", "current", "bin", "ffmpeg.exe"),
    ]

    return candidates


def get_ffmpeg_path() -> str:
    """Return the ffmpeg executable path, or raise if not found."""
    # 1. Check system PATH first (fastest, respects user's own setup)
    found = shutil.which("ffmpeg")
    if found:
        return found

    # 2. Try each candidate path
    for candidate in _find_ffmpeg_candidates():
        if candidate and Path(candidate).exists():
            return candidate

    raise FileNotFoundError(
        "ffmpeg לא נמצא. התקן דרך:\n"
        "  winget install --id Gyan.FFmpeg\n"
        "או הורד ffmpeg.exe ל-bin/ בתיקיית הפרויקט."
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
