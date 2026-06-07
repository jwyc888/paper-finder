#!/usr/bin/env python3
"""
show_graph.py - open an interactive review session for the relationship graph.

Stands up a small local server, opens your browser to the graph, and serves it
with Authenticate / Reject buttons on edge-click. Clicking a node opens its source.

With --chat, a chat box is docked beside the graph:
  - ask a question and the answer's source papers highlight while the view zooms;
  - click nodes to select a cluster (double-click opens the paper), then
    "Synthesize selected" runs a cross-paper synthesis in the background and posts
    a downloadable PDF link when ready, so you can keep chatting meanwhile.

Chat/synthesis need the real index (PAPERFINDER_EMBEDDER=st,
PAPERFINDER_VECTOR_STORE=qdrant) and, for PDF export, reportlab (pip install
reportlab). Without --chat the window is review-only and lightweight.

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
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from paperfinder.graph.relationship import RelationshipGraph
from paperfinder.graph.viz import render_html
from paperfinder.studio.studyset import build_studyset
from paperfinder.studio.synthesis import synthesize
from paperfinder.studio.export import synthesis_to_pdf

REL_DB = os.environ.get("PAPERFINDER_REL_DB", "relationships.db")
HOST = "127.0.0.1"
PORT = int(os.environ.get("PAPERFINDER_REVIEW_PORT", "8765"))
WHO = os.environ.get("USER", "review-ui")
OUTDIR = os.path.join(os.getcwd(), "studysets")

JOBS = {}                         # job_id -> {status, n, pdf?, error?}
JOBS_LOCK = threading.Lock()


def _qs_id(path):
    return (parse_qs(urlparse(path).query).get("id") or [""])[0]


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
        elif self.path.startswith("/synthesis_status"):
            with JOBS_LOCK:
                job = dict(JOBS.get(_qs_id(self.path)) or {})
            if not job:
                return self._send(404, json.dumps({"status": "unknown"}))
            out = {"status": job.get("status"), "n": job.get("n")}
            if job.get("status") == "error":
                out["error"] = job.get("error")
            self._send(200, json.dumps(out))
        elif self.path.startswith("/download"):
            with JOBS_LOCK:
                job = dict(JOBS.get(_qs_id(self.path)) or {})
            pdf = job.get("pdf")
            if job.get("status") != "done" or not pdf or not os.path.exists(pdf):
                return self._send(404, '{"ok":false}')
            with open(pdf, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition",
                             'attachment; filename="%s"' % os.path.basename(pdf))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
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
        elif self.path == "/synthesize":
            self._start_synthesis(body)
        elif self.path == "/shutdown":
            self._send(200, '{"ok":true}')
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send(404, '{"ok":false}')

    def _start_synthesis(self, body):
        sess = self.server.session
        if not sess:
            return self._send(404, '{"ok":false}')
        ids = [i for i in (body.get("ids") or []) if i]
        if len(ids) < 2:
            return self._send(400, json.dumps({"error": "select at least two papers"}))
        # Build the study set here, on the request thread: this is the only part
        # that reads the shared index/SQLite. The worker below touches neither.
        try:
            studyset = build_studyset(sess.finder, RelationshipGraph(REL_DB), ids)
        except Exception as e:
            return self._send(500, json.dumps({"error": "could not build study set: %s" % e}))
        if len(studyset.papers) < 2:
            return self._send(400, json.dumps({"error": "fewer than two of those are known papers"}))

        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "running", "n": len(studyset.papers)}

        def run():
            try:
                md = synthesize(studyset, frontier=sess.frontier, complete=sess._complete)
                os.makedirs(OUTDIR, exist_ok=True)
                pdf = os.path.join(OUTDIR, "synthesis-%s.pdf" % job_id)
                synthesis_to_pdf(md, pdf, "Synthesis of %d papers" % len(studyset.papers),
                                 [p.title for p in studyset.papers])
                with JOBS_LOCK:
                    JOBS[job_id].update(status="done", pdf=pdf)
            except Exception as e:
                with JOBS_LOCK:
                    JOBS[job_id].update(status="error", error=str(e))

        threading.Thread(target=run, daemon=True).start()
        self._send(200, json.dumps({"job_id": job_id, "n": len(studyset.papers)}))


def main():
    ap = argparse.ArgumentParser(description="Interactive relationship-graph review, optionally with chat + synthesis.")
    ap.add_argument("--chat", action="store_true", help="dock a chat box and enable cluster synthesis")
    ap.add_argument("--folder", help="scope chat to a folder (or beneath it)")
    ap.add_argument("--frontier", action="store_true", help="chat/synthesis via the frontier model")
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
    # synthesis runs on its own worker thread that touches neither.
    server_class = HTTPServer if args.chat else ThreadingHTTPServer
    server = server_class((HOST, PORT), Handler)
    server.session = session
    server.chat = bool(args.chat)

    url = "http://%s:%d/" % (HOST, PORT)
    print("review session at " + url)
    tail = "authenticate/reject by clicking edges"
    if args.chat:
        tail += "; ask the chat box, or select nodes and Synthesize selected"
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
