from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_multi_tab_plan import (  # noqa: F401 — re-exported for pytest collection
    qapp,
    mvc,
    test_26_fullscreen_no_document_is_noop,
    test_27_fullscreen_enter_and_escape_restore_chrome,
    test_28_fullscreen_restores_zoom_scroll_and_dirty_state,
    test_29_fullscreen_clears_search_and_cancels_editor,
    test_30_fullscreen_blocked_while_print_busy_or_modal,
    test_31_fullscreen_exit_button_stays_visible,
    test_33_fullscreen_from_highlight_mode_cancels_partial_state_and_enters_browse,
    test_34_fullscreen_quick_button_sits_between_fit_and_undo_and_f5_toggles,
    test_34a_fullscreen_quick_button_has_12px_gap_from_fit_button,
    test_34b_fullscreen_context_menu_offers_exit_action_and_triggers_toggle,
)
