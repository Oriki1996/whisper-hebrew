"""core/whisper_runner.py — Whisper transcription wrapper."""
import warnings
from pathlib import Path
from typing import Callable, Optional

from .config import setup_ffmpeg_env, OUTPUT_DIR

# Suppress FP16 warning on CPU
warnings.filterwarnings("ignore", message="FP16 is not supported on CPU")

_model_cache: dict = {}


def _get_model(model_name: str):
    """Load and cache Whisper model (avoid reloading between files)."""
    if model_name not in _model_cache:
        import whisper
        _model_cache[model_name] = whisper.load_model(model_name)
    return _model_cache[model_name]


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm."""
    ms = int((seconds % 1) * 1000)
    s = int(seconds) % 60
    m = int(seconds) // 60 % 60
    h = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(segments: list, out_path: Path):
    """Write SRT subtitle file from Whisper segments."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_timestamp(seg["start"])
        end = _format_timestamp(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _write_txt(text: str, out_path: Path):
    out_path.write_text(text.strip(), encoding="utf-8")


def transcribe(
    file_path: str | Path,
    model_name: str = "small",
    language: str = "he",
    output_dir: Optional[Path] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    Transcribe an audio/video file with Whisper.

    Args:
        file_path: Path to audio/video file.
        model_name: Whisper model name (tiny/small/medium/large).
        language: Language code, e.g. "he" for Hebrew.
        output_dir: Where to save .txt and .srt. Defaults to OUTPUT_DIR.
        progress_cb: Optional callback(pct: float, msg: str) for progress updates.

    Returns:
        dict with keys: text, segments, duration, txt_path, srt_path
    """
    setup_ffmpeg_env()

    file_path = Path(file_path)
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = file_path.stem
    txt_path = out_dir / f"{stem}.txt"
    srt_path = out_dir / f"{stem}.srt"

    if progress_cb:
        progress_cb(0.0, f"טוען מודל {model_name}...")

    model = _get_model(model_name)

    if progress_cb:
        progress_cb(0.05, f"מתמלל: {file_path.name}")

    result = model.transcribe(
        str(file_path),
        language=language,
        verbose=False,
    )

    segments = result.get("segments", [])
    full_text = result.get("text", "")
    duration = segments[-1]["end"] if segments else 0.0

    # Simulate per-segment progress after transcription
    if progress_cb:
        total = len(segments) or 1
        for i, seg in enumerate(segments):
            pct = 0.05 + 0.85 * (i + 1) / total
            progress_cb(pct, seg["text"].strip()[:60])

    _write_txt(full_text, txt_path)
    _write_srt(segments, srt_path)

    if progress_cb:
        progress_cb(0.95, "שומר קבצים...")

    return {
        "text": full_text,
        "segments": segments,
        "duration": duration,
        "txt_path": str(txt_path),
        "srt_path": str(srt_path),
    }
