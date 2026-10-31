---
assigned: Codex
created: 2026-10-28T18:09:23.052Z
started: 2026-10-28T18:09:23.052Z
updated: 2026-10-28T18:18:55.951Z
completed: 2026-10-28T18:16:20.712Z
---

# Support YAML configuration and annotated initialization

Support .kanitor.yml and .kanitor.yaml consistently across native views, projects, and work logging with live reload. Add --init-yml to create a non-overwriting annotated configuration containing the current defaults and commented examples. Acceptance: JSON remains supported; deterministic selection and accurate config errors; generated defaults match runtime defaults; YAML reload, CLI initialization and work configuration validated; docs updated.

## Comments

- author: Codex
  date: 2026-10-28T18:16:20.474Z
  Implemented .kanitor.yml/.yaml support through a shared validated loader for boards, projects, work recording and live refresh. Added --init-yml to generate all runtime defaults plus commented examples without overwriting any supported config. JSON > YML > YAML precedence documented. Added minTerminalWidth to retain responsive defaults and synchronized packaged work schema. Verification: make check passes all 206 Python tests plus both JavaScript syntax checks; uv build --offline succeeds; isolated packaged initializer and Work snapshot work without Node/kanbn and create no work storage. Existing square UI fixture now freezes its clock during key handling so completions do not expire based on the calendar date.
- author: Codex
  date: 2026-10-28T18:18:55.715Z
  Follow-up: PATH tool used a separate editable environment without PyYAML. User reinstalled it with MCP extras preserved; actual installed kanitor --init-yml now succeeds in a temporary directory. YAML imports now raise actionable ConfigError guidance instead of an unhandled ModuleNotFoundError when an older editable environment lacks dependencies. Added regression coverage and documented refreshing uv tool environments after dependency changes. Verification: make check passes all 207 tests and both JavaScript syntax checks.

## History

- type: created
  date: 2026-10-28T18:09:23.052Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T18:16:20.712Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: moved
  date: 2026-10-28T18:17:16.532Z
  fromColumn: Done
  toColumn: In Progress
  author: Codex
- type: moved
  date: 2026-10-28T18:18:55.951Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:48.247Z
  column: Done
  board: configuration
  author: Codex
- type: removed
  date: 2026-10-28T20:39:48.513Z
  fromColumn: Done
  author: Codex
