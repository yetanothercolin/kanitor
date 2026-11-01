---
assigned: Codex
created: 2026-10-31T20:44:16.779Z
started: 2026-10-31T20:44:16.779Z
updated: 2026-10-31T20:56:16.306Z
completed: 2026-10-31T20:51:06.815Z
---

# Add independent pane resizing mode

Add configurable resize-mode toggle (r by default; manual refresh R) in Projects, Boards, and Tasks. Draw focusable dividers; Tab/Shift+Tab cycles them, Up/Down moves only that divider. Support left-button click-and-drag with live rendering, release-time persistence and cancellation on keys, terminal resize and new clicks. Keep other dividers fixed, respect minimum heights (Main/Activity five rows; Preview three), default lower panes to eight rows and let the main pane fill remaining space. Persist positions locally per view/visible panes and clamp temporarily on terminal shrink. Preserve list selection and inert previews. Acceptance: regression coverage for keyboard and drag geometry, bounds, persistence, routing, preview clipping/empty states, mouse decoding and terminal mode cleanup; native terminal smokes and make check pass.

## History

- type: created
  date: 2026-10-31T20:44:16.779Z
  column: In Progress
  board: explorer
  fromProgress: 0
  toProgress: 0
  author: Colin
- type: moved
  date: 2026-10-31T20:51:06.815Z
  fromColumn: In Progress
  toColumn: Done
  board: explorer
  author: Colin
- type: moved
  date: 2026-10-31T20:52:23.935Z
  fromColumn: Done
  toColumn: In Progress
  board: explorer
  author: Colin
- type: moved
  date: 2026-10-31T20:56:16.306Z
  fromColumn: In Progress
  toColumn: Done
  board: explorer
  author: Colin
