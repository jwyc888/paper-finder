"""show_graph's /chat endpoint returns an answer plus deduped sources with doc_ids
(so the page can highlight nodes), and 404s when chat is disabled. No model needed:
a stub session stands in for the real ChatSession."""
import json
import os
import sys
import threading
import urllib.request
from http.server import HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "examples"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import show_graph  # noqa: E402


class StubSession:
    def __init__(self):
        self.asked = []
        self.finder = None        # build_studyset is monkeypatched, so unused
        self.frontier = False
        self._complete = lambda *a, **k: "stub"

    def ask(self, msg, graph_text=None):
        self.asked.append(msg)
        self.last_graph_text = graph_text
        return {"answer": "telomerase reactivation is the throughline.",
                "sources": [
                    {"doc_id": "gdrive:abc", "title": "Telomerase paper", "source_url": ""},
                    {"doc_id": "gdrive:abc", "title": "Telomerase paper", "source_url": ""},
                    {"doc_id": "x", "title": "Senescence paper", "source_url": "http://e/p2"},
                ]}


def _post(port, path, body):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def _get(port, path):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=5) as r:
            return r.status, json.loads(r.read() or "{}"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, {}, {}


def _get_bytes(port, path):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=5) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, b"", ""


def _serve(chat, session):
    srv = HTTPServer(("127.0.0.1", 0), show_graph.Handler)
    srv.chat = chat
    srv.session = session
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def main():
    import tempfile
    show_graph.REL_DB = os.path.join(tempfile.mkdtemp(), "rel.db")
    checks = []

    stub = StubSession()
    srv, port = _serve(True, stub)
    code, payload = _post(port, "/chat", {"message": "what about telomeres"})
    srv.shutdown()
    checks.append(("chat on: 200", code == 200))
    checks.append(("chat on: session was asked the message", stub.asked == ["what about telomeres"]))
    checks.append(("chat on: answer returned", "telomerase" in payload.get("answer", "")))
    # answer has no [citations] and this graph has no nodes, so no chunk sources leak through
    checks.append(("chat on: no sources without citations", payload.get("sources", []) == []))

    srv2, port2 = _serve(False, None)
    code2, _ = _post(port2, "/chat", {"message": "hi"})
    srv2.shutdown()
    checks.append(("chat off: /chat is 404", code2 == 404))

    # selection awareness: the selected ids should reach the model via graph_text
    sel_stub = StubSession()
    srv_s, port_s = _serve(True, sel_stub)
    _post(port_s, "/chat", {"message": "which papers have I selected", "selected": ["paperX", "paperY"]})
    srv_s.shutdown()
    gt = sel_stub.last_graph_text or ""
    checks.append(("chat: selection injected into prompt",
                   "CURRENTLY SELECTED" in gt and "paperX" in gt and "paperY" in gt))

    # sources/highlights come from the answer's [citations] mapped to graph nodes,
    # not from the retrieved chunks (which caused the long misaligned list).
    from paperfinder.graph.relationship import RelationshipGraph
    rg = RelationshipGraph(show_graph.REL_DB)
    rg.add_document("kp", "Known Paper", [], [], source_url="http://x/kp")

    class CiteStub:
        def ask(self, msg, graph_text=None):
            return {"answer": "You selected [Known Paper], not [Nonexistent Paper].",
                    "sources": [{"doc_id": "chunk-zzz", "title": "A retrieved chunk", "source_url": ""}]}

    srv_c, port_c = _serve(True, CiteStub())
    _, dc = _post(port_c, "/chat", {"message": "which paper did I select", "selected": ["kp"]})
    srv_c.shutdown()
    csrcs = dc.get("sources", [])
    checks.append(("chat: sources are the cited paper, not retrieved chunks",
                   [s["doc_id"] for s in csrcs] == ["kp"]))
    checks.append(("chat: uncited/unknown citations are dropped",
                   all(s["doc_id"] != "chunk-zzz" for s in csrcs)))

    # /open: bare path serves the in-page viewer; ?raw=1 streams the bytes; web links redirect
    import tempfile as _tf
    pdfpath = os.path.join(_tf.mkdtemp(), "paper.pdf")
    with open(pdfpath, "wb") as f:
        f.write(b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n")
    rg.add_document("localdoc", "Local PDF", [], [], source_url="file://" + pdfpath)
    rg.add_document("webdoc", "Web Paper", [], [], source_url="https://example.com/paper")
    rg.add_document("gdrive:FILEID123", "Drive Paper", [], [],
                    source_url="https://drive.google.com/file/d/FILEID123/view")
    srv_o, port_o = _serve(True, StubSession())
    vc, vb, vctype = _get_bytes(port_o, "/open?id=localdoc")
    vtxt = vb.decode("utf-8", "replace")
    checks.append(("open: bare path serves the in-page viewer",
                   vc == 200 and "html" in vctype and "pdf.js" in vtxt
                   and "raw=1" in vtxt and ">Download<" in vtxt))
    oc, ob, octype = _get_bytes(port_o, "/open?id=localdoc&raw=1")
    checks.append(("open: raw streams local pdf inline as pdf",
                   oc == 200 and ob[:5] == b"%PDF-" and "pdf" in octype))

    class _NoRedir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    op = urllib.request.build_opener(_NoRedir)
    rcode, rloc = 0, ""
    try:
        op.open("http://127.0.0.1:%d/open?id=webdoc" % port_o, timeout=5)
    except urllib.error.HTTPError as e:
        rcode, rloc = e.code, e.headers.get("Location", "")
    checks.append(("open: web link redirects to the browser",
                   rcode == 302 and rloc == "https://example.com/paper"))

    # a Drive node serves the viewer; only the raw fetch needs the service account, which is
    # not configured in tests, so the raw path falls back to the Drive web link
    dvc, dvb, dvtype = _get_bytes(port_o, "/open?id=gdrive%3AFILEID123")
    checks.append(("open: drive node serves the viewer page",
                   dvc == 200 and "html" in dvtype and "pdf.js" in dvb.decode("utf-8", "replace")))
    gcode, gloc = 0, ""
    try:
        op.open("http://127.0.0.1:%d/open?id=gdrive%%3AFILEID123&raw=1" % port_o, timeout=5)
    except urllib.error.HTTPError as e:
        gcode, gloc = e.code, e.headers.get("Location", "")
    checks.append(("open: raw drive fetch falls back to the web link when SA unavailable",
                   gcode == 302 and "FILEID123" in gloc))
    omiss, _ob, _oc = _get_bytes(port_o, "/open?id=does-not-exist")
    checks.append(("open: unknown id 404", omiss == 404))
    srv_o.shutdown()

    # --- cluster -> synthesis (background job + PDF), with the index/LLM stubbed ---
    import tempfile, time
    from paperfinder.studio.studyset import StudySet, Paper
    show_graph.OUTDIR = tempfile.mkdtemp()
    orig_bs, orig_syn = show_graph.build_studyset, show_graph.synthesize
    show_graph.build_studyset = lambda finder, rel, ids: StudySet(
        papers=[Paper(doc_id=i, title="Paper " + i, folder="", source_url="", text="body of " + i) for i in ids])
    show_graph.synthesize = lambda ss, frontier=False, complete=None: (
        "# Synthesis\n\n## Shared topic\n\nThese **" + str(len(ss.papers)) + "** papers connect.\n\n- a\n- b")

    sstub = StubSession()
    srv3, port3 = _serve(True, sstub)
    code_few, _ = _post(port3, "/synthesize", {"ids": ["only-one"]})
    checks.append(("synthesis: <2 ids rejected", code_few == 400))

    code_s, dj = _post(port3, "/synthesize", {"ids": ["p1", "p2", "p3"]})
    checks.append(("synthesis: job starts", code_s == 200 and bool(dj.get("job_id")) and dj.get("n") == 3))
    job = dj.get("job_id", "")
    status, n = "", 0
    for _ in range(50):
        sc, sd, _h = _get(port3, "/synthesis_status?id=" + job)
        status, n = sd.get("status"), sd.get("n")
        if status in ("done", "error"):
            break
        time.sleep(0.1)
    checks.append(("synthesis: job completes", status == "done" and n == 3))
    dcode, dbytes, dctype = _get_bytes(port3, "/download?id=" + job)
    checks.append(("synthesis: PDF downloads", dcode == 200 and dbytes[:5] == b"%PDF-" and "pdf" in dctype))
    ucode, _ub, _uc = _get_bytes(port3, "/download?id=nope")
    checks.append(("synthesis: unknown job download 404", ucode == 404))
    srv3.shutdown()
    show_graph.build_studyset, show_graph.synthesize = orig_bs, orig_syn

    ok = True
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
