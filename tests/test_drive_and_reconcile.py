"""
test_drive_and_reconcile.py — verify the two new capabilities without a real Drive.

  1. Alias following: a mock Drive service with a central folder containing a real
     subfolder, a folder-shortcut to an OUTSIDE folder, and a file-shortcut to an
     OUTSIDE paper. The crawl should index all three targets (keyed to target id,
     deduped) and ignore everything not reachable from the root.
  2. Reconcile: index a local folder, authenticate a relationship, delete a file,
     re-backfill — the removed paper is archived and drops from search, while the
     human-verified relationship survives untouched.

Run:  python3 test_drive_and_reconcile.py
"""

import os
import shutil
import sys
import tempfile

from paperfinder.core.capture import GoogleDriveSource, LocalFolderSource
from paperfinder.core.finder import HashingEmbedder, PaperFinder
from paperfinder.graph.relationship import RelationshipGraph

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"


# --- a tiny mock of the bits of the Drive API the crawl uses ----------------
class _Exec:
    def __init__(self, v): self._v = v
    def execute(self): return self._v


class _Files:
    def __init__(self, store): self.s = store

    def list(self, q=None, fields=None, pageToken=None, pageSize=None, **kw):
        import re
        m = re.search(r"'([^']+)' in parents", q or "")
        parent = m.group(1) if m else None
        files = [f for f in self.s.values() if parent in f.get("parents", [])]
        return _Exec({"files": files, "nextPageToken": None})

    def get(self, fileId=None, fields=None, **kw):
        return _Exec(self.s[fileId])

    def get_media(self, fileId=None, **kw):
        return _Exec(self.s[fileId].get("_bytes", b""))


class _Changes:
    def getStartPageToken(self): return _Exec({"startPageToken": "1"})
    def list(self, **kw): return _Exec({"changes": [], "newStartPageToken": "1"})


class MockDriveService:
    def __init__(self, files): self._f = files
    def files(self): return _Files(self._f)
    def changes(self): return _Changes()


def _doc(id, name, parents, body):
    return {"id": id, "name": name, "mimeType": "text/plain", "parents": parents,
            "webViewLink": f"https://drive.google.com/file/{id}", "_bytes": body.encode()}


def test_alias_following():
    body = "patient sentiment toward AI chatbots in clinical care"
    files = {
        "root":   {"id": "root", "name": "Index", "mimeType": FOLDER, "parents": []},
        "subA":   {"id": "subA", "name": "ProjectA", "mimeType": FOLDER, "parents": ["root"]},
        "subA2":  {"id": "subA2", "name": "Deep", "mimeType": FOLDER, "parents": ["subA"]},
        "extF":   {"id": "extF", "name": "SharedLit", "mimeType": FOLDER, "parents": ["zzz"]},
        "ignore": {"id": "ignore", "name": "Other", "mimeType": FOLDER, "parents": ["zzz"]},
        "a1": _doc("a1", "a1.txt", ["subA"], body),         # physically under root/ProjectA
        "a2": _doc("a2", "a2.txt", ["subA2"], body),        # under root/ProjectA/Deep
        "e1": _doc("e1", "e1.txt", ["extF"], body),         # reached via folder alias
        "x1": _doc("x1", "x1.txt", ["other"], body),        # reached via file alias
        "n1": _doc("n1", "n1.txt", ["ignore"], body),       # NOT reachable -> ignored
        "scF":    {"id": "scF", "name": "->SharedLit", "mimeType": SHORTCUT, "parents": ["root"],
                   "shortcutDetails": {"targetId": "extF", "targetMimeType": FOLDER}},
        "scFile": {"id": "scFile", "name": "->x1", "mimeType": SHORTCUT, "parents": ["root"],
                   "shortcutDetails": {"targetId": "x1", "targetMimeType": "text/plain"}},
    }
    src = GoogleDriveSource(MockDriveService(files), folder_ids=["root"])
    refs = src.crawl()
    ids = {r.doc_id for r in refs}
    tag = {r.doc_id: r.tag for r in refs}

    checks = [
        ("physical file under root indexed", "gdrive:a1" in ids),
        ("folder alias followed (outside root)", "gdrive:e1" in ids),
        ("file alias followed (outside root)", "gdrive:x1" in ids),
        ("unreachable folder ignored", "gdrive:n1" not in ids),
        ("alias target folder added to scope", "extF" in src._scope),
        ("no duplicates", len(refs) == len(ids)),
        ("folder tag is full path from root", tag.get("gdrive:a1") == "ProjectA"),
        ("nested folder tag is full path", tag.get("gdrive:a2") == "ProjectA/Deep"),
        ("folder-alias tag uses the tree name", tag.get("gdrive:e1") == "->SharedLit"),
        ("root-level file-alias tag is empty", tag.get("gdrive:x1") == ""),
    ]

    # and the whole pipeline runs on the mock Drive
    db = "test_drive.db"
    if os.path.exists(db):
        os.remove(db)
    pf = PaperFinder(db, embedder=HashingEmbedder())
    pf.run_backfill(src, source_key="gdrive", reconcile=True)
    pf.run_metadata_pass()
    pf.run_embed_pass()
    hits = {h["doc_id"] for h in pf.search("patient sentiment chatbots", k=10)}
    checks.append(("pipeline indexes aliased docs end-to-end",
                   {"gdrive:a1", "gdrive:a2", "gdrive:e1", "gdrive:x1"} <= hits and "gdrive:n1" not in hits))
    checks.append(("folder persisted on the document row",
                   pf.get_document("gdrive:a1")["folder"] == "ProjectA"))
    scoped = {h["doc_id"] for h in pf.search("patient sentiment chatbots", k=10, folder="ProjectA")}
    checks.append(("folder filter is prefix-aware",
                   {"gdrive:a1", "gdrive:a2"} <= scoped
                   and "gdrive:e1" not in scoped and "gdrive:x1" not in scoped))
    return checks


def test_reconcile_preserves_edges():
    d = tempfile.mkdtemp()
    body = "patient sentiment toward AI chatbots and conversational agents"
    for fn in ("p_a.txt", "p_b.txt", "p_c.txt"):
        with open(os.path.join(d, fn), "w") as f:
            f.write(body + f"\n({fn})")

    db, reldb = "test_reconcile.db", "test_reconcile_rel.db"
    for p in (db, reldb):
        if os.path.exists(p):
            os.remove(p)

    pf = PaperFinder(db, embedder=HashingEmbedder())
    src = LocalFolderSource(d)
    pf.run_backfill(src, source_key="local", reconcile=True)
    pf.run_metadata_pass()
    pf.run_embed_pass()

    by_name = {os.path.basename(x["source_url"]): x["doc_id"] for x in pf.all_documents()}
    a, b = by_name["p_a.txt"], by_name["p_b.txt"]

    # authenticate a human relationship that touches the paper we're about to remove
    rg = RelationshipGraph(reldb)
    for x in pf.all_documents():
        rg.add_document(x["doc_id"], x["title"], [], pf.store.get(x["doc_id"]) or [])
    rg.authenticate(a, b, ["shared topic"], "john")

    # remove p_b from disk, then re-backfill with reconcile
    os.remove(os.path.join(d, "p_b.txt"))
    pf.run_backfill(src, source_key="local", reconcile=True)
    pf.run_metadata_pass()
    pf.run_embed_pass()

    search_ids = {h["doc_id"] for h in pf.search("patient sentiment chatbots", k=10)}
    edge_still_there = any(n["doc_id"] == b for n in rg.neighbors(a, "authenticated"))

    shutil.rmtree(d, ignore_errors=True)
    return [
        ("removed paper is archived", pf.get_document(b)["archived"] == 1),
        ("removed paper drops out of search", b not in search_ids),
        ("kept paper still searchable", a in search_ids),
        ("verified relationship survives reconcile", edge_still_there),
    ]


def test_folder_rename_updates():
    body = "patient sentiment toward AI chatbots in clinical care"
    files = {
        "root": {"id": "root", "name": "Index", "mimeType": FOLDER, "parents": []},
        "sub":  {"id": "sub", "name": "OldName", "mimeType": FOLDER, "parents": ["root"]},
        "d1": _doc("d1", "d1.txt", ["sub"], body),
    }
    src = GoogleDriveSource(MockDriveService(files), folder_ids=["root"])
    db = "test_rename.db"
    if os.path.exists(db):
        os.remove(db)
    pf = PaperFinder(db, embedder=HashingEmbedder())
    pf.run_backfill(src, source_key="gdrive", reconcile=True)
    pf.run_metadata_pass()
    pf.run_embed_pass()
    before = pf.get_document("gdrive:d1")["folder"]

    files["sub"]["name"] = "NewName"            # rename the folder on the "Drive"
    pf.run_backfill(src, source_key="gdrive", reconcile=True)
    pf.run_metadata_pass()
    after = pf.get_document("gdrive:d1")["folder"]

    return [
        ("tag captured on first index", before == "OldName"),
        ("tag refreshes after a folder rename", after == "NewName"),
    ]


def main():
    all_checks = []
    print("=== alias following (mock Drive) ===")
    all_checks += test_alias_following()
    print("=== folder rename ===")
    all_checks += test_folder_rename_updates()
    print("=== reconcile / prune ===")
    all_checks += test_reconcile_preserves_edges()

    ok = True
    for name, passed in all_checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
