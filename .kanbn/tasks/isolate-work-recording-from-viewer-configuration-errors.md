---
assigned: Codex
created: 2026-10-31T03:34:02.470Z
updated: 2026-10-31T03:43:28.083Z
started: 2026-10-31T03:34:02.612Z
completed: 2026-10-31T03:43:28.083Z
---

# Isolate work recording from viewer configuration errors

Diagnose older MCP runtime rejecting activityColumns and prevent valid work operations from depending on viewer settings. Load and validate workTracking independently of TUI keys, layouts and project display rules, preserving local precedence and declared-project inheritance. Cover CLI/MCP behavior, invalid view rules, newer unknown display keys and actual work-rule enforcement. Give concrete runtime refresh guidance and document boundaries around unreadable configuration. Preserve durable work logs and other project state.

## History

- type: created
  date: 2026-10-31T03:34:02.470Z
  column: Todo
  board: work
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-31T03:34:02.612Z
  fromColumn: Todo
  toColumn: In Progress
  board: work
  author: Codex
- type: moved
  date: 2026-10-31T03:43:28.083Z
  fromColumn: In Progress
  toColumn: Done
  board: work
  author: Codex
