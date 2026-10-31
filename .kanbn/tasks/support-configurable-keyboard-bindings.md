---
assigned: Codex
created: 2026-10-29T02:41:59.612Z
started: 2026-10-29T02:41:59.612Z
updated: 2026-10-29T02:58:23.631Z
completed: 2026-10-29T02:58:23.631Z
---

# Support configurable keyboard bindings

Add a keybindings action-to-key map to JSON/YAML Kanitor configuration. Preserve current defaults, allow per-action replacement and disabling with [], validate key names and conflicting assignments, and reload with each project effective settings. Apply bindings throughout tables, headers, squares, menus, details/help and project navigation without stealing printable text from editors. Update on-screen help/hints, annotated YAML defaults and agent/user configuration guidance. Verify defaults, remapping, conflicts, disabling, live reload/inheritance, text input and real terminal key input.

## Comments

- author: Codex
  date: 2026-10-29T02:58:23.352Z
  Added top-level keybindings in JSON/YAML with all current shortcuts as defaults, per-action replacement/disable, named keys and modifiers, and terminal-alias conflict validation. Bindings apply to tables/headers, squares, menus, details/help and project views; text input keeps standard editing and literal characters. Effective settings reload live per project, with dynamic Help/footer hints. YAML initialization includes defaults and examples; README and agent guidance document all actions. Verification: make check passed 245 Python tests and both JavaScript bridges; real PTY passed remapped activation/back, Ctrl+F menu, F1/F2, live updates, invalid-conflict retention and clean exit. Initializer and source/wheel builds passed, with packaged sources verified.

## History

- type: created
  date: 2026-10-29T02:41:59.612Z
  column: In Progress
  board: configuration
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-29T02:58:23.631Z
  fromColumn: In Progress
  toColumn: Done
  board: configuration
  author: Codex
