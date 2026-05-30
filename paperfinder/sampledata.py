"""Sample corpus generator — shared by `paperfinder sample` and the Tier A test.

Writes a small inbox: a chatbot-sentiment cluster, a KG/drug-discovery cluster
(noise), an on-topic PDF, and a 'supplementary' PDF whose first page is generic
boilerplate but whose body is on-topic (to exercise the staged metadata/embed gap).
"""

import os
import shutil

from reportlab.pdfgen import canvas

SENTIMENT = {
    "p1_chatbot_attitudes.txt":
        "Patient attitudes toward AI chatbots in primary care\n\n"
        "This study surveys patient sentiment and attitudes toward AI chatbots "
        "used for triage in primary care, measuring acceptance and concerns.",
    "p2_trust_mental_health.txt":
        "Trust and acceptance of conversational agents in mental health\n\n"
        "We examine patient trust and acceptance of conversational agents and "
        "chatbots delivering mental health support.",
    "p3_symptom_checkers.txt":
        "User perceptions of symptom-checker apps\n\n"
        "User perception and patient sentiment regarding symptom-checker apps "
        "and medical chatbots are analysed across demographics.",
}
NOISE = {
    "k1_rotate_drug.txt":
        "RotatE knowledge graph embeddings for drug repurposing\n\n"
        "We apply RotatE knowledge graph embeddings to biomedical graphs for "
        "drug repurposing and link prediction.",
    "k2_link_prediction.txt":
        "Link prediction over biomedical knowledge graphs\n\n"
        "Graph embedding methods for link prediction over biomedical knowledge "
        "graphs such as Hetionet and PrimeKG.",
}


def _make_pdf(path, pages, title=None):
    c = canvas.Canvas(path)
    if title:
        c.setTitle(title)
    for text in pages:
        y = 800
        for line in text.split("\n"):
            c.drawString(60, y, line)
            y -= 16
        c.showPage()
    c.save()


def build_sample_inbox(folder: str) -> int:
    """(Re)create a sample inbox at `folder`; return the file count."""
    if os.path.exists(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)
    for name, body in {**SENTIMENT, **NOISE}.items():
        with open(os.path.join(folder, name), "w") as f:
            f.write(body)
    _make_pdf(os.path.join(folder, "p4_clinical_trust.pdf"),
              ["Measuring patient trust in clinical decision support",
               "We quantify patient trust in clinical decision support and "
               "chatbot-mediated advice."],
              title="Measuring patient trust in clinical decision support")
    # page 1 generic, body on-topic -> hidden at metadata, found after embed
    _make_pdf(os.path.join(folder, "supplementary_S3.pdf"),
              ["Supplementary Materials. Table of Contents. Figure S1. Figure S2.",
               "This appendix reports patient sentiment and attitudes toward AI "
               "chatbots and conversational agents in clinical settings."])
    return len(os.listdir(folder))
