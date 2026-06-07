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

    def ask(self, msg):
        self.asked.append(msg)
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
    checks = []

    stub = StubSession()
    srv, port = _serve(True, stub)
    code, payload = _post(port, "/chat", {"message": "what about telomeres"})
    srv.shutdown()
    checks.append(("chat on: 200", code == 200))
    checks.append(("chat on: session was asked the message", stub.asked == ["what about telomeres"]))
    checks.append(("chat on: answer returned", "telomerase" in payload.get("answer", "")))
    src = payload.get("sources", [])
    checks.append(("chat on: sources deduped, doc_ids kept",
                   [s["doc_id"] for s in src] == ["gdrive:abc", "x"]))
    checks.append(("chat on: drive link derived for highlighting/open",
                   src[0]["link"] == "https://drive.google.com/file/d/abc/view"))
    checks.append(("chat on: explicit url kept", src[1]["link"] == "http://e/p2"))

    srv2, port2 = _serve(False, None)
    code2, _ = _post(port2, "/chat", {"message": "hi"})
    srv2.shutdown()
    checks.append(("chat off: /chat is 404", code2 == 404))

    # --- cluster -> synthesis (background job + PDF), with the index/LLM stubbed ---
    import tempfile, time
    from paperfinder.studio.studyset import StudySet, Paper
    show_graph.REL_DB = os.path.join(tempfile.mkdtemp(), "rel.db")
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
