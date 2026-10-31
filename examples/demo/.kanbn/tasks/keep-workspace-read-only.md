---
assigned: Morgan
tags:
  - integration
---

# Keep workspace read only

Kanitor reads boards and task files and follows external edits. All writes stay
in kanbn. No settings or caches are written to the workspace.

## Sub-tasks

- [x] Disable actions in the native reader
- [x] Avoid mutation APIs
- [x] Compare file contents and modification times before and after reads
