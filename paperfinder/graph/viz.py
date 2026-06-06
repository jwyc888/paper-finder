"""Self-contained interactive graph visualisation. Authenticated edges are solid;
inferred candidates are dashed and faint, so provenance is legible at a glance.
Edge tooltips show the two passages that linked the papers (the evidence)."""

import json


def build_viz(graph: dict, path: str, title: str = "Paper relationships") -> None:
    data = json.dumps(graph)
    html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500&family=Newsreader:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  :root{--paper:#faf8f3;--ink:#27241d;--muted:#6f6a5f;--teal:#0f6e56;--amber:#a06414;--line:#e2ddd0}
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:"Newsreader",Georgia,serif}
  header{padding:28px 32px 18px;border-bottom:1px solid var(--line)}
  h1{font-family:"Fraunces",Georgia,serif;font-weight:500;font-size:30px;margin:0;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:15px;margin-top:4px}
  .legend{display:flex;gap:22px;align-items:center;padding:12px 32px;font-size:14px;color:var(--muted);border-bottom:1px solid var(--line);flex-wrap:wrap}
  .legend b{color:var(--ink);font-weight:500}
  .swatch{display:inline-block;width:30px;height:0;vertical-align:middle;margin-right:7px}
  .s-auth{border-top:3px solid var(--teal)}
  .s-cand{border-top:2px dashed var(--amber)}
  #net{height:72vh;width:100%}
  .hint{padding:10px 32px;color:var(--muted);font-size:13px}
  .vis-tooltip{font-family:"Newsreader",Georgia,serif !important;max-width:380px;white-space:normal !important;
    background:#fffdf8 !important;border:1px solid var(--line) !important;color:var(--ink) !important;
    border-radius:6px !important;padding:10px 12px !important;box-shadow:0 4px 14px rgba(0,0,0,.10) !important}
</style></head>
<body>
  <header>
    <h1>__TITLE__</h1>
    <div class="sub">Solid links are human-verified. Dashed links are inferred candidates awaiting your verdict. Hover any link to read the passages that connect the two papers.</div>
  </header>
  <div class="legend">
    <span><span class="swatch s-auth"></span><b>Authenticated</b>: verified by a human</span>
    <span><span class="swatch s-cand"></span><b>Candidate</b>: inferred from shared passages</span>
  </div>
  <div id="net"></div>
  <div class="hint">Drag nodes to rearrange. Hover an edge to see the connecting passages; hover a node for its title.</div>
<script>
  const G = __DATA__;
  const teal = "#0f6e56", amber = "#a06414", ink = "#27241d";
  const esc = s => (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  const trim = (s, n=240) => { s = (s||"").replace(/\\s+/g," ").trim(); return s.length>n ? s.slice(0,n)+"\\u2026" : s; };

  const nodes = new vis.DataSet(G.nodes.map(n => ({
    id: n.id,
    label: n.title,
    title: esc(n.title),
    shape: "dot", size: 13,
    color: { background: "#fffdf8", border: teal, highlight: { background: "#eaf5f0", border: teal } },
    font: { face: "Newsreader", size: 15, color: ink, multi: false }
  })));

  const edges = new vis.DataSet(G.edges.map(e => {
    const auth = e.status === "authenticated";
    const prov = auth ? ("Verified by " + esc(e.verified_by || "human"))
                      : ("Inferred candidate, score " + (e.confidence ?? "").toString().slice(0,5));
    const el = document.createElement("div");
    let html = "<b>" + prov + "</b>";
    const why = (e.descriptors && e.descriptors.length) ? esc(e.descriptors.join(", ")) : "";
    if (why) html += "<br>via: " + why;
    const ev = e.evidence || {};
    if (ev.src_passage) html += "<br><br>" + esc(trim(ev.src_passage));
    if (ev.dst_passage) html += "<br><br>" + esc(trim(ev.dst_passage));
    el.innerHTML = html;
    return {
      from: e.src, to: e.dst,
      color: { color: auth ? teal : amber, opacity: auth ? 0.95 : 0.5 },
      width: auth ? 3 : 1.4,
      dashes: auth ? false : [5,5],
      title: el
    };
  }));

  new vis.Network(document.getElementById("net"), { nodes, edges }, {
    physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -45, springLength: 130 }, stabilization: { iterations: 220 } },
    interaction: { hover: true, tooltipDelay: 80 },
    nodes: { borderWidth: 1.5 }
  });
</script>
</body></html>"""
    html = html.replace("__TITLE__", title).replace("__DATA__", data)
    with open(path, "w") as f:
        f.write(html)
