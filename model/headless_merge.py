from __future__ import annotations

from pathlib import Path

import fitz


def headless_merge(inputs: list[str], output: str) -> None:
    if not inputs:
        raise ValueError("headless_merge requires at least one input file")

    resolved_inputs = [Path(path) for path in inputs]
    missing = next((path for path in resolved_inputs if not path.exists()), None)
    if missing is not None:
        raise FileNotFoundError(str(missing))

    output_path = Path(output)
    if not output_path.parent.exists():
        raise FileNotFoundError(str(output_path.parent))

    merged = fitz.open()
    try:
        for input_path in resolved_inputs:
            src = fitz.open(input_path)
            try:
                merged.insert_pdf(src)
            finally:
                src.close()
        merged.save(output_path)
    finally:
        merged.close()
