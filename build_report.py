"""Render the completed study report from Markdown to an embedded-font PDF."""

import argparse
import os
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def text_markup(text):
    result = escape(text)
    # Make reference URLs clickable without exposing local file locations.
    return re.sub(r"https://[^\s（）]+", lambda match: '<link href="' + match.group() + '" color="#244B66">' + match.group() + '</link>', result)


def render_report(source, output, regular_font, bold_font):
    pdfmetrics.registerFont(TTFont("ReportBody", str(regular_font), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("ReportBold", str(bold_font), subfontIndex=0))
    pdfmetrics.registerFontFamily("ReportBody", normal="ReportBody", bold="ReportBold", italic="ReportBody", boldItalic="ReportBold")
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height = A4
    content_width = width - 100
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=50, leftMargin=50,
                            topMargin=43, bottomMargin=45, title="序列呈现 Gabor 光栅的方位差辨别实验报告",
                            author="", creator="", subject="Orientation discrimination study", pageCompression=1)
    base = dict(fontName="ReportBody", textColor=colors.black, wordWrap="CJK", splitLongWords=True)
    styles = {
        "body": ParagraphStyle("Body", fontSize=10.5, leading=15, spaceAfter=5, alignment=TA_JUSTIFY, **base),
        "title": ParagraphStyle("Title", fontSize=19, leading=27, spaceAfter=12, alignment=TA_CENTER, fontName="ReportBold", textColor=colors.black, wordWrap="CJK"),
        "h1": ParagraphStyle("H1", fontSize=13.5, leading=21, spaceBefore=9, spaceAfter=6, keepWithNext=True, fontName="ReportBold", textColor=colors.black, wordWrap="CJK"),
        "h2": ParagraphStyle("H2", fontSize=11.5, leading=18, spaceBefore=7, spaceAfter=5, keepWithNext=True, fontName="ReportBold", textColor=colors.black, wordWrap="CJK"),
        "caption": ParagraphStyle("Caption", fontSize=9, leading=13, spaceAfter=7, **base),
        "table_title": ParagraphStyle("TableTitle", fontSize=9.5, leading=14, spaceBefore=4, spaceAfter=5, keepWithNext=True, **base),
        "cell": ParagraphStyle("Cell", fontSize=9.2, leading=13, alignment=TA_CENTER, **base),
        "note": ParagraphStyle("Note", fontSize=9, leading=13, spaceAfter=8, **base),
        "ref": ParagraphStyle("Reference", fontSize=9.5, leading=15, spaceAfter=9, alignment=TA_LEFT, **base),
        "equation": ParagraphStyle("Equation", fontSize=10, leading=16, spaceAfter=6, alignment=TA_CENTER, **base),
    }
    lines = source.read_text(encoding="utf-8").splitlines()
    story = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue
        if line == "<!-- pagebreak -->":
            story.append(PageBreak())
            continue
        if line.startswith("# "):
            story.append(Paragraph(text_markup(line[2:]), styles["title"]))
            continue
        if line.startswith("### ") or line.startswith("## "):
            prefix = "### " if line.startswith("### ") else "## "
            story.append(Paragraph(text_markup(line[len(prefix):]), styles["h2" if prefix == "### " else "h1"]))
            continue
        if line.startswith("!["):
            match = re.fullmatch(r"!\[(.*?)\]\((.*?)\)", line)
            path = source.parent / match.group(2)
            image = Image(str(path))
            image.drawHeight *= content_width / image.drawWidth
            image.drawWidth = content_width
            # Keep the caption with the figure on the same page.
            while index < len(lines) and not lines[index].strip():
                index += 1
            items = [image, Spacer(1, 4)]
            if index < len(lines) and re.match(r"图\s*\d", lines[index]):
                items.append(Paragraph(text_markup(lines[index]), styles["caption"]))
                index += 1
            story.append(KeepTogether(items))
            continue
        if line.startswith("|"):
            raw = [line]
            while index < len(lines) and lines[index].strip().startswith("|"):
                raw.append(lines[index].strip())
                index += 1
            rows = [[cell.strip() for cell in item.strip("|").split("|")] for item in raw if not re.fullmatch(r"[|\s:\-]+", item)]
            n = len(rows[0])
            widths = {8: [48, 44, 44, 44, 44, 44, 44, 92], 6: [48, 85, 76, 91, 91, 75], 5: [55, 105, 110, 110, 92]}.get(n, [1] * n)
            widths = [x / sum(widths) * content_width for x in widths]
            table = Table([[Paragraph(text_markup(cell), styles["cell"]) for cell in row] for row in rows], colWidths=widths, repeatRows=1, hAlign="CENTER")
            table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF1F4")),
                                       ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#D9D9D9")),
                                       ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                       ("TOPPADDING", (0, 0), (-1, -1), 5),
                                       ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 4),
                                       ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
            story.extend([table, Spacer(1, 8)])
            continue
        if line.startswith("表 "):
            style = "table_title"
        elif line.startswith("注：") or line.startswith("实验日期：") or line.startswith("关键词："):
            style = "note"
        elif re.match(r"\[\d\]", line):
            style = "ref"
        elif re.match(r"^(Hδ|C|BAδ|δ75) = ", line):
            style = "equation"
        else:
            style = "body"
        story.append(Paragraph(text_markup(line), styles[style]))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("ReportBody", 8.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawCentredString(width / 2, 25, str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("Report PDF created.")


def main():
    windows_directory = os.environ.get("WINDIR")
    fonts = Path(windows_directory) / "Fonts" if windows_directory else Path("fonts")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("docs/experiment_report.md"))
    parser.add_argument("--output", type=Path, default=Path("output/pdf/experiment_report.pdf"))
    parser.add_argument("--regular-font", type=Path, default=fonts / "simsun.ttc")
    parser.add_argument("--bold-font", type=Path, default=fonts / "simhei.ttf")
    args = parser.parse_args()
    render_report(args.source, args.output, args.regular_font, args.bold_font)


if __name__ == "__main__":
    main()
