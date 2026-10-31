---
assigned: Codex
created: 2026-10-28T18:35:27.379Z
started: 2026-10-28T18:35:27.379Z
updated: 2026-10-28T18:35:59.705Z
completed: 2026-10-28T18:35:59.705Z
---

# Distinguish board table headings from board names

Give board table column headings a visually distinct style from board names while retaining the existing palette. Acceptance: headings use a separate color and stronger weight; board names and selection styles remain readable; existing UI checks pass.

## Comments

- author: Codex
  date: 2026-10-28T18:35:59.464Z
  Board table headers now use bold mauve, distinct from the teal board slugs and ordinary board-name text. Custom headings receive the same consistent style. Verification: make check passes all 207 Python tests and both JavaScript syntax checks. Changed kanitor/ui.py draw_boards.

## History

- type: created
  date: 2026-10-28T18:35:27.379Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T18:35:59.705Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:49.579Z
  column: Done
  board: explorer
  author: Codex
- type: removed
  date: 2026-10-28T20:39:49.859Z
  fromColumn: Done
  author: Codex
