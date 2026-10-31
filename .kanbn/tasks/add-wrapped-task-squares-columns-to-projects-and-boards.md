---
assigned: Codex
created: 2026-10-27T22:11:44.288Z
started: 2026-10-27T22:11:44.288Z
updated: 2026-10-27T22:33:26.286Z
completed: 2026-10-27T22:33:26.286Z
---

# Add wrapped Task Squares columns to projects and boards

Support a configurable Task Squares column in Projects and Boards. Show recent completions, active tasks colored by recent linked work, paused tasks, and recent/old unstarted tasks. Hide old completions. Wrap into completion, active, and paused/unstarted lanes when needed, preserving active task positions through live state changes until leaving the view.

Acceptance criteria:
- Shared classification and grouped wrapping in both views, with gentle active pulsing.
- Configurable recency thresholds and column widths; native workflow and work-log reads remain read-only.
- Stable active ordering and correct scrolling/mouse/keyboard behavior for variable-height rows.
- Document configuration and verify classification, ordering, rendering, live updates, and regressions.

## Comments

- author: Codex
  date: 2026-10-27T22:33:26.096Z
  Implemented Task Squares in default/custom Projects and Boards layouts. Recency defaults: completion/creation 24h and logged work 15m; paused uses native workflow/start history. Added grouped wrapping, pinned active lanes through state changes, gentle color pulses, physical-line scrolling, projectColumns rules, and taskSquares thresholds. Documentation: README.md Task Squares section and kanitor --agent-guide. Verification: 181 tests plus JavaScript checks passed; real-terminal and isolated-wheel checks passed with unchanged fixture files. Linked work session: 59a17a3c-68ba-4ab2-bff8-f02a8aab5cfe.

## History

- type: created
  date: 2026-10-27T22:11:44.288Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-27T22:33:26.286Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:51.313Z
  column: Done
  board: task-squares
  author: Codex
- type: removed
  date: 2026-10-28T20:39:51.587Z
  fromColumn: Done
  author: Codex
