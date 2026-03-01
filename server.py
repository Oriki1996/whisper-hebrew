"""
server.py — Local Flask web server for whisper-hebrew.

Run: python server.py
Then open: http://localhost:5000
"""
import csv
import io
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


# ── Static / index ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


@app.route("/output/<path:filename>")
def serve_output(filename):
    """Serve files from the output directory (audio/video for in-browser playback)."""
    output_dir = Path("output").resolve()
    return send_from_directory(str(output_dir), filename)


# ── Transcription ─────────────────────────────────────────────────────────────
@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    model   = request.form.get("model", "small")
    lang    = request.form.get("lang", "he")
    fix     = request.form.get("fix", "false").lower() == "true"
    diarize = request.form.get("diarize", "false").lower() == "true"
    folder  = request.form.get("folder", "").strip()

    jid = _new_job()

    if folder:
        thread = threading.Thread(
            target=_run_batch_job,
            args=(jid, folder, model, lang, fix),
            daemon=True,
        )
    elif "file" in request.files:
        uploaded  = request.files["file"]
        tmp_dir   = Path("output") / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(uploaded.filename).name
        tmp_path  = tmp_dir / safe_name
        uploaded.save(str(tmp_path))
        thread = threading.Thread(
            target=_run_single_job,
            args=(jid, tmp_path, model, lang, fix, diarize),
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
                yield ": keepalive\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Library ───────────────────────────────────────────────────────────────────
@app.route("/api/library", methods=["GET"])
def api_library_list():
    from core.database import init_db, get_lectures
    init_db()
    return jsonify(get_lectures())


@app.route("/api/library/<int:lid>", methods=["GET"])
def api_library_get(lid):
    from core.database import get_lecture, get_segments, get_insights
    lecture = get_lecture(lid)
    if not lecture:
        return jsonify({"error": "לא נמצא"}), 404
    return jsonify({
        "lecture":  lecture,
        "segments": get_segments(lid),
        "insights": get_insights(lid),
    })


@app.route("/api/library/<int:lid>", methods=["PUT"])
def api_library_update(lid):
    from core.database import update_lecture
    data = request.get_json(silent=True) or {}
    update_lecture(lid, **data)
    return jsonify({"ok": True})


@app.route("/api/library/<int:lid>", methods=["DELETE"])
def api_library_delete(lid):
    from core.database import delete_lecture
    delete_lecture(lid)
    return jsonify({"ok": True})


# ── Search ────────────────────────────────────────────────────────────────────
@app.route("/api/search", methods=["POST"])
def api_search():
    data  = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    mode  = data.get("mode", "both")
    top_k = int(data.get("top_k", 10))

    if not query:
        return jsonify({"error": "שאילתה ריקה"}), 400

    from core.database import semantic_search, lexical_search
    results = []
    seen_ids: set = set()

    if mode in ("semantic", "both"):
        try:
            from core.embedder import embed_query
            qvec = embed_query(query)
            for r in semantic_search(qvec, top_k=top_k):
                seen_ids.add(r["id"])
                results.append(r)
        except Exception as e:
            print(f"  ⚠ semantic search error: {e}", flush=True)

    if mode in ("lexical", "both"):
        for r in lexical_search(query, limit=top_k):
            if r["id"] not in seen_ids:
                results.append(r)
                seen_ids.add(r["id"])

    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return jsonify(results[:top_k])


# ── Insights ──────────────────────────────────────────────────────────────────
@app.route("/api/insights", methods=["POST"])
def api_insights():
    """Generate insights ad-hoc (from the current transcription, no DB save)."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "טקסט ריק"}), 400
    try:
        from core.claude_fixer import generate_insights, insights_to_markdown
        result = generate_insights(text)
        return jsonify({"ok": True, "data": result, "markdown": insights_to_markdown(result)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/library/<int:lid>/insights", methods=["POST"])
def api_library_insights(lid):
    """Generate insights for a stored lecture and save to DB."""
    from core.database import get_lecture, save_insights
    lecture = get_lecture(lid)
    if not lecture:
        return jsonify({"error": "לא נמצא"}), 404
    text = lecture.get("full_fixed_text") or lecture.get("full_raw_text", "")
    if not text:
        return jsonify({"error": "אין טקסט לניתוח"}), 400
    try:
        from core.claude_fixer import generate_insights, insights_to_markdown
        result = generate_insights(text)
        save_insights(lid,
                      summary=result.get("summary", ""),
                      key_terms=result.get("key_terms", []),
                      anki_cards=result.get("anki_cards", []),
                      citations=result.get("citations", []))
        return jsonify({"ok": True, "data": result, "markdown": insights_to_markdown(result)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Citations / Bibliography / Zotero ─────────────────────────────────────────
@app.route("/api/library/<int:lid>/citations/extract", methods=["POST"])
def api_citations_extract(lid):
    """
    Run NER + Zotero matching for a stored lecture and persist the result.
    Body (optional): { "zotero": true|false }  — default true (run Zotero matching)
    Returns: { entities: {...} }
    """
    from core.database import get_lecture, get_segments, save_entities
    lecture = get_lecture(lid)
    if not lecture:
        return jsonify({"error": "לא נמצא"}), 404
    text = lecture.get("full_fixed_text") or lecture.get("full_raw_text", "")
    if not text:
        return jsonify({"error": "אין טקסט לניתוח"}), 400

    data          = request.get_json(silent=True) or {}
    run_zotero    = data.get("zotero", True)
    segments      = get_segments(lid)

    try:
        from core.citation_engine import extract_citations
        entities = extract_citations(text, segments=segments)

        if run_zotero:
            try:
                from core.zotero_link import match_entities
                entities = match_entities(entities)
            except Exception as ze:
                print(f"  ⚠ Zotero matching skipped: {ze}", flush=True)

        save_entities(lid, entities)
        return jsonify({"ok": True, "entities": entities})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bibliography", methods=["GET"])
def api_bibliography():
    """Return global bibliography across all lectures."""
    from core.database import init_db, get_all_citations
    init_db()
    return jsonify(get_all_citations())


@app.route("/api/zotero/match", methods=["POST"])
def api_zotero_match():
    """
    Fuzzy-match a single query string against the Zotero library.
    Body: { "query": str, "type": "title"|"author" }
    Returns: list of up to 5 matches with zotero_uri.
    """
    data  = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    etype = data.get("type", "title")
    if not query:
        return jsonify({"error": "שאילתה ריקה"}), 400
    try:
        from core.zotero_link import match_single
        return jsonify(match_single(query, entity_type=etype))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Export ────────────────────────────────────────────────────────────────────
@app.route("/api/library/<int:lid>/anki")
def api_anki_export(lid):
    from core.database import get_insights
    ins = get_insights(lid)
    if not ins or not ins.get("anki_cards"):
        return jsonify({"error": "אין כרטיסיות. יש להריץ ניתוח הרצאה תחילה."}), 404

    buf = io.StringIO()
    writer = csv.writer(buf)
    for card in ins["anki_cards"]:
        writer.writerow([card.get("front", ""), card.get("back", "")])

    return Response(
        buf.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=anki_{lid}.csv"},
    )


@app.route("/api/library/<int:lid>/obsidian")
def api_obsidian_export(lid):
    from core.database import get_lecture, get_segments, get_insights, get_entities
    lecture = get_lecture(lid)
    if not lecture:
        return jsonify({"error": "לא נמצא"}), 404
    segments = get_segments(lid)
    insights = get_insights(lid)
    entities = get_entities(lid)

    def _fmt(sec: float) -> str:
        h = int(sec) // 3600
        m = int(sec) // 60 % 60
        s = int(sec) % 60
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    lines = [
        f"# {lecture.get('filename', 'הרצאה')}",
        "",
        f"**קורס:** {lecture.get('course_name') or '—'}",
        f"**מרצה:** {lecture.get('lecturer') or '—'}",
        f"**תאריך:** {lecture.get('date') or '—'}",
        f"**משך:** {_fmt(lecture.get('duration', 0))}",
        "", "---", "",
    ]

    if insights and insights.get("summary"):
        lines += ["## סיכום", "", insights["summary"], "", "---", ""]

    if insights and insights.get("key_terms"):
        lines += ["## מושגי מפתח", ""]
        for t in insights["key_terms"]:
            lines.append(f"- **{t.get('term','')}** — {t.get('definition','')}")
        lines += ["", "---", ""]

    if segments:
        lines += ["## תמלול", ""]
        current_speaker = None
        for seg in segments:
            spk = seg.get("speaker_id", "")
            if spk and spk != current_speaker:
                lines.append(f"\n**{spk}**")
                current_speaker = spk
            lines.append(f"[{_fmt(seg.get('start_time', 0))}] {seg.get('text', '')}")
        lines += ["", "---", ""]

    # NER-based references (with timestamps)
    if entities:
        lines += ["## רשימת מקורות", ""]
        ref_num = 1

        def _ts_note(timestamps: list) -> str:
            if not timestamps:
                return ""
            ts_str = " · ".join(_fmt(t) for t in timestamps[:4])
            return f"  *(מוזכר ב: {ts_str})*"

        for author in entities.get("authors", []):
            field = f" ({author['field']})" if author.get("field") else ""
            zuri  = f" → [{author['zotero_key']}]({author['zotero_uri']})" if author.get("zotero_uri") else ""
            ts    = _ts_note(author.get("timestamps", []))
            lines.append(f"{ref_num}. **{author['name']}**{field}{zuri}{ts}")
            ref_num += 1

        for book in entities.get("books", []):
            author_str = f" — {book['author']}" if book.get("author") else ""
            year_str   = f" ({book['year']})" if book.get("year") else ""
            zuri       = f" → [{book.get('zotero_key','')}]({book['zotero_uri']})" if book.get("zotero_uri") else ""
            ts         = _ts_note(book.get("timestamps", []))
            lines.append(f"{ref_num}. *{book['title']}*{author_str}{year_str}{zuri}{ts}")
            ref_num += 1

        for law in entities.get("laws", []):
            yr  = f" ({law['year']})" if law.get("year") else ""
            jur = f" — {law['jurisdiction']}" if law.get("jurisdiction") else ""
            ts  = _ts_note(law.get("timestamps", []))
            lines.append(f"{ref_num}. **{law['name']}**{yr}{jur}{ts}")
            ref_num += 1

        for case in entities.get("cases", []):
            court = f" ({case['court']})" if case.get("court") else ""
            yr    = f" {case['year']}" if case.get("year") else ""
            ts    = _ts_note(case.get("timestamps", []))
            lines.append(f"{ref_num}. *{case['name']}*{court}{yr}{ts}")
            ref_num += 1

    elif insights and insights.get("citations"):
        # Fallback to AI-insights citations if no NER entities yet
        lines += ["## מקורות", ""]
        for c in insights["citations"]:
            ref = f"- {c.get('author','')}"
            if c.get("title"):
                ref += f", *{c['title']}*"
            if c.get("year"):
                ref += f" ({c['year']})"
            lines.append(ref)

    return Response(
        "\n".join(lines).encode("utf-8"),
        mimetype="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=lecture_{lid}.md"},
    )


# ── PDF / DOCX Export ─────────────────────────────────────────────────────────
@app.route("/api/library/<int:lid>/export/pdf")
def api_export_pdf(lid):
    """Generate and stream an academic-style PDF for a lecture."""
    from core.database import get_lecture, get_segments, get_insights, get_entities
    lecture = get_lecture(lid)
    if not lecture:
        return jsonify({"error": "לא נמצא"}), 404
    try:
        from core.pdf_exporter import generate_pdf
        pdf_bytes = generate_pdf(
            lecture  = lecture,
            segments = get_segments(lid),
            insights = get_insights(lid),
            entities = get_entities(lid),
        )
        safe_name = Path(lecture["filename"]).stem + ".pdf"
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={safe_name}"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/library/<int:lid>/export/docx")
def api_export_docx(lid):
    """Generate and stream an academic-style DOCX for a lecture."""
    from core.database import get_lecture, get_segments, get_insights, get_entities
    lecture = get_lecture(lid)
    if not lecture:
        return jsonify({"error": "לא נמצא"}), 404
    try:
        from core.docx_exporter import generate_docx
        docx_bytes = generate_docx(
            lecture  = lecture,
            segments = get_segments(lid),
            insights = get_insights(lid),
            entities = get_entities(lid),
        )
        safe_name = Path(lecture["filename"]).stem + ".docx"
        return Response(
            docx_bytes,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename={safe_name}"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Segment update ────────────────────────────────────────────────────────────
@app.route("/api/library/<int:lid>/segments/<int:sid>", methods=["PUT"])
def api_segment_update(lid, sid):
    """Update the text of a single segment after live editing."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "טקסט ריק"}), 400
    from core.database import update_segment_text
    update_segment_text(sid, lid, text)
    return jsonify({"ok": True})


# ── Annotations ───────────────────────────────────────────────────────────────
@app.route("/api/library/<int:lid>/annotations", methods=["GET"])
def api_annotations_list(lid):
    from core.database import get_annotations
    return jsonify(get_annotations(lid))


@app.route("/api/library/<int:lid>/annotations", methods=["POST"])
def api_annotations_create(lid):
    data = request.get_json(silent=True) or {}
    required = ("segment_id", "selected_text", "note")
    if not all(data.get(k) for k in required):
        return jsonify({"error": "חסרים שדות: segment_id, selected_text, note"}), 400
    from core.database import save_annotation
    aid = save_annotation(
        lecture_id        = lid,
        segment_id        = int(data["segment_id"]),
        text_offset_start = int(data.get("text_offset_start", 0)),
        text_offset_end   = int(data.get("text_offset_end", 0)),
        selected_text     = data["selected_text"],
        note              = data["note"],
        color             = data.get("color", "yellow"),
    )
    return jsonify({"ok": True, "id": aid}), 201


@app.route("/api/library/<int:lid>/annotations/<int:aid>", methods=["PUT"])
def api_annotations_update(lid, aid):
    data  = request.get_json(silent=True) or {}
    note  = data.get("note", "")
    color = data.get("color", "yellow")
    from core.database import update_annotation
    update_annotation(aid, note, color)
    return jsonify({"ok": True})


@app.route("/api/library/<int:lid>/annotations/<int:aid>", methods=["DELETE"])
def api_annotations_delete(lid, aid):
    from core.database import delete_annotation
    delete_annotation(aid)
    return jsonify({"ok": True})


# ── Ollama status ─────────────────────────────────────────────────────────────
@app.route("/api/ollama/status", methods=["GET"])
def api_ollama_status():
    from core.ollama_client import is_available, list_models
    available = is_available()
    return jsonify({
        "available": available,
        "models":    list_models() if available else [],
    })


@app.route("/api/ollama/fix", methods=["POST"])
def api_ollama_fix():
    """Fix Hebrew text using local Ollama model."""
    data  = request.get_json(silent=True) or {}
    text  = data.get("text", "").strip()
    model = data.get("model", "")
    if not text:
        return jsonify({"error": "טקסט ריק"}), 400
    try:
        from core.ollama_client import fix_hebrew_local
        fixed = fix_hebrew_local(text, model=model)
        return jsonify({"ok": True, "fixed": fixed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Settings ──────────────────────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    RAG chat over the lecture library.
    Body: { question: str, history: [{role, content}], search_mode: str }
    Returns: { answer: str, sources: [...] }
    """
    data    = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    history  = data.get("history",  [])
    mode     = data.get("search_mode", "both")

    if not question:
        return jsonify({"error": "שאלה ריקה"}), 400

    try:
        from core.chat_engine import answer
        result = answer(question=question, history=history, search_mode=mode)
        # Strip embedding bytes from sources before serialising
        clean_sources = [
            {k: v for k, v in s.items() if k != "embedding"}
            for s in result["sources"]
        ]
        return jsonify({
            "answer":  result["answer"],
            "sources": clean_sources,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = request.get_json(silent=True) or {}
    key  = data.get("anthropic_key", "").strip()
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
    key    = get_anthropic_key() or ""
    masked = key[:8] + "..." if len(key) > 8 else ("מוגדר" if key else "")
    return jsonify({"has_key": bool(key), "masked": masked})


# ── Job runners ───────────────────────────────────────────────────────────────
def _run_single_job(jid: str, file_path: Path, model: str, lang: str,
                    fix: bool, diarize: bool = False):
    try:
        from core.whisper_runner import transcribe
        from core.claude_fixer import fix_hebrew
        from core.database import init_db, save_lecture, save_segments
        from core.embedder import embed_texts

        init_db()

        def cb(pct, msg):
            _push(jid, pct * 0.83, msg)

        result = transcribe(
            file_path=file_path,
            model_name=model,
            language=lang,
            progress_cb=cb,
            diarize=diarize,
        )

        if fix:
            _push(jid, 0.85, "מתקן עם Claude...")
            try:
                fixed = fix_hebrew(result["text"])
                result["fixed_text"] = fixed
                Path(result["txt_path"]).write_text(fixed, encoding="utf-8")
            except Exception as e:
                result["fix_error"] = str(e)

        _push(jid, 0.90, "יוצר embeddings לחיפוש סמנטי...")
        try:
            texts      = [s["text"] for s in result["segments"]]
            embeddings = embed_texts(texts)
            segs_for_db = [
                {**s, "embedding": emb}
                for s, emb in zip(result["segments"], embeddings)
            ]
        except Exception as e:
            print(f"  ⚠ embedding failed (ממשיך ללא embeddings): {e}", flush=True)
            segs_for_db = result["segments"]

        _push(jid, 0.96, "שומר בספרייה...")
        lecture_id = save_lecture(
            filename   = Path(file_path).name,
            raw_text   = result["text"],
            fixed_text = result.get("fixed_text", ""),
            audio_path = str(file_path),
            model      = model,
            language   = lang,
            duration   = result.get("duration", 0.0),
        )
        save_segments(lecture_id, segs_for_db)

        audio_url = "/output/tmp/" + Path(file_path).name
        _push(jid, 1.0, "הושלם!", done=True, result={
            "text":       result.get("fixed_text") or result["text"],
            "raw_text":   result["text"],
            "segments":   result["segments"],
            "txt_path":   result["txt_path"],
            "srt_path":   result["srt_path"],
            "audio_url":  audio_url,
            "fixed":      "fixed_text" in result,
            "lecture_id": lecture_id,
        })

    except Exception as e:
        _push(jid, 0, "", error=str(e), done=True)


def _run_batch_job(jid: str, folder: str, model: str, lang: str, fix: bool):
    try:
        from core.batch import process_folder

        def cb(file_idx, total, file_name, pct, msg):
            overall = (file_idx - 1 + pct) / max(total, 1)
            _push(jid, overall * 0.95, f"[{file_idx}/{total}] {file_name}: {msg}")

        results = process_folder(
            folder=folder, model=model, language=lang,
            fix=fix, skip_existing=True, progress_cb=cb,
        )
        done = [r for r in results if not r.get("skipped")]
        _push(jid, 1.0, f"הושלמו {len(done)} קבצים", done=True, result={
            "batch": True, "total": len(results),
            "processed": len(done), "skipped": len(results) - len(done),
        })
    except Exception as e:
        _push(jid, 0, "", error=str(e), done=True)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"whisper-hebrew server → http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
