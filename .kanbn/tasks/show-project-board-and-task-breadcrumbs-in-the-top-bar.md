---
assigned: Codex
created: 2026-10-28T19:38:27.908Z
started: 2026-10-28T19:38:27.908Z
updated: 2026-10-28T19:39:54.576Z
completed: 2026-10-28T19:39:54.576Z
---

# Show project board and task breadcrumbs in the top bar

Render KANITOR / project_name / board_name / task_id for task pages; truncate the path by navigation depth in task and board lists. Use project basename/display name and native board display name, handle tasks opened through Boards/Projects squares, and keep the top-right live/read-only status separate.

## Comments

- author: Codex
  date: 2026-10-28T19:39:54.222Z
  Top bar now renders KANITOR / project / board display name / exact task ID on task pages, with project/board in task lists and project only in board lists. Nested project paths use the project basename, task pages opened through project squares show the correct context, and Work avoids stale board/task breadcrumbs. Existing status indicator remains separate. README describes the hierarchy. Verification: make check passes 227 tests and both JavaScript syntax checks, including breadcrumb navigation, shared-task board names, nested project naming, Work context, narrow rendering and project-square task opening.

## History

- type: created
  date: 2026-10-28T19:38:27.908Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T19:39:54.576Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:50.028Z
  column: Done
  board: explorer
  author: Codex
- type: removed
  date: 2026-10-28T20:39:50.295Z
  fromColumn: Done
  author: Codex
