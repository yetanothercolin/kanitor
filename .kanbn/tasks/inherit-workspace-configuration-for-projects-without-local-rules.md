---
assigned: Codex
created: 2026-10-28T18:40:13.837Z
started: 2026-10-28T18:40:13.837Z
updated: 2026-10-28T18:46:08.553Z
completed: 2026-10-28T18:46:08.553Z
---

# Inherit workspace configuration for projects without local rules

Use the overall Kanitor workspace configuration for a declared project when its own config file is missing. Preserve explicit local configurations and per-board task overrides, avoid inheriting the project roster, update live on parent/local config changes, and keep snapshot/work configuration consistent. Document and validate fallback across JSON/YAML and project contexts.

## Comments

- author: Codex
  date: 2026-10-28T18:46:08.289Z
  Implemented workspace fallback for declared projects with no local JSON/YML/YAML config. Uses nearest ancestor explicitly listing that project, strips its project roster, and preserves explicit local configs as whole-file overrides. Boards without per-board task overrides use effective global task columns. Native and work readers follow inherited config edits and local creation/deletion; direct child launches, CLI snapshots, and work recording use the same rules. Updated README, agent guide, YAML initializer comments, and work docs. Verification: make check passes 214 tests plus both JavaScript syntax checks; tracking validates.

## History

- type: created
  date: 2026-10-28T18:40:13.837Z
  column: In Progress
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-28T18:46:08.553Z
  fromColumn: In Progress
  toColumn: Done
  author: Codex
- type: added
  date: 2026-10-28T20:39:48.674Z
  column: Done
  board: configuration
  author: Codex
- type: removed
  date: 2026-10-28T20:39:48.958Z
  fromColumn: Done
  author: Codex
