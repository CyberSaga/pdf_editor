# reflow — Multi-track parallel PDF reflow & object editor engine
#
# Stage 0 baseline:
#   reflow_agent_loop.py  — 主控多軌並行迭代循環
#   track_A_core.py       — Vision LLM 重生頁面版（開發期輔助）
#   track_B_core.py       — 低階 content stream 精準操作版
#   unified_command.py    — UnifiedObjectCommand（整合 reflow + 物件操作）
#   test_suite.py         — 自動視覺 diff + 文字選取測試
