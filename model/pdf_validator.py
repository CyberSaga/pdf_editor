"""PDF conformance checks.

Light-weight structural validation used as evidence that the editor's output
targets a well-formed PDF (see ``docs/pdf_compliance.md``). This is not a full
PDF/A validator; it checks the structural invariants the editor relies on and
that the XREF-repair feature guards against: a parseable cross-reference table,
a parseable page tree, and resolvable object references.
"""

from __future__ import annotations

import fitz


def check_pdf_conformance(path: str) -> list[str]:
    """Return a list of conformance issues for the PDF at ``path``.

    An empty list means no structural problems were detected. Each entry is a
    short human-readable description. The check is intentionally conservative:
    it reports problems it is confident about rather than guessing.
    """
    issues: list[str] = []
    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001 - report any open failure as an issue
        return [f"cannot open PDF: {exc}"]

    try:
        # 1. PDF version header — PyMuPDF exposes it via metadata "format".
        metadata = doc.metadata or {}
        fmt = str(metadata.get("format", "")).upper()
        if "PDF" not in fmt:
            issues.append("missing or unrecognised PDF version header")

        # 2. Cross-reference table: PyMuPDF rebuilds a damaged xref on open and
        #    flags it. A conformant file does not need repair.
        if bool(getattr(doc, "is_repaired", False)):
            issues.append("cross-reference table is damaged (rebuilt on open)")

        # 3. Page tree must be parseable and non-empty.
        try:
            page_count = int(doc.page_count)
        except Exception as exc:  # noqa: BLE001
            page_count = 0
            issues.append(f"page tree is not parseable: {exc}")
        if page_count <= 0:
            issues.append("page tree contains no pages")
        else:
            for index in range(page_count):
                try:
                    page = doc[index]
                    _ = page.rect
                except Exception as exc:  # noqa: BLE001
                    issues.append(f"page {index + 1} is not parseable: {exc}")

        # 4. Object references: every in-use xref entry must resolve to an object
        #    definition. A dangling/broken reference raises here.
        try:
            xref_count = int(doc.xref_length())
        except Exception as exc:  # noqa: BLE001
            xref_count = 0
            issues.append(f"object table is not parseable: {exc}")
        broken = 0
        for xref in range(1, xref_count):
            try:
                definition = doc.xref_object(xref, compressed=True)
            except Exception:  # noqa: BLE001 - count, don't abort the scan
                broken += 1
                continue
            # A free/unused slot legitimately has no definition; only a None
            # (failed resolution of an in-use object) is a problem.
            if definition is None:
                broken += 1
        if broken:
            issues.append(f"{broken} object reference(s) could not be resolved")
    finally:
        doc.close()

    return issues


def is_pdf_conformant(path: str) -> bool:
    """Convenience wrapper: True when :func:`check_pdf_conformance` finds nothing."""
    return not check_pdf_conformance(path)
