"""
Query CLI for .codegraph/graph.db.

Usage:
    python .codegraph/query.py search <query>           # FTS search
    python .codegraph/query.py context <symbol>         # node + neighbors
    python .codegraph/query.py callers <symbol>         # reverse edge traversal
    python .codegraph/query.py callees <symbol>         # forward edge traversal
    python .codegraph/query.py explore <symbol> [depth] # BFS to depth N (default 2)

Output is compact JSON printed to stdout.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DB_PATH = ROOT / ".codegraph" / "graph.db"


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        print(json.dumps({"error": "graph.db not found — run: python .codegraph/indexer.py"}))
        sys.exit(1)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_search(query: str) -> None:
    con = _connect()
    cur = con.cursor()
    # wrap in quotes so FTS5 treats it as a phrase and handles special chars
    fts_query = f'"{query.replace(chr(34), "")}"'
    try:
        rows = cur.execute(
            """
            SELECT n.id, n.kind, n.name, n.qualname, n.file, n.line, n.signature, n.docstring
            FROM nodes_fts
            JOIN nodes n ON nodes_fts.rowid = n.rowid
            WHERE nodes_fts MATCH ?
            ORDER BY rank
            LIMIT 30
            """,
            (fts_query,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()
    print(json.dumps([_row_to_dict(r) for r in rows], indent=2))


def _lookup_node(cur: sqlite3.Cursor, symbol: str) -> dict | None:
    # exact id match first
    row = cur.execute("SELECT * FROM nodes WHERE id = ?", (symbol,)).fetchone()
    if row:
        return _row_to_dict(row)
    # name match
    rows = cur.execute(
        "SELECT * FROM nodes WHERE name = ? OR qualname = ? ORDER BY kind LIMIT 5",
        (symbol, symbol),
    ).fetchall()
    if rows:
        return _row_to_dict(rows[0])
    # FTS fallback — wrap in double-quotes to escape special chars like /
    fts_query = f'"{symbol.replace(chr(34), "")}"'
    try:
        rows = cur.execute(
            """
            SELECT n.*
            FROM nodes_fts
            JOIN nodes n ON nodes_fts.rowid = n.rowid
            WHERE nodes_fts MATCH ?
            LIMIT 1
            """,
            (fts_query,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    return _row_to_dict(rows[0]) if rows else None


def cmd_context(symbol: str) -> None:
    con = _connect()
    cur = con.cursor()
    node = _lookup_node(cur, symbol)
    if not node:
        print(json.dumps({"error": f"symbol not found: {symbol}"}))
        con.close()
        return

    nid = node["id"]
    out_edges = cur.execute(
        "SELECT dst, kind FROM edges WHERE src = ?", (nid,)
    ).fetchall()
    in_edges = cur.execute(
        "SELECT src, kind FROM edges WHERE dst = ?", (nid,)
    ).fetchall()

    print(json.dumps({
        "node": node,
        "outgoing": [dict(r) for r in out_edges],
        "incoming": [dict(r) for r in in_edges],
    }, indent=2))
    con.close()


def cmd_callers(symbol: str) -> None:
    con = _connect()
    cur = con.cursor()
    node = _lookup_node(cur, symbol)
    if not node:
        print(json.dumps({"error": f"symbol not found: {symbol}"}))
        con.close()
        return

    nid = node["id"]
    rows = cur.execute(
        """
        SELECT e.src, e.kind, n.file, n.line, n.signature
        FROM edges e
        LEFT JOIN nodes n ON n.id = e.src
        WHERE e.dst = ?
        """,
        (nid,),
    ).fetchall()
    print(json.dumps({"symbol": nid, "callers": [dict(r) for r in rows]}, indent=2))
    con.close()


def cmd_callees(symbol: str) -> None:
    con = _connect()
    cur = con.cursor()
    node = _lookup_node(cur, symbol)
    if not node:
        print(json.dumps({"error": f"symbol not found: {symbol}"}))
        con.close()
        return

    nid = node["id"]
    rows = cur.execute(
        """
        SELECT e.dst, e.kind, n.file, n.line, n.signature
        FROM edges e
        LEFT JOIN nodes n ON n.id = e.dst
        WHERE e.src = ?
        """,
        (nid,),
    ).fetchall()
    print(json.dumps({"symbol": nid, "callees": [dict(r) for r in rows]}, indent=2))
    con.close()


def cmd_explore(symbol: str, depth: int = 2) -> None:
    con = _connect()
    cur = con.cursor()
    node = _lookup_node(cur, symbol)
    if not node:
        print(json.dumps({"error": f"symbol not found: {symbol}"}))
        con.close()
        return

    start_id = node["id"]
    visited: dict[str, dict] = {}
    frontier = [start_id]

    for _ in range(depth):
        next_frontier: list[str] = []
        for nid in frontier:
            if nid in visited:
                continue
            n_row = cur.execute("SELECT * FROM nodes WHERE id = ?", (nid,)).fetchone()
            edges = cur.execute(
                "SELECT dst, kind FROM edges WHERE src = ?", (nid,)
            ).fetchall()
            visited[nid] = {
                "node": _row_to_dict(n_row) if n_row else {"id": nid},
                "edges": [dict(e) for e in edges],
            }
            for e in edges:
                if e["dst"] not in visited:
                    next_frontier.append(e["dst"])
        frontier = next_frontier

    print(json.dumps({"root": start_id, "depth": depth, "graph": visited}, indent=2))
    con.close()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: python .codegraph/query.py <search|context|callers|callees|explore> <symbol> [depth]")
        sys.exit(1)

    cmd = args[0]
    if cmd == "search":
        if len(args) < 2:
            print(json.dumps({"error": "search requires a query argument"}))
            sys.exit(1)
        cmd_search(" ".join(args[1:]))
    elif cmd == "context":
        if len(args) < 2:
            print(json.dumps({"error": "context requires a symbol argument"}))
            sys.exit(1)
        cmd_context(args[1])
    elif cmd == "callers":
        if len(args) < 2:
            print(json.dumps({"error": "callers requires a symbol argument"}))
            sys.exit(1)
        cmd_callers(args[1])
    elif cmd == "callees":
        if len(args) < 2:
            print(json.dumps({"error": "callees requires a symbol argument"}))
            sys.exit(1)
        cmd_callees(args[1])
    elif cmd == "explore":
        if len(args) < 2:
            print(json.dumps({"error": "explore requires a symbol argument"}))
            sys.exit(1)
        depth = int(args[2]) if len(args) > 2 else 2
        cmd_explore(args[1], depth)
    else:
        print(json.dumps({"error": f"unknown command: {cmd}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
