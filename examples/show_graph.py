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
from urllib.parse import urlparse, parse_qs, quote

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

_DRIVE = {}                       # lazily-built service-account Drive client


def _drive_fetch(file_id: str):
    """Return (bytes, mime_type, name) for a Drive file using the service account
    (which has access to everything it crawled). Raises if creds/library are
    unavailable; the caller logs and falls back to the Drive web link."""
    svc = _DRIVE.get("svc")
    if svc is None:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        key = os.environ.get("PAPERFINDER_SA_KEY", "service_account.json")
        creds = service_account.Credentials.from_service_account_file(
            key, scopes=["https://www.googleapis.com/auth/drive.readonly"])
        svc = build("drive", "v3", credentials=creds)
        _DRIVE["svc"] = svc
    meta = svc.files().get(fileId=file_id, fields="mimeType,name").execute()
    data = svc.files().get_media(fileId=file_id).execute()
    return data, (meta.get("mimeType") or ""), (meta.get("name") or file_id)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# In-page PDF viewer: renders the paper with PDF.js (canvas), so it opens in the tab
# regardless of the browser's PDF-download setting, and offers an explicit Download.
PDF_VIEWER_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
  html,body{margin:0;height:100%;background:#3a3a3a;font-family:Georgia,serif;}
  #bar{position:sticky;top:0;z-index:1;display:flex;align-items:center;gap:12px;
       padding:8px 14px;background:#222;color:#eee;}
  #bar .t{flex:1;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  #bar a{color:#ffd23f;text-decoration:none;border:1px solid #ffd23f;
         padding:4px 12px;border-radius:4px;font-size:13px;}
  #pages{padding:16px;display:flex;flex-direction:column;align-items:center;gap:12px;}
  #pages canvas{box-shadow:0 1px 6px rgba(0,0,0,.5);max-width:100%;height:auto;}
  #msg{color:#ccc;padding:24px;font-size:14px;}
</style></head>
<body>
  <div id="bar"><span class="t">__TITLE__</span>
    <a href="__RAW__&dl=1" download>Download</a></div>
  <div id="pages"><div id="msg">Loading paper...</div></div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
  <script>
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
    var pages = document.getElementById("pages");
    var msg = document.getElementById("msg");
    pdfjsLib.getDocument("__RAW__").promise.then(async function (pdf) {
      msg.remove();
      for (var i = 1; i <= pdf.numPages; i++) {
        var page = await pdf.getPage(i);
        var vp = page.getViewport({ scale: 1.5 });
        var c = document.createElement("canvas");
        c.width = vp.width; c.height = vp.height;
        pages.appendChild(c);
        await page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise;
      }
    }).catch(function (e) {
      msg.textContent = "Could not render this file in the browser (" + e +
        "). Use the Download button above.";
    });
  </script>
</body></html>"""


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

    def _stream_inline(self, data, name, ctype=None, disposition="inline"):
        if not ctype:
            ctype = "application/pdf" if data[:5] == b"%PDF-" else "application/octet-stream"
        elif ctype == "application/octet-stream" and data[:5] == b"%PDF-":
            ctype = "application/pdf"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", '%s; filename="%s"' % (disposition, name))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            self._do_get()
        except Exception as e:
            try:
                self._send(500, json.dumps({"error": str(e)}))
            except Exception:
                pass

    def do_POST(self):
        try:
            self._do_post()
        except Exception as e:
            try:
                self._send(500, json.dumps({"error": str(e)}))
            except Exception:
                pass

    def _do_get(self):
        if self.path in ("/", "/index.html"):
            graph = RelationshipGraph(REL_DB).export_graph(include_candidates=True)
            self._send(200, render_html(graph, interactive=True, chat=self.server.chat),
                       "text/html; charset=utf-8")
        elif self.path.startswith("/open"):
            q = parse_qs(urlparse(self.path).query)
            nid = (q.get("id") or [""])[0]
            raw = bool(q.get("raw"))
            dl = bool(q.get("dl"))
            doc = RelationshipGraph(REL_DB).get_document(nid) if nid else None
            src = (doc or {}).get("source_url") or ""
            is_gdrive = nid.startswith("gdrive:")
            is_local = src.startswith("file://")
            weblink = src if src.startswith("http") else (
                "https://drive.google.com/file/d/%s/view" % nid[7:] if is_gdrive else "")

            # raw bytes: requested by the in-page viewer and by its Download button
            if raw and (is_gdrive or is_local):
                disp = "attachment" if dl else "inline"
                if is_local:
                    path = src[7:]
                    if not os.path.exists(path):
                        return self._send(404, '{"ok":false}')
                    with open(path, "rb") as f:
                        return self._stream_inline(f.read(), os.path.basename(path),
                                                   disposition=disp)
                try:
                    data, mime, name = _drive_fetch(nid[7:])
                    return self._stream_inline(data, name, mime, disposition=disp)
                except Exception as e:
                    sys.stderr.write(
                        "[/open] service-account fetch failed for %s: %s; "
                        "redirecting to the Drive web link\n" % (nid, e))
                    if weblink:
                        self.send_response(302)
                        self.send_header("Location", weblink)
                        self.end_headers()
                        return
                    return self._send(404, '{"ok":false}')

            # default: the in-page viewer for anything we can stream (Drive or local file)
            if is_gdrive or is_local:
                title = (doc or {}).get("title") or (
                    os.path.basename(src[7:]) if is_local else nid)
                rawurl = "/open?id=%s&raw=1" % quote(nid, safe="")
                html = (PDF_VIEWER_HTML
                        .replace("__TITLE__", _esc(title))
                        .replace("__RAW__", rawurl))
                return self._send(200, html, "text/html; charset=utf-8")

            # external web link we do not hold bytes for: open it directly
            if weblink:
                self.send_response(302)
                self.send_header("Location", weblink)
                self.end_headers()
                return
            self._send(404, '{"ok":false}')
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

    def _do_post(self):
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
            import re
            from paperfinder.studio.chat import web_sources
            from paperfinder.graph.stats import graph_digest
            msg = (body.get("message") or "").strip()
            selected = [s for s in (body.get("selected") or []) if s]
            try:
                if msg:
                    export = RelationshipGraph(REL_DB).export_graph(include_candidates=True)
                    digest = graph_digest(export)
                    if selected:
                        id2t = {nd["id"]: (nd.get("title") or nd["id"]) for nd in export["nodes"]}
                        titles = ", ".join('"%s"' % id2t.get(s, s) for s in selected)
                        digest += ("\n\nCURRENTLY SELECTED BY THE USER (papers the user has "
                                   "selected in the graph right now): " + titles + ".")
                    res = self.server.session.ask(msg, graph_text=digest)
                    answer = res.get("answer", "")
                    # Highlight/list only the papers the answer cites by [Title], so the
                    # sources match what was discussed rather than every retrieved chunk.
                    by_title = {}
                    for nd in export["nodes"]:
                        t = (nd.get("title") or "").strip().lower()
                        if t:
                            by_title.setdefault(t, nd)
                    cited = []
                    for mt in re.findall(r"\[([^\[\]]+)\]", answer):
                        nd = by_title.get(mt.strip().lower())
                        if nd:
                            cited.append({"doc_id": nd["id"], "title": nd.get("title") or nd["id"],
                                          "source_url": nd.get("source_url") or ""})
                    payload = {"answer": answer, "sources": web_sources(cited)}
                else:
                    payload = {"answer": "", "sources": []}
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
    server_class.request_queue_size = 128   # absorb status polls while a slow chat is in flight
    server = server_class((HOST, PORT), Handler)
    server.session = session
    server.chat = bool(args.chat)

    url = "http://%s:%d/" % (HOST, PORT)
    print("review session at " + url)
    tail = "authenticate/reject by clicking edges"
    if args.chat:
        tail += "; ask the chat box, or select nodes and Synthesize selected"
    print(tail + "; press Ctrl-C to stop")
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
