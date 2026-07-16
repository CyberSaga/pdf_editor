from __future__ import annotations

import logging

import fitz

# R3.1: the stateless parsing layer (helpers, dataclasses, fitz-dict -> dataclass
# transforms) lives in text_block_parsing. TextBlockManager (below) keeps ownership
# of every page-keyed index and delegates the pure transforms. The dataclasses and
# rotation_degrees_from_dir are re-exported here for backward compatibility.
from model import text_block_parsing as _tbp
from model.text_block_parsing import (
    EditableParagraph,
    EditableSpan,
    TextBlock,
    rotation_degrees_from_dir,  # noqa: F401  (re-export: pdf_model imports it from here)
)

logger = logging.getLogger(__name__)


class TextBlockManager:
    def __init__(self):
        self._index: dict[int, list[TextBlock]] = {}
        self._span_index: dict[int, list[EditableSpan]] = {}
        self._paragraph_index: dict[int, list[EditableParagraph]] = {}
        self._run_to_paragraph: dict[int, dict[str, str]] = {}
        self._page_plain_lines: dict[int, list[str]] = {}
        # Page-level cache state for the current document snapshot.
        #
        # Why it exists:
        # - Structural operations (insert/delete pages) shift page numbers. Existing cached entries are still
        #   useful, but their "page_idx -> content" mapping becomes invalid until rebuilt.
        # - Instead of forcing a full-document rebuild (slow + UI-stalling), we keep unaffected entries and
        #   mark shifted entries as "stale". They will be rebuilt on-demand (edit/search) or drained in a
        #   background batch loop (controller).
        #
        # State values:
        # - "missing": no cache (default for absent key)
        # - "clean"  : cache matches the current doc snapshot for this page_idx
        # - "stale"  : cache exists but the page index was shifted by a structural op; must rebuild before use
        self._page_state: dict[int, str] = {}

    def build_index(self, doc: fitz.Document) -> None:
        self._index.clear()
        self._span_index.clear()
        self._paragraph_index.clear()
        self._run_to_paragraph.clear()
        self._page_plain_lines.clear()
        self._page_state.clear()
        for page_num in range(len(doc)):
            self._build_page_index(page_num, doc[page_num])
        total = sum(len(blocks) for blocks in self._index.values())
        logger.info(f"TextBlockManager index built: {total} blocks")

    def rebuild_page(self, page_num: int, doc: fitz.Document) -> None:
        if page_num < 0 or page_num >= len(doc):
            logger.warning(f"rebuild_page out of range: {page_num}")
            return
        self._build_page_index(page_num, doc[page_num])

    def page_state(self, page_idx: int) -> str:
        """Return cache state for 0-based page index ("missing" | "clean" | "stale")."""
        return self._page_state.get(page_idx, "missing")

    def list_stale_pages(self) -> list[int]:
        """Return sorted 0-based page indices that are known stale and safe to rebuild lazily."""
        return sorted(page_idx for page_idx, state in self._page_state.items() if state == "stale")

    def shift_after_insert(self, insert_at: int, count: int) -> None:
        if count <= 0:
            return
        # Keep cached entries, but shift their keys to match the new page numbering.
        # Any moved page becomes stale because the underlying page content at that new index is different.
        for store_name in ("_index", "_span_index", "_paragraph_index", "_run_to_paragraph", "_page_plain_lines"):
            store = getattr(self, store_name)
            moved = {}
            for page_idx in sorted(store.keys(), reverse=True):
                if page_idx >= insert_at:
                    moved[page_idx + count] = store.pop(page_idx)
            store.update(moved)
        moved_state: dict[int, str] = {}
        for page_idx in sorted(self._page_state.keys(), reverse=True):
            if page_idx >= insert_at:
                moved_state[page_idx + count] = "stale"
                self._page_state.pop(page_idx)
        self._page_state.update(moved_state)

    def shift_after_delete(self, deleted_pages: list[int]) -> None:
        if not deleted_pages:
            return
        deleted = sorted(set(deleted_pages))
        deleted_set = set(deleted)
        # After deletion, later cached pages slide left; any page that moved becomes stale until rebuilt.
        for store_name in ("_index", "_span_index", "_paragraph_index", "_run_to_paragraph", "_page_plain_lines"):
            store = getattr(self, store_name)
            remapped = {}
            for page_idx in sorted(store.keys()):
                if page_idx in deleted_set:
                    continue
                shift = sum(1 for deleted_idx in deleted if deleted_idx < page_idx)
                remapped[page_idx - shift] = store[page_idx]
            store.clear()
            store.update(remapped)
        remapped_state: dict[int, str] = {}
        for page_idx in sorted(self._page_state.keys()):
            if page_idx in deleted_set:
                continue
            shift = sum(1 for deleted_idx in deleted if deleted_idx < page_idx)
            new_idx = page_idx - shift
            state = self._page_state[page_idx]
            remapped_state[new_idx] = "stale" if shift else state
        self._page_state.clear()
        self._page_state.update(remapped_state)

    def shift_after_move(self, source_idx: int, destination_idx: int) -> None:
        """Remap cached pages after moving one page to its final 0-based destination.

        Every page in the moved interval becomes stale.  The cached content follows
        its PDF page to the correct key so no unrelated page is lost, but callers
        must rebuild the stale interval before trusting its text geometry.
        """
        if source_idx == destination_idx:
            return

        first_idx = min(source_idx, destination_idx)
        last_idx = max(source_idx, destination_idx)

        def remap_page_idx(page_idx: int) -> int:
            if page_idx == source_idx:
                return destination_idx
            if source_idx < destination_idx and source_idx < page_idx <= destination_idx:
                return page_idx - 1
            if destination_idx < source_idx and destination_idx <= page_idx < source_idx:
                return page_idx + 1
            return page_idx

        for store_name in ("_index", "_span_index", "_paragraph_index", "_run_to_paragraph", "_page_plain_lines"):
            store = getattr(self, store_name)
            remapped = {remap_page_idx(page_idx): value for page_idx, value in store.items()}
            store.clear()
            store.update(remapped)

        remapped_state = {
            remap_page_idx(page_idx): state for page_idx, state in self._page_state.items()
        }
        for page_idx in range(first_idx, last_idx + 1):
            remapped_state[page_idx] = "stale"
        self._page_state.clear()
        self._page_state.update(remapped_state)

    def _build_page_index(self, page_num: int, page: fitz.Page) -> None:
        blocks_raw = page.get_text("dict", flags=0).get("blocks", [])
        raw_blocks = page.get_text("rawdict", flags=0).get("blocks", [])
        plain_lines = self._extract_plain_text_lines(page)
        page_blocks: list[TextBlock] = []
        page_spans: list[EditableSpan] = []

        for block_idx, block in enumerate(blocks_raw):
            tb = self._parse_block(page_num, block_idx, block)
            if tb is not None:
                page_blocks.append(tb)
            raw_block = raw_blocks[block_idx] if block_idx < len(raw_blocks) else None
            if raw_block and raw_block.get("type") == 0:
                runs = self._parse_runs_from_raw_block(page_num, block_idx, raw_block, plain_lines=plain_lines)
                if runs:
                    page_spans.extend(runs)
                    continue
            page_spans.extend(self._parse_spans(page_num, block_idx, block))

        self._index[page_num] = page_blocks
        self._span_index[page_num] = page_spans
        paragraphs = self._build_paragraphs(page_num, page_spans)
        self._paragraph_index[page_num] = paragraphs
        run_map: dict[str, str] = {}
        for para in paragraphs:
            for run_id in para.run_ids:
                run_map[run_id] = para.paragraph_id
        self._run_to_paragraph[page_num] = run_map
        self._page_plain_lines[page_num] = plain_lines
        self._page_state[page_num] = "clean"
        logger.debug(
            f"page {page_num + 1}: {len(page_blocks)} blocks, {len(page_spans)} spans(runs), "
            f"{len(paragraphs)} paragraphs"
        )

    def get_blocks(self, page_num: int) -> list[TextBlock]:
        return self._index.get(page_num, [])

    def get_spans(self, page_num: int) -> list[EditableSpan]:
        return self._span_index.get(page_num, [])

    # Run-level aliases: reconstructed runs are stored in _span_index for compatibility.
    def get_runs(self, page_num: int) -> list[EditableSpan]:
        return self.get_spans(page_num)

    def get_paragraphs(self, page_num: int) -> list[EditableParagraph]:
        return self._paragraph_index.get(page_num, [])

    def find_by_id(self, page_num: int, block_id: str) -> TextBlock | None:
        for block in self._index.get(page_num, []):
            if block.block_id == block_id:
                return block
        return None

    def find_span_by_id(self, page_num: int, span_id: str) -> EditableSpan | None:
        for span in self._span_index.get(page_num, []):
            if span.span_id == span_id:
                return span
        return None

    def find_run_by_id(self, page_num: int, run_id: str) -> EditableSpan | None:
        return self.find_span_by_id(page_num, run_id)

    def find_paragraph_by_id(self, page_num: int, paragraph_id: str) -> EditableParagraph | None:
        for para in self._paragraph_index.get(page_num, []):
            if para.paragraph_id == paragraph_id:
                return para
        return None

    def find_paragraph_for_run(self, page_num: int, run_id: str) -> EditableParagraph | None:
        para_id = self._run_to_paragraph.get(page_num, {}).get(run_id)
        if not para_id:
            return None
        return self.find_paragraph_by_id(page_num, para_id)

    def find_overlapping_spans(
        self,
        page_num: int,
        rect: fitz.Rect,
        tol: float = 0.5,
    ) -> list[EditableSpan]:
        expanded = fitz.Rect(rect.x0 - tol, rect.y0 - tol, rect.x1 + tol, rect.y1 + tol)
        return [
            span
            for span in self._span_index.get(page_num, [])
            if fitz.Rect(span.bbox).intersects(expanded)
        ]

    def find_overlapping_runs(
        self,
        page_num: int,
        rect: fitz.Rect,
        tol: float = 0.5,
    ) -> list[EditableSpan]:
        return self.find_overlapping_spans(page_num, rect, tol=tol)

    def find_overlapping_paragraphs(
        self,
        page_num: int,
        rect: fitz.Rect,
        tol: float = 0.5,
    ) -> list[EditableParagraph]:
        expanded = fitz.Rect(rect.x0 - tol, rect.y0 - tol, rect.x1 + tol, rect.y1 + tol)
        return [
            para
            for para in self._paragraph_index.get(page_num, [])
            if fitz.Rect(para.bbox).intersects(expanded)
        ]

    def find_by_rect(
        self,
        page_num: int,
        rect: fitz.Rect,
        original_text: str | None = None,
        doc: fitz.Document | None = None,
    ) -> TextBlock | None:
        candidates = [
            b for b in self._index.get(page_num, []) if fitz.Rect(b.layout_rect).intersects(rect)
        ]

        if not candidates:
            if doc is not None:
                return self._dynamic_scan(page_num, rect, original_text, doc)
            return None

        if original_text and original_text.strip():
            matched = self._match_by_text(candidates, original_text)
            if matched is not None:
                return matched
        return self._closest_to_center(candidates, rect)

    def update_block(self, block: TextBlock, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(block, key):
                setattr(block, key, value)
        if "rotation" in kwargs:
            block.is_vertical = block.rotation in (90, 270)

    def clear(self) -> None:
        # Clears all cached indices and page state. Callers should rebuild only the pages they need now.
        self._index.clear()
        self._span_index.clear()
        self._paragraph_index.clear()
        self._run_to_paragraph.clear()
        self._page_plain_lines.clear()
        self._page_state.clear()
        logger.debug("TextBlockManager index cleared")

    def _parse_block(self, page_num: int, raw_index: int, block: dict) -> TextBlock | None:
        return _tbp._parse_block(page_num, raw_index, block)

    def _parse_spans(self, page_num: int, block_idx: int, block: dict) -> list[EditableSpan]:
        return _tbp._parse_spans(page_num, block_idx, block)

    def _parse_runs_from_raw_block(
        self,
        page_num: int,
        block_idx: int,
        raw_block: dict,
        plain_lines: list[str] | None = None,
    ) -> list[EditableSpan]:
        return _tbp._parse_runs_from_raw_block(page_num, block_idx, raw_block, plain_lines=plain_lines)

    def _parse_runs_from_raw_line(
        self,
        page_num: int,
        block_idx: int,
        line_idx: int,
        line: dict,
        plain_lines: list[str] | None = None,
    ) -> list[EditableSpan]:
        return _tbp._parse_runs_from_raw_line(
            page_num, block_idx, line_idx, line, plain_lines=plain_lines
        )

    @staticmethod
    def _extract_plain_text_lines(page: fitz.Page) -> list[str]:
        return _tbp._extract_plain_text_lines(page)

    @staticmethod
    def _repair_replacement_chars(text: str, plain_lines: list[str] | None) -> str:
        return _tbp._repair_replacement_chars(text, plain_lines)

    def _build_paragraphs(self, page_num: int, runs: list[EditableSpan]) -> list[EditableParagraph]:
        return _tbp._build_paragraphs(page_num, runs)

    def _merge_vertical_paragraphs(
        self,
        page_num: int,
        paragraphs: list[EditableParagraph],
    ) -> list[EditableParagraph]:
        return _tbp._merge_vertical_paragraphs(page_num, paragraphs)

    @staticmethod
    def _can_merge_vertical_paragraph(left: EditableParagraph, right: EditableParagraph) -> bool:
        return _tbp._can_merge_vertical_paragraph(left, right)

    @staticmethod
    def _compose_merged_vertical_paragraph(
        page_num: int,
        group: list[EditableParagraph],
        merge_idx: int,
    ) -> EditableParagraph:
        return _tbp._compose_merged_vertical_paragraph(page_num, group, merge_idx)

    @staticmethod
    def _expand_ligatures(text: str) -> str:
        return _tbp._expand_ligatures(text)

    def _match_by_text(self, candidates: list[TextBlock], original_text: str) -> TextBlock | None:
        return _tbp._match_by_text(candidates, original_text)

    def _closest_to_center(self, candidates: list[TextBlock], rect: fitz.Rect) -> TextBlock | None:
        return _tbp._closest_to_center(candidates, rect)

    def _dynamic_scan(
        self,
        page_num: int,
        rect: fitz.Rect,
        original_text: str | None,
        doc: fitz.Document,
    ) -> TextBlock | None:
        return _tbp._dynamic_scan(page_num, rect, original_text, doc)
