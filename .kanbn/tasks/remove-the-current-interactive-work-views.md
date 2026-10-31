---
assigned: Codex
created: 2026-10-28T20:11:28.351Z
started: 2026-10-28T20:11:28.351Z
updated: 2026-10-28T20:20:24.552Z
completed: 2026-10-28T20:20:24.552Z
---

# Remove the current interactive Work views

Remove all current Work TUI screens, modes, navigation, shortcuts, launch flags, work-only browsing and view instrumentation. Preserve work logs, CLI/MCP recording and read APIs, inherited work validation, and background work data used by Task Squares. Remove obsolete view docs/tests, retain compatibility with existing workTracking config, and validate remaining explorer and recorder behavior.

## Comments

- author: Codex
  date: 2026-10-28T20:20:24.308Z
  Removed the Work UI/model modules and view-only timeline/audit formatting, Work tabs/mode and w/W shortcuts, --work launch/snapshot handling, work-only project browsing, task Work summaries, and Work tracing hooks. Task Squares now use WorkReader directly; recorder/MCP/storage/subject resolution remain intact. Existing sessionColumns configs are still accepted for compatibility, but generated YAML and current guidance omit view settings. Updated docs/examples/AGENTS and replaced obsolete view tests with removal/recording preservation coverage. Verification: make check passes 209 tests and both JS syntax checks; wheel/sdist build succeeds; isolated package excludes Work view modules and records/reads work without Node; actual PTY navigates Projects→boards→tasks→details, ignores removed shortcuts, exits cleanly and writes no workspace files. Tracking validates.

## History

- type: created
  date: 2026-10-28T20:11:28.351Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T20:20:24.552Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:54.252Z
  column: Done
  board: work
  author: Codex
- type: removed
  date: 2026-10-28T20:39:54.531Z
  fromColumn: Done
  author: Codex
