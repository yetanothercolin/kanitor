---
assigned: Codex
created: 2026-10-28T20:38:20.968Z
started: 2026-10-28T20:38:20.968Z
updated: 2026-10-28T20:41:26.698Z
completed: 2026-10-28T20:41:26.698Z
---

# Organize kanbn boards by broad feature group

Update the workspace usage policy so boards represent stable broad feature groups, not statuses, releases or individual work sessions. Create the feature boards and migrate every existing task to one primary board using native kanbn commands, preserving IDs, workflow states, lifecycle dates and work-log links. Acceptance: AGENTS documents taxonomy/commands; all tasks have exactly one appropriate board; every board uses the common workflow; native validation and Kanitor snapshots agree.

## Comments

- author: Codex
  date: 2026-10-28T20:41:26.415Z
  Updated AGENTS policy to group boards by broad feature area and require explicit board selection plus one primary membership. Main index is Workflow & Tooling (2 tasks); Workspace & Configuration has 4, Explorer UI 4, Task Squares 5, Work Tracking 3. All 17 previous cards plus this task are classified. Native command migration preserved IDs, statuses, created/started/completed dates, assignments, descriptions/comments, prior history and work links. Kanitor snapshots and native membership audit agree. kanbn validate --all-boards reports no errors and one expected shared-completed-field warning, now documented. Application tests were not run because changes are policy/tracking only.

## History

- type: created
  date: 2026-10-28T20:38:20.968Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T20:41:26.698Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
