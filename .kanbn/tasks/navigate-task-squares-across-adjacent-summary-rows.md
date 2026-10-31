---
assigned: Codex
created: 2026-10-27T23:41:11.949Z
started: 2026-10-27T23:41:11.949Z
updated: 2026-10-27T23:44:35.643Z
completed: 2026-10-27T23:44:35.643Z
---

# Navigate task squares across adjacent summary rows

Extend Up/Down task-square selection across board/project rows while retaining the nearest horizontal position. Continue through wrapped task-square lines, cross summary boundaries, and fall back to row focus when an adjacent summary row contains no squares. Preserve ten-item jumps, page navigation, source previews, and task detail opening.

## Comments

- author: Codex
  date: 2026-10-27T23:44:35.459Z
  Implemented Up/Down across wrapped lines and adjacent board/project rows, choosing the nearest square and preserving the preferred horizontal column through shorter lines. Empty rows receive row focus. In-progress squares now precede completions. Validation: 193 tests and both JavaScript syntax checks passed. Linked work session: 6f59c34a-00b2-411f-beb7-422635e9da86.

## History

- type: created
  date: 2026-10-27T23:41:11.949Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-27T23:44:35.643Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:53.011Z
  column: Done
  board: task-squares
  author: Codex
- type: removed
  date: 2026-10-28T20:39:53.270Z
  fromColumn: Done
  author: Codex
