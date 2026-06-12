"""
sectionstrip.py - detect a paper's section structure, and (optionally) remove
back-matter before chunking.

Two consumers share one heading detector and one local-LLM classification pass:

  strip_back_matter(text)  -> text with references/bibliography/supplementary
                              removed, body + appendix kept. Unchanged behaviour.
  segment(text)            -> a list of labelled spans covering the whole text,
                              each carrying the verbatim heading (section_text)
                              and a normalized type (section_type). This is what
                              section-aware chunking consumes.

A cheap regex finds candidate heading lines (IMRaD words, numbered headings, and
back-matter words). A local LLM (any OpenAI-compatible endpoint, e.g. Ollama)
adjudicates which candidates are real section starts and of what type; a false
positive is typed "body" and ignored. Any failure (no endpoint, bad output, no
candidates) is safe: strip returns the text unchanged, and segment returns a
single "other" span over the whole document. We never silently drop body.

Hybrid labelling: section_text is the paper's own heading verbatim (faithful for
non-IMRaD documents like guidelines), and section_type is a normalized bucket
(introduction, methods, results, ...) when the heading maps to one, else "other".

Config (env):
  PAPERFINDER_LLM_URL    OpenAI-compatible base URL (default http://localhost:11434/v1)
  PAPERFINDER_LLM_MODEL  model tag (default llama3.1:8b)
"""

import json
import os
import re
import urllib.request

LLM_URL = os.environ.get("PAPERFINDER_LLM_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("PAPERFINDER_LLM_MODEL", "llama3.1:8b")

# normalized types that segment() can assign (besides "body" = false positive)
NORMALIZED_TYPES = {
    "abstract", "introduction", "background", "methods", "results",
    "discussion", "conclusion", "references", "supplementary", "appendix",
    "other",
}
# back-matter that the section-aware chunker drops before embedding
DROP_TYPES = {"references", "supplementary"}

# strip_back_matter keeps its original (pre-normalization) vocabulary so its
# behaviour and its test are unchanged.
REMOVE_TYPES = {"references", "bibliography", "supplementary"}
KEEP_TYPES = {"appendix"}
SECTION_TYPES = REMOVE_TYPES | KEEP_TYPES

# heading detection: a known section word anchored at line start, after optional
# numbering/lettering. Kept anchored so a sentence that merely mentions a word
# (".. our method ..") is not picked up.
_KEYWORD_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+|[A-Za-z]\.?\s+|[ivxlcIVXLC]+\.?\s+)?"
    r"(abstract|introduction|background|related\s+work|"
    r"materials?\s+and\s+methods|methods?|materials?|"
    r"results?|findings?|discussions?|conclusions?|limitations?|"
    r"references?|bibliography|works\s+cited|literature\s+cited|"
    r"supplementary[\w\s]*|supporting\s+information|appendix|appendices)\b",
    re.IGNORECASE,
)
# numbered headings without a known word (e.g. "4.1.2 Lifestyle Management").
# Requires Title-case start and no '.' in the title text, which excludes numbered
# citation lines ("1. Smith J, et al. Nature 2020.").
_NUMBERED_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+[A-Z][^.\n]{0,58}$")

# map a heading word OR a classifier label to a normalized type
_NORMALIZE = [
    (r"abstract", "abstract"),
    (r"introduction", "introduction"),
    (r"background|related\s+work", "background"),
    (r"method|material", "methods"),
    (r"result|finding", "results"),
    (r"discussion|limitation", "discussion"),
    (r"conclusion", "conclusion"),
    (r"reference|bibliograph|works\s+cited|literature\s+cited", "references"),
    (r"supplementary|supporting\s+information", "supplementary"),
    (r"appendix|appendices", "appendix"),
    (r"\bbody\b", "body"),
]


def normalize_type(s: str):
    """Bucket a heading word or classifier label into a normalized type, or None."""
    s = (s or "").lower()
    for pat, t in _NORMALIZE:
        if re.search(pat, s):
            return t
    return None


def find_candidates(text: str, max_heading_len: int = 60) -> list[dict]:
    """Heading-like lines that might start a section. Short lines only, so a
    sentence that merely mentions a section word is not picked up."""
    out = []
    for i, line in enumerate(text.splitlines()):
        s = line.strip()
        if s and len(s) <= max_heading_len and (_KEYWORD_RE.match(s) or _NUMBERED_RE.match(s)):
            out.append({"line": i, "text": s})
    return out


def _build_prompt(text_lines: list[str], candidates: list[dict]) -> str:
    items = []
    for c in candidates:
        i = c["line"]
        following = " ".join(l.strip() for l in text_lines[i + 1:i + 4])[:120]
        items.append(f'[line {i}] "{c["text"]}"  | following: {following}')
    listing = "\n".join(items)
    return (
        "You label section headings in a scientific paper. For each candidate "
        "line below, classify it as exactly one of: abstract, introduction, "
        "background, methods, results, discussion, conclusion, references, "
        "bibliography, supplementary, appendix, body. Use 'body' if the line is "
        "NOT a real section heading (a false positive). Judge from the heading "
        "and the text that follows it.\n\n"
        "Return ONLY a JSON array, one object per candidate, in the same order, "
        'like: [{"line": 412, "type": "references"}]. No prose, no code fences.\n\n'
        f"Candidates:\n{listing}\n"
    )


def _chat(prompt: str, timeout: float) -> str:
    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        LLM_URL.rstrip("/") + "/chat/completions",
        data=payload, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    return body["choices"][0]["message"]["content"]


def _llm_classify(text_lines: list[str], candidates: list[dict],
                  timeout: float = 60.0) -> list[dict]:
    """Ask the local model to type each candidate. Returns [] on any failure so
    callers fall back to leaving the text untouched."""
    try:
        return _parse_decisions(_chat(_build_prompt(text_lines, candidates), timeout))
    except Exception:
        return []


def _parse_decisions(content: str) -> list[dict]:
    """Pull the JSON array out of a model reply, tolerating stray fences/prose."""
    content = content.strip()
    if "```" in content:
        content = re.sub(r"```[a-zA-Z]*", "", content).replace("```", "").strip()
    start, end = content.find("["), content.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(content[start:end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    for d in data if isinstance(data, list) else []:
        if isinstance(d, dict) and "line" in d and "type" in d:
            out.append({"line": int(d["line"]), "type": str(d["type"]).lower().strip()})
    return out


def strip_back_matter(text: str, classify=_llm_classify) -> str:
    """Return `text` with references/bibliography/supplementary removed and
    appendix/body kept. `classify` is injectable for testing. Safe: returns the
    original text on anything unexpected."""
    if not text:
        return text
    lines = text.splitlines()
    candidates = find_candidates(text)
    if not candidates:
        return text

    decisions = classify(lines, candidates)
    cand_lines = {c["line"] for c in candidates}
    starts = sorted(
        (d for d in decisions if d["line"] in cand_lines and d["type"] in SECTION_TYPES),
        key=lambda d: d["line"],
    )
    if not starts:
        return text

    bounds = [s["line"] for s in starts] + [len(lines)]
    remove = set()
    for idx, s in enumerate(starts):
        if s["type"] in REMOVE_TYPES:
            remove.update(range(bounds[idx], bounds[idx + 1]))

    kept = [ln for i, ln in enumerate(lines) if i not in remove]
    cleaned = "\n".join(kept).strip()
    return cleaned or text


def _whole_doc_span(lines: list[str]) -> list[dict]:
    return [{"start": 0, "end": len(lines), "section_text": "", "section_type": "other"}]


def segment(text: str, classify=_llm_classify) -> list[dict]:
    """Cover `text` with labelled spans. Each span: {start, end, section_text,
    section_type}, where section_text is the verbatim heading ("" for leading
    front-matter) and section_type is a normalized bucket. `classify` is
    injectable for testing. Safe: returns one "other" span over the whole text on
    no candidates or classifier failure, so nothing is ever lost."""
    if not text:
        return [{"start": 0, "end": 0, "section_text": "", "section_type": "other"}]
    lines = text.splitlines()
    candidates = find_candidates(text)
    if not candidates:
        return _whole_doc_span(lines)

    decisions = classify(lines, candidates)
    cand_text = {c["line"]: c["text"].strip() for c in candidates}
    starts = []
    for d in sorted(decisions, key=lambda x: x["line"]):
        if d["line"] not in cand_text:
            continue
        if normalize_type(d.get("type") or "") == "body":   # explicit false positive
            continue
        ntype = (normalize_type(d.get("type") or "")
                 or normalize_type(cand_text[d["line"]]) or "other")
        starts.append({"line": d["line"], "section_text": cand_text[d["line"]],
                       "section_type": ntype})
    if not starts:
        return _whole_doc_span(lines)

    spans = []
    if starts[0]["line"] > 0:                                # leading front-matter
        spans.append({"start": 0, "end": starts[0]["line"],
                      "section_text": "", "section_type": "other"})
    bounds = [s["line"] for s in starts] + [len(lines)]
    for i, s in enumerate(starts):
        spans.append({"start": s["line"], "end": bounds[i + 1],
                      "section_text": s["section_text"], "section_type": s["section_type"]})
    return spans
