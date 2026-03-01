"""core/pdf_exporter.py — Academic-style PDF export with Hebrew RTL support."""
import io
import os
from pathlib import Path
from typing import Optional


# ── Font registration ─────────────────────────────────────────────────────────
# Ordered list of (regular_path, bold_path, family_name)
_FONT_CANDIDATES = [
    (r"C:\Windows\Fonts\david.ttf",   r"C:\Windows\Fonts\davidbd.ttf",  "David"),
    (r"C:\Windows\Fonts\arial.ttf",   r"C:\Windows\Fonts\arialbd.ttf",  "Arial"),
    (r"C:\Windows\Fonts\calibri.ttf", r"C:\Windows\Fonts\calibrib.ttf", "Calibri"),
    ("/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf",
     "/usr/share/fonts/truetype/noto/NotoSansHebrew-Bold.ttf",    "NotoHebrew"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf",         "Arial"),
]

_REGISTERED_FAMILY: Optional[str] = None


def _register_fonts() -> str:
    """Register Hebrew-capable fonts with ReportLab. Returns family name."""
    global _REGISTERED_FAMILY
    if _REGISTERED_FAMILY:
        return _REGISTERED_FAMILY

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for reg_path, bold_path, family in _FONT_CANDIDATES:
        if not os.path.exists(reg_path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(family, reg_path))
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont(f"{family}-Bold", bold_path))
                from reportlab.pdfbase.pdfmetrics import registerFontFamily
                registerFontFamily(family, normal=family, bold=f"{family}-Bold")
            _REGISTERED_FAMILY = family
            return family
        except Exception:
            continue

    _REGISTERED_FAMILY = "Helvetica"
    return "Helvetica"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_time(sec: float) -> str:
    h = int(sec) // 3600
    m = int(sec) // 60 % 60
    s = int(sec) % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _rtl(text: str) -> str:
    """Apply bidi algorithm for proper Hebrew RTL display in ReportLab."""
    if not text:
        return ""
    try:
        from bidi.algorithm import get_display
        return get_display(str(text))
    except Exception:
        return str(text)


def _safe(text: str) -> str:
    """Escape XML special chars for ReportLab Paragraph strings."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def generate_pdf(
    lecture: dict,
    segments: list[dict],
    insights: Optional[dict] = None,
    entities: Optional[dict] = None,
) -> bytes:
    """
    Generate an academic-style Hebrew PDF.

    Args:
        lecture:  Lecture row dict (filename, course_name, lecturer, date, duration).
        segments: List of segment dicts (start_time, end_time, speaker_id, text).
        insights: Optional insights dict (summary, key_terms, anki_cards, citations).
        entities: Optional NER entities dict (authors, books, laws, cases).

    Returns:
        PDF as raw bytes.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer,
            Table, TableStyle, HRFlowable,
        )
    except ImportError:
        raise ImportError("pip install reportlab python-bidi")

    font = _register_fonts()

    def _p(name, align=TA_RIGHT, size=10, bold=False,
           color=colors.HexColor("#2b1f14"), space_after=3):
        fn = f"{font}-Bold" if bold and f"{font}-Bold" in _registered_bold_names() else font
        return ParagraphStyle(
            name, fontName=fn, fontSize=size, alignment=align,
            textColor=color, leading=int(size * 1.45), spaceAfter=space_after,
        )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=2.2 * cm, leftMargin=2.2 * cm,
        topMargin=2.5 * cm, bottomMargin=2.5 * cm,
    )

    # Styles
    s_title   = _p("Title",   TA_CENTER, 17, bold=True,
                   color=colors.HexColor("#c8813a"), space_after=4)
    s_meta    = _p("Meta",    TA_RIGHT,   9, color=colors.HexColor("#6b5740"))
    s_h2      = _p("H2",      TA_RIGHT,  13, bold=True,
                   color=colors.HexColor("#2b1f14"), space_after=5)
    s_body    = _p("Body",    TA_RIGHT,  10, space_after=2)
    s_bullet  = _p("Bullet",  TA_RIGHT,  10, space_after=2)
    s_ts      = _p("TS",      TA_LEFT,    8, color=colors.HexColor("#6b5740"))
    s_ref     = _p("Ref",     TA_RIGHT,   9, space_after=1)

    ORANGE    = colors.HexColor("#c8813a")
    LTGRAY    = colors.HexColor("#e0d5c8")

    story = []

    # ── Title / Metadata ────────────────────────────────────────────────────
    story.append(Paragraph(_safe(_rtl(lecture.get("filename", "הרצאה"))), s_title))
    story.append(Spacer(1, 0.2 * cm))

    meta_pairs = [
        ("קורס",  lecture.get("course_name")),
        ("מרצה",  lecture.get("lecturer")),
        ("תאריך", lecture.get("date")),
        ("משך",   _fmt_time(lecture.get("duration", 0)) if lecture.get("duration") else None),
    ]
    for label, val in meta_pairs:
        if val:
            story.append(Paragraph(
                f"{_safe(_rtl(val))}  :{_safe(_rtl(label))}", s_meta))

    story.append(HRFlowable(width="100%", thickness=1.2,
                            color=ORANGE, spaceAfter=8, spaceBefore=6))

    # ── Summary ────────────────────────────────────────────────────────────
    if insights and insights.get("summary"):
        story.append(Paragraph(_safe(_rtl("סיכום")), s_h2))
        story.append(Paragraph(_safe(_rtl(insights["summary"])), s_body))
        story.append(Spacer(1, 0.35 * cm))

    # ── Key Terms ──────────────────────────────────────────────────────────
    if insights and insights.get("key_terms"):
        story.append(Paragraph(_safe(_rtl("מושגי מפתח")), s_h2))
        for t in insights["key_terms"]:
            term = _safe(_rtl(t.get("term", "")))
            defn = _safe(_rtl(t.get("definition", "")))
            story.append(Paragraph(
                f"<b>{term}</b> \u2014 {defn}", s_bullet))
        story.append(Spacer(1, 0.35 * cm))

    # ── Transcript ─────────────────────────────────────────────────────────
    if segments:
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=LTGRAY, spaceAfter=4, spaceBefore=4))
        story.append(Paragraph(_safe(_rtl("תמלול")), s_h2))

        current_speaker = None
        for seg in segments:
            spk = seg.get("speaker_id", "")
            if spk and spk != current_speaker:
                label = _safe(_rtl(spk.replace("SPEAKER_", "דובר ")))
                story.append(Paragraph(f"<b>{label}</b>", s_h2))
                current_speaker = spk

            ts   = _fmt_time(seg.get("start_time", 0))
            text = _safe(_rtl(seg.get("text", "").strip()))

            row = [[Paragraph(ts, s_ts), Paragraph(text, s_body)]]
            tbl = Table(row, colWidths=[1.6 * cm, None])
            tbl.setStyle(TableStyle([
                ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",  (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
                ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ]))
            story.append(tbl)

        story.append(Spacer(1, 0.4 * cm))

    # ── References ─────────────────────────────────────────────────────────
    def _has_refs():
        if entities:
            return any(entities.get(k) for k in ("authors", "books", "laws", "cases"))
        return bool(insights and insights.get("citations"))

    if _has_refs():
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=LTGRAY, spaceAfter=4, spaceBefore=4))
        story.append(Paragraph(_safe(_rtl("רשימת מקורות")), s_h2))
        n = 1

        if entities:
            for author in entities.get("authors", []):
                field = f" ({author['field']})" if author.get("field") else ""
                tss   = ", ".join(_fmt_time(t) for t in author.get("timestamps", [])[:3])
                ts_s  = f" [{tss}]" if tss else ""
                story.append(Paragraph(
                    _safe(_rtl(f"{n}. {author.get('name','')}{field}{ts_s}")), s_ref))
                n += 1

            for book in entities.get("books", []):
                a_s  = f" — {book['author']}" if book.get("author") else ""
                y_s  = f" ({book['year']})" if book.get("year") else ""
                tss  = ", ".join(_fmt_time(t) for t in book.get("timestamps", [])[:3])
                ts_s = f" [{tss}]" if tss else ""
                story.append(Paragraph(
                    _safe(_rtl(f"{n}. {book.get('title','')}{a_s}{y_s}{ts_s}")), s_ref))
                n += 1

            for law in entities.get("laws", []):
                y_s  = f" ({law['year']})" if law.get("year") else ""
                tss  = ", ".join(_fmt_time(t) for t in law.get("timestamps", [])[:3])
                ts_s = f" [{tss}]" if tss else ""
                story.append(Paragraph(
                    _safe(_rtl(f"{n}. {law.get('name','')}{y_s}{ts_s}")), s_ref))
                n += 1

            for case in entities.get("cases", []):
                c_s  = f" ({case['court']})" if case.get("court") else ""
                y_s  = f" {case['year']}" if case.get("year") else ""
                tss  = ", ".join(_fmt_time(t) for t in case.get("timestamps", [])[:3])
                ts_s = f" [{tss}]" if tss else ""
                story.append(Paragraph(
                    _safe(_rtl(f"{n}. {case.get('name','')}{c_s}{y_s}{ts_s}")), s_ref))
                n += 1

        elif insights and insights.get("citations"):
            for c in insights["citations"]:
                ref = c.get("author", "")
                if c.get("title"): ref += f", {c['title']}"
                if c.get("year"):  ref += f" ({c['year']})"
                story.append(Paragraph(_safe(_rtl(f"{n}. {ref}")), s_ref))
                n += 1

    doc.build(story)
    return buf.getvalue()


def _registered_bold_names():
    """Return set of currently registered ReportLab font names."""
    from reportlab.pdfbase import pdfmetrics
    return set(pdfmetrics._fonts.keys())
