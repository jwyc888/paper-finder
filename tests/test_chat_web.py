#!/usr/bin/env python3
"""chat_web tests: page contents, answer_payload shaping, and live server routing.

Uses a stub session (no model, no index), so no embedder is loaded.
"""

import json
import os
import sys
import threading
import urllib.request
from http.server import HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples"))

import chat_web  # noqa: E402


class StubSession:
    def __init__(self):
        self.history = []
        self.asked = []

    def ask(self, message):
        self.asked.append(message)
        self.history.append(("user", message))
        self.history.append(("assistant", "stub answer"))
        return {"answer": "stub answer about [Paper One]",
                "sources": [
                    {"doc_id": "gdrive:111", "title": "Paper One", "source_url": ""},
                    {"doc_id": "gdrive:111", "title": "Paper One", "source_url": ""},   # dup
                    {"doc_id": "z", "title": "Paper Two", "source_url": "http://example/p2"},
                ]}


def _post(url, obj=None):
    data = json.dumps(obj).encode() if obj is not None else b""
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read() or b"{}")


def main():
    checks = []

    # --- page + payload (no server) ---
    page = chat_web.page_html("[BioBank ref]", "local")
    checks.append(("page has the input box", 'id="box"' in page))
    checks.append(("page wires /ask, /reset, /shutdown",
                   "/ask" in page and "/reset" in page and "/shutdown" in page))
    checks.append(("page shows scope and model labels", "BioBank ref" in page and "local" in page))

    payload = chat_web.answer_payload(StubSession(), "what do I have on telomeres?")
    checks.append(("payload returns the answer text", payload["answer"].startswith("stub answer")))
    checks.append(("payload dedupes sources", len(payload["sources"]) == 2))
    checks.append(("gdrive source gets a Drive link",
                   payload["sources"][0]["link"] == "https://drive.google.com/file/d/111/view"))
    checks.append(("explicit source_url is preserved",
                   payload["sources"][1]["link"] == "http://example/p2"))

    # --- live server routing ---
    sess = StubSession()
    httpd = HTTPServer(("127.0.0.1", 0), chat_web.Handler)
    httpd.session = sess
    httpd.labels = ("[BioBank ref]", "local")
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(base + "/", timeout=5) as r:
            home = r.read().decode()
        checks.append(("GET / serves the page", "paper-finder chat" in home))

        ask = _post(base + "/ask", {"message": "telomeres?"})
        checks.append(("POST /ask returns answer + sources", ask["answer"].startswith("stub answer") and len(ask["sources"]) == 2))
        checks.append(("ask reached the session", sess.asked == ["telomeres?"]))

        _post(base + "/reset", {})
        checks.append(("POST /reset clears the conversation", sess.history == []))

        shut = _post(base + "/shutdown", {})
        checks.append(("POST /shutdown acknowledges", shut.get("ok") is True))
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=5)
    checks.append(("server stopped after /shutdown", not th.is_alive()))

    print("=== chat_web: page, payload, and server routing ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
