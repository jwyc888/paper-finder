"""Interactive graph visualisation. Authenticated edges are solid; inferred
candidates are dashed and faint. Edge tooltips show the passages that linked the
papers. A score-threshold slider hides weak links, labels are compacted/wrapped,
and clicking a node opens its source file.

render_html(graph, interactive=True) adds a click-to-review layer (Authenticate /
Reject buttons that POST to a local server). build_viz writes the static, non
interactive page used by the automation."""

import json

_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  :root{--paper:#faf8f3;--ink:#27241d;--muted:#6f6a5f;--teal:#0f6e56;--amber:#a06414;--line:#e2ddd0}
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:"Newsreader",Georgia,serif}
  header{padding:28px 32px 14px;border-bottom:1px solid var(--line)}
  h1{font-family:"Fraunces",Georgia,serif;font-weight:500;font-size:30px;margin:0;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:15px;margin-top:4px}
  .legend{display:flex;gap:22px;align-items:center;padding:12px 32px;font-size:14px;color:var(--muted);border-bottom:1px solid var(--line);flex-wrap:wrap}
  .legend b{color:var(--ink);font-weight:500}
  .swatch{display:inline-block;width:30px;height:0;vertical-align:middle;margin-right:7px}
  .s-auth{border-top:3px solid var(--teal)}
  .s-cand{border-top:2px dashed var(--amber)}
  .s-cross{border-top:3px solid #d6336c}
  .dot{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:middle;margin-right:7px;border:1px solid rgba(0,0,0,.15)}
  .controls{display:flex;gap:14px;align-items:center;padding:12px 32px;font-size:14px;color:var(--muted);border-bottom:1px solid var(--line)}
  .controls label{color:var(--ink)}
  #thr{width:280px;accent-color:var(--teal)}
  .val{font-variant-numeric:tabular-nums;color:var(--ink);min-width:42px}
  .cnt{margin-left:auto}
  #net{height:64vh;width:100%}
  .hint{padding:10px 32px;color:var(--muted);font-size:13px}
  .btn{font-family:"Newsreader",Georgia,serif;font-size:13px;padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);cursor:pointer}
  .btn:hover{background:#f3efe6}
  .btn-auth{border-color:var(--teal);color:var(--teal)}
  .btn-reject{border-color:var(--amber);color:var(--amber)}
  #review{display:none;position:fixed;right:24px;bottom:24px;width:340px;background:#fffdf8;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.14);padding:16px;z-index:10}
  #rv-pair{font-size:14px;line-height:1.35;margin-bottom:6px}
  #rv-score{color:var(--muted);font-size:13px;margin-bottom:12px}
  #rv-msg{color:var(--muted);font-size:12px;margin-top:8px}
  .vis-tooltip{font-family:"Newsreader",Georgia,serif !important;max-width:380px;white-space:normal !important;
    background:#fffdf8 !important;border:1px solid var(--line) !important;color:var(--ink) !important;
    border-radius:6px !important;padding:10px 12px !important;box-shadow:0 4px 14px rgba(0,0,0,.10) !important}
  #chat{display:none;flex-direction:column;position:fixed;left:24px;top:calc(100vh - 472px);width:420px;height:440px;min-width:280px;min-height:200px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px);background:#fffdf8;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.14);padding:12px;z-index:10;resize:both;overflow:hidden}
  #chat-head{display:flex;align-items:center;gap:8px;margin:0 0 8px;cursor:move;user-select:none}
  #chat-head h2{font-family:"Fraunces",Georgia,serif;font-weight:500;font-size:14px;margin:0}
  #chat-max{margin-left:auto;cursor:pointer;border:1px solid var(--line);background:#fff;border-radius:6px;font-size:12px;padding:2px 8px;color:var(--ink)}
  #chat-log{flex:1;overflow-y:auto;font-size:13px;line-height:1.45;margin-bottom:8px}
  #chat-row{display:flex;gap:6px}
  #chat-box{flex:1;font-family:inherit;font-size:13px;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink)}
  #chat-syn{margin-top:8px;width:100%;cursor:pointer}
  #chat .cmsg{margin-bottom:8px}
  #chat .cu{color:var(--muted)}
  #chat .cb .ans{white-space:pre-wrap}
  #chat .csrc{margin-top:4px;color:var(--muted)}
  #chat .csrc a{color:var(--teal);cursor:pointer;text-decoration:underline}
  #chat .thinking{color:var(--muted);font-style:italic}
</style></head>
<body>
  <header>
    <h1>__TITLE__</h1>
    <div class="sub">Solid links are human-verified. Dashed links are inferred candidates. Hover a link to read the connecting passages; click a node to open its source.</div>
  </header>
  <div class="legend">
    <span><span class="swatch s-auth"></span><b>Authenticated</b>: verified by a human</span>
    <span><span class="swatch s-cand"></span><b>Candidate</b>: inferred from shared passages</span>
    <span><span class="swatch s-cross"></span><b>Cross-folder</b>: links two different folders</span>
  </div>
  <div class="legend" id="folderlegend"></div>
  <div class="controls">
    <label for="thr">Min score</label>
    <input id="thr" type="range">
    <span id="thrval" class="val"></span>
    <label class="emphlbl"><input id="emph" type="checkbox" checked> Emphasize cross-folder links</label>
    <span id="nodecnt" class="cnt"></span>
    <span id="cnt" class="cnt"></span>
  </div>
  <div id="net"></div>
  <div class="hint">__HINT__</div>
  __REVIEWUI__
  __CHATUI__
<script>
  const G = __DATA__;
  const INTERACTIVE = __INTERACTIVE__;
  const CHAT = __CHAT__;
  const teal = "#0f6e56", amber = "#a06414", ink = "#27241d";
  const esc = s => (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  const trim = (s, n=240) => { s = (s||"").replace(/\\s+/g," ").trim(); return s.length>n ? s.slice(0,n)+"\\u2026" : s; };
  const shortLabel = t => { t = (t||"").trim(); return t.length>60 ? t.slice(0,60)+"\\u2026" : t; };
  const rawUrl = n => n.source_url || (String(n.id).startsWith("gdrive:")
        ? "https://drive.google.com/file/d/" + String(n.id).slice(7) + "/view" : "");
  const nodeUrl = n => { const u = rawUrl(n); return u ? (INTERACTIVE ? "/open?id=" + encodeURIComponent(n.id) : u) : ""; };
  const topFolder = n => { const f = (n.folder || ""); return f ? f.split("/")[0] : ""; };
  const PALETTE = ["#0f6e56","#a06414","#3b6ea5","#8a5a2b","#6b7e3a","#2f7d7d","#9a3b6e","#5b6770"];
  const ROOTCOLOR = "#b8b2a7";
  const FOCUSFILL = "#ffd23f";   // bright, distinct from every folder color, for the in-focus node
  const topFolders = [...new Set(G.nodes.map(topFolder).filter(Boolean))].sort();
  const folderColor = {}; topFolders.forEach((f, i) => folderColor[f] = PALETTE[i % PALETTE.length]);
  const colorFor = n => { const t = topFolder(n); return t ? folderColor[t] : ROOTCOLOR; };
  const topById = {}; G.nodes.forEach(n => topById[n.id] = topFolder(n));
  const titleById = {}; G.nodes.forEach(n => titleById[n.id] = n.title);
  (function(){ const fl = document.getElementById("folderlegend"); if (!fl) return;
    let h = topFolders.map(f => "<span><span class='dot' style='background:" + folderColor[f] + "'></span>" + esc(f) + "</span>").join("");
    if (G.nodes.some(n => !topFolder(n))) h += "<span><span class='dot' style='background:" + ROOTCOLOR + "'></span>(root)</span>";
    fl.innerHTML = h; })();

  const nodes = new vis.DataSet(G.nodes.map(n => {
    const tip = document.createElement("div");
    let th = "<b>" + esc(n.title) + "</b>";
    if (n.folder) th += "<br><span style='color:#6f6a5f'>" + esc(n.folder) + "</span>";
    const kw = (n.descriptors && n.descriptors.length)
      ? esc(n.descriptors.slice(0, 6).join(", ")) : "";
    if (kw) th += "<br><span style='color:#6f6a5f'>" + kw + "</span>";
    if (nodeUrl(n)) th += "<br><span style='color:#6f6a5f'>click to open</span>";
    tip.innerHTML = th;
    return {
      id: n.id,
      label: (topFolder(n) ? "[" + topFolder(n) + "] " : "") + shortLabel(n.title),
      title: tip,
      url: nodeUrl(n),
      shape: "dot", size: 13,
      widthConstraint: { maximum: 170 },
      borderWidthSelected: 3,
      color: { background: colorFor(n), border: ink, highlight: { background: FOCUSFILL, border: amber } },
      font: { face: "Georgia", size: 15, color: ink, multi: false }
    };
  }));

  // Unconnected papers (no edges) get flung off-screen by the repulsion physics.
  // Take them out of the sim now, then (after stabilization) park them in a grid just
  // below the connected cluster's bounding box so they are always visible. placeIsolated
  // runs once physics has settled, when the cluster's real extent is known.
  const degree = {};
  G.edges.forEach(e => { degree[e.src] = (degree[e.src] || 0) + 1; degree[e.dst] = (degree[e.dst] || 0) + 1; });
  const isolated = G.nodes.filter(n => !degree[n.id]);
  if (isolated.length) nodes.update(isolated.map(n => ({ id: n.id, fixed: true, physics: false })));
  function placeIsolated() {
    if (!isolated.length) return;
    const connIds = G.nodes.filter(n => degree[n.id]).map(n => n.id);
    const pos = connIds.length ? network.getPositions(connIds) : {};
    let minX = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const id in pos) { const p = pos[id]; minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y); }
    if (!isFinite(minX)) { minX = -200; maxX = 200; maxY = -140; }
    const cols = Math.max(1, Math.ceil(Math.sqrt(isolated.length) * 1.5));
    const GAP = 80, width = (cols - 1) * GAP, cx = (minX + maxX) / 2;
    nodes.update(isolated.map((n, idx) => {
      const r = Math.floor(idx / cols), c = idx % cols;
      return { id: n.id, x: cx - width / 2 + c * GAP, y: maxY + 140 + r * GAP, fixed: true, physics: false };
    }));
  }

  let emphasizeCross = true;
  const emphColor = "#d6336c";
  const edgeStyle = ed => {
    const auth = ed._status === "authenticated";
    const cross = emphasizeCross && ed._cross;
    return {
      color: { color: cross ? emphColor : (auth ? teal : amber), opacity: cross ? 0.95 : (auth ? 0.95 : 0.5) },
      width: cross ? (auth ? 3.5 : 2.6) : (auth ? 3 : 1.4),
      dashes: auth ? false : [5,5]
    };
  };

  const allEdges = new vis.DataSet(G.edges.map((e, i) => {
    const auth = e.status === "authenticated";
    const prov = auth ? ("Verified by " + esc(e.verified_by || "human"))
                      : ("Inferred candidate, score " + (e.confidence ?? "").toString().slice(0,5));
    const el = document.createElement("div");
    let h = "<b>" + prov + "</b>";
    const why = (e.descriptors && e.descriptors.length) ? esc(e.descriptors.join(", ")) : "";
    if (why) h += "<br>via: " + why;
    const ev = e.evidence || {};
    if (ev.src_passage) h += "<br><br>" + esc(trim(ev.src_passage));
    if (ev.dst_passage) h += "<br><br>" + esc(trim(ev.dst_passage));
    el.innerHTML = h;
    const sg = topById[e.src] || "", dg = topById[e.dst] || "";
    const base = {
      id: i, from: e.src, to: e.dst, _src: e.src, _dst: e.dst, _status: e.status,
      _score: (e.confidence == null ? null : e.confidence),
      _cross: !!(sg && dg && sg !== dg), title: el
    };
    return Object.assign(base, edgeStyle(base));
  }));

  const restyle = () => allEdges.update(allEdges.get().map(ed => Object.assign({ id: ed.id }, edgeStyle(ed))));
  const emphBox = document.getElementById("emph");
  if (emphBox) emphBox.addEventListener("change", () => { emphasizeCross = emphBox.checked; restyle(); });

  const scores = G.edges.filter(e => e.confidence != null).map(e => e.confidence);
  const lo = scores.length ? Math.floor(Math.min(...scores) * 100) / 100 : 0;
  const hi = scores.length ? Math.ceil(Math.max(...scores) * 100) / 100 : 1;
  const thr = document.getElementById("thr");
  const thrval = document.getElementById("thrval");
  const cnt = document.getElementById("cnt");
  thr.min = 0; thr.max = hi; thr.step = 0.01; thr.value = lo;
  let threshold = lo;
  const nodecnt = document.getElementById("nodecnt");
  if (nodecnt) nodecnt.textContent = G.nodes.length + " papers (" + isolated.length + " unconnected) | ";

  const view = new vis.DataView(allEdges, { filter: e => e._score == null || e._score >= threshold });
  const refresh = () => {
    threshold = parseFloat(thr.value);
    thrval.textContent = threshold.toFixed(2);
    view.refresh();
    const shown = allEdges.get({ filter: e => e._score == null || e._score >= threshold }).length;
    cnt.textContent = shown + " of " + allEdges.length + " links shown";
  };
  thr.addEventListener("input", refresh);
  refresh();

  const network = new vis.Network(document.getElementById("net"), { nodes, edges: view }, {
    physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -45, springLength: 130 }, stabilization: { iterations: 220 } },
    interaction: { hover: true, tooltipDelay: 80, multiselect: true },
    nodes: { borderWidth: 1.5 }
  });

  network.once("stabilizationIterationsDone", () => { placeIsolated(); network.fit({ animation: false }); });
  setTimeout(() => { placeIsolated(); network.fit({ animation: false }); }, 2500);

  const synSel = new Set();
  const updateSynBtn = () => { const b = document.getElementById("chat-syn"); if (b) b.textContent = "Synthesize selected (" + synSel.size + ")"; };
  let selectedEdge = null;
  network.on("click", params => {
    if (params.nodes.length) {
      const id = params.nodes[0];
      const se = params.event && params.event.srcEvent;
      if (CHAT && se && (se.metaKey || se.ctrlKey)) {   // cmd/ctrl-click: select for synthesis
        if (synSel.has(id)) synSel.delete(id); else synSel.add(id);
        network.setSelection({ nodes: Array.from(synSel) });
        updateSynBtn();
        return;
      }
      const n = nodes.get(id);                           // plain click: open the paper
      if (n && n.url) window.open(n.url, "_blank");
      return;
    }
    if (INTERACTIVE && params.edges.length) {
      selectedEdge = params.edges[0];
      const ed = allEdges.get(selectedEdge);
      if (!ed) return;
      document.getElementById("rv-pair").innerHTML =
        esc(titleById[ed._src] || ed._src) + "<br><b>&harr;</b><br>" + esc(titleById[ed._dst] || ed._dst);
      document.getElementById("rv-score").textContent =
        ed._status === "authenticated" ? "already authenticated"
          : ("candidate, score " + (ed._score == null ? "" : ed._score.toFixed(3)));
      document.getElementById("rv-msg").textContent = "";
      document.getElementById("review").style.display = "block";
    }
  });

  if (INTERACTIVE) {
    const post = async (path, body) => {
      try { const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); return r.ok; }
      catch (e) { return false; }
    };
    document.getElementById("rv-auth").onclick = async () => {
      const ed = allEdges.get(selectedEdge); if (!ed) return;
      if (await post("/authenticate", { src: ed._src, dst: ed._dst })) {
        allEdges.update({ id: selectedEdge, _score: null, _status: "authenticated" });
        restyle();
        refresh(); document.getElementById("rv-msg").textContent = "Authenticated.";
      } else document.getElementById("rv-msg").textContent = "Failed to reach server.";
    };
    document.getElementById("rv-reject").onclick = async () => {
      const ed = allEdges.get(selectedEdge); if (!ed) return;
      if (await post("/reject", { src: ed._src, dst: ed._dst })) {
        allEdges.remove(selectedEdge); refresh();
        document.getElementById("review").style.display = "none";
      } else document.getElementById("rv-msg").textContent = "Failed to reach server.";
    };
    document.getElementById("rv-close").onclick = () => { document.getElementById("review").style.display = "none"; };
  }

  if (CHAT) {
    const panel = document.getElementById("chat");
    panel.style.display = "flex";
    const head = document.getElementById("chat-head");
    let drag = null;
    head.addEventListener("mousedown", e => {
      if (e.target.id === "chat-max") return;
      const r = panel.getBoundingClientRect();
      drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
      e.preventDefault();
    });
    document.addEventListener("mousemove", e => {
      if (!drag) return;
      let x = Math.max(0, Math.min(e.clientX - drag.dx, window.innerWidth - panel.offsetWidth));
      let y = Math.max(0, Math.min(e.clientY - drag.dy, window.innerHeight - panel.offsetHeight));
      panel.style.left = x + "px"; panel.style.top = y + "px";
    });
    document.addEventListener("mouseup", () => { drag = null; });
    const maxBtn = document.getElementById("chat-max");
    let saved = null;
    maxBtn.onclick = () => {
      if (saved) {
        Object.assign(panel.style, saved); saved = null; maxBtn.textContent = "Max";
      } else {
        saved = { left: panel.style.left, top: panel.style.top, width: panel.style.width, height: panel.style.height };
        panel.style.left = "16px"; panel.style.top = "16px";
        panel.style.width = (window.innerWidth - 32) + "px";
        panel.style.height = (window.innerHeight - 32) + "px";
        maxBtn.textContent = "Restore";
      }
    };
    const clog = document.getElementById("chat-log");
    const cbox = document.getElementById("chat-box");
    const nodeIds = new Set(G.nodes.map(n => n.id));
    const cbubble = cls => { const d = document.createElement("div"); d.className = "cmsg " + cls; clog.appendChild(d); clog.scrollTop = clog.scrollHeight; return d; };
    const focusNodes = ids => {
      const hl = ids.filter(d => nodeIds.has(d));
      if (!hl.length) return;
      network.unselectAll();
      network.selectNodes(hl);
      network.fit({ nodes: hl, animation: { duration: 600 } });
    };
    const cask = async () => {
      const q = cbox.value.trim(); if (!q) return;
      cbox.value = "";
      cbubble("cu").textContent = "> " + q;
      const t = cbubble("cb");
      const th = document.createElement("div"); th.className = "thinking"; th.textContent = "thinking..."; t.appendChild(th);
      try {
        const r = await fetch("/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: q, selected: Array.from(synSel) }) });
        const d = await r.json();
        t.innerHTML = "";
        const ans = document.createElement("div"); ans.className = "ans"; ans.textContent = d.answer || ""; t.appendChild(ans);
        const srcs = d.sources || [];
        if (srcs.length) {
          const sd = document.createElement("div"); sd.className = "csrc"; sd.appendChild(document.createTextNode("sources: "));
          srcs.forEach((s, i) => {
            const a = document.createElement("a"); a.textContent = s.title; a.title = "focus in graph";
            a.onclick = () => focusNodes([s.doc_id]);
            sd.appendChild(a);
            if (i < srcs.length - 1) sd.appendChild(document.createTextNode(", "));
          });
          t.appendChild(sd);
          focusNodes(srcs.map(s => s.doc_id));
        }
      } catch (e) { t.innerHTML = ""; t.textContent = "(error: " + e + ")"; }
      clog.scrollTop = clog.scrollHeight;
    };
    document.getElementById("chat-send").onclick = cask;
    cbox.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); cask(); } });

    updateSynBtn();
    document.getElementById("chat-syn").onclick = async () => {
      const ids = Array.from(synSel);
      if (ids.length < 2) { cbubble("cb").textContent = "Select at least two papers (click their nodes) to synthesize."; return; }
      const note = cbubble("cb");
      note.textContent = "Synthesizing " + ids.length + " papers in the background. You can keep chatting; the PDF link will appear here when it is ready.";
      let job;
      try {
        const r = await fetch("/synthesize", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids }) });
        const d = await r.json();
        if (!r.ok || !d.job_id) { note.textContent = "(could not start synthesis: " + (d.error || r.status) + ")"; return; }
        job = d.job_id;
      } catch (e) { note.textContent = "(error starting synthesis: " + e + ")"; return; }
      const poll = setInterval(async () => {
        try {
          const r = await fetch("/synthesis_status?id=" + encodeURIComponent(job));
          const d = await r.json();
          if (d.status === "done") {
            clearInterval(poll);
            note.innerHTML = "";
            note.appendChild(document.createTextNode("Synthesis ready (" + d.n + " papers). "));
            const a = document.createElement("a"); a.href = "/download?id=" + encodeURIComponent(job);
            a.textContent = "Download PDF"; a.setAttribute("download", "");
            note.appendChild(a);
          } else if (d.status === "error") {
            clearInterval(poll);
            note.textContent = "(synthesis failed: " + (d.error || "unknown") + ")";
          }
        } catch (e) { /* transient; keep polling */ }
      }, 2000);
    };
  }
</script>
</body></html>"""

_REVIEW_UI = """<div id="review">
    <div id="rv-pair"></div>
    <div id="rv-score"></div>
    <div style="display:flex;gap:8px">
      <button id="rv-auth" class="btn btn-auth">Authenticate</button>
      <button id="rv-reject" class="btn btn-reject">Reject</button>
      <button id="rv-close" class="btn" style="margin-left:auto">Close</button>
    </div>
    <div id="rv-msg"></div>
  </div>"""

_CHAT_UI = """<div id="chat">
    <div id="chat-head"><h2>Ask the library</h2><button id="chat-max" title="Maximize / restore">Max</button></div>
    <div id="chat-log"></div>
    <div id="chat-row">
      <input id="chat-box" type="text" placeholder="what do I have on...">
      <button id="chat-send" class="btn btn-auth">Ask</button>
    </div>
    <button id="chat-syn" class="btn">Synthesize selected (0)</button>
  </div>"""


def render_html(graph: dict, title: str = "Paper relationships",
                interactive: bool = False, chat: bool = False) -> str:
    base_hint = "Drag nodes to rearrange. Drag the slider to hide weaker connections. Click a node to open the paper."
    review_hint = " Click an edge to authenticate or reject the connection."
    chat_hint = " Click a paper to open it; cmd or ctrl-click papers to select them, then Synthesize selected. Ask the box and the matching papers highlight."
    return (_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__DATA__", json.dumps(graph))
            .replace("__INTERACTIVE__", "true" if interactive else "false")
            .replace("__CHAT__", "true" if chat else "false")
            .replace("__REVIEWUI__", _REVIEW_UI if interactive else "")
            .replace("__CHATUI__", _CHAT_UI if chat else "")
            .replace("__HINT__", base_hint + (review_hint if interactive else "") + (chat_hint if chat else "")))


def build_viz(graph: dict, path: str, title: str = "Paper relationships") -> None:
    with open(path, "w") as f:
        f.write(render_html(graph, title, interactive=False))
