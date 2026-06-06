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

    ok = True
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
