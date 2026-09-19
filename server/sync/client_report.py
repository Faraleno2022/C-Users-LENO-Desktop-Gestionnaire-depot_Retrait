"""PDF des soldes clients partagé par le site, la console et le bureau."""
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


def build_client_pdf(title, headers, rows, subtitle=""):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), title=title,
                           leftMargin=15*mm, rightMargin=15*mm,
                           topMargin=15*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()
    cell_styles = {}
    for name, align in (("text", TA_LEFT), ("amount", TA_RIGHT), ("center", TA_CENTER)):
        cell_styles[name] = ParagraphStyle(name, fontName="Helvetica", fontSize=8,
                                          leading=11, alignment=align, splitLongWords=True)
    heading = ParagraphStyle("heading", parent=cell_styles["text"],
                             fontName="Helvetica-Bold", textColor=colors.white)
    data = [[Paragraph(escape(str(h)), heading) for h in headers]]
    for row in rows:
        data.append([Paragraph(escape(str(value)) if value is not None else "",
                              cell_styles["amount" if col in (3, 4) else "text"])
                     for col, value in enumerate(row)])
    table = LongTable(data, colWidths=[n*mm for n in (38, 88, 44, 43, 26, 28)],
                      repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F1F5F9"), colors.white]),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1F4E78")),
        ("LINEBELOW", (0, 1), (-1, -1), .25, colors.HexColor("#CBD5E1")),
    ]
    if rows:
        commands.extend([
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#DBEAFE")),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#1F4E78")),
        ])
    table.setStyle(TableStyle(commands))
    story = [Paragraph(escape(title), styles["Title"])]
    if subtitle:
        story.append(Paragraph(escape(subtitle), styles["Normal"]))
    story += [Spacer(1, 6*mm), table]

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#475569"))
        canvas.drawString(15*mm, 10*mm, "EMAB GROUP - Clients et soldes")
        canvas.drawRightString(282*mm, 10*mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
