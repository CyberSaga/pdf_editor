"""
Generate codegraph_viz.html — interactive workflow graph of the entire project.

Run from project root:
    python .codegraph/viz_gen.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / ".codegraph" / "graph.db"
OUTPUT = ROOT / "codegraph_viz.html"


def main() -> None:
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    all_nodes = [dict(r) for r in con.execute("SELECT * FROM nodes").fetchall()]
    all_edges = [dict(r) for r in con.execute("SELECT * FROM edges").fetchall()]
    con.close()

    node_id_set = {n["id"] for n in all_nodes}

    # Identify never-called functions/methods.
    # calls edges store dst as bare ast.unparse strings like "self.save_as",
    # "logger.debug", "PDFModel.open_pdf" — not full node IDs. So we match by
    # extracting the final attribute component and comparing to function names.
    callee_names: set[str] = set()
    for e in all_edges:
        if e["kind"] == "calls":
            callee_names.add(e["dst"].split(".")[-1])

    never_called_ids: set[str] = set()
    for n in all_nodes:
        if n["kind"] in ("function", "method") and n["name"] not in callee_names:
            never_called_ids.add(n["id"])

    # Build cytoscape elements
    cy_elements: list[dict] = []

    # Compound parent for never-called cluster
    cy_elements.append({
        "data": {
            "id": "__never_called__",
            "label": f"Never Called ({len(never_called_ids)} symbols)",
            "kind": "cluster",
        },
        "classes": "cluster-never-called",
    })

    # Node elements
    for n in all_nodes:
        is_nc = n["id"] in never_called_ids
        tip = f"{n['kind']}: {n['qualname']}\n{n['file']}:{n['line']}"
        if n["signature"]:
            tip += f"\n{n['signature']}"
        elem: dict = {
            "data": {
                "id": n["id"],
                "label": n["name"],
                "kind": n["kind"],
                "file": n["file"],
                "line": n["line"] or 0,
                "signature": n["signature"] or "",
                "tooltip": tip,
                "never_called": is_nc,
            },
        }
        if is_nc:
            elem["data"]["parent"] = "__never_called__"
            elem["classes"] = "never-called"
        else:
            elem["classes"] = f"kind-{n['kind']}"
        cy_elements.append(elem)

    # Edge elements — only include edges where both endpoints are known nodes
    edge_counter = 0
    for e in all_edges:
        if e["src"] not in node_id_set or e["dst"] not in node_id_set:
            continue
        # Skip defines edges into never-called (they clutter the cluster)
        if e["kind"] == "defines" and e["dst"] in never_called_ids:
            continue
        cy_elements.append({
            "data": {
                "id": f"e{edge_counter}",
                "source": e["src"],
                "target": e["dst"],
                "kind": e["kind"],
            },
            "classes": f"edge-{e['kind']}",
        })
        edge_counter += 1

    elements_json = json.dumps(cy_elements, ensure_ascii=False)

    stats = {
        "files": sum(1 for n in all_nodes if n["kind"] == "file"),
        "classes": sum(1 for n in all_nodes if n["kind"] == "class"),
        "functions": sum(1 for n in all_nodes if n["kind"] == "function"),
        "methods": sum(1 for n in all_nodes if n["kind"] == "method"),
        "never_called": len(never_called_ids),
        "edges": edge_counter,
    }

    html = _render_html(elements_json, stats)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Written: {OUTPUT}")
    print(f"  nodes  : {len(all_nodes)} ({stats['files']} files, {stats['classes']} classes, "
          f"{stats['functions']} functions, {stats['methods']} methods)")
    print(f"  edges  : {edge_counter} (filtered to known endpoints)")
    print(f"  never-called: {stats['never_called']} functions/methods")


def _render_html(elements_json: str, stats: dict) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>pdf_editor — Code Workflow Graph</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0f1117; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }}

#toolbar {{ padding: 10px 16px; background: #1a1d27; border-bottom: 1px solid #2d3144;
           display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
#toolbar h1 {{ font-size: 15px; font-weight: 600; color: #fff; margin-right: 8px; }}

.btn {{ padding: 5px 12px; border-radius: 5px; border: 1px solid #3d4166;
       background: #252a3d; color: #ccc; cursor: pointer; font-size: 12px; }}
.btn:hover {{ background: #3a4060; color: #fff; }}
.btn.active {{ background: #4f6ef7; border-color: #4f6ef7; color: #fff; }}

#legend {{ display: flex; gap: 10px; align-items: center; margin-left: auto; flex-wrap: wrap; }}
.leg {{ display: flex; align-items: center; gap: 5px; font-size: 11px; }}
.dot {{ width: 10px; height: 10px; border-radius: 50%; }}

#stats {{ font-size: 11px; color: #888; white-space: nowrap; }}

#cy {{ flex: 1; }}

#info-panel {{ position: absolute; bottom: 16px; right: 16px; width: 300px;
              background: #1a1d27cc; backdrop-filter: blur(8px);
              border: 1px solid #2d3144; border-radius: 8px; padding: 12px;
              font-size: 12px; display: none; z-index: 10; }}
#info-panel h3 {{ font-size: 13px; margin-bottom: 6px; color: #fff; }}
#info-panel pre {{ white-space: pre-wrap; word-break: break-all; color: #aaa;
                  font-family: 'Fira Code', monospace; font-size: 11px;
                  max-height: 200px; overflow-y: auto; }}
#info-close {{ float: right; cursor: pointer; color: #888; font-size: 14px; }}

#search-box {{ padding: 5px 10px; border-radius: 5px; border: 1px solid #3d4166;
              background: #1a1d27; color: #ccc; font-size: 12px; width: 180px; }}
#search-box::placeholder {{ color: #555; }}
</style>
</head>
<body>

<div id="toolbar">
  <h1>pdf_editor — Workflow Graph</h1>
  <input id="search-box" type="text" placeholder="Search symbol…">
  <button class="btn" onclick="fitAll()">Fit All</button>
  <button class="btn" id="btn-physics" onclick="togglePhysics()">Physics ON</button>
  <button class="btn" onclick="filterKind('file')">Files only</button>
  <button class="btn" onclick="filterKind('class')">Classes only</button>
  <button class="btn" onclick="showAll()">Show All</button>
  <button class="btn" onclick="focusNeverCalled()">Never Called</button>
  <span id="stats">
    {stats['files']} files &nbsp;|&nbsp;
    {stats['classes']} classes &nbsp;|&nbsp;
    {stats['functions']} functions &nbsp;|&nbsp;
    {stats['methods']} methods &nbsp;|&nbsp;
    <span style="color:#ff6b6b">{stats['never_called']} never-called</span> &nbsp;|&nbsp;
    {stats['edges']} edges
  </span>
  <div id="legend">
    <div class="leg"><div class="dot" style="background:#4a90d9"></div> file</div>
    <div class="leg"><div class="dot" style="background:#27ae60"></div> class</div>
    <div class="leg"><div class="dot" style="background:#e67e22"></div> function</div>
    <div class="leg"><div class="dot" style="background:#9b59b6"></div> method</div>
    <div class="leg"><div class="dot" style="background:#e74c3c; outline: 2px solid #ff0"></div> never-called</div>
  </div>
</div>

<div id="cy"></div>

<div id="info-panel">
  <span id="info-close" onclick="closeInfo()">✕</span>
  <h3 id="info-title">Node</h3>
  <pre id="info-body"></pre>
</div>

<script>
const elements = {elements_json};

const cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: elements,
  style: [
    {{
      selector: 'node',
      style: {{
        'label': 'data(label)',
        'font-size': '9px',
        'color': '#ddd',
        'text-valign': 'center',
        'text-halign': 'center',
        'width': 28,
        'height': 28,
        'background-color': '#555',
        'border-width': 1,
        'border-color': '#444',
        'text-wrap': 'ellipsis',
        'text-max-width': '60px',
        'min-zoomed-font-size': 6,
      }}
    }},
    {{
      selector: '.kind-file',
      style: {{
        'background-color': '#1a5fa8',
        'border-color': '#4a90d9',
        'border-width': 2,
        'width': 44,
        'height': 44,
        'font-size': '10px',
        'font-weight': 'bold',
        'shape': 'round-rectangle',
      }}
    }},
    {{
      selector: '.kind-class',
      style: {{
        'background-color': '#1a6b38',
        'border-color': '#27ae60',
        'border-width': 2,
        'width': 34,
        'height': 34,
        'shape': 'hexagon',
      }}
    }},
    {{
      selector: '.kind-function',
      style: {{
        'background-color': '#7d4200',
        'border-color': '#e67e22',
        'border-width': 1.5,
        'width': 22,
        'height': 22,
        'shape': 'ellipse',
      }}
    }},
    {{
      selector: '.kind-method',
      style: {{
        'background-color': '#4a1a6e',
        'border-color': '#9b59b6',
        'border-width': 1.5,
        'width': 20,
        'height': 20,
        'shape': 'ellipse',
      }}
    }},
    {{
      selector: '.never-called',
      style: {{
        'background-color': '#7a0000',
        'border-color': '#ff4444',
        'border-width': 2,
        'width': 20,
        'height': 20,
        'shape': 'diamond',
      }}
    }},
    {{
      selector: '.cluster-never-called',
      style: {{
        'background-color': '#1f0505',
        'border-color': '#ff4444',
        'border-width': 2,
        'border-style': 'dashed',
        'label': 'data(label)',
        'text-valign': 'top',
        'text-halign': 'center',
        'font-size': '13px',
        'font-weight': 'bold',
        'color': '#ff6b6b',
        'padding': '20px',
        'shape': 'round-rectangle',
      }}
    }},
    {{
      selector: 'edge',
      style: {{
        'width': 0.8,
        'line-color': '#333',
        'target-arrow-color': '#333',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.6,
        'curve-style': 'bezier',
        'opacity': 0.5,
      }}
    }},
    {{
      selector: '.edge-defines',
      style: {{
        'line-color': '#2d5a8e',
        'target-arrow-color': '#2d5a8e',
        'width': 1,
        'opacity': 0.6,
      }}
    }},
    {{
      selector: '.edge-calls',
      style: {{
        'line-color': '#5a3a00',
        'target-arrow-color': '#e67e22',
        'width': 0.7,
        'opacity': 0.35,
        'line-style': 'solid',
      }}
    }},
    {{
      selector: '.edge-imports',
      style: {{
        'line-color': '#1a5fa8',
        'target-arrow-color': '#4a90d9',
        'width': 1.2,
        'opacity': 0.7,
        'line-style': 'dashed',
      }}
    }},
    {{
      selector: '.edge-inherits',
      style: {{
        'line-color': '#27ae60',
        'target-arrow-color': '#27ae60',
        'width': 1.5,
        'opacity': 0.8,
        'target-arrow-shape': 'triangle-backcurve',
      }}
    }},
    {{
      selector: ':selected',
      style: {{
        'border-color': '#fff',
        'border-width': 3,
        'overlay-opacity': 0.1,
      }}
    }},
    {{
      selector: '.highlighted',
      style: {{
        'border-color': '#ffff00',
        'border-width': 3,
        'opacity': 1,
      }}
    }},
    {{
      selector: '.faded',
      style: {{
        'opacity': 0.08,
      }}
    }},
  ],
  layout: {{
    name: 'cose',
    animate: 'end',
    animationDuration: 800,
    randomize: true,
    nodeRepulsion: 6000,
    idealEdgeLength: 70,
    edgeElasticity: 0.45,
    nestingFactor: 1.2,
    gravity: 0.3,
    numIter: 1200,
    tile: true,
    tilingPaddingVertical: 8,
    tilingPaddingHorizontal: 8,
    fit: true,
    padding: 30,
  }},
  wheelSensitivity: 0.3,
}});

let physicsOn = true;

// Info panel
cy.on('tap', 'node', function(evt) {{
  const n = evt.target;
  const d = n.data();
  const panel = document.getElementById('info-panel');
  document.getElementById('info-title').textContent = d.kind + ': ' + d.label;
  const lines = [];
  if (d.file) lines.push('File: ' + d.file + (d.line ? ':' + d.line : ''));
  if (d.signature) lines.push('Sig:  ' + d.signature);
  if (d.never_called) lines.push('⚠ Never called (no incoming call edges)');
  const callers = n.incomers('edge.edge-calls').length;
  const callees = n.outgoers('edge.edge-calls').length;
  lines.push('Callers: ' + callers + '  Callees: ' + callees);
  document.getElementById('info-body').textContent = lines.join('\\n');
  panel.style.display = 'block';

  // highlight neighborhood
  cy.elements().addClass('faded');
  const hood = n.neighborhood().union(n);
  hood.removeClass('faded');
  n.addClass('highlighted');
}});

cy.on('tap', function(evt) {{
  if (evt.target === cy) {{
    cy.elements().removeClass('faded highlighted');
  }}
}});

function closeInfo() {{
  document.getElementById('info-panel').style.display = 'none';
  cy.elements().removeClass('faded highlighted');
}}

function fitAll() {{
  cy.fit(cy.elements(), 30);
}}

function togglePhysics() {{
  physicsOn = !physicsOn;
  const btn = document.getElementById('btn-physics');
  if (physicsOn) {{
    cy.layout({{ name: 'cose', animate: true, randomize: false, numIter: 500 }}).run();
    btn.textContent = 'Physics ON';
    btn.classList.add('active');
  }} else {{
    btn.textContent = 'Physics OFF';
    btn.classList.remove('active');
  }}
}}

function filterKind(kind) {{
  cy.elements().show();
  cy.elements('node[kind != "' + kind + '"][kind != "cluster"]').hide();
  cy.elements('edge').hide();
  cy.fit(cy.elements(':visible'), 30);
}}

function showAll() {{
  cy.elements().show();
  cy.fit(cy.elements(), 30);
}}

function focusNeverCalled() {{
  cy.elements().show();
  cy.elements().addClass('faded');
  const nc = cy.$('.never-called, .cluster-never-called');
  nc.removeClass('faded');
  nc.addClass('highlighted');
  cy.fit(nc, 60);
}}

// Search
document.getElementById('search-box').addEventListener('input', function() {{
  const q = this.value.trim().toLowerCase();
  if (!q) {{
    cy.elements().removeClass('faded highlighted');
    return;
  }}
  cy.elements().addClass('faded');
  const matches = cy.nodes().filter(n => {{
    const d = n.data();
    return (d.label || '').toLowerCase().includes(q)
        || (d.file || '').toLowerCase().includes(q)
        || (d.signature || '').toLowerCase().includes(q);
  }});
  matches.removeClass('faded');
  matches.addClass('highlighted');
  if (matches.length > 0) cy.fit(matches, 60);
}});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
