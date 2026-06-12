"""Turn the relationship graph into a compact, deterministic text digest the chat
LLM can read, plus persistence so the daily run can capture it once and any chat
(graph window or standalone) can pick it up.

The numbers here are computed in code, not by the model: counts, degrees, and
neighbour lists are exact, so the model only relays them. "Neighbours" means the
relationship-graph edges (what the graph draws), not embedding similarity.
"""
import os
from collections import Counter

STATS_PATH = os.path.expanduser("~/.paperfinder/graph_stats.md")
_MAX_ADJ = 150          # cap adjacency listing on large graphs; counts stay exact


def _top_folder(node) -> str:
    f = node.get("folder") or ""
    return f.split("/")[0] if f else "(root)"


def graph_digest(export: dict) -> str:
    nodes = export.get("nodes") or []
    edges = export.get("edges") or []
    id2title = {n["id"]: (n.get("title") or n["id"]) for n in nodes}
    id2top = {n["id"]: _top_folder(n) for n in nodes}

    adj = {n["id"]: {} for n in nodes}       # id -> {neighbour_id: (confidence, status)}
    authed = 0
    for e in edges:
        if e.get("status") == "authenticated":
            authed += 1
        conf, st = e.get("confidence"), e.get("status")
        for x, y in ((e.get("src"), e.get("dst")), (e.get("dst"), e.get("src"))):
            if x in adj and y in id2title:
                prev = adj[x].get(y)
                if prev is None or (conf or 0) > (prev[0] or 0):
                    adj[x][y] = (conf, st)
    deg = {i: len(adj[i]) for i in adj}

    n_nodes, n_edges = len(nodes), len(edges)
    cand = n_edges - authed
    ftally = Counter(id2top[n["id"]] for n in nodes)
    folder_str = ", ".join("%s (%d)" % (f, c)
                           for f, c in sorted(ftally.items(), key=lambda kv: (-kv[1], kv[0]))) or "none"
    ranked = sorted(((deg[n["id"]], id2title[n["id"]]) for n in nodes), key=lambda t: (-t[0], t[1]))
    most = ", ".join('"%s" (%d)' % (t, d) for d, t in ranked[:3] if d > 0) or "none yet"
    isolated = [id2title[n["id"]] for n in nodes if deg[n["id"]] == 0]
    iso_str = ", ".join('"%s"' % t for t in isolated) if isolated else "none"

    lines = [
        "GRAPH STRUCTURE (the relationship graph as currently built)",
        "Counts: %d papers (nodes), %d connections (edges) - %d authenticated, %d candidate."
        % (n_nodes, n_edges, authed, cand),
        "Folders: %s." % folder_str,
        "Most connected: %s." % most,
        "Papers with no connections: %s." % iso_str,
        "",
        "Each paper and what it connects to (strongest first; a=authenticated, c=candidate):",
    ]
    listed = sorted(nodes, key=lambda n: (-deg[n["id"]], id2title[n["id"]]))
    for n in listed[:_MAX_ADJ]:
        i = n["id"]
        nbrs = sorted(adj[i].items(), key=lambda kv: -((kv[1][0]) or 0))
        if nbrs:
            parts = []
            for nid, (conf, st) in nbrs:
                sc = (" %.2f" % conf) if isinstance(conf, (int, float)) else ""
                parts.append('"%s"%s (%s)' % (id2title[nid], sc, "a" if st == "authenticated" else "c"))
            lines.append('- "%s" [%s]: %s' % (id2title[i], id2top[i], ", ".join(parts)))
        else:
            lines.append('- "%s" [%s]: (none)' % (id2title[i], id2top[i]))
    if n_nodes > _MAX_ADJ:
        lines.append("(adjacency truncated to the %d most-connected papers; counts above are exact)" % _MAX_ADJ)
    return "\n".join(lines)


def write_graph_stats(export: dict, path: str = STATS_PATH) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(graph_digest(export) + "\n")
    return path


def load_graph_stats(path: str = STATS_PATH) -> str:
    try:
        return open(path).read()
    except OSError:
        return ""
