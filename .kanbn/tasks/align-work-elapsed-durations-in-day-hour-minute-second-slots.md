---
assigned: Codex
created: 2026-10-28T19:55:28.521Z
started: 2026-10-28T19:55:28.521Z
updated: 2026-10-28T19:59:03.591Z
completed: 2026-10-28T19:59:03.591Z
---

# Align Work elapsed durations in day hour minute second slots

Display Work duration columns with aligned days, hours, minutes and seconds. Hide only leading unused units, show zero units after the first significant one, render known durations below one second as <1s, and preserve unknown/unresolved duration semantics. Keep numeric filters and confirmed timing unchanged; validate day-width alignment and narrow columns.

## Comments

- author: Codex
  date: 2026-10-28T19:59:03.343Z
  Work duration columns now show stable right-aligned day/hour/minute/second slots, matching all supplied examples. Leading unused units are blank; zero units after a larger unit remain shown. Known durations under one second (including zero) show <1s; unknown durations retain an em dash. Multi-digit day counts align across rows; narrow columns retain readable short values. Raw millisecond values, typed filters, and compact preview/timeline formatting are preserved. Updated work docs and agent guide. Verification: make check passes 230 tests and both JavaScript syntax checks; kanbn tracking validates.

## History

- type: created
  date: 2026-10-28T19:55:28.521Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T19:59:03.591Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:53.844Z
  column: Done
  board: work
  author: Codex
- type: removed
  date: 2026-10-28T20:39:54.091Z
  fromColumn: Done
  author: Codex
