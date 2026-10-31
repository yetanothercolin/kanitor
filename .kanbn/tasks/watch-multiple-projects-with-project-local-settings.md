---
assigned: Codex
created: 2026-10-27T20:55:50.635Z
started: 2026-10-27T20:55:50.635Z
updated: 2026-10-27T21:11:59.463Z
completed: 2026-10-27T21:11:59.463Z
---

# Watch multiple projects with project-local settings

Add a Projects layer above Boards. A parent .kanitor.json declares descendant project directories. Drill into each project using its own board, task, and Work settings; return to Projects and watch changes independently.

Acceptance criteria:
- Validate and document the projects configuration.
- Add keyboard and mouse navigation, scrolling, and per-project context.
- Keep independent live readers and errors so one project does not block others.
- Preserve standalone workspace behavior and verify project-local board/task/Work rules with regression tests.

## Comments

- author: Codex
  date: 2026-10-27T21:11:59.261Z
  Implemented Projects above Boards using an ordered projects array in the parent .kanitor.json. Child board/task/Work settings and view contexts remain independent; live roster/config changes and isolated errors are supported. Documentation and example: README.md and examples/kanitor-projects.json. Validation: make check passed 166 tests plus JavaScript syntax checks; native and Node-free PTY checks and isolated-wheel checks passed. Linked work session: d221fcbf-7074-4e24-a3df-30e1294b4cfc.

## History

- type: created
  date: 2026-10-27T20:55:50.635Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-27T21:11:59.463Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:47.807Z
  column: Done
  board: configuration
  author: Codex
- type: removed
  date: 2026-10-28T20:39:48.081Z
  fromColumn: Done
  author: Codex
