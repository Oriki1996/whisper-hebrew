"""
server.py — Local Flask web server for whisper-hebrew.

Run: python server.py
Then open: http://localhost:5000
"""
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from queue import Empty, Queue

sys.stdout.reconfigure(encoding="utf-8")

from flask import Flask, Response, jsonify, request, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="static")

# ── Job state ─────────────────────────────────────────────────────────────────
# Each job: { id, status, progress, msg, result, error }
_jobs: dict[str, dict] = {}
_job_queues: dict[str, Queue] = {}
_lock = threading.Lock()


def _new_job() -> str:
    jid = str(uuid.uuid4())
    q: Queue = Queue()
    with _lock:
        _jobs[jid] = {"id": jid, "status": "queued", "progress": 0.0, "msg": "ממתין..."}
        _job_queues[jid] = q
    return jid


def _push(jid: str, pct: float, msg: str, done=False, error=None, result=None):
    event = {"progress": round(pct * 100), "msg": msg}
    if done:
        event["done"] = True
    if error:
        event["error"] = error
    if result:
        event["result"] = result
    with _lock:
        if jid in _jobs:
            _jobs[jid].update({"progress": pct, "msg": msg})
        if jid in _job_queues:
            _job_queues[jid].put(event)


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    """
    Accepts multipart/form-data with:
      - file: audio/video file (required)
      - model: whisper model name (optional, default small)
      - lang: language code (optional, default he)
      - fix: "true" to apply Claude correction (optional)
      - folder: folder path for batch (alternative to file)
    """
    model = request.form.get("model", "small")
    lang = request.form.get("lang", "he")
    fix = request.form.get("fix", "false").lower() == "true"
    folder = request.form.get("folder", "").strip()

    jid = _new_job()

    if folder:
        # Batch mode
        thread = threading.Thread(
            target=_run_batch_job,
            args=(jid, folder, model, lang, fix),
            daemon=True,
        )
    elif "file" in request.files:
        # Single file upload
        uploaded = request.files["file"]
        tmp_dir = Path("output") / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / uploaded.filename
        uploaded.save(str(tmp_path))
        thread = threading.Thread(
            target=_run_single_job,
            args=(jid, tmp_path, model, lang, fix),
            daemon=True,
        )
    else:
        return jsonify({"error": "יש לצרף קובץ או נתיב תיקייה"}), 400

    thread.start()
    return jsonify({"job_id": jid})


@app.route("/api/progress/<jid>")
def api_progress(jid):
    """SSE endpoint — stream progress events for a job."""
    if jid not in _job_queues:
        return jsonify({"error": "job not found"}), 404

    def generate():
        q = _job_queues[jid]
        while True:
            try:
                event = q.get(timeout=30)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("done") or event.get("error"):
                    break
            except Empty:
                # keepalive
                yield ": keepalive\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/settings", methods=["POST"])
def api_settings():
    """Save Anthropic API key to .env."""
    data = request.get_json(silent=True) or {}
    key = data.get("anthropic_key", "").strip()
    if not key:
        return jsonify({"error": "מפתח ריק"}), 400
    try:
        from core.config import save_anthropic_key
        save_anthropic_key(key)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    from core.config import get_anthropic_key
    key = get_anthropic_key() or ""
    # Return masked key
    masked = key[:8] + "..." if len(key) > 8 else ("מוגדר" if key else "")
    return jsonify({"has_key": bool(key), "masked": masked})


# ── Job runners ───────────────────────────────────────────────────────────────
def _run_single_job(jid: str, file_path: Path, model: str, lang: str, fix: bool):
    try:
        from core.whisper_runner import transcribe
        from core.claude_fixer import fix_hebrew

        def cb(pct, msg):
            _push(jid, pct * 0.9, msg)

        result = transcribe(
            file_path=file_path,
            model_name=model,
            language=lang,
            progress_cb=cb,
        )

        if fix:
            _push(jid, 0.92, "מתקן עם Claude...")
            try:
                fixed = fix_hebrew(result["text"])
                result["fixed_text"] = fixed
                Path(result["txt_path"]).write_text(fixed, encoding="utf-8")
            except Exception as e:
                result["fix_error"] = str(e)

        _push(jid, 1.0, "הושלם!", done=True, result={
            "text": result.get("fixed_text") or result["text"],
            "raw_text": result["text"],
            "txt_path": result["txt_path"],
            "srt_path": result["srt_path"],
            "fixed": "fixed_text" in result,
        })

    except Exception as e:
        _push(jid, 0, "", error=str(e), done=True)


def _run_batch_job(jid: str, folder: str, model: str, lang: str, fix: bool):
    try:
        from core.batch import process_folder

        total_files = [0]

        def cb(file_idx, total, file_name, pct, msg):
            total_files[0] = total
            overall = (file_idx - 1 + pct) / max(total, 1)
            _push(jid, overall * 0.95, f"[{file_idx}/{total}] {file_name}: {msg}")

        results = process_folder(
            folder=folder,
            model=model,
            language=lang,
            fix=fix,
            skip_existing=True,
            progress_cb=cb,
        )

        done = [r for r in results if not r.get("skipped")]
        _push(jid, 1.0, f"הושלמו {len(done)} קבצים", done=True, result={
            "batch": True,
            "total": len(results),
            "processed": len(done),
            "skipped": len(results) - len(done),
        })

    except Exception as e:
        _push(jid, 0, "", error=str(e), done=True)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"whisper-hebrew server → http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
