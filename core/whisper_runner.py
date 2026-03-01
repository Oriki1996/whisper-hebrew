"""core/whisper_runner.py — Whisper transcription wrapper (faster-whisper)."""
from pathlib import Path
from typing import Callable, Optional

from .config import setup_ffmpeg_env, OUTPUT_DIR

_model_cache: dict = {}


def _detect_device() -> tuple[str, str]:
    """Return (device, compute_type) based on available hardware."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _get_model(model_name: str):
    """Load and cache faster-whisper model (avoid reloading between files)."""
    if model_name not in _model_cache:
        from faster_whisper import WhisperModel
        device, compute_type = _detect_device()
        _model_cache[model_name] = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )
    return _model_cache[model_name]


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm."""
    ms = int((seconds % 1) * 1000)
    s = int(seconds) % 60
    m = int(seconds) // 60 % 60
    h = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(segments: list, out_path: Path):
    """Write SRT subtitle file from segment dicts."""
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
    Transcribe an audio/video file with faster-whisper.

    Args:
        file_path: Path to audio/video file.
        model_name: Whisper model name (tiny/small/medium/large).
        language: Language code, e.g. "he" for Hebrew. Pass None for auto-detect.
        output_dir: Where to save .txt and .srt. Defaults to OUTPUT_DIR.
        progress_cb: Optional callback(pct: float, msg: str) for progress updates.

    Returns:
        dict with keys: text, segments (list of dicts), duration, txt_path, srt_path
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

    # faster-whisper returns a (segments_generator, info) tuple
    lang_arg = language if language and language != "auto" else None
    segments_gen, info = model.transcribe(
        str(file_path),
        language=lang_arg,
        beam_size=5,
        vad_filter=True,           # skip silent sections — faster + cleaner
        vad_parameters={"min_silence_duration_ms": 500},
    )

    # Materialise the generator so we can iterate twice (progress + SRT)
    # and convert Segment objects → plain dicts (same shape as openai-whisper)
    segments: list[dict] = []
    full_text_parts: list[str] = []
    duration = info.duration or 0.0

    for seg in segments_gen:
        text = seg.text.strip()
        segments.append({
            "start": seg.start,
            "end":   seg.end,
            "text":  text,
        })
        full_text_parts.append(text)

        if progress_cb and duration > 0:
            pct = 0.05 + 0.85 * (seg.end / duration)
            progress_cb(min(pct, 0.90), text[:60])

    full_text = " ".join(full_text_parts)

    _write_txt(full_text, txt_path)
    _write_srt(segments, srt_path)

    if progress_cb:
        progress_cb(0.95, "שומר קבצים...")

    return {
        "text":     full_text,
        "segments": segments,
        "duration": duration,
        "txt_path": str(txt_path),
        "srt_path": str(srt_path),
    }
