"""Assemble a StudySet from a plain list of doc_ids.

The list is the contract between selectors (manual list, folder, later a graph
click) and the generators. This module only consumes a list and reads from the
existing finder index and relationship graph; it never decides how the list was
formed.
"""

from dataclasses import dataclass, field


@dataclass
class Paper:
    doc_id: str
    title: str
    folder: str
    source_url: str
    text: str


@dataclass
class Connection:
    a: str
    b: str
    a_title: str
    b_title: str
    status: str
    descriptors: list
    a_passage: str
    b_passage: str


@dataclass
class StudySet:
    papers: list = field(default_factory=list)        # list[Paper], in the given order
    connections: list = field(default_factory=list)   # list[Connection], edges within the set


def ids_for_folder(finder, folder: str) -> list:
    """A selector helper: every active doc whose folder is `folder` or beneath it."""
    out = []
    for d in finder.all_documents():
        if d.get("archived"):
            continue
        f = d.get("folder") or ""
        if f == folder or f.startswith(folder + "/"):
            out.append(d["doc_id"])
    return out


def build_studyset(finder, rel_graph, doc_ids) -> StudySet:
    ids = list(dict.fromkeys(doc_ids))                # dedupe, preserve order
    papers = []
    for did in ids:
        d = finder.get_document(did)
        if not d or d.get("archived"):
            continue
        papers.append(Paper(
            doc_id=did,
            title=d.get("title") or did,
            folder=d.get("folder") or "",
            source_url=d.get("source_url") or "",
            text=(d.get("full_text") or d.get("first_text") or ""),
        ))

    present = {p.doc_id for p in papers}
    title_by = {p.doc_id: p.title for p in papers}
    connections = []
    for e in rel_graph.export_graph()["edges"]:
        if e["src"] in present and e["dst"] in present:
            ev = e.get("evidence") or {}
            connections.append(Connection(
                a=e["src"], b=e["dst"],
                a_title=title_by.get(e["src"], e["src"]),
                b_title=title_by.get(e["dst"], e["dst"]),
                status=e["status"],
                descriptors=e.get("descriptors") or [],
                a_passage=(ev.get("src_passage") or ""),
                b_passage=(ev.get("dst_passage") or ""),
            ))
    return StudySet(papers=papers, connections=connections)
