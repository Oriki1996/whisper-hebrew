"""core/diarizer.py — Speaker diarization using pyannote-audio 3.x."""
import os
from pathlib import Path
from typing import Optional

_pipeline = None


def get_pipeline():
    """Lazy-load the pyannote diarization pipeline (requires HF_TOKEN in env)."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    try:
        from pyannote.audio import Pipeline
    except ImportError:
        raise ImportError(
            "pip install pyannote.audio  (also requires accepting model license on HuggingFace)"
        )

    hf_token = os.environ.get("HF_TOKEN", "").strip()
    if not hf_token:
        raise ValueError(
            "HF_TOKEN is required for speaker diarization.\n"
            "1. Accept the model at: https://huggingface.co/pyannote/speaker-diarization-3.1\n"
            "2. Generate a token at: https://huggingface.co/settings/tokens\n"
            "3. Add HF_TOKEN=hf_... to your .env file."
        )

    print("טוען pipeline של דיאריזציה (pyannote)...", flush=True)
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )

    try:
        import torch
        if torch.cuda.is_available():
            pipeline = pipeline.to(torch.device("cuda"))
            print("  דיאריזציה תרוץ על GPU.", flush=True)
    except Exception:
        pass

    _pipeline = pipeline
    return _pipeline


def diarize(audio_path: str | Path) -> list[dict]:
    """
    Run speaker diarization on an audio file.

    Returns:
        List of {start, end, speaker} dicts sorted by start time.
        Speaker values are strings like "SPEAKER_00", "SPEAKER_01".
    """
    pipeline = get_pipeline()
    diarization = pipeline(str(audio_path))

    result = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        result.append({
            "start":   turn.start,
            "end":     turn.end,
            "speaker": speaker,
        })

    result.sort(key=lambda x: x["start"])
    return result


def assign_speakers(
    segments: list[dict],
    diarization: list[dict],
) -> list[dict]:
    """
    Assign a speaker_id to each segment using maximum-overlap with diarization turns.

    Args:
        segments:    list of segment dicts (must have 'start' and 'end' keys)
        diarization: output of diarize()

    Returns:
        Same segments list with 'speaker_id' key populated.
    """
    for seg in segments:
        seg_start = seg.get("start", seg.get("start_time", 0.0))
        seg_end   = seg.get("end",   seg.get("end_time",   0.0))

        best_speaker = ""
        best_overlap = 0.0

        for turn in diarization:
            overlap = max(
                0.0,
                min(seg_end, turn["end"]) - max(seg_start, turn["start"]),
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn["speaker"]

        seg["speaker_id"] = best_speaker or "SPEAKER_00"

    return segments
