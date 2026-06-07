"""Render a synthesis brief (markdown) to a PDF the user can download.

Kept deliberately small: it maps the handful of markdown constructs the synthesis
prompt emits (headings, bullets, bold, paragraphs) onto reportlab flowables. No
attempt at full markdown. reportlab is a pure-Python dependency; install it with
`pip install reportlab` if it is missing.
"""
import html
import re


def _markup(text: str) -> str:
    """Escape, then turn **bold** into reportlab's <b> markup."""
    t = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


def synthesis_to_pdf(markdown: str, out_path: str, title: str = "Synthesis",
                     paper_titles=None) -> str:
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        ListFlowable, ListItem)
    except ImportError:
        raise RuntimeError("PDF export needs reportlab; install it with: pip install reportlab")

    styles = getSampleStyleSheet()
    body, h1, h2, h3 = styles["BodyText"], styles["Heading1"], styles["Heading2"], styles["Heading3"]
    doc = SimpleDocTemplate(out_path, pagesize=LETTER,
                            leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                            topMargin=0.9 * inch, bottomMargin=0.9 * inch, title=title)

    story = [Paragraph(html.escape(title), styles["Title"])]
    if paper_titles:
        story.append(Paragraph("Papers: " + html.escape(", ".join(paper_titles)), styles["Italic"]))
    story.append(Spacer(1, 12))

    bullets = []

    def flush():
        if bullets:
            story.append(ListFlowable([ListItem(Paragraph(b, body)) for b in bullets],
                                      bulletType="bullet", leftIndent=18))
            bullets.clear()

    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush(); story.append(Spacer(1, 6)); continue
        if line.startswith("### "):
            flush(); story.append(Paragraph(_markup(line[4:]), h3))
        elif line.startswith("## "):
            flush(); story.append(Paragraph(_markup(line[3:]), h2))
        elif line.startswith("# "):
            flush(); story.append(Paragraph(_markup(line[2:]), h1))
        elif line.lstrip().startswith(("- ", "* ")):
            bullets.append(_markup(line.lstrip()[2:]))
        else:
            flush(); story.append(Paragraph(_markup(line), body))
    flush()

    doc.build(story)
    return out_path
