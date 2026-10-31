---
assigned: Codex
created: 2026-10-31T03:13:19.192Z
updated: 2026-10-31T03:16:14.641Z
started: 2026-10-31T03:13:19.336Z
completed: 2026-10-31T03:16:14.641Z
---

# Support board slug columns in Activity

Accept field: slug in activityColumns and populate it with the native board slug so board-list YAML anchors can be reused. Treat slug as a board-context column: show it in Projects/Boards, hide it in Tasks, support default enum filtering and sorting, and open the exact project/board when activated. Preserve field: board as the board display name. Update README, agent guide and YAML initializer guidance; verify configuration loading, display/filter/sort, navigation with colliding board names, and contextual visibility.

## History

- type: created
  date: 2026-10-31T03:13:19.192Z
  column: Todo
  board: configuration
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-31T03:13:19.336Z
  fromColumn: Todo
  toColumn: In Progress
  board: configuration
  author: Codex
- type: moved
  date: 2026-10-31T03:16:14.641Z
  fromColumn: In Progress
  toColumn: Done
  board: configuration
  author: Codex
