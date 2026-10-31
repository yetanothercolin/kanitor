---
assigned: Codex
created: 2026-10-27T23:36:44.644Z
started: 2026-10-27T23:36:44.644Z
updated: 2026-10-27T23:39:12.010Z
completed: 2026-10-27T23:39:12.010Z
---

# Outline focused task status cells and rename the default heading

Remove the reversed white row background behind Task Squares while keeping task colors/pulses. Use a thin outline-style focus treatment around the status cell without changing wrapping or hit targets. Rename the default column heading to Task Status in Projects and Boards, preserving explicitly configured titles.

Acceptance criteria:
- Focused square cells have a normal background including gaps and padding.
- Focus is indicated by lightweight outline edges and individual square selection still works.
- Default heading is Task Status in both views; custom titles remain unchanged.
- Verify styled-cell rendering and interaction regressions.

## Comments

- author: Codex
  date: 2026-10-27T23:39:11.817Z
  Fixed white highlight strips by clearing the entire task status cell background and using thin outline-style focus edges. Default heading is now Task Status in Projects and Boards; custom titles such as this repo Tasks are preserved. Styled rendering tests and full make check passed: 190 tests plus JavaScript checks. Real-terminal selection/preview/double-click checks passed. Linked work session: 8063b6ca-6498-4970-940b-f1f803790b91.

## History

- type: created
  date: 2026-10-27T23:36:44.644Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-27T23:39:12.010Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:52.186Z
  column: Done
  board: task-squares
  author: Codex
- type: removed
  date: 2026-10-28T20:39:52.436Z
  fromColumn: Done
  author: Codex
