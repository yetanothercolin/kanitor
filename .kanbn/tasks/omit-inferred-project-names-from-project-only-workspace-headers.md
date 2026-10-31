---
assigned: Codex
created: 2026-10-28T19:59:35.874Z
started: 2026-10-28T19:59:35.874Z
updated: 2026-10-28T20:00:27.504Z
completed: 2026-10-28T20:00:27.504Z
---

# Omit inferred project names from project-only workspace headers

Projects view should show exactly KANITOR / when its workspace has no native kanbn project. Preserve the root name for workspaces with native kanbn markers and project names after drilling into a child. Validate both workspace cases and existing Projects navigation.

## Comments

- author: Codex
  date: 2026-10-28T20:00:27.234Z
  Projects header now shows KANITOR / with no inferred directory name when the workspace lacks native kanbn markers. Workspaces with .kanbn, kanbn.json, or kanbn.yml retain their project name; drilling into a child still shows that child name. Verification: all 12 Projects tests pass; temporary-grid smoke check verifies project-only workspace, all three native marker cases, and child navigation. Tracking validates.

## History

- type: created
  date: 2026-10-28T19:59:35.874Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T20:00:27.504Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:50.459Z
  column: Done
  board: explorer
  author: Codex
- type: removed
  date: 2026-10-28T20:39:50.740Z
  fromColumn: Done
  author: Codex
