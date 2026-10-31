---
assigned: Codex
created: 2026-10-28T21:40:08.242Z
started: 2026-10-28T21:40:08.242Z
updated: 2026-10-28T23:06:23.501Z
completed: 2026-10-28T23:06:23.501Z
---

# Add cell navigation typed filters and column sorting

Implement shared cell navigation and column context menus across Tasks, Boards and Projects.

Acceptance criteria:
- Arrows navigate all cells and headers; Enter/Space activates; Escape returns; Tab and Right do not activate. Task Squares retain individual selection, preview, wrapping and adjacent-column navigation.
- Scalar columns support filterable, sortable and inferred/explicit enum|string|date filterType. Provide raw-value Only/Exclude actions, enum checkboxes, string search and local calendar date filtering with validated drafts.
- Defaults enable Status enum, Updated date/sort, Assigned enum/sort and Description name/body search. Only active filters show a chevron.
- Stable typed runtime sorting keeps missing values last; boards default to computed updated descending; reset restores each table default without writing kanbn data.
- Upward wheel gestures pause at the first data row and require a fresh gesture after 200 ms quiet to enter headers; reversal responds immediately.
- Preserve selection and viewport anchors across live refresh, filtering, sorting and resizing. Update help, YAML examples, agent guidance and developer tracing.

Verification: make check passed 234 Python tests and both JavaScript bridge syntax checks. Native reader tests verify board recency and read-only behavior; a real PTY verified menus, Right navigation, SGR right-click, details and Escape. uv build --offline produced matching source/wheel artifacts with no developer instrumentation or removed Work views.

## Comments

- author: Codex
  date: 2026-10-28T23:06:23.301Z
  Implemented shared cell/header navigation and runtime column menus in Projects, Boards and Tasks; enum/string/calendar-date filters and raw Only/Exclude actions; configurable sortable/filterType rules; typed stable sorting and computed board recency; fresh-gesture wheel pause beneath headers; preserved Task Squares previews, wrapping and adjacent-column navigation. Updated README, agent guide, YAML template and dev-only tracing. Verification: make check passed all 235 Python tests plus both JavaScript bridge checks; real PTY verified header navigation, non-activating Right, SGR right-click, details, Escape and clean exit. uv build --offline succeeded and final wheel matches source, excluding dev instrumentation and removed Work views. Tracking validation has no errors and only the documented shared-completed-field warning.

## History

- type: created
  date: 2026-10-28T21:40:08.242Z
  column: In Progress
  board: explorer
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T23:06:23.501Z
  fromColumn: In Progress
  toColumn: Done
  board: explorer
  author: Codex
