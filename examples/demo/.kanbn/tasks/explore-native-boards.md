---
assigned: Alex
tags:
  - navigation
  - tui
---

# Explore native boards

Show native boards in their configured order. Select a board and press Right
or Enter to see its cards in the main pane.

### Workflow

Activate the Status header to filter by native column. Use Right to inspect a
card and Left to return to its board. A card's board column is authoritative
even when an old completed timestamp remains in metadata.

## Sub-tasks

- [x] Discover all boards with the native API
- [x] Show board completion and active counts
- [ ] Verify navigation in a small terminal

## Comments

- author: Alex
  date: 2026-10-22T16:00:00Z
  Keep board-specific settings; do not assume that every board uses Done.

## History

- type: created
  date: 2026-10-21T12:00:00Z
  column: Todo
- type: moved
  date: 2026-10-22T15:00:00Z
  fromColumn: Todo
  toColumn: In Progress
