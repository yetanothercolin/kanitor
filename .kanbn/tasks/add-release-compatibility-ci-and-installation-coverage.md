---
assigned: Codex
created: 2026-10-31T04:48:22.689Z
---

# Add release compatibility CI and installation coverage

Public-release assessment found no automated CI matrix despite Python 3.11+ and macOS/Linux support claims. Add checks for minimum/current Python and supported OSes, install kanbn/Node and MCP extras for native/protocol integration tests, and validate built-wheel installation from outside the checkout. Ensure integration suites do not silently skip their required tools. The current local suite passes on macOS/Python 3.14.

## Comments

- author: Codex
  date: 2026-10-31T04:56:16.905Z
  Deferred for the alpha/preview release at the user request. Current release documentation and capabilities will state macOS/Python 3.14 is tested and older Python/Linux are untested possibilities. This CI matrix task remains Backlog; documentation changes do not complete its acceptance criteria.

## History

- type: created
  date: 2026-10-31T04:48:22.689Z
  column: Backlog
  fromProgress: 0
  toProgress: 0
  author: Codex
