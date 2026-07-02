#!/bin/bash
cd "$(dirname "$0")"

if [ -x .venv/bin/python ]; then
    exec .venv/bin/python main.py "$@"
else
    echo "ERROR: No .venv/bin/python found." >&2
    echo "Run: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
    exit 1
fi
