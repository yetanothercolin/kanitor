---
assigned: Codex
created: 2026-10-28T19:14:44.444Z
started: 2026-10-28T19:14:44.444Z
updated: 2026-10-28T19:19:11.777Z
completed: 2026-10-28T19:19:11.777Z
---

# Support bounded hug and fill column widths

Implement comma-separated width constraints (fill,8; 8,fill; hug,8; 8,hug; 2,hug,8; bounded fill), equal final fill widths with cap redistribution, soft minimums under pressure and readability floors before hiding trailing columns. Apply to all table views, preserve existing width forms, update work schemas and configuration guidance, and validate allocation, live config, Unicode/filter headers and Task Squares reflow.

## Comments

- author: Codex
  date: 2026-10-28T19:19:11.513Z
  Implemented bounded widths across all table scopes using normalized sizing, equal final fill allocation with cap redistribution, proportional shrinking of soft minimums, and readability floors before trailing-column hiding. Existing fixed/hug/fill/default widths remain supported. Added shared grammar to discoverable work schema and synchronized packaged artifact; updated README, agent guide, YAML initializer examples and work docs. Verification: make check passes 226 tests and both JavaScript syntax checks; uv build --offline creates wheel/sdist; isolated wheel verifies constrained allocations, generated YAML guidance and schema agreement. Tests cover live JSON/YAML reload/recovery, budget/cap invariants, Unicode, filters, and board/project Task Squares selection and mouse opening after actual width reflow.

## History

- type: created
  date: 2026-10-28T19:14:44.444Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T19:19:11.777Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:49.131Z
  column: Done
  board: configuration
  author: Codex
- type: removed
  date: 2026-10-28T20:39:49.409Z
  fromColumn: Done
  author: Codex
