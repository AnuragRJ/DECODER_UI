"""PDF renderer for the INCOIS ARPY Daily Fleet Decoding Report.

Renders the authoritative ``BatchReport`` data model (report_data.py) into a
professional oceanographic/scientific operational report using ReportLab.

Design language: restrained navy/ocean-blue INCOIS ARPY branding, clean
scientific typography (Helvetica family), banded section headings, fine-grid
data tables, running header/footer with "Page X of Y".

This module performs NO data derivation — every value shown comes from the
BatchReport passed in.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from models import utc_now_iso
from report_data import REPORTS_DIR, BatchReport

# ---------------------------------------------------------------------------
# Palette & page geometry
# ---------------------------------------------------------------------------

NAVY = colors.HexColor("#163857")
NAVY_DEEP = colors.HexColor("#0F2439")
OCEAN = colors.HexColor("#276095")
SKY_LIGHT = colors.HexColor("#DBEAFE")
SLATE = colors.HexColor("#475569")
SLATE_LIGHT = colors.HexColor("#64748B")
LINE = colors.HexColor("#CBD5E1")
ZEBRA = colors.HexColor("#F1F5F9")
PAPER = colors.white
EMERALD = colors.HexColor("#047857")
ROSE = colors.HexColor("#BE123C")
ROSE_BG = colors.HexColor("#FFF1F2")
AMBER = colors.HexColor("#B45309")
INK = colors.HexColor("#0F172A")

PAGE_W, PAGE_H = A4
MARGIN_X = 16 * mm
MARGIN_TOP = 17 * mm
MARGIN_BOTTOM = 16 * mm
USABLE_W = PAGE_W - 2 * MARGIN_X

COVER_BAND_GAP = 12 * mm          # gap between page top and cover band
COVER_BAND_H = 46 * mm            # cover band height
COVER_CONTENT_GAP = 8 * mm        # gap between band bottom and page-1 content
COVER_CONTENT_FROM_TOP = COVER_BAND_GAP + COVER_BAND_H + COVER_CONTENT_GAP


def _fmt_ts(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d  %H:%M:%S UTC")
    except ValueError:
        return iso


def _fmt_bytes(n: int | None) -> str:
    if not n:
        return "0 B"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

S = {
    "body": ParagraphStyle(
        "body", fontName="Helvetica", fontSize=8.6, leading=12.8,
        textColor=INK, alignment=TA_JUSTIFY, spaceAfter=4,
    ),
    "bodySmall": ParagraphStyle(
        "bodySmall", fontName="Helvetica", fontSize=7.8, leading=11,
        textColor=SLATE, alignment=TA_JUSTIFY, spaceAfter=2,
    ),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=7.5, leading=10, textColor=INK),
    "cellBold": ParagraphStyle("cellBold", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=INK),
    "cellMono": ParagraphStyle("cellMono", fontName="Courier", fontSize=6.4, leading=8.4, textColor=SLATE),
    "sectionTitle": ParagraphStyle(
        "sectionTitle", fontName="Helvetica-Bold", fontSize=12.5, leading=16,
        textColor=NAVY, spaceBefore=14, spaceAfter=2,
    ),
    "sectionSub": ParagraphStyle(
        "sectionSub", fontName="Helvetica", fontSize=8.2, leading=11,
        textColor=SLATE_LIGHT, spaceAfter=6,
    ),
    "floatTitle": ParagraphStyle(
        "floatTitle", fontName="Helvetica-Bold", fontSize=10, leading=13,
        textColor=NAVY, spaceBefore=10, spaceAfter=3,
    ),
    "label": ParagraphStyle("label", fontName="Helvetica", fontSize=7.2, leading=9.5, textColor=SLATE_LIGHT),
    "note": ParagraphStyle(
        "note", fontName="Helvetica-Oblique", fontSize=7.4, leading=10,
        textColor=SLATE_LIGHT, spaceAfter=6,
    ),
}


def _section(num: str, title: str, sub: str | None = None):
    out = [
        Table(
            [[Paragraph(f"{num}.", S["sectionTitle"]), Paragraph(title.upper(), S["sectionTitle"])]],
            colWidths=[14, USABLE_W - 14],
            style=TableStyle([
                ("ALIGN", (0, 0), (0, 0), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]),
        ),
        Table(
            [[""]], colWidths=[USABLE_W], rowHeights=[1.2],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), OCEAN),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]),
        ),
    ]
    if sub:
        out.append(Paragraph(sub, S["sectionSub"]))
    out.append(Spacer(1, 4))
    return out


def _grid_style(header_rows: int = 1, zebra: bool = True) -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), PAPER),
        ("FONTNAME", (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, header_rows - 1), 6.8),
        ("FONTNAME", (0, header_rows), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, header_rows), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, header_rows - 1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [PAPER, ZEBRA] if zebra else [PAPER]),
    ])


def _status_cell(status: str) -> Paragraph:
    st = (status or "").lower()
    if st == "completed":
        return Paragraph('<font color="#047857"><b>SUCCESS</b></font>', S["cell"])
    if st == "error":
        return Paragraph('<font color="#BE123C"><b>FAILED</b></font>', S["cell"])
    if st in ("stopped", "cancelled"):
        return Paragraph('<font color="#B45309"><b>STOPPED</b></font>', S["cell"])
    if st == "active":
        return Paragraph('<font color="#0284C7"><b>RUNNING</b></font>', S["cell"])
    return Paragraph(_esc((status or "—").upper()), S["cell"])


def _basis_cell(basis: str) -> Paragraph:
    b = (basis or "").upper()
    if b == "OBSERVED":
        return Paragraph('<font color="#047857"><b>OBSERVED</b></font>', S["cell"])
    if b == "VERIFIED PRODUCT":
        return Paragraph('<font color="#0284C7"><b>VERIFIED PRODUCT</b></font>', S["cell"])
    if b == "INFERRED":
        return Paragraph('<font color="#64748B"><b>INFERRED</b></font>', S["cell"])
    return Paragraph(_esc(b), S["cell"])


# ---------------------------------------------------------------------------
# Canvas with running header/footer + "Page X of Y" + cover band
# ---------------------------------------------------------------------------

class _ReportCanvas(pdfcanvas.Canvas):
    def __init__(self, *args: Any, ctx: dict | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.ctx = ctx or {}
        self._saved_states: list[dict] = []

    def showPage(self) -> None:
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_states) or 1
        for state in self._saved_states:
            self.__dict__.update(state)
            self._draw_chrome(total)
            super().showPage()
        self.ctx["pages"] = total
        super().save()

    def _draw_chrome(self, total: int) -> None:
        page = self._pageNumber
        c = self
        c.saveState()

        if page == 1:
            # Cover band (navy) with title block
            band_top = PAGE_H - COVER_BAND_GAP
            c.setFillColor(NAVY)
            c.rect(0, band_top - COVER_BAND_H, PAGE_W, COVER_BAND_H, stroke=0, fill=1)
            c.setFillColor(NAVY_DEEP)
            c.rect(0, band_top - COVER_BAND_H, PAGE_W, 2.2 * mm, stroke=0, fill=1)
            c.setFillColor(OCEAN)
            c.rect(0, band_top - COVER_BAND_H - 1.4 * mm, PAGE_W, 0.9 * mm, stroke=0, fill=1)

            c.setFillColor(PAPER)
            c.setFont("Helvetica-Bold", 17)
            c.drawString(MARGIN_X, band_top - 15 * mm, "INCOIS ARPY DECODER WORKSTATION")
            c.setFillColor(SKY_LIGHT)
            c.setFont("Helvetica", 11.5)
            c.drawString(MARGIN_X, band_top - 22 * mm, "Daily Fleet Decoding Report")
            c.setFillColor(colors.HexColor("#93C5FD"))
            c.setFont("Helvetica", 7.8)
            c.drawString(MARGIN_X, band_top - 28.5 * mm,
                         "Argo Float Telemetry Ingestion & Real-Time Quality Control — Operational Batch Report")

            batch_id = str(self.ctx.get("batch_id", ""))
            status = str(self.ctx.get("status", ""))
            c.setFont("Courier", 8)
            c.setFillColor(SKY_LIGHT)
            c.drawRightString(PAGE_W - MARGIN_X, band_top - 15 * mm, f"Batch: {batch_id}")
            badge = status.upper()
            if badge:
                c.setFont("Helvetica-Bold", 8.5)
                bw = c.stringWidth(badge, "Helvetica-Bold", 8.5) + 14
                bx = PAGE_W - MARGIN_X - bw
                by = band_top - 20.5 * mm
                color = EMERALD if status == "completed" else (ROSE if status == "error" else AMBER)
                c.setFillColor(color)
                c.roundRect(bx, by - 6, bw, 11, 2, stroke=0, fill=1)
                c.setFillColor(PAPER)
                c.drawCentredString(bx + bw / 2, by - 1.6, badge)
        else:
            # Running header
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(NAVY)
            c.drawString(MARGIN_X, PAGE_H - 10.5 * mm,
                         "INCOIS ARPY Decoder Workstation — Daily Fleet Decoding Report")
            c.setFont("Courier", 7.5)
            c.setFillColor(SLATE)
            c.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 10.5 * mm, str(self.ctx.get("batch_id", "")))
            c.setStrokeColor(LINE)
            c.setLineWidth(0.6)
            c.line(MARGIN_X, PAGE_H - 12.2 * mm, PAGE_W - MARGIN_X, PAGE_H - 12.2 * mm)

        # Footer (all pages)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.line(MARGIN_X, 11.5 * mm, PAGE_W - MARGIN_X, 11.5 * mm)
        c.setFont("Helvetica", 7)
        c.setFillColor(SLATE_LIGHT)
        c.drawString(MARGIN_X, 8.2 * mm, f"Generated: {self.ctx.get('generated', '—')}")
        c.drawCentredString(PAGE_W / 2, 8.2 * mm,
                            "INCOIS ARPY Fleet Decoder Workstation · ADMT v3.1 Compliant")
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(NAVY)
        c.drawRightString(PAGE_W - MARGIN_X, 8.2 * mm, f"Page {page} of {total}")
        c.restoreState()


# ---------------------------------------------------------------------------
# Story builders (sections 1–8)
# ---------------------------------------------------------------------------

def _s1_report_header(rep: BatchReport):
    b = rep.batch
    status = b.status.value if hasattr(b.status, "value") else str(b.status)
    rows = [
        ("Report generated", _fmt_ts(rep.generated_at)),
        ("Batch ID", _esc(b.batch_id)),
        ("Batch name", _esc(b.name or "Today's Fleet Decoding")),
        ("Batch status", status.upper()),
        ("Batch started", _fmt_ts(b.created_at)),
        ("Batch ended", _fmt_ts(b.ended_at)),
        ("Total processing duration", f"{b.duration_seconds:.2f} s" if b.duration_seconds else "—"),
        ("Floats processed", str(rep.fleet.total_floats)),
        ("Profiles generated", str(rep.fleet.total_profiles)),
        ("Deliverable files", str(rep.fleet.total_outputs)),
    ]
    data = [[Paragraph(_esc(k), S["label"]), Paragraph(v, S["cellBold"])] for k, v in rows]
    t = Table(data, colWidths=[44 * mm, USABLE_W - 44 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), ZEBRA),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return [t, Spacer(1, 4)]


def _s2_fleet_summary(rep: BatchReport):
    f = rep.fleet
    metrics = [
        ("Total floats processed", str(f.total_floats), NAVY),
        ("Successful floats", str(f.completed), EMERALD),
        ("Failed floats", str(f.failed), ROSE),
        ("Stopped floats", str(f.stopped), AMBER),
        ("Total cycles", str(f.total_cycles), OCEAN),
        ("Profiles generated", str(f.total_profiles), OCEAN),
        ("Missing profiles", str(f.total_missing), ROSE if f.total_missing else SLATE_LIGHT),
        ("NetCDF outputs", str(f.nc_outputs), NAVY),
        ("XML outputs", str(f.xml_outputs), NAVY),
    ]
    boxes = []
    for i in range(0, 9, 3):
        row = []
        for label, value, color in metrics[i:i + 3]:
            box = Table(
                [
                    [Spacer(1, 2)],
                    [Paragraph(f"<b>{_esc(value)}</b>",
                               ParagraphStyle("mv", parent=S["cell"], fontSize=15,
                                              leading=18, alignment=1, textColor=color))],
                    [Paragraph(label.upper(),
                               ParagraphStyle("ml", parent=S["label"], fontSize=6.4,
                                              leading=8.4, alignment=1))],
                ],
                colWidths=[(USABLE_W / 3) - 2],
                style=TableStyle([
                    ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                    ("BACKGROUND", (0, 0), (-1, 0), ZEBRA),
                    ("BACKGROUND", (0, 1), (-1, -1), PAPER),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 1), (-1, 1), 5),
                    ("BOTTOMPADDING", (0, 2), (-1, 2), 6),
                ]),
            )
            row.append(box)
        boxes.append(row)
    grid = Table(boxes, colWidths=[USABLE_W / 3] * 3, hAlign="LEFT")
    grid.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return [grid, Spacer(1, 4)]


def _s3_fleet_table(rep: BatchReport):
    headers = ["WMO", "Platform", "Status", "Cycles", "Profiles",
               "RTQC", "Failed", "Flagged", "Outputs"]
    data = [headers]
    for fr in rep.floats:
        data.append([
            str(fr.wmo),
            _esc(fr.platform),
            _status_cell(fr.status),
            str(fr.cycles),
            str(fr.profiles),
            str(fr.rtqc.applicable) if fr.rtqc.has_records else "—",
            str(fr.rtqc.failed) if fr.rtqc.has_records else "—",
            str(fr.rtqc.flagged_levels) if fr.rtqc.has_records else "—",
            str(fr.outputs),
        ])
    t = Table(data, colWidths=[40, 78, 56, 44, 50, 46, 46, 50, 52], repeatRows=1)
    t.setStyle(_grid_style())
    for r in range(1, len(data)):
        t.setStyle(TableStyle([
            ("ALIGN", (3, r), (8, r), "CENTER"),
            ("FONTNAME", (0, r), (0, r), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, r), (0, r), OCEAN),
        ]))
    return [t, Spacer(1, 4)]


def _s4_per_float(rep: BatchReport):
    out: list = []
    for idx, fr in enumerate(rep.floats, start=1):
        color = ("#047857" if fr.status == "completed"
                 else "#BE123C" if fr.status == "error" else "#B45309")
        out.append(Paragraph(
            f"4.{idx}&nbsp;&nbsp;WMO {fr.wmo} — {_esc(fr.platform)} / {_esc(fr.transmission)}"
            f"&nbsp;&nbsp;<font color=\"{color}\"><b>· {fr.status.upper()}</b></font>",
            S["floatTitle"],
        ))

        decoder_txt = fr.decoder_name or (f"#{fr.decoder_id}" if fr.decoder_id is not None else "—")
        facts = [
            ("Run ID", fr.run_id or "—"),
            ("Decoder", decoder_txt),
            ("Duration", f"{fr.duration:.2f} s" if fr.duration else "—"),
            ("Cycles", str(fr.cycles)),
            ("Profiles", f"{fr.profiles} ({fr.missing_profiles} missing)"),
            ("Outputs", f"{fr.outputs} file(s)"),
        ]
        # 3 label/value pairs per row, full usable width
        label_w = 46
        value_w = (USABLE_W - 3 * label_w) / 3
        frow1 = []
        frow2 = []
        for i, (k, v) in enumerate(facts):
            tgt = frow1 if i < 3 else frow2
            tgt.append(Paragraph(f'<font size="5.8" color="#64748B">{_esc(k.upper())}</font>', S["cell"]))
            tgt.append(Paragraph(_esc(str(v)), S["cellMono"] if k == "Run ID" else S["cell"]))
        ft = Table([frow1, frow2], colWidths=[label_w, value_w, label_w, value_w, label_w, value_w])
        ft.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
            ("BOX", (0, 0), (-1, -1), 0.4, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))
        out.append(ft)
        out.append(Spacer(1, 4))
        out.append(Paragraph(_esc(fr.narrative), S["body"]))

        if fr.bgc.has_bgc:
            out.append(Spacer(1, 3))
            out.append(Paragraph(
                '<font color="#1D547D"><b>BGC:</b></font> ' + _esc(fr.bgc.summary_line()),
                S["bodySmall"],
            ))

        if fr.failure:
            fa = fr.failure
            rows = [
                ("What failed", fa.what_failed),
                ("Where it failed", fa.where_failed),
                ("Why (as reported by the backend)", fa.why_failed),
                ("What had already succeeded", "; ".join(fa.succeeded)),
                ("What remains incomplete", fa.incomplete),
            ]
            data = [[Paragraph(f"<b>{_esc(k)}</b>", S["cellBold"]),
                     Paragraph(_esc(v), S["cell"])] for k, v in rows]
            ft2 = Table(data, colWidths=[46 * mm, USABLE_W - 46 * mm])
            ft2.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), ROSE_BG),
                ("BACKGROUND", (1, 0), (1, -1), PAPER),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#FECDD3")),
                ("LINEBEFORE", (1, 0), (1, -1), 0.8, ROSE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TEXTCOLOR", (0, 0), (0, -1), ROSE),
            ]))
            out.append(ft2)
            out.append(Spacer(1, 6))

        if fr.warnings:
            seen: dict[str, int] = {}
            for w in fr.warnings:
                seen[w] = seen.get(w, 0) + 1
            bits = [w if n == 1 else f"{w} (×{n})" for w, n in list(seen.items())[:6]]
            out.append(Paragraph(
                '<font color="#B45309"><b>Warnings logged:</b></font> ' + _esc(" | ".join(bits)),
                S["bodySmall"],
            ))
    return out


def _s5_pipeline(rep: BatchReport):
    chain = "  →  ".join(p.label for p in rep.pipeline)
    out = [
        Paragraph(f'<font size="7.6" color="#475569"><b>Processing flow:</b> {_esc(chain)}</font>',
                  S["bodySmall"]),
        Spacer(1, 4),
    ]
    data = [["Stage", "Evidence Basis", "Status across batch",
             "Explanation (from real run state &amp; events)"]]
    for st in rep.pipeline:
        expl = _esc(st.explanation)
        if st.sample:
            expl += f' <font size="6.8" color="#64748B">[observed: {_esc(st.sample)}]</font>'
        data.append([
            Paragraph(f"<b>{_esc(st.label)}</b>", S["cell"]),
            _basis_cell(st.basis),
            Paragraph(_esc(st.status_summary), S["cell"]),
            Paragraph(expl, S["cell"]),
        ])
    t = Table(data, colWidths=[30 * mm, 24 * mm, 38 * mm, USABLE_W - 92 * mm], repeatRows=1)
    t.setStyle(_grid_style())
    out.append(t)
    out.append(Spacer(1, 3))
    out.append(Paragraph(
        "Basis key — <b>OBSERVED</b>: direct backend events recorded in the run event log. "
        "<b>VERIFIED PRODUCT</b>: confirmed through on-disk deliverables (no dedicated backend event is emitted for that stage). "
        "<b>INFERRED</b>: pipeline lifecycle stage confirmed by downstream stage success (no direct event). "
        "<b>NOT REACHED</b>: no float executed the stage.",
        S["note"],
    ))
    return out


def _s6_rtqc(rep: BatchReport):
    out: list = []
    for idx, fr in enumerate(rep.floats, start=1):
        r = fr.rtqc
        heading = f"6.{idx}&nbsp;&nbsp;WMO {fr.wmo} ({_esc(fr.platform)})"
        if not r.has_records:
            out.append(Paragraph(heading + "&nbsp;&nbsp;<font color=\"#64748B\">— no RTQC records in this run</font>",
                                 S["floatTitle"]))
            continue
        out.append(Paragraph(heading, S["floatTitle"]))
        metrics = [
            ("APPLICABLE TESTS", str(r.applicable), NAVY),
            ("EXECUTED TESTS", str(r.executed), NAVY),
            ("FAILED TESTS", str(r.failed), ROSE if r.failed else SLATE_LIGHT),
            ("FLAGGED MEASUREMENTS", str(r.flagged_levels), ROSE if r.flagged_levels else NAVY),
        ]
        mrow_labels = [Paragraph(f'<font size="6.2" color="#64748B">{k}</font>',
                                 ParagraphStyle("ml2", parent=S["cell"], alignment=1)) for k, _, _ in metrics]
        mrow_values = [Paragraph(f"<b>{_esc(v)}</b>",
                                 ParagraphStyle("rv", parent=S["cell"], fontSize=9.5, leading=12,
                                                alignment=1, textColor=col)) for _, v, col in metrics]
        mt = Table([mrow_labels, mrow_values], colWidths=[USABLE_W / 4] * 4)
        mt.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.4, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
            ("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        out.append(mt)
        out.append(Spacer(1, 3))

        if r.per_test:
            tdata = [["Test ID", "Test", "Pass", "Status", "Failed", "Flagged Levels"]]
            for t in r.per_test:
                tdata.append([
                    t["test_id"],
                    _esc(t["name"]),
                    t["pass"].replace("PASS_", ""),
                    Paragraph(f'<font color="{"#BE123C" if t["failed"] else "#047857"}"><b>{t["status"]}</b></font>',
                              S["cell"]),
                    "yes" if t["failed"] else "—",
                    str(t["flagged"]) if t["flagged"] is not None else "—",
                ])
            tt = Table(tdata, colWidths=[24 * mm, 62 * mm, 16 * mm, 30 * mm, 20 * mm, 24 * mm], repeatRows=1)
            tt.setStyle(_grid_style())
            for rix in range(1, len(tdata)):
                tt.setStyle(TableStyle([
                    ("FONTNAME", (0, rix), (0, rix), "Courier"),
                    ("FONTSIZE", (0, rix), (0, rix), 6.4),
                    ("ALIGN", (2, rix), (5, rix), "CENTER"),
                ]))
            out.append(tt)
            if r.not_executed_count:
                out.append(Paragraph(
                    f"{r.not_executed_count} further Table 11 test(s) are defined but were not executed for this float.",
                    S["note"],
                ))
        for n in r.notes:
            out.append(Paragraph(f"• {_esc(n)}", S["bodySmall"]))
        out.append(Spacer(1, 4))
    out.append(Paragraph(
        "Per-test flagged-level counts are not recorded by the backend for this decoder build; flagged measurements are "
        "reported per float above (degraded QC flag 3/4 across PRES/TEMP/PSAL). Test status is verified from the QCP$/QCF$ "
        "masks stored in the generated profile NetCDF files.",
        S["note"],
    ))
    return out


CAT_LABELS = {
    "mono_profile": "Profile NetCDF (individual cycle)",
    "multi_profile": "Multi-profile NetCDF",
    "meta": "Meta NetCDF",
    "tech": "Technical NetCDF",
    "traj": "Trajectory NetCDF",
    "xml": "Coriolis XML report",
    "other": "Other",
}


def _s7_deliverables(rep: BatchReport):
    out: list = []
    total_files = sum(len(fr.files) for fr in rep.floats)
    if total_files == 0:
        out.append(Paragraph("No deliverable files were produced in this batch.", S["body"]))
        return out

    for idx, fr in enumerate(rep.floats, start=1):
        out.append(Paragraph(f"7.{idx}&nbsp;&nbsp;WMO {fr.wmo} — {len(fr.files)} file(s)", S["floatTitle"]))
        if not fr.files:
            out.append(Paragraph("<font color=\"#64748B\">No deliverable files for this float in this run.</font>",
                                 S["bodySmall"]))
            out.append(Spacer(1, 3))
            continue
        data = [["File", "Category", "Size", "Dimensions", "SHA-256 (first 16)", "Validation"]]
        for f in fr.files:
            dims = ", ".join(f"{k}={v}" for k, v in sorted(f.dimensions.items(), key=lambda kv: -kv[1])[:3])
            if len(f.dimensions) > 3:
                dims += f" (+{len(f.dimensions) - 3})"
            checksum = f.checksum_sha256 or "—"
            data.append([
                Paragraph(_esc(f.filename), S["cellMono"]),
                Paragraph(_esc(CAT_LABELS.get(f.category, f.category)), S["cell"]),
                _fmt_bytes(f.size_bytes),
                Paragraph(_esc(dims) if dims else "—", S["cellMono"]),
                Paragraph(_esc(checksum[:16] + "…"), S["cellMono"]),
                Paragraph(
                    f'<font color="{"#047857" if f.validation == "verified" else "#BE123C"}">'
                    f"<b>{_esc(f.validation)}</b></font>",
                    S["cell"],
                ),
            ])
        t = Table(data, colWidths=[48 * mm, 30 * mm, 16 * mm, 30 * mm, 34 * mm, USABLE_W - 158 * mm],
                  repeatRows=1)
        t.setStyle(_grid_style())
        for rix in range(1, len(data)):
            t.setStyle(TableStyle([("ALIGN", (2, rix), (2, rix), "RIGHT")]))
        out.append(t)
        out.append(Spacer(1, 4))
    out.append(Paragraph(
        "Validation: “verified” = file present on disk and successfully indexed (NetCDF opened, dimensions and checksum "
        "read) at report generation time. “missing on disk” = file listed in the run record but not found at report "
        "generation time. Full 64-character SHA-256 checksums are recorded in the run history and on the Results page.",
        S["note"],
    ))
    return out


def _s8_assessment(rep: BatchReport):
    return [Paragraph(_esc(rep.assessment), S["body"]), Spacer(1, 8)]


# ---------------------------------------------------------------------------
# Render / generate / save
# ---------------------------------------------------------------------------

def render_batch_report_pdf(rep: BatchReport) -> tuple[bytes, int]:
    """Renders the report. Returns (pdf_bytes, page_count)."""
    batch = rep.batch
    status = batch.status.value if hasattr(batch.status, "value") else str(batch.status)
    ctx: dict[str, Any] = {
        "batch_id": batch.batch_id,
        "status": status,
        "generated": _fmt_ts(rep.generated_at),
        "pages": 0,
    }

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"INCOIS ARPY Daily Fleet Decoding Report — {batch.batch_id}",
        author="INCOIS ARPY Decoder Workstation",
        subject="Daily fleet decoding batch report",
    )

    frame_first = Frame(
        MARGIN_X, MARGIN_BOTTOM, USABLE_W,
        PAGE_H - MARGIN_BOTTOM - COVER_CONTENT_FROM_TOP,
        id="first", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    frame_rest = Frame(
        MARGIN_X, MARGIN_BOTTOM, USABLE_W,
        PAGE_H - MARGIN_BOTTOM - 15 * mm,
        id="rest", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.pageTemplates = [
        PageTemplate(id="first", frames=[frame_first]),
        PageTemplate(id="rest", frames=[frame_rest]),
    ]

    def _make_canvas(ctx_value: dict):
        class _CanvasMaker(_ReportCanvas):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, ctx=ctx_value, **kwargs)

        return _CanvasMaker

    story: list = [NextPageTemplate("rest")]
    story += _section("1", "Report Header")
    story += _s1_report_header(rep)
    story += _section("2", "Fleet Summary",
                      "Fleet-wide execution totals — read directly from the authoritative batch record.")
    story += _s2_fleet_summary(rep)
    story += _section("3", "Fleet Table", "Per-float execution results for the whole batch.")
    story += _s3_fleet_table(rep)
    story += _section("4", "Per-Float Natural-Language Report",
                      "Complete execution narrative for every float, from input discovery to final status, "
                      "based on actual run events and verified deliverables.")
    story += _s4_per_float(rep)
    story += _section("5", "Pipeline Summary",
                      "The actual processing flow and, for each stage, the evidence basis "
                      "(directly observed backend events vs inferred lifecycle stages).")
    story += _s5_pipeline(rep)
    story += _section("6", "RTQC Summary",
                      "Argo Table 11 real-time quality control per float — applicable, executed and failed tests, "
                      "flagged measurements and relevant notes.")
    story += _s6_rtqc(rep)
    story += _section("7", "Deliverables",
                      "Actual generated files with category, size, dimensions, checksum and validation status.")
    story += _s7_deliverables(rep)
    story += _section("8", "Final Batch Assessment", "Natural-language conclusion of the batch operation.")
    story += _s8_assessment(rep)

    doc.build(story, canvasmaker=_make_canvas(ctx))
    return buf.getvalue(), int(ctx.get("pages") or 0)


def report_file_name(batch_id: str) -> str:
    return f"INCOIS-ARPY-Daily-Fleet-Decoding-Report-{batch_id}.pdf"


def report_file_path(batch_id: str) -> Path:
    return REPORTS_DIR / report_file_name(batch_id)


def generate_batch_report_pdf(batch_id: str) -> dict:
    """Builds, renders and persists the PDF report for a batch.

    Returns a metadata dict: {status, generated_at, size_bytes, pages, error}.
    A failure here is recorded by the caller on the batch record; it never
    alters the decoder/batch result.
    """
    from report_data import build_batch_report_data

    try:
        report = build_batch_report_data(batch_id)
        pdf_bytes, pages = render_batch_report_pdf(report)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = report_file_path(batch_id)
        tmp = path.with_suffix(".pdf.tmp")
        tmp.write_bytes(pdf_bytes)
        tmp.replace(path)
        return {
            "status": "generated",
            "generated_at": utc_now_iso(),
            "size_bytes": len(pdf_bytes),
            "pages": pages,
            "filepath": str(path),
            "filename": report_file_name(batch_id),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — report failure must be recorded, not raised
        return {
            "status": "failed",
            "generated_at": utc_now_iso(),
            "size_bytes": None,
            "pages": None,
            "filepath": None,
            "filename": report_file_name(batch_id),
            "error": f"{type(exc).__name__}: {exc}",
        }
