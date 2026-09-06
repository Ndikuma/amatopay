"""Render docs/AMATOPAY_FUNCTIONALITY.md to a branded PDF report.

    python manage.py functionality_report
    python manage.py functionality_report --source docs/AMATOPAY_FUNCTIONALITY.md \
        --output build/AmatoPay-Functionality-Report.pdf

Supports a small Markdown subset: #/##/### headings, paragraphs with **bold**
and `code`, "- " bullets, GitHub-style | tables |, ``` fenced code blocks, and a
literal <<<PAGEBREAK>>> line. The first level-1 heading becomes the cover title.
"""

import html
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

TEAL = "#0d897f"
NAVY = "#071f2b"
INK = "#16313b"
MUTED = "#5f747b"
LINE = "#d9e2e3"


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+?)`", r'<font face="Courier" size="8.5">\1</font>', text)
    return text


class Command(BaseCommand):
    help = "Render the AmatoPay functionality report (Markdown) to a branded PDF."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="docs/AMATOPAY_FUNCTIONALITY.md")
        parser.add_argument("--output", default="build/AmatoPay-Functionality-Report.pdf")

    def handle(self, *args, **opts):
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                HRFlowable, PageBreak, Paragraph, Preformatted,
                SimpleDocTemplate, Spacer, Table, TableStyle,
            )
        except ImportError as exc:  # pragma: no cover
            raise CommandError("reportlab is required: pip install reportlab") from exc

        src = (settings.BASE_DIR / opts["source"]) if not Path(opts["source"]).is_absolute() else Path(opts["source"])
        if not src.exists():
            raise CommandError(f"Source not found: {src}")
        out = Path(opts["output"])
        if not out.is_absolute():
            out = settings.BASE_DIR / out
        out.parent.mkdir(parents=True, exist_ok=True)

        lines = src.read_text(encoding="utf-8").splitlines()

        base = getSampleStyleSheet()
        styles = {
            "h1": ParagraphStyle("h1", parent=base["Heading1"], fontSize=17, leading=21,
                                 spaceBefore=18, spaceAfter=8, textColor=colors.HexColor(NAVY)),
            "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, leading=17,
                                 spaceBefore=14, spaceAfter=6, textColor=colors.HexColor(TEAL)),
            "h3": ParagraphStyle("h3", parent=base["Heading3"], fontSize=10.5, leading=14,
                                 spaceBefore=10, spaceAfter=3, textColor=colors.HexColor(NAVY)),
            "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=9.3, leading=13.5,
                                   textColor=colors.HexColor(INK), spaceAfter=6),
            "bullet": ParagraphStyle("bullet", parent=base["BodyText"], fontSize=9.3, leading=12.5,
                                     textColor=colors.HexColor(INK), spaceAfter=4,
                                     leftIndent=14, bulletIndent=2),
            "bullet2": ParagraphStyle("bullet2", parent=base["BodyText"], fontSize=9, leading=12,
                                      textColor=colors.HexColor(INK), spaceAfter=3,
                                      leftIndent=30, bulletIndent=18),
            "eyebrow": ParagraphStyle("eyebrow", parent=base["BodyText"], fontSize=9.5,
                                      alignment=TA_CENTER, textColor=colors.HexColor(TEAL)),
            "cell": ParagraphStyle("cell", parent=base["BodyText"], fontSize=8.2, leading=10.5,
                                   textColor=colors.HexColor(INK)),
            "cellh": ParagraphStyle("cellh", parent=base["BodyText"], fontSize=8.2, leading=10.5,
                                    textColor=colors.white, fontName="Helvetica-Bold"),
            "cover_title": ParagraphStyle("ct", parent=base["Title"], fontSize=30, leading=34,
                                          textColor=colors.HexColor(NAVY)),
            "cover_sub": ParagraphStyle("cs", parent=base["BodyText"], fontSize=11, leading=17,
                                        alignment=TA_CENTER, textColor=colors.HexColor(MUTED)),
        }

        story = []
        title = "AmatoPay"
        i = 0
        # Cover: consume the first "# ..." + following non-blank lines.
        while i < len(lines) and not lines[i].startswith("# "):
            i += 1
        if i < len(lines):
            title = lines[i][2:].strip()
            i += 1
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        cover_meta = []
        while i < len(lines) and lines[i].strip() not in ("", "---"):
            cover_meta.append(lines[i].strip())
            i += 1

        story += [
            Spacer(1, 60 * mm),
            Paragraph("CONFIDENTIAL", styles["eyebrow"]),
            Spacer(1, 7 * mm),
            Paragraph(title, styles["cover_title"]),
            Spacer(1, 12 * mm),
        ]
        for m in cover_meta:
            story.append(Paragraph(_inline(m), styles["cover_sub"]))
        story += [
            Spacer(1, 14 * mm),
            HRFlowable(width="40%", thickness=1, color=colors.HexColor(TEAL)),
            Spacer(1, 6 * mm),
            Paragraph(
                f"Generated {timezone.localtime().strftime('%d %B %Y, %H:%M')} · Confidential — internal",
                styles["cover_sub"],
            ),
            PageBreak(),
        ]

        def flush_table(rows):
            if not rows:
                return
            body = [r for r in rows if not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", r)]
            grid = []
            for r in body:
                cells = [c.strip() for c in r.strip().strip("|").split("|")]
                grid.append(cells)
            if not grid:
                return
            ncol = max(len(r) for r in grid)
            grid = [r + [""] * (ncol - len(r)) for r in grid]
            data = [[Paragraph(_inline(c), styles["cellh"] if ri == 0 else styles["cell"])
                     for c in row] for ri, row in enumerate(grid)]
            usable = 170 * mm
            first = 0.34 if ncol <= 3 else 0.2
            widths = [usable * first] + [usable * (1 - first) / (ncol - 1)] * (ncol - 1) if ncol > 1 else [usable]
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(TEAL)),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5faf9")]),
            ]))
            story.append(Spacer(1, 2))
            story.append(t)
            story.append(Spacer(1, 8))

        code_style = ParagraphStyle(
            "code", fontName="Courier", fontSize=7.8, leading=10.5,
            textColor=colors.HexColor("#cfe6e4"),
        )

        def code_block(text):
            inner = Preformatted(text, code_style)
            t = Table([[inner]], colWidths=[170 * mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0b2934")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]))
            return t

        state = {"table": [], "code": None, "bullets": [], "para": []}

        def flush_para():
            if state["para"]:
                story.append(Paragraph(_inline(" ".join(state["para"])), styles["body"]))
                state["para"] = []

        def flush_bullets():
            if not state["bullets"]:
                return
            for level, text in state["bullets"]:
                st = styles["bullet2"] if level else styles["bullet"]
                dot = "–" if level else "•"
                colour = MUTED if level else TEAL
                story.append(Paragraph(
                    f'<font color="{colour}">{dot}</font>&nbsp;&nbsp;' + _inline(text),
                    ParagraphStyle("b", parent=st, firstLineIndent=-(st.leftIndent - st.bulletIndent)),
                ))
            story.append(Spacer(1, 5))
            state["bullets"] = []

        def flush_table():
            rows = state["table"]
            state["table"] = []
            body = [r for r in rows if not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", r)]
            grid = [[c.strip() for c in r.strip().strip("|").split("|")] for r in body]
            if not grid:
                return
            ncol = max(len(r) for r in grid)
            grid = [r + [""] * (ncol - len(r)) for r in grid]
            data = [[Paragraph(_inline(c), styles["cellh"] if ri == 0 else styles["cell"])
                     for c in row] for ri, row in enumerate(grid)]
            usable = 170 * mm
            first = 0.34 if ncol <= 3 else 0.2
            widths = ([usable * first] + [usable * (1 - first) / (ncol - 1)] * (ncol - 1)
                      if ncol > 1 else [usable])
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(TEAL)),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5faf9")]),
            ]))
            story.extend([Spacer(1, 2), t, Spacer(1, 9)])

        def flush_all():
            flush_para(); flush_bullets(); flush_table()

        for raw in lines[i:]:
            line = raw.rstrip()
            stripped = line.strip()

            if state["code"] is not None:
                if stripped.startswith("```"):
                    story.append(code_block("\n".join(state["code"])))
                    story.append(Spacer(1, 8))
                    state["code"] = None
                else:
                    state["code"].append(raw)
                continue
            if stripped.startswith("```"):
                flush_all()
                state["code"] = []
                continue

            if line.startswith("|"):
                flush_para(); flush_bullets()
                state["table"].append(line)
                continue
            if state["table"]:
                flush_table()

            if stripped == "":
                flush_para(); flush_bullets()
            elif stripped == "<<<PAGEBREAK>>>":
                flush_all(); story.append(PageBreak())
            elif stripped == "---":
                flush_all()
                story.append(HRFlowable(width="100%", thickness=0.5,
                                        color=colors.HexColor(LINE), spaceBefore=6, spaceAfter=6))
            elif line.startswith("### "):
                flush_all(); story.append(Paragraph(_inline(stripped[4:]), styles["h3"]))
            elif line.startswith("## "):
                flush_all(); story.append(Paragraph(_inline(stripped[3:]), styles["h2"]))
            elif line.startswith("# "):
                flush_all(); story.append(Paragraph(_inline(stripped[2:]), styles["h1"]))
            elif re.match(r"^\s*-\s+", line):
                flush_para()
                indent = len(line) - len(line.lstrip())
                state["bullets"].append([1 if indent >= 2 else 0, re.sub(r"^\s*-\s+", "", line)])
            elif state["bullets"]:
                state["bullets"][-1][1] += " " + stripped
            else:
                state["para"].append(stripped)

        flush_all()

        def _footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(colors.HexColor(MUTED))
            canvas.drawString(20 * mm, 12 * mm, f"{settings.COMPANY_NAME} — AmatoPay functionality report")
            canvas.drawRightString(190 * mm, 12 * mm, f"Page {doc.page}")
            canvas.setStrokeColor(colors.HexColor(LINE))
            canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
            canvas.restoreState()

        doc = SimpleDocTemplate(
            str(out), pagesize=A4,
            leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
            title=title, author=settings.COMPANY_NAME,
        )
        doc.build(story, onLaterPages=_footer)
        self.stdout.write(self.style.SUCCESS(f"Wrote {out} ({out.stat().st_size // 1024} KB)"))
