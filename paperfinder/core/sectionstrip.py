"""
sectionstrip.py - remove bibliography/supplementary back-matter before chunking.

References, Bibliography, and Supplementary sections inflate cross-document
similarity (citation formatting and shared citations look alike across papers),
so they pollute the relationship graph. We drop them while KEEPING the Appendix
and the body.

A cheap regex finds candidate heading lines; a local LLM (any OpenAI-compatible
endpoint, e.g. Ollama) adjudicates which candidates are real section starts and
of what type. Sections span from one heading to the next, so an Appendix that
sits AFTER the references is still preserved. Any failure (no endpoint, bad
output, no candidates) returns the text unchanged: we never silently drop body.

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

REMOVE_TYPES = {"references", "bibliography", "supplementary"}
KEEP_TYPES = {"appendix"}            # appendix + body are retained
SECTION_TYPES = REMOVE_TYPES | KEEP_TYPES

_KEYWORD_RE = re.compile(
    r"^\s*(?:\d+\.?\s+|[a-z]\.?\s+|[ivxlc]+\.?\s+)?"          # optional numbering/lettering
    r"(references?|bibliography|works\s+cited|literature\s+cited|"
    r"supplementary[\w\s]*|supporting\s+information|appendix|appendices)\b",
    re.IGNORECASE,
)


def find_candidates(text: str, max_heading_len: int = 60) -> list[dict]:
    """Heading-like lines that might start back-matter. Short lines only, so a
    sentence that merely mentions 'references' is not picked up."""
    out = []
    for i, line in enumerate(text.splitlines()):
        s = line.strip()
        if s and len(s) <= max_heading_len and _KEYWORD_RE.match(s):
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
        "line below, classify it as exactly one of: references, bibliography, "
        "supplementary, appendix, body. Use 'body' if the line is NOT a real "
        "back-matter section heading (a false positive). Judge from the heading "
        "and the text that follows it.\n\n"
        "Return ONLY a JSON array, one object per candidate, in the same order, "
        'like: [{"line": 412, "type": "references"}]. No prose, no code fences.\n\n'
        f"Candidates:\n{listing}\n"
    )


def _llm_classify(text_lines: list[str], candidates: list[dict],
                  timeout: float = 60.0) -> list[dict]:
    """Ask the local model to type each candidate. Returns [] on any failure so
    the caller falls back to leaving the text untouched."""
    prompt = _build_prompt(text_lines, candidates)
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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
        content = body["choices"][0]["message"]["content"]
        return _parse_decisions(content)
    except Exception:
        return []


def _parse_decisions(content: str) -> list[dict]:
    """Pull the JSON array out of a model reply, tolerating stray fences/prose."""
    content = content.strip()
    if "```" in content:                       # strip code fences if present
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
    """Return `text` with references/bibliography/supplementary sections removed
    and appendix/body kept. `classify` is injectable for testing; by default it
    calls the local LLM. Safe: returns the original text on anything unexpected."""
    if not text:
        return text
    lines = text.splitlines()
    candidates = find_candidates(text)
    if not candidates:
        return text

    decisions = classify(lines, candidates)
    # keep only decisions that name a real section start at a known candidate line
    cand_lines = {c["line"] for c in candidates}
    starts = sorted(
        (d for d in decisions if d["line"] in cand_lines and d["type"] in SECTION_TYPES),
        key=lambda d: d["line"],
    )
    if not starts:
        return text

    # each section runs from its heading to the next section start (or EOF)
    bounds = [s["line"] for s in starts] + [len(lines)]
    remove = set()
    for idx, s in enumerate(starts):
        if s["type"] in REMOVE_TYPES:
            remove.update(range(bounds[idx], bounds[idx + 1]))

    kept = [ln for i, ln in enumerate(lines) if i not in remove]
    cleaned = "\n".join(kept).strip()
    return cleaned or text          # never return empty if we started with content
