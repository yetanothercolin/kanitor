---
assigned: Codex
created: 2026-10-29T03:04:09.851Z
started: 2026-10-29T03:04:09.851Z
updated: 2026-10-29T03:08:24.824Z
completed: 2026-10-29T03:08:24.824Z
---

# Add horizontal jump bindings for task squares

Add configurable jumpLeft and jumpRight actions, defaulting to Shift+Left and Shift+Right. They move one cell in ordinary table rows and headers, and five squares within the focused Task Squares column, across wrapped lines. Clamp a jump to the first/last square; a further jump at that edge enters the adjacent cell, matching existing horizontal navigation. Preserve square previews/activation and support Boards/Projects plus remapping/disabling, generated defaults and Help/guidance.

## Comments

- author: Codex
  date: 2026-10-29T03:08:24.618Z
  Added jumpLeft/jumpRight actions with Shift+Left/Right defaults. Ordinary table rows and headers move one cell; focused task squares move five in their wrapped order, clamp to the first/last square, and enter the adjacent cell on a further edge jump. Custom bindings work in Boards and Projects and preserve previews. Updated runtime Help, generated YAML comments/defaults, README and agent guide. Verification: make check passed 247 Python tests and both JavaScript bridge syntax checks, including native/extended Shift key aliases, remapping, all table/header contexts, wrapping, previews and boundary behavior.

## History

- type: created
  date: 2026-10-29T03:04:09.851Z
  column: In Progress
  board: task-squares
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-29T03:08:24.824Z
  fromColumn: In Progress
  toColumn: Done
  board: task-squares
  author: Codex
