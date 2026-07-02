"""
Build .codegraph/graph.db and CODEINDEX.md from the project source tree.

Usage (from project root):
    python .codegraph/indexer.py
"""
from __future__ import annotations

import ast
import fnmatch
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DB_PATH = ROOT / ".codegraph" / "graph.db"
IGNORE_FILE = ROOT / ".codegraphignore"
CODEINDEX_PATH = ROOT / ".codegraph" / "CODEINDEX.md"


# ---------------------------------------------------------------------------
# Exclude-pattern loader
# ---------------------------------------------------------------------------

def load_ignore_patterns() -> list[str]:
    if not IGNORE_FILE.exists():
        return []
    lines = IGNORE_FILE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def is_ignored(rel: str, patterns: list[str]) -> bool:
    rel_norm = rel.replace("\\", "/")
    for pat in patterns:
        pat_norm = pat.rstrip("/")
        if fnmatch.fnmatch(rel_norm, pat_norm):
            return True
        if fnmatch.fnmatch(rel_norm, pat_norm + "/*"):
            return True
        # match any path component
        parts = rel_norm.split("/")
        for part in parts:
            if fnmatch.fnmatch(part, pat_norm):
                return True
    return False


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    parts: list[str] = []
    defaults_offset = len(args.args) - len(args.defaults)
    for i, arg in enumerate(args.args):
        name = arg.arg
        di = i - defaults_offset
        if di >= 0:
            try:
                default_str = ast.unparse(args.defaults[di])
            except Exception:
                default_str = "..."
            parts.append(f"{name}={default_str}")
        else:
            parts.append(name)
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    ret = ""
    if node.returns:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(parts)}){ret}"


def _bases(node: ast.ClassDef) -> str:
    result: list[str] = []
    for base in node.bases:
        try:
            result.append(ast.unparse(base))
        except Exception:
            pass
    return ", ".join(result)


# ---------------------------------------------------------------------------
# File walker
# ---------------------------------------------------------------------------

def iter_py_files(patterns: list[str]):
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT)
        # prune ignored dirs in-place
        dirnames[:] = [
            d for d in dirnames
            if not is_ignored(os.path.join(rel_dir, d).replace("\\", "/") + "/", patterns)
            and not is_ignored(d, patterns)
        ]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fname), ROOT).replace("\\", "/")
            if not is_ignored(rel, patterns):
                yield Path(dirpath) / fname, rel


# ---------------------------------------------------------------------------
# AST extractor
# ---------------------------------------------------------------------------

def extract(filepath: Path, rel: str) -> tuple[list[dict], list[dict]]:
    """Return (nodes, edges) for one file."""
    try:
        source = filepath.read_text(encoding="utf-8-sig", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return [], []

    nodes: list[dict] = []
    edges: list[dict] = []

    file_id = f"{rel}::__file__"
    nodes.append({
        "id": file_id,
        "kind": "file",
        "name": rel.split("/")[-1],
        "qualname": rel,
        "file": rel,
        "line": 0,
        "docstring": ast.get_docstring(tree) or "",
        "signature": "",
        "bases": "",
    })

    # internal import resolution cache
    def _resolve_module(module_name: str | None) -> str | None:
        if not module_name:
            return None
        parts = module_name.split(".")
        candidates = [
            "/".join(parts) + ".py",
            "/".join(parts) + "/__init__.py",
        ]
        for c in candidates:
            if (ROOT / c).exists():
                return c
        return None

    # walk top-level and one level deep (classes)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                target = _resolve_module(node.module)
            else:
                target = None
                for alias in node.names:
                    target = _resolve_module(alias.name)
                    if target:
                        break
            if target:
                edges.append({"src": file_id, "dst": f"{target}::__file__", "kind": "imports"})

    def _walk_body(body, parent_qualname: str, parent_id: str, is_class: bool = False):
        for stmt in body:
            if isinstance(stmt, ast.ClassDef):
                qualname = f"{parent_qualname}.{stmt.name}" if parent_qualname else stmt.name
                nid = f"{rel}::{qualname}"
                doc = ast.get_docstring(stmt) or ""
                b = _bases(stmt)
                nodes.append({
                    "id": nid,
                    "kind": "class",
                    "name": stmt.name,
                    "qualname": qualname,
                    "file": rel,
                    "line": stmt.lineno,
                    "docstring": doc,
                    "signature": f"class {stmt.name}({b})" if b else f"class {stmt.name}",
                    "bases": b,
                })
                edges.append({"src": parent_id, "dst": nid, "kind": "defines"})
                for base_str in (b.split(", ") if b else []):
                    base_str = base_str.strip()
                    if base_str:
                        edges.append({"src": nid, "dst": base_str, "kind": "inherits"})
                _walk_body(stmt.body, qualname, nid, is_class=True)

            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{parent_qualname}.{stmt.name}" if parent_qualname else stmt.name
                nid = f"{rel}::{qualname}"
                kind = "method" if is_class else "function"
                doc = ast.get_docstring(stmt) or ""
                sig = _signature(stmt)
                nodes.append({
                    "id": nid,
                    "kind": kind,
                    "name": stmt.name,
                    "qualname": qualname,
                    "file": rel,
                    "line": stmt.lineno,
                    "docstring": doc,
                    "signature": sig,
                    "bases": "",
                })
                edges.append({"src": parent_id, "dst": nid, "kind": "defines"})
                # collect calls inside function body
                for child in ast.walk(stmt):
                    if isinstance(child, ast.Call):
                        try:
                            callee = ast.unparse(child.func)
                        except Exception:
                            callee = ""
                        if callee:
                            edges.append({"src": nid, "dst": callee, "kind": "calls"})

    _walk_body(tree.body, "", file_id)
    return nodes, edges


# ---------------------------------------------------------------------------
# Database builder
# ---------------------------------------------------------------------------

def build_db(all_nodes: list[dict], all_edges: list[dict]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()

    cur.executescript("""
        CREATE TABLE nodes (
            id        TEXT PRIMARY KEY,
            kind      TEXT NOT NULL,
            name      TEXT NOT NULL,
            qualname  TEXT NOT NULL,
            file      TEXT NOT NULL,
            line      INTEGER,
            docstring TEXT,
            signature TEXT,
            bases     TEXT
        );
        CREATE VIRTUAL TABLE nodes_fts USING fts5(
            id UNINDEXED, name, qualname, docstring, signature,
            content=nodes, content_rowid=rowid
        );
        CREATE TABLE edges (
            src   TEXT NOT NULL,
            dst   TEXT NOT NULL,
            kind  TEXT NOT NULL,
            PRIMARY KEY (src, dst, kind)
        );
        CREATE INDEX edges_dst ON edges(dst);
        CREATE INDEX edges_src ON edges(src);
    """)

    seen_ids: set[str] = set()
    unique_nodes = []
    for n in all_nodes:
        if n["id"] not in seen_ids:
            seen_ids.add(n["id"])
            unique_nodes.append(n)

    cur.executemany(
        "INSERT INTO nodes VALUES (:id,:kind,:name,:qualname,:file,:line,:docstring,:signature,:bases)",
        unique_nodes,
    )
    # rebuild FTS
    cur.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")

    seen_edges: set[tuple] = set()
    unique_edges = []
    for e in all_edges:
        key = (e["src"], e["dst"], e["kind"])
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append(e)

    cur.executemany("INSERT OR IGNORE INTO edges VALUES (:src,:dst,:kind)", unique_edges)

    con.commit()
    con.close()
    print(f"  nodes: {len(unique_nodes)}  edges: {len(unique_edges)}")


# ---------------------------------------------------------------------------
# CODEINDEX.md generator
# ---------------------------------------------------------------------------

def generate_codeindex(all_nodes: list[dict], all_edges: list[dict]) -> None:
    # group by file
    file_nodes: dict[str, dict] = {}
    children: dict[str, list[dict]] = {}

    for n in all_nodes:
        if n["kind"] == "file":
            file_nodes[n["file"]] = n
            children[n["file"]] = []

    for n in all_nodes:
        if n["kind"] != "file":
            children.setdefault(n["file"], []).append(n)

    # import graph: file -> list of imported files
    imports: dict[str, list[str]] = {f: [] for f in file_nodes}
    for e in all_edges:
        if e["kind"] == "imports":
            src_file = e["src"].split("::")[0]
            dst_file = e["dst"].split("::")[0]
            if src_file in imports and dst_file in file_nodes:
                imports[src_file].append(dst_file)

    lines: list[str] = []
    lines.append("# CODEINDEX.md — Auto-generated symbol inventory")
    lines.append("")
    lines.append("> Generated by `.codegraph/indexer.py`. Re-run after structural changes.")
    lines.append("> Read this file OR run `python .codegraph/query.py search <symbol>` for targeted lookup.")
    lines.append("")

    # Layer map heuristic
    layers = {"view": [], "controller": [], "model": [], "utils": [], "src": [], "other": []}
    for f in sorted(file_nodes):
        first = f.split("/")[0]
        if first in layers:
            layers[first].append(f)
        else:
            layers["other"].append(f)

    lines.append("## Layer Map")
    lines.append("")
    for layer, files in layers.items():
        if files:
            lines.append(f"**{layer}/**")
            for f in files:
                lines.append(f"  - `{f}`")
    lines.append("")

    # Module map
    lines.append("## Module Map")
    lines.append("")
    for f in sorted(file_nodes):
        syms = children.get(f, [])
        classes = [n for n in syms if n["kind"] == "class"]
        funcs = [n for n in syms if n["kind"] == "function"]
        methods = [n for n in syms if n["kind"] == "method"]
        lines.append(f"### `{f}`")
        if classes:
            lines.append("**Classes:** " + ", ".join(
                f"`{n['name']}` (L{n['line']})" for n in classes
            ))
        if funcs:
            lines.append("**Functions:** " + ", ".join(
                f"`{n['name']}` (L{n['line']})" for n in funcs
            ))
        if methods:
            lines.append(f"**Methods ({len(methods)}):** " + ", ".join(
                f"`{n['name']}`" for n in methods[:20]
            ) + (" …" if len(methods) > 20 else ""))
        lines.append("")

    # Import graph
    lines.append("## Internal Import Graph")
    lines.append("")
    for f in sorted(imports):
        targets = sorted(set(imports[f]))
        if targets:
            lines.append(f"- `{f}` → " + ", ".join(f"`{t}`" for t in targets))
    lines.append("")

    CODEINDEX_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"  CODEINDEX.md written ({len(lines)} lines)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("codegraph indexer — scanning project root:", ROOT)
    patterns = load_ignore_patterns()
    print(f"  ignore patterns: {patterns}")

    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    file_count = 0

    for filepath, rel in iter_py_files(patterns):
        nodes, edges = extract(filepath, rel)
        all_nodes.extend(nodes)
        all_edges.extend(edges)
        file_count += 1

    print(f"  parsed {file_count} Python files")
    print("building graph.db …")
    build_db(all_nodes, all_edges)
    print("generating CODEINDEX.md …")
    generate_codeindex(all_nodes, all_edges)
    print("done.")


if __name__ == "__main__":
    main()
