---
assigned: Codex
created: 2026-10-31T03:18:11.194Z
updated: 2026-10-31T03:22:53.114Z
started: 2026-10-31T03:18:11.352Z
completed: 2026-10-31T03:22:53.114Z
---

# Use explicit project board and task name fields

Make name fields consistent across view scopes: project is the project name in Projects and Activity, board is the board display name in Boards and Activity, and task is the task title in Tasks and Activity. Use these explicit fields in defaults, initializer, documentation and examples. Retain name as a compatibility alias with canonical filter/focus identity so live migration preserves state. Align nested project display names across Projects and Activity. Verify value resolution, defaults, YAML anchor reuse, filtering/sorting, navigation and live alias migration without changing native data.

## History

- type: created
  date: 2026-10-31T03:18:11.194Z
  column: Todo
  board: configuration
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-31T03:18:11.352Z
  fromColumn: Todo
  toColumn: In Progress
  board: configuration
  author: Codex
- type: moved
  date: 2026-10-31T03:22:53.114Z
  fromColumn: In Progress
  toColumn: Done
  board: configuration
  author: Codex
