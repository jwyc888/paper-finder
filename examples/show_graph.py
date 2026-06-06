#!/usr/bin/env python3
"""
show_graph.py - open an interactive review session for the relationship graph.

Stands up a small local server, opens your browser to the graph, and serves it
with Authenticate / Reject buttons on edge-click. Clicking a node opens its source.

With --chat, a chat box is docked beside the graph: ask a question and the
answer's source papers highlight while the view zooms to them. Chat needs the real
index (set PAPERFINDER_EMBEDDER=st and PAPERFINDER_VECTOR_STORE=qdrant); the first
question warms up the embedder. Without --chat the window is review-only and
lightweight, exactly as before.

Run:
    python3 examples/show_graph.py
    python3 examples/show_graph.py --chat
    python3 examples/show_graph.py --chat --folder "BioBank ref" --frontier

Config (env):
    PAPERFINDER_REL_DB       relationship DB        (default relationships.db)
    PAPERFINDER_REVIEW_PORT  local port             (default 8765)
"""

import argparse
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

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
            self._send(200, render_html(graph, interactive=True, chat=self.server.chat),
                       "text/html; charset=utf-8")
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
        elif self.path == "/chat":
            if not self.server.session:
                return self._send(404, '{"ok":false}')
            from paperfinder.studio.chat import web_sources
            msg = (body.get("message") or "").strip()
            try:
                res = self.server.session.ask(msg) if msg else {"answer": "", "sources": []}
                payload = {"answer": res.get("answer", ""),
                           "sources": web_sources(res.get("sources", []))}
            except Exception as e:
                payload = {"answer": "(error: %s)" % e, "sources": []}
            self._send(200, json.dumps(payload))
        elif self.path == "/shutdown":
            self._send(200, '{"ok":true}')
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send(404, '{"ok":false}')


def main():
    ap = argparse.ArgumentParser(description="Interactive relationship-graph review, optionally with chat.")
    ap.add_argument("--chat", action="store_true", help="dock a chat box that highlights answer sources in the graph")
    ap.add_argument("--folder", help="scope chat to a folder (or beneath it)")
    ap.add_argument("--frontier", action="store_true", help="chat answers via the frontier model")
    ap.add_argument("--k", type=int, default=8, help="chat passages retrieved per turn")
    args = ap.parse_args()

    if not RelationshipGraph(REL_DB).export_graph(include_candidates=True)["nodes"]:
        print("graph is empty - run examples/build_graph.py first")
        return 1

    session = None
    if args.chat:
        from paperfinder.cli import open_finder
        from paperfinder.studio.chat import ChatSession
        print("loading the index for chat (the first question warms up the embedder)...")
        session = ChatSession(open_finder(), k=args.k, folder=args.folder, frontier=args.frontier)

    # Single-threaded when chatting so the shared index/SQLite stay on one thread;
    # multi-threaded review otherwise, unchanged.
    server_class = HTTPServer if args.chat else ThreadingHTTPServer
    server = server_class((HOST, PORT), Handler)
    server.session = session
    server.chat = bool(args.chat)

    url = "http://%s:%d/" % (HOST, PORT)
    print("review session at " + url)
    tail = "authenticate/reject by clicking edges"
    if args.chat:
        tail += "; ask the chat box on the left to highlight papers"
    print(tail + "; click 'Done reviewing' (or Ctrl-C) to stop")
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
