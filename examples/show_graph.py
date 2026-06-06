#!/usr/bin/env python3
"""
show_graph.py - open an interactive review session for the relationship graph.

Stands up a small local server, opens your browser to the graph, and serves it
with Authenticate / Reject buttons on edge-click. Clicking a node opens its
source. The server is ephemeral: it runs only for this session and stops when you
click "Done reviewing" in the page (or press Ctrl-C here). Nothing stays running.

Run:
    python3 examples/show_graph.py

Config (env):
    PAPERFINDER_REL_DB       relationship DB        (default relationships.db)
    PAPERFINDER_REVIEW_PORT  local port             (default 8765)
"""

import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from paperfinder.graph.relationship import RelationshipGraph
from paperfinder.graph.viz import render_html

REL_DB = os.environ.get("PAPERFINDER_REL_DB", "relationships.db")
HOST = "127.0.0.1"
PORT = int(os.environ.get("PAPERFINDER_REVIEW_PORT", "8765"))
WHO = os.environ.get("USER", "review-ui")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):            # keep the terminal quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            graph = RelationshipGraph(REL_DB).export_graph(include_candidates=True)
            self._send(200, render_html(graph, interactive=True), "text/html; charset=utf-8")
        else:
            self._send(404, '{"ok":false}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(n) or "{}")
        except json.JSONDecodeError:
            return self._send(400, '{"ok":false}')
        if self.path == "/authenticate":
            RelationshipGraph(REL_DB).authenticate(body["src"], body["dst"], [], WHO)
            self._send(200, '{"ok":true}')
        elif self.path == "/reject":
            RelationshipGraph(REL_DB).reject(body["src"], body["dst"])
            self._send(200, '{"ok":true}')
        elif self.path == "/shutdown":
            self._send(200, '{"ok":true}')
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send(404, '{"ok":false}')


def main():
    if not RelationshipGraph(REL_DB).export_graph(include_candidates=True)["nodes"]:
        print("graph is empty - run examples/build_graph.py first")
        return 1
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = "http://%s:%d/" % (HOST, PORT)
    print("review session at " + url)
    print("authenticate/reject by clicking edges; click 'Done reviewing' (or Ctrl-C) to stop")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("review session ended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
