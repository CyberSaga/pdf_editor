# .codegraph — Python-native code knowledge graph

Indexes all `.py` source files into a SQLite semantic graph. Agents query it
instead of scanning files with grep/glob/Read.

## Quick start

```bash
# Re-index (run from project root after structural changes)
python .codegraph/indexer.py

# Search by name/keyword/docstring
python .codegraph/query.py search PDFModel

# Full node info + callers/callees
python .codegraph/query.py context PDFModel

# Reverse edge traversal: who calls save_as?
python .codegraph/query.py callers save_as

# Forward edge traversal: what does open_pdf call?
python .codegraph/query.py callees open_pdf

# BFS graph exploration to depth 2
python .codegraph/query.py explore PDFController 2
```

All output is compact JSON.

## Schema (graph.db)

### nodes

| column    | type    | description                                  |
|-----------|---------|----------------------------------------------|
| id        | TEXT PK | `"<file>::<qualname>"` e.g. `model/pdf_model.py::PDFModel` |
| kind      | TEXT    | `file` \| `class` \| `function` \| `method` |
| name      | TEXT    | short name (e.g. `PDFModel`)                 |
| qualname  | TEXT    | dotted name inside file (e.g. `PDFModel.save_as`) |
| file      | TEXT    | relative path from project root              |
| line      | INT     | line number                                  |
| docstring | TEXT    | extracted docstring                          |
| signature | TEXT    | reconstructed `def foo(a, b) -> T`           |
| bases     | TEXT    | comma-separated base class names (classes)   |

### nodes_fts (FTS5 virtual table)

Columns indexed: `name`, `qualname`, `docstring`, `signature`.
Use FTS5 phrase queries: `python .codegraph/query.py search "text edit"`.

### edges

| column | type | description                                         |
|--------|------|-----------------------------------------------------|
| src    | TEXT | source node id                                      |
| dst    | TEXT | destination node id or bare callee name             |
| kind   | TEXT | `defines` \| `imports` \| `inherits` \| `calls`    |

## Exclude patterns

Edit `.codegraphignore` at project root (gitignore syntax). Default exclusions:
`.venv/`, `test_files/`, `__pycache__/`, `build/`, `dist/`, `.codegraph/`.

## Files

| file           | purpose                                          |
|----------------|--------------------------------------------------|
| `indexer.py`   | one-shot indexer — builds `graph.db` + `CODEINDEX.md` |
| `query.py`     | query CLI — agents call this for targeted lookups |
| `graph.db`     | SQLite database (created by indexer)             |
| `README.md`    | this file                                        |
| `CODEINDEX.md` | pre-built static symbol inventory |
