---
assigned: Codex
created: 2026-10-31T02:34:01.083Z
started: 2026-10-31T02:34:01.083Z
updated: 2026-10-31T02:55:11.857Z
completed: 2026-10-31T02:55:11.857Z
---

# Add a togglable live activity pane for in-progress tasks

Add an Activity pane toggled by a by default, with Tab/Shift+Tab switching focus between it and the main table. Show native in-progress tickets across declared projects in Projects, project boards in Boards, and the current board in Tasks. Include project/board context, ticket name or abbreviated description, current work activity and a live elapsed counter for the latest open work session linked to the exact task ID; no open session means unknown elapsed. Focused activity tickets drive the existing task preview and open exact task details like task squares, restoring browsing context on return. Support live updates, stable selection, scrolling, resizing, configurable keybindings and appropriate configuration/guidance. Keep all browsing read-only.

## Comments

- author: Codex
  date: 2026-10-31T02:55:11.653Z
  Implemented an Activity pane toggled by a; Tab/Shift+Tab switches focus. Native in-progress tickets are scoped to all projects, all project boards, or the current board. Contextual/configurable columns show project/board, current phase/session label, aligned live elapsed since the latest open task-linked session, assignment and task name/description. Missing/closed/interrupted/unavailable sessions do not produce a live counter. Activity selection drives the shared preview and exact task details, restoring browsing context. Added stable selection, keyboard/mouse navigation, scrollbars, resize handling, live work reads and guidance/YAML defaults. Verification: make check passed 260 Python tests and both JS bridges. Real PTYs passed Boards/Projects toggle, Tab focus, ticking elapsed, preview, exact project/task opening, restored context and clean exit; work logs stayed unchanged. Offline package build and generated-default configuration checks passed; package excludes dev probes and removed Work views.

## History

- type: created
  date: 2026-10-31T02:34:01.083Z
  column: In Progress
  board: explorer
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-31T02:55:11.857Z
  fromColumn: In Progress
  toColumn: Done
  board: explorer
  author: Codex
