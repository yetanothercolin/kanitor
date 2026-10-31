---
assigned: Codex
created: 2026-10-31T04:48:22.539Z
updated: 2026-10-31T04:57:34.717Z
started: 2026-10-31T04:52:53.989Z
completed: 2026-10-31T04:57:34.717Z
---

# Isolate unlisted workspaces from invalid ancestor configs

Assessment reproduced: parent .kanitor.yml with projects: [other] and columns: [] causes load_document on an unlisted child to fail, despite the child not inheriting settings. A malformed unrelated ancestor config also blocks work_begin. Establish applicability before validating inherited view rules, define safe handling for unreadable unrelated ancestors without bypassing explicit recording policy, and add viewer/CLI/MCP regression coverage for unlisted versus declared children and local overrides.

## Comments

- author: Codex
  date: 2026-10-31T04:52:54.140Z
  User authorized the fix and alpha release preparation: document macOS/Python 3.14 as the tested environment, describe earlier Python/Linux as untested possibilities, add the kanbn install command and package README metadata. CI matrix is deferred for this alpha. Ancestor lookup will require a readable declaration listing this workspace before validating inherited settings; unreadable unrelated files will be skipped. Local configuration and applicable decoded work-policy validation remain strict.
- author: Codex
  date: 2026-10-31T04:57:34.460Z
  Completed all four alpha-readiness changes. Ancestor discovery ignores unreadable/unrelated configs, validates applicable decoded rules, and preserves strict local-file validation; readable selected work policy remains enforced. Added JSON/YML/YAML, CLI and real MCP regressions. Public docs and capabilities now distinguish macOS/Python 3.14 as tested from untested Linux/earlier Python. README includes npm installation for kanbn. Package metadata includes README and Alpha classifier. Verification: all 285 tests and both JS checks passed; wheel/SDist builds passed; README long description verified in both, exact README present in SDist; native demo reads succeeded under both invalid-view and malformed unrelated ancestors. CI remains a deferred backlog item per alpha scope.

## History

- type: created
  date: 2026-10-31T04:48:22.539Z
  column: Backlog
  board: configuration
  fromProgress: 0
  toProgress: 0
  author: Codex
- type: moved
  date: 2026-10-31T04:52:53.989Z
  fromColumn: Backlog
  toColumn: In Progress
  board: configuration
  author: Codex
- type: moved
  date: 2026-10-31T04:57:34.717Z
  fromColumn: In Progress
  toColumn: Done
  board: configuration
  author: Codex
