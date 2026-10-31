---
assigned: Codex
created: 2026-10-27T22:42:25.367Z
started: 2026-10-27T22:42:25.367Z
updated: 2026-10-27T22:56:41.214Z
completed: 2026-10-27T22:56:41.214Z
---

# Select task squares and preview or open their tasks

Make individual Task Squares selectable in Boards and Projects. Selecting a square reveals that task preview; double-click opens the exact task details in its project/board. Support keyboard selection and wrapped/scrolled hit targets without disrupting stable lane ordering.

Acceptance criteria:
- Mouse and keyboard square selection, preview, and task detail navigation in both views.
- Preserve the correct source project/board and provide a return path from details.
- Configure this repo to show Board, Name, and Tasks squares only.
- Document the two-column Projects configuration and validate with regression/terminal checks.

## Comments

- author: Codex
  date: 2026-10-27T22:56:41.018Z
  Implemented individual square selection, task previews, Enter/double-click task details, keyboard/spatial paging, and source-aware project return context. Double-click remains reliable when the preview reflows the list. Added .kanitor.json with only Board, Name, and Tasks; README and agent guidance include the Project/Tasks projectColumns line. Validation: 187 tests plus JavaScript syntax checks, real-terminal interaction checks, native configuration verification, and package inspection passed. Linked work session: 42390434-effc-4483-8875-ee226dbbd04d.

## History

- type: created
  date: 2026-10-27T22:42:25.367Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-27T22:56:41.214Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:51.759Z
  column: Done
  board: task-squares
  author: Codex
- type: removed
  date: 2026-10-28T20:39:52.025Z
  fromColumn: Done
  author: Codex
