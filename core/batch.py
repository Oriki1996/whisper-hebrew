"""core/batch.py — Batch folder processing."""
from pathlib import Path
from typing import Callable, Optional

from .config import AUDIO_EXTENSIONS, OUTPUT_DIR
from .whisper_runner import transcribe
from .claude_fixer import fix_hebrew


def find_audio_files(folder: str | Path) -> list[Path]:
    """Return all supported audio/video files in folder (non-recursive)."""
    folder = Path(folder)
    return sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    )


def process_folder(
    folder: str | Path,
    model: str = "small",
    language: str = "he",
    fix: bool = False,
    output_dir: Optional[Path] = None,
    skip_existing: bool = True,
    progress_cb: Optional[Callable[[int, int, str, float, str], None]] = None,
) -> list[dict]:
    """
    Transcribe all audio/video files in a folder.

    Args:
        folder: Folder to scan.
        model: Whisper model name.
        language: Language code.
        fix: Whether to apply Claude Hebrew correction.
        output_dir: Output directory. Defaults to OUTPUT_DIR.
        skip_existing: Skip files that already have a .txt output.
        progress_cb: Callback(file_idx, total, file_name, pct, msg).

    Returns:
        List of result dicts (one per file), each with keys from transcribe()
        plus 'fixed_text' if fix=True.
    """
    files = find_audio_files(folder)
    if not files:
        return []

    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for idx, file in enumerate(files):
        txt_path = out_dir / f"{file.stem}.txt"
        if skip_existing and txt_path.exists():
            if progress_cb:
                progress_cb(idx + 1, len(files), file.name, 1.0, "כבר מעובד — מדלג")
            results.append({"skipped": True, "file": str(file), "txt_path": str(txt_path)})
            continue

        def _cb(pct, msg, _idx=idx, _total=len(files), _name=file.name):
            if progress_cb:
                progress_cb(_idx + 1, _total, _name, pct, msg)

        result = transcribe(
            file_path=file,
            model_name=model,
            language=language,
            output_dir=out_dir,
            progress_cb=_cb,
        )

        if fix:
            if progress_cb:
                progress_cb(idx + 1, len(files), file.name, 0.96, "מתקן עם Claude...")
            try:
                fixed = fix_hebrew(result["text"])
                result["fixed_text"] = fixed
                # Overwrite .txt with corrected version
                Path(result["txt_path"]).write_text(fixed, encoding="utf-8")
            except Exception as e:
                result["fix_error"] = str(e)

        if progress_cb:
            progress_cb(idx + 1, len(files), file.name, 1.0, "הושלם")

        results.append(result)

    return results
