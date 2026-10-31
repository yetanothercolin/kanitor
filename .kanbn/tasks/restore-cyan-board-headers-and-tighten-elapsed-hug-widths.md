---
assigned: Codex
created: 2026-10-28T20:03:26.828Z
started: 2026-10-28T20:03:26.828Z
updated: 2026-10-28T20:05:43.641Z
completed: 2026-10-28T20:05:43.641Z
---

# Restore cyan board headers and tighten elapsed hug widths

Restore Boards table column headings to the cyan style used by other tables. Measure Work duration hug widths from the displayed content without unused leading day/hour slots, preserving right-aligned units, explicit width constraints and stable widths across matching rows. Regress the minutes-only case from the screenshot and mixed-unit durations.

## Comments

- author: Codex
  date: 2026-10-28T20:05:43.385Z
  Boards column headers restored to bold cyan. Duration hug sizing now ignores unused leading day/hour slots while right-aligned rendering retains stable unit positions. Minutes/seconds-only Elapsed columns now hug to 7 cells rather than reserving 14. Measuring all matching rows preserves widths while scrolling and updates after filtering; bounded widths and mixed-day alignment remain supported. Work docs and agent guide updated. Verification: make check passes all 231 tests and both JavaScript syntax checks.

## History

- type: created
  date: 2026-10-28T20:03:26.828Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T20:05:43.641Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:50.907Z
  column: Done
  board: explorer
  author: Codex
- type: removed
  date: 2026-10-28T20:39:51.155Z
  fromColumn: Done
  author: Codex
