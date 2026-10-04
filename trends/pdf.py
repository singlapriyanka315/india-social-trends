"""Render the daily trends report as a PDF with ReportLab.

Built-in Helvetica keeps the PDF identical on every machine, but it cannot draw
Hindi, Bengali etc. That's fine here: the LLM gives every topic an English name.
Raw titles in other scripts are shown as a plain "source link" instead.
"""

from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#616e7c")
RULE = colors.HexColor("#d9dee5")
ROW_ALT = colors.HexColor("#f5f7fa")
ONE_PLATFORM = colors.HexColor("#93a4bb")
MULTI_PLATFORM = colors.HexColor("#c2410c")
NEW = "#047857"
LINK = "#1d4ed8"

REPLACE = {"₹": "Rs ", "‑": "-", "‐": "-", "−": "-", " ": " ",
           " ": " ", " ": " ", "≈": "~", "🆕": ""}


def _latin(text):
    for bad, good in REPLACE.items():
        text = text.replace(bad, good)
    return text.encode("cp1252", errors="replace").decode("cp1252")


def clean(text):
    return escape(_latin(text or ""))


def is_drawable(text):
    """False when Helvetica can't draw most of the text (Hindi, Bengali, ...)."""
    for bad, good in REPLACE.items():
        text = text.replace(bad, good)
    undrawable = sum(1 for ch in text if not ch.encode("cp1252", errors="ignore"))
    return undrawable <= len(text) * 0.2


def _styles():
    base = getSampleStyleSheet()
    p = lambda name, **kw: ParagraphStyle(name, parent=base["Normal"], **{"textColor": INK, **kw})
    return {
        "title": p("title", fontName="Helvetica-Bold", fontSize=22, leading=26, spaceAfter=2),
        "sub": p("sub", fontSize=9, textColor=MUTED, spaceAfter=10),
        "h2": p("h2", fontName="Helvetica-Bold", fontSize=13, leading=16, spaceBefore=12, spaceAfter=6),
        "h3": p("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=13, spaceBefore=8, spaceAfter=1),
        "body": p("body", fontSize=9.5, leading=13.5),
        "small": p("small", fontSize=8, leading=11, textColor=MUTED),
        "link": p("link", fontSize=8.5, leading=11.5, leftIndent=8),
        "cell": p("cell", fontSize=8.8, leading=11),
        "num": p("num", fontSize=8.8, leading=11, alignment=2),
    }


def _table(group, st):
    head = ["#", "Topic", "Category", "Platforms", "Days", "Score"]
    rows = [[Paragraph(f"<b>{h}</b>", st["num"] if h in ("#", "Days", "Score") else st["cell"]) for h in head]]
    for t in group:
        new = f' <font color="{NEW}" size="7"><b>NEW</b></font>' if t["is_new"] else ""
        plat = ", ".join(t["platforms_list"])
        if t["platforms"] > 1:
            plat = f'<font color="#c2410c"><b>{plat}</b></font>'
        rows.append([
            Paragraph(str(t["position"]), st["num"]),
            Paragraph(clean(t["label"]) + new, st["cell"]),
            Paragraph(clean((t["category"] or "-").title()), st["cell"]),
            Paragraph(plat, st["cell"]),
            Paragraph(str(t["days_trending"]), st["num"]),
            Paragraph(f"{t['score']:.2f}", st["num"]),
        ])
    tbl = Table(rows, colWidths=[8 * mm, 72 * mm, 26 * mm, 36 * mm, 12 * mm, 16 * mm], repeatRows=1)
    style = [("LINEBELOW", (0, 0), (-1, 0), 0.8, INK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]
    style += [("BACKGROUND", (0, r), (-1, r), ROW_ALT) for r in range(2, len(rows), 2)]
    tbl.setStyle(TableStyle(style))
    return tbl


def _chart(group):
    items = list(reversed(group))  # drawn bottom-up, so reverse to put #1 on top
    width, height = 174 * mm, 16 * mm + 7.5 * mm * len(items)
    d = Drawing(width, height)
    c = HorizontalBarChart()
    c.x, c.y = 62 * mm, 8 * mm
    c.width, c.height = width - 74 * mm, height - 16 * mm
    c.data = [[float(t["score"]) for t in items]]
    labels = [_latin(t["label"]) for t in items]
    c.categoryAxis.categoryNames = [l if len(l) <= 38 else l[:36] + "..." for l in labels]
    c.categoryAxis.labels.fontName = "Helvetica"
    c.categoryAxis.labels.fontSize = 7.5
    c.categoryAxis.labels.fillColor = INK
    c.categoryAxis.strokeColor = RULE
    c.categoryAxis.visibleTicks = False
    c.valueAxis.valueMin = 0
    c.valueAxis.valueMax = max(1.0, max(float(t["score"]) for t in items) * 1.15)
    c.valueAxis.labels.fontName = "Helvetica"
    c.valueAxis.labels.fontSize = 7
    c.valueAxis.labels.fillColor = MUTED
    c.valueAxis.strokeColor = RULE
    c.valueAxis.visibleGrid = True
    c.valueAxis.gridStrokeColor = RULE
    c.valueAxis.gridStrokeWidth = 0.3
    c.bars.strokeColor = None
    c.barWidth = 5
    for i, t in enumerate(items):
        c.bars[(0, i)].fillColor = MULTI_PLATFORM if t["platforms"] > 1 else ONE_PLATFORM
    c.barLabelFormat = "%.2f"
    c.barLabels.fontName = "Helvetica"
    c.barLabels.fontSize = 7
    c.barLabels.boxAnchor = "w"
    c.barLabels.dx = 3
    d.add(c)
    # legend
    y = height - 5 * mm
    d.add(String(0, y, "Trend score", fontName="Helvetica-Bold", fontSize=8, fillColor=INK))
    for x, color, text in ((62 * mm, MULTI_PLATFORM, "on 2+ platforms"), (92 * mm, ONE_PLATFORM, "on 1 platform")):
        d.add(Rect(x, y - 0.5, 6, 6, fillColor=color, strokeColor=None))
        d.add(String(x + 9, y, text, fontName="Helvetica", fontSize=7.5, fillColor=MUTED))
    return d


def _cards(group, st, heading):
    out = []
    for n, t in enumerate(group):
        meta = [clean((t["category"] or "").title()), ", ".join(t["platforms_list"])]
        meta.append(f'<font color="{NEW}"><b>new today</b></font>' if t["is_new"]
                    else f"trending {t['days_trending']} day{'s' if t['days_trending'] != 1 else ''}")
        block = [Paragraph(heading, st["h2"])] if n == 0 else []  # keeps heading with first card
        block += [Paragraph(f"{t['position']}. {clean(t['label'])}", st["h3"]),
                 Paragraph(" · ".join(m for m in meta if m), st["small"]), Spacer(1, 2)]
        if t["explanation"]:
            block += [Paragraph(clean(t["explanation"]), st["body"]), Spacer(1, 2)]
        for i in t["items"][:3]:
            text = clean(i["raw_title"]) if is_drawable(i["raw_title"]) else "source link"
            if i["url"]:
                text = f'<a href="{escape(i["url"])}" color="{LINK}">{text}</a>'
            block.append(Paragraph(f'{text} <font color="#616e7c">· {clean(i["source_name"])} #{i["rank"]}</font>',
                                   st["link"], bulletText="•"))
        out.append(KeepTogether(block))
    return out


def _footer(disclaimer):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.setStrokeColor(RULE)
        canvas.line(doc.leftMargin, 14 * mm, A4[0] - doc.rightMargin, 14 * mm)
        canvas.drawString(doc.leftMargin, 10 * mm, f"India Social Trends · {disclaimer}")
        canvas.drawRightString(A4[0] - doc.rightMargin, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def render_pdf(path, day, india, world, faded, summary, disclaimer):
    st = _styles()
    story = [
        Paragraph("India Social Trends", st["title"]),
        Paragraph(f"{day:%A, %d %b %Y} · Google Trends, Wikipedia, Bluesky, Mastodon, Hacker News", st["sub"]),
    ]
    if summary:
        story += [Paragraph("Summary", st["h2"]), Paragraph(clean(summary), st["body"])]

    if india:
        story += [Paragraph("Top in India", st["h2"]), _table(india, st), Spacer(1, 10), _chart(india)]
    if world:
        story += [KeepTogether([Paragraph("Global", st["h2"]), _table(world, st)])]

    story += _cards(india, st, "Why it's trending: India")
    story += _cards(world, st, "Why it's trending: Global")

    if faded:
        story += [Paragraph("Fading since last report", st["h2"]),
                  Paragraph(" · ".join(clean(f["label"]) for f in faded), st["body"])]

    story += [Spacer(1, 12), Paragraph(
        "<b>How the score works:</b> on each platform a topic gets 1.0 for rank #1 down to about 0 for "
        "the last item; scores are added across platforms, so topics trending in several places rise to "
        "the top. Similar items are grouped into one topic with vector search (ChromaDB).", st["small"])]

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=20 * mm,
                            title="India Social Trends", author="india-social-trends")
    doc.build(story, onFirstPage=_footer(disclaimer), onLaterPages=_footer(disclaimer))
