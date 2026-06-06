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
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500&family=Newsreader:wght@400;500&display=swap" rel="stylesheet">
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
</style></head>
<body>
  <header>
    <h1>__TITLE__</h1>
    <div class="sub">Solid links are human-verified. Dashed links are inferred candidates. Hover a link to read the connecting passages; click a node to open its source.</div>
  </header>
  <div class="legend">
    <span><span class="swatch s-auth"></span><b>Authenticated</b>: verified by a human</span>
    <span><span class="swatch s-cand"></span><b>Candidate</b>: inferred from shared passages</span>
  </div>
  <div class="controls">
    <label for="thr">Min score</label>
    <input id="thr" type="range">
    <span id="thrval" class="val"></span>
    <span id="cnt" class="cnt"></span>
    __DONE__
  </div>
  <div id="net"></div>
  <div class="hint">__HINT__</div>
  __REVIEWUI__
<script>
  const G = __DATA__;
  const INTERACTIVE = __INTERACTIVE__;
  const teal = "#0f6e56", amber = "#a06414", ink = "#27241d";
  const esc = s => (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  const trim = (s, n=240) => { s = (s||"").replace(/\\s+/g," ").trim(); return s.length>n ? s.slice(0,n)+"\\u2026" : s; };
  const shortLabel = t => { t = (t||"").trim(); return t.length>60 ? t.slice(0,60)+"\\u2026" : t; };
  const nodeUrl = n => n.source_url || (String(n.id).startsWith("gdrive:")
        ? "https://drive.google.com/file/d/" + String(n.id).slice(7) + "/view" : "");
  const topFolder = n => { const f = (n.folder || ""); return f ? f.split("/")[0] : ""; };
  const titleById = {}; G.nodes.forEach(n => titleById[n.id] = n.title);

  const nodes = new vis.DataSet(G.nodes.map(n => ({
    id: n.id,
    label: (topFolder(n) ? "[" + topFolder(n) + "] " : "") + shortLabel(n.title),
    title: esc(n.title)
      + (n.folder ? "<br><span style='color:#6f6a5f'>" + esc(n.folder) + "</span>" : "")
      + (nodeUrl(n) ? "<br><span style='color:#6f6a5f'>click to open source</span>" : ""),
    url: nodeUrl(n),
    shape: "dot", size: 13,
    widthConstraint: { maximum: 170 },
    color: { background: "#fffdf8", border: teal, highlight: { background: "#eaf5f0", border: teal } },
    font: { face: "Newsreader", size: 15, color: ink, multi: false }
  })));

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
    return {
      id: i, from: e.src, to: e.dst, _src: e.src, _dst: e.dst, _status: e.status,
      _score: (e.confidence == null ? null : e.confidence),
      color: { color: auth ? teal : amber, opacity: auth ? 0.95 : 0.5 },
      width: auth ? 3 : 1.4, dashes: auth ? false : [5,5], title: el
    };
  }));

  const scores = G.edges.filter(e => e.confidence != null).map(e => e.confidence);
  const lo = scores.length ? Math.floor(Math.min(...scores) * 100) / 100 : 0;
  const hi = scores.length ? Math.ceil(Math.max(...scores) * 100) / 100 : 1;
  const thr = document.getElementById("thr");
  const thrval = document.getElementById("thrval");
  const cnt = document.getElementById("cnt");
  thr.min = lo; thr.max = hi; thr.step = 0.01; thr.value = lo;
  let threshold = lo;

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
    interaction: { hover: true, tooltipDelay: 80 },
    nodes: { borderWidth: 1.5 }
  });

  let selectedEdge = null;
  network.on("click", params => {
    if (params.nodes.length) {
      const n = nodes.get(params.nodes[0]);
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
        allEdges.update({ id: selectedEdge, _score: null, _status: "authenticated",
          color: { color: teal, opacity: 0.95 }, width: 3, dashes: false });
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
    document.getElementById("done").onclick = async () => {
      await post("/shutdown", {});
      document.body.innerHTML = "<div style='padding:48px 40px;font-family:Newsreader,Georgia,serif;font-size:18px;color:#27241d'>Review server stopped. You can close this tab.</div>";
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


def render_html(graph: dict, title: str = "Paper relationships",
                interactive: bool = False) -> str:
    base_hint = "Drag nodes to rearrange. Drag the slider to hide weaker connections. Click a node to open the paper."
    review_hint = " Click an edge to authenticate or reject the connection."
    return (_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__DATA__", json.dumps(graph))
            .replace("__INTERACTIVE__", "true" if interactive else "false")
            .replace("__DONE__", '<button id="done" class="btn">Done reviewing</button>' if interactive else "")
            .replace("__REVIEWUI__", _REVIEW_UI if interactive else "")
            .replace("__HINT__", base_hint + (review_hint if interactive else "")))


def build_viz(graph: dict, path: str, title: str = "Paper relationships") -> None:
    with open(path, "w") as f:
        f.write(render_html(graph, title, interactive=False))
