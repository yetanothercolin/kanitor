---
assigned: Codex
created: 2026-10-28T23:10:32.737Z
started: 2026-10-28T23:10:32.737Z
updated: 2026-10-29T02:34:40.957Z
completed: 2026-10-29T02:34:40.957Z
---

# Bracket focused rows and highlight focused cells and squares

Use cyan brackets around the full focused row in Projects, Boards and Tasks. Replace full-row reverse highlighting with a highlight on only the focused scalar cell or individual task square. Wrapped rows must retain clear outer edges, task-square status colors and hit targets must remain intact, and header focus must remove data-row focus markers. Update relevant rendering checks and guidance.

## Comments

- author: Codex
  date: 2026-10-29T02:34:40.751Z
  Implemented cyan brackets around the full focused row across Projects, Boards and Tasks, including corner/vertical edges for wrapped rows. Reverse highlighting now follows only the focused scalar cell or individual square; neighboring cells and spaces stay normal, and header focus clears data-row markers. Updated README and agent guidance. Verification: make check passed all 235 Python tests and both JavaScript bridge checks; rendering checks cover highlight movement, wrapped outer brackets, project/task rows, header focus and unchanged square hit coordinates.

## History

- type: created
  date: 2026-10-28T23:10:32.737Z
  column: In Progress
  board: explorer
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-29T02:34:40.957Z
  fromColumn: In Progress
  toColumn: Done
  board: explorer
  author: Codex
