"""
Generate CODEGRAPH_REPORT.md at project root from graph.db.

Run from project root:
    python .codegraph/report_gen.py
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / ".codegraph" / "graph.db"
OUTPUT = ROOT / "CODEGRAPH_REPORT.md"


def main() -> None:
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    all_nodes = [dict(r) for r in con.execute("SELECT * FROM nodes").fetchall()]
    all_edges = [dict(r) for r in con.execute("SELECT * FROM edges").fetchall()]
    con.close()

    node_by_id: dict[str, dict] = {n["id"]: n for n in all_nodes}

    # ── Never-called detection ──────────────────────────────────────────────
    callee_names: set[str] = set()
    for e in all_edges:
        if e["kind"] == "calls":
            callee_names.add(e["dst"].split(".")[-1])

    callable_nodes = [n for n in all_nodes if n["kind"] in ("function", "method")]
    never_called = [n for n in callable_nodes if n["name"] not in callee_names]
    called = [n for n in callable_nodes if n["name"] in callee_names]

    # ── Per-file stats ──────────────────────────────────────────────────────
    file_children: dict[str, list[dict]] = defaultdict(list)
    for n in all_nodes:
        if n["kind"] != "file":
            file_children[n["file"]].append(n)

    file_nodes = sorted(
        [n for n in all_nodes if n["kind"] == "file"],
        key=lambda n: n["file"],
    )

    # ── Import graph ────────────────────────────────────────────────────────
    import_edges = [e for e in all_edges if e["kind"] == "imports"]
    importers: dict[str, list[str]] = defaultdict(list)
    imported_by: dict[str, list[str]] = defaultdict(list)
    for e in import_edges:
        src_file = e["src"].split("::")[0]
        dst_file = e["dst"].split("::")[0]
        if src_file != dst_file:
            importers[src_file].append(dst_file)
            imported_by[dst_file].append(src_file)

    # Most imported files (hottest modules)
    hottest = sorted(imported_by.items(), key=lambda x: len(x[1]), reverse=True)[:15]

    # ── Inheritance ─────────────────────────────────────────────────────────
    inherits_edges = [e for e in all_edges if e["kind"] == "inherits"]

    # ── Classes with most methods ───────────────────────────────────────────
    class_method_count: dict[str, int] = defaultdict(int)
    for n in all_nodes:
        if n["kind"] == "method":
            parent_class = ".".join(n["qualname"].split(".")[:-1])
            class_method_count[parent_class] += 1
    heaviest_classes = sorted(class_method_count.items(), key=lambda x: x[1], reverse=True)[:15]

    # ── Files with most never-called symbols ───────────────────────────────
    nc_by_file: dict[str, list[dict]] = defaultdict(list)
    for n in never_called:
        nc_by_file[n["file"]].append(n)
    nc_file_ranking = sorted(nc_by_file.items(), key=lambda x: len(x[1]), reverse=True)

    # ── Layer breakdown ─────────────────────────────────────────────────────
    layers = ["view", "controller", "model", "utils", "src", "scripts", "test_scripts"]
    layer_stats: dict[str, dict] = {}
    for layer in layers:
        lnodes = [n for n in all_nodes if n["file"].startswith(layer + "/") or n["file"] == layer]
        if lnodes:
            layer_stats[layer] = {
                "files": sum(1 for n in lnodes if n["kind"] == "file"),
                "classes": sum(1 for n in lnodes if n["kind"] == "class"),
                "functions": sum(1 for n in lnodes if n["kind"] == "function"),
                "methods": sum(1 for n in lnodes if n["kind"] == "method"),
                "never_called": sum(1 for n in lnodes if n in never_called),
            }

    # ── Render ──────────────────────────────────────────────────────────────
    lines: list[str] = []

    def h(level: int, text: str) -> None:
        lines.append(f"{'#' * level} {text}")
        lines.append("")

    def line(text: str = "") -> None:
        lines.append(text)

    def table_row(*cols: str) -> str:
        return "| " + " | ".join(cols) + " |"

    def table_sep(*widths: int) -> str:
        return "| " + " | ".join("-" * w for w in widths) + " |"

    h(1, "CODEGRAPH_REPORT — pdf_editor")
    line(f"> Generated {date.today().isoformat()} by `.codegraph/report_gen.py`  ")
    line(f"> Source: `.codegraph/graph.db` — re-run after structural changes.")
    line()

    # ── 1. Summary ──────────────────────────────────────────────────────────
    h(2, "1. Summary")
    line(table_row("Metric", "Count"))
    line(table_sep(30, 10))
    line(table_row("Python files indexed", str(len(file_nodes))))
    line(table_row("Classes", str(sum(1 for n in all_nodes if n["kind"] == "class"))))
    line(table_row("Functions", str(sum(1 for n in all_nodes if n["kind"] == "function"))))
    line(table_row("Methods", str(sum(1 for n in all_nodes if n["kind"] == "method"))))
    line(table_row("Total callable symbols", str(len(callable_nodes))))
    line(table_row("Called (name seen in a call site)", str(len(called))))
    line(table_row("**Never-called**", f"**{len(never_called)}**"))
    line(table_row("Never-called %", f"{100*len(never_called)/max(len(callable_nodes),1):.1f}%"))
    line(table_row("Total edges", str(len(all_edges))))
    line(table_row("  — defines", str(sum(1 for e in all_edges if e["kind"] == "defines"))))
    line(table_row("  — calls", str(sum(1 for e in all_edges if e["kind"] == "calls"))))
    line(table_row("  — imports", str(sum(1 for e in all_edges if e["kind"] == "imports"))))
    line(table_row("  — inherits", str(sum(1 for e in all_edges if e["kind"] == "inherits"))))
    line()

    # ── 2. Layer Breakdown ──────────────────────────────────────────────────
    h(2, "2. Layer Breakdown")
    line(table_row("Layer", "Files", "Classes", "Functions", "Methods"))
    line(table_sep(20, 7, 9, 11, 9))
    for layer, s in layer_stats.items():
        line(table_row(
            f"`{layer}/`",
            str(s["files"]),
            str(s["classes"]),
            str(s["functions"]),
            str(s["methods"]),
        ))
    line()

    # ── 3. Heaviest Classes ─────────────────────────────────────────────────
    h(2, "3. Heaviest Classes (by method count)")
    line(table_row("Class", "Methods"))
    line(table_sep(50, 9))
    for cls, cnt in heaviest_classes:
        line(table_row(f"`{cls}`", str(cnt)))
    line()

    # ── 4. Most Imported Modules ────────────────────────────────────────────
    h(2, "4. Most Imported Modules (internal)")
    line("> Modules that appear most often as import targets — changing them has the widest blast radius.")
    line()
    line(table_row("Module", "Imported by N files"))
    line(table_sep(55, 20))
    for f, importers_list in hottest:
        line(table_row(f"`{f}`", str(len(importers_list))))
    line()

    # ── 5. Inheritance Graph ────────────────────────────────────────────────
    h(2, "5. Inheritance Relationships")
    if inherits_edges:
        line(table_row("Subclass", "Base"))
        line(table_sep(55, 35))
        for e in sorted(inherits_edges, key=lambda x: x["src"])[:60]:
            src_name = node_by_id.get(e["src"], {}).get("qualname", e["src"])
            line(table_row(f"`{src_name}`", f"`{e['dst']}`"))
        if len(inherits_edges) > 60:
            line(f"*… {len(inherits_edges) - 60} more inheritance edges not shown.*")
    else:
        line("*No inheritance edges detected.*")
    line()

    # ── 6. Never-Called Symbols ─────────────────────────────────────────────
    h(2, "6. Never-Called Symbols")
    line("> These functions/methods have no call-site reference detected by static AST analysis.")
    line("> **Caveats:** Qt signal-connected slots, `__dunder__` methods, and entry points called")
    line("> via `getattr`/reflection may appear here as false positives.")
    line()

    h(3, "6.1 By File (ranked by count)")
    line(table_row("File", "Never-called count"))
    line(table_sep(55, 18))
    for f, syms in nc_file_ranking:
        line(table_row(f"`{f}`", str(len(syms))))
    line()

    h(3, "6.2 Full Never-Called Symbol List")
    line(table_row("Kind", "File", "Line", "Symbol"))
    line(table_sep(8, 50, 6, 50))
    for n in sorted(never_called, key=lambda x: (x["file"], x["line"] or 0)):
        line(table_row(
            n["kind"],
            f"`{n['file']}`",
            str(n["line"] or ""),
            f"`{n['qualname']}`",
        ))
    line()

    # ── 7. Module Map ───────────────────────────────────────────────────────
    h(2, "7. Module Map")
    line("> All files with their classes and top-level functions.")
    line()
    for fn in file_nodes:
        children = file_children.get(fn["file"], [])
        classes = [c for c in children if c["kind"] == "class"]
        funcs = [c for c in children if c["kind"] == "function"]
        methods = [c for c in children if c["kind"] == "method"]
        line(f"### `{fn['file']}`")
        if fn.get("docstring"):
            line(f"*{fn['docstring'][:120].replace(chr(10),' ')}*")
        if classes:
            line("**Classes:** " + ", ".join(f"`{c['name']}`" for c in classes))
        if funcs:
            line("**Functions:** " + ", ".join(
                f"`{c['name']}`{'⚠' if c['name'] not in callee_names else ''}"
                for c in funcs
            ))
        if methods:
            nc_count = sum(1 for m in methods if m["name"] not in callee_names)
            line(f"**Methods:** {len(methods)} total, {nc_count} never-called")
        line()

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written: {OUTPUT}")
    print(f"  {len(lines)} lines, {OUTPUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
