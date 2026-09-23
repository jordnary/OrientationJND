"""Render the completed study report from Markdown to an embedded-font PDF."""

import argparse
import os
import re
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from matplotlib import get_data_path
from matplotlib.font_manager import FontProperties
from matplotlib.mathtext import MathTextParser
from pypdf import PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


class MathEquation(Flowable):
    """Draw typeset mathematics as searchable vector glyphs and fraction rules."""

    def __init__(self, expression, font_size=11.5):
        super().__init__()
        self.math = MathTextParser("path").parse(
            f"${expression}$", dpi=72,
            prop=FontProperties(size=font_size, math_fontfamily="stix"))
        self.width = float(self.math.width)
        self.height = float(self.math.height) + 4
        self.hAlign = "CENTER"
        self.spaceBefore = 4
        self.spaceAfter = 8
        self.glyphs = []
        for font, size, character, *position in self.math.glyphs:
            # Newer Matplotlib releases also include a glyph index before x/y.
            x, y = position[-2:]
            font_name = "Equation-" + Path(font.fname).stem
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, font.fname))
            self.glyphs.append((font_name, size, chr(character), x, y))

    def wrap(self, available_width, available_height):
        if self.width > available_width:
            raise ValueError("Display equation exceeds the report column width")
        return self.width, self.height

    def draw(self):
        self.canv.saveState()
        self.canv.setFillColor(colors.black)
        baseline = float(self.math.depth) + 2
        for font, size, character, x, y in self.glyphs:
            self.canv.setFont(font, size)
            self.canv.drawString(float(x), float(y) + baseline, character)
        for x, y, width, height in self.math.rects:
            self.canv.rect(float(x), float(y) + baseline,
                           float(width), float(height), stroke=0, fill=1)
        self.canv.restoreState()


def inline_math(expression):
    """Keep short inline variables in a math font with real subscripts."""
    match = re.fullmatch(r"(\\mathrm\{BA\}|[A-Za-z]|\\delta)(?:_\{?(\\delta|\d+)\}?)?", expression)
    if match is None:
        raise ValueError("Unsupported inline math expression")
    symbol, subscript = match.groups()
    font_name = "ReportMath" if symbol == r"\mathrm{BA}" else "ReportMathItalic"
    symbol = "BA" if symbol == r"\mathrm{BA}" else symbol.replace(r"\delta", "δ")
    result = f'<font name="{font_name}">{symbol}</font>'
    if subscript:
        subscript_font = "ReportMathItalic" if subscript == r"\delta" else "ReportMath"
        subscript = subscript.replace(r"\delta", "δ")
        result += f'<sub rise="20%" size="70%"><font name="{subscript_font}">{subscript}</font></sub>'
    return "<nobr>" + result + "</nobr>"


class ReportDocTemplate(SimpleDocTemplate):
    """Attach navigation bookmarks to the rendered section headings."""

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and hasattr(flowable, "outline_level"):
            # Use the final page and position after pagination, including splits.
            key = f"section-{self.seq.nextf('outline')}"
            heading_top = self.frame._y + flowable.height + flowable.getSpaceAfter()
            self.canv.bookmarkHorizontalAbsolute(key, heading_top)
            self.canv.addOutlineEntry(flowable.getPlainText(), key,
                                     level=flowable.outline_level, closed=False)


def text_markup(text):
    result = escape(text)
    result = re.sub(r"\$([^$]+)\$", lambda match: inline_math(match.group(1)), result)
    # Make reference URLs clickable without exposing local file locations.
    return re.sub(r"https://[^\s（）]+", lambda match: '<link href="' + match.group() + '" color="#244B66">' + match.group() + '</link>', result)


def render_report(source, output, regular_font, bold_font):
    pdfmetrics.registerFont(TTFont("ReportBody", str(regular_font), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("ReportBold", str(bold_font), subfontIndex=0))
    pdfmetrics.registerFontFamily("ReportBody", normal="ReportBody", bold="ReportBold", italic="ReportBody", boldItalic="ReportBold")
    math_fonts = Path(get_data_path()) / "fonts" / "ttf"
    pdfmetrics.registerFont(TTFont("ReportMath", str(math_fonts / "STIXGeneral.ttf")))
    pdfmetrics.registerFont(TTFont("ReportMathItalic", str(math_fonts / "STIXGeneralItalic.ttf")))
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = source.read_text(encoding="utf-8").splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), "实验报告")
    pdf_buffer = BytesIO()
    width, height = A4
    content_width = width - 100
    doc = ReportDocTemplate(pdf_buffer, pagesize=A4, rightMargin=50, leftMargin=50,
                            topMargin=43, bottomMargin=45, title=title,
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
    }
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
        if line.startswith("$$") and line.endswith("$$"):
            story.append(MathEquation(line[2:-2].strip()))
            continue
        if line.startswith("# "):
            story.append(Paragraph(text_markup(line[2:]), styles["title"]))
            continue
        if line.startswith("### ") or line.startswith("## "):
            prefix = "### " if line.startswith("### ") else "## "
            heading = Paragraph(text_markup(line[len(prefix):]), styles["h2" if prefix == "### " else "h1"])
            heading.outline_level = 1 if prefix == "### " else 0
            story.append(heading)
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
        elif line.startswith("注：") or line.startswith("关键词："):
            style = "note"
        elif re.match(r"\[\d\]", line):
            style = "ref"
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
    pdf_buffer.seek(0)
    writer = PdfWriter(clone_from=pdf_buffer)
    # ReportLab adds calendar metadata automatically; the submission omits it.
    writer.metadata = {key: value for key, value in writer.metadata.items()
                       if key not in {"/CreationDate", "/ModDate"}}
    writer.page_mode = "/UseOutlines"
    writer.write(output)
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
