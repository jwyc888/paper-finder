#!/usr/bin/env python3
"""Standalone local chat window over your paper library.

A thin front-end over studio.chat.ChatSession: it opens a browser page with a
transcript and an input box and answers through the same engine the CLI uses.
Local only (binds 127.0.0.1), single conversation, stdlib server (no Flask).

  python examples/chat_web.py                        # whole corpus, local model
  python examples/chat_web.py --folder "BioBank ref"
  python examples/chat_web.py --frontier             # answer with Anthropic
  python examples/chat_web.py --k 12 --port 8770

Model and scope are fixed at launch by these flags. Click "Stop server" in the
page (or Ctrl-C in the terminal) to shut it down.
"""

import argparse
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from paperfinder.cli import open_finder
from paperfinder.studio.chat import ChatSession


def _link(p) -> str:
    if p.get("source_url"):
        return p["source_url"]
    if str(p.get("doc_id", "")).startswith("gdrive:"):
        return "https://drive.google.com/file/d/" + p["doc_id"][7:] + "/view"
    return ""


def answer_payload(session, message: str) -> dict:
    """Run one turn and shape the JSON the page expects (deduped sources with links)."""
    res = session.ask(message)
    seen, sources = set(), []
    for p in res.get("sources", []):
        if p["doc_id"] in seen:
            continue
        seen.add(p["doc_id"])
        sources.append({"title": p["title"], "link": _link(p)})
    return {"answer": res.get("answer", ""), "sources": sources}


def page_html(scope_label: str, model_label: str) -> str:
    sub = (scope_label + " | " if scope_label else "") + "model: " + model_label
    return _PAGE.replace("__SUB__", sub)


_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>paper-finder chat</title>
<style>
  :root{--paper:#faf8f3;--ink:#27241d;--muted:#6f6a5f;--teal:#0f6e56;--line:#e2ddd0}
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:"Newsreader",Georgia,serif;display:flex;flex-direction:column}
  header{padding:18px 24px 12px;border-bottom:1px solid var(--line)}
  h1{font-family:"Fraunces",Georgia,serif;font-weight:500;font-size:22px;margin:0}
  .sub{color:var(--muted);font-size:13px;margin-top:3px}
  #log{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:14px}
  .msg{max-width:760px;line-height:1.5}
  .msg.user{align-self:flex-end;background:#eef3f0;border:1px solid var(--line);border-radius:10px;padding:8px 12px}
  .msg.bot .ans{white-space:pre-wrap}
  .msg.bot{align-self:flex-start}
  .thinking{color:var(--muted);font-style:italic}
  .src{margin-top:8px;font-size:13px;color:var(--muted)}
  .src ul{margin:4px 0 0;padding-left:18px}
  .src a{color:var(--teal)}
  footer{border-top:1px solid var(--line);padding:12px 24px;display:flex;gap:10px;align-items:flex-end}
  textarea{flex:1;resize:none;height:46px;font-family:inherit;font-size:15px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:#fffdf8;color:var(--ink)}
  button{font-family:inherit;font-size:14px;padding:10px 16px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink);cursor:pointer}
  button.primary{border-color:var(--teal);color:var(--teal)}
  button:hover{background:#f3efe6}
  .spacer{flex:1}
</style></head>
<body>
  <header>
    <h1>paper-finder chat</h1>
    <div class="sub">__SUB__ &middot; ask what you have on a topic, how papers relate, and follow up</div>
  </header>
  <div id="log"></div>
  <footer>
    <textarea id="box" placeholder="Ask a question, then Enter (Shift+Enter for a new line)"></textarea>
    <button id="send" class="primary">Send</button>
    <button id="reset">Reset</button>
    <button id="stop">Stop server</button>
  </footer>
<script>
  const log = document.getElementById("log");
  const box = document.getElementById("box");
  function bubble(role){ const d=document.createElement("div"); d.className="msg "+role; log.appendChild(d); log.scrollTop=log.scrollHeight; return d; }
  async function send(){
    const q = box.value.trim(); if(!q) return;
    box.value="";
    const u = bubble("user"); u.textContent = q;
    const t = bubble("bot"); const th=document.createElement("div"); th.className="thinking"; th.textContent="thinking..."; t.appendChild(th);
    log.scrollTop = log.scrollHeight;
    try{
      const r = await fetch("/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:q})});
      const d = await r.json();
      t.innerHTML="";
      const ans=document.createElement("div"); ans.className="ans"; ans.textContent=d.answer||""; t.appendChild(ans);
      if(d.sources && d.sources.length){
        const sd=document.createElement("div"); sd.className="src"; sd.appendChild(document.createTextNode("sources:"));
        const ul=document.createElement("ul");
        d.sources.forEach(s=>{ const li=document.createElement("li");
          if(s.link){ const a=document.createElement("a"); a.href=s.link; a.target="_blank"; a.textContent=s.title; li.appendChild(a); }
          else { li.textContent=s.title; }
          ul.appendChild(li); });
        sd.appendChild(ul); t.appendChild(sd);
      }
    }catch(e){ t.innerHTML=""; const er=document.createElement("div"); er.textContent="(error: "+e+")"; t.appendChild(er); }
    log.scrollTop = log.scrollHeight;
  }
  box.addEventListener("keydown", e=>{ if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); send(); }});
  document.getElementById("send").onclick = send;
  document.getElementById("reset").onclick = async ()=>{ await fetch("/reset",{method:"POST"}); log.innerHTML=""; };
  document.getElementById("stop").onclick = async ()=>{ await fetch("/shutdown",{method:"POST"}); document.body.innerHTML="<div style='padding:40px;font-family:Newsreader,serif'>Chat server stopped. You can close this tab.</div>"; };
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, page_html(*self.server.labels), "text/html; charset=utf-8")
        else:
            self._send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b""
        if self.path == "/ask":
            try:
                msg = (json.loads(raw or b"{}").get("message") or "").strip()
                payload = answer_payload(self.server.session, msg) if msg else {"answer": "", "sources": []}
            except Exception as e:
                payload = {"answer": f"(error: {e})", "sources": []}
            self._send(200, json.dumps(payload))
        elif self.path == "/reset":
            self.server.session.history.clear()
            self._send(200, json.dumps({"ok": True}))
        elif self.path == "/shutdown":
            self._send(200, json.dumps({"ok": True}))
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send(404, "{}")

    def log_message(self, *a):
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Standalone chat window over the paper library.")
    ap.add_argument("--folder", help="scope the chat to a folder (or beneath it)")
    ap.add_argument("--frontier", action="store_true", help="answer with the frontier model")
    ap.add_argument("--k", type=int, default=8, help="passages retrieved per turn")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PAPERFINDER_CHAT_PORT", "8770")))
    args = ap.parse_args()

    finder = open_finder()
    session = ChatSession(finder, k=args.k, folder=args.folder, frontier=args.frontier)
    httpd = HTTPServer(("127.0.0.1", args.port), Handler)
    httpd.session = session
    httpd.labels = (f"[{args.folder}]" if args.folder else "", "frontier" if args.frontier else "local")

    url = f"http://127.0.0.1:{args.port}/"
    print(f"chat window at {url}  (Ctrl-C or the Stop button to quit)", file=sys.stderr)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
