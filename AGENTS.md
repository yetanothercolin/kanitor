# Workspace workflow

Use **kanbn** to track tasks and **kanitor** to record work in this workspace.
Manage Python dependencies and commands with **uv**.

## Task and work tracking

- Before substantive work, inspect the board with `uv run kanitor --once`.
  Use `kanbn boards --tasks --all` to find existing cards across feature boards.
  Reuse a matching card, or create a scoped card with
  `kanbn add --board <feature-board>`. Keep its
  description and acceptance criteria current. Use `kanbn help <command>` for
  the installed command syntax.
- When a task description contains multiple items to complete, write them as
  a Markdown list rather than packing them into a paragraph. Keep context brief
  and put each deliverable or acceptance criterion in its own list item.
- Move the card to `In Progress` with
  `kanbn move <task-id> --board <feature-board> --column 'In Progress'`
  when starting. Use kanbn commands for task changes so history and dates stay
  consistent; avoid editing managed task metadata by hand.
- Read `uv run kanitor --agent-guide` and
  `uv run kanitor work capabilities --workspace "$PWD"` before recording work.
  Start a work session linked to the exact kanbn task ID, retaining its returned
  `session_id`. Use a new session for a later work period on the same task.
- Record meaningful phase changes with `work transition`, useful decisions,
  blockers, and verification with `work note`, and independent operations with
  spans when useful. Record actual observations; do not invent historical timing
  or infer a worker identity from git configuration or a card's assignment.
- Give each mutation a unique `request_id`. Reuse an ID only when retrying the
  identical operation and payload. Never edit the JSONL log directly.
- At completion, end the session with the actual outcome and concrete evidence
  (checks run and their results, relevant files, or an explanation when checks
  do not apply). Move the card to `Done` only after its acceptance criteria are
  met, targeting its feature board explicitly. Ending a session does not move
  its card automatically.
- If work stops unfinished, record the remaining work or blocker on the card
  and in a work note. End the work period with an accurate outcome, or explicitly
  mark an interrupted session through an amendment if its end is unknown. Keep
  unfinished cards out of `Done`.

## Feature boards

Boards represent stable, broad feature groups. Use columns for workflow status;
do not create boards for individual tasks, agents, sessions, or releases.

| Board slug | Feature group | Put work here |
| --- | --- | --- |
| `index` | Workflow & Tooling | Repository practices, kanbn usage, developer tooling, and validation infrastructure |
| `configuration` | Workspace & Configuration | Project discovery/watching, config formats and inheritance, custom column rules and sizing |
| `explorer` | Explorer UI | General board/task browsing, navigation, breadcrumbs, headers, and table presentation |
| `task-squares` | Task Squares | Square classification, ordering, wrapping, selection, previews, and task entry |
| `work` | Work Tracking | Work recording, sessions/activities, timing, and CLI/MCP integration |

- Workflow & Tooling (`index`) is local-only. Keep `.kanbn/index.md` and every
  card on that board ignored by Git while preserving them for kanbn. Boards
  share the tasks folder, so add each new `index` card's exact file path to
  the Workflow & Tooling block in `.gitignore` as part of creating it. Update
  those entries when deliberately reclassifying a card. Other feature boards
  and their cards remain shareable.
- After cloning, the ignored main board may be absent. Before inspecting or
  changing tasks, initialize it with `kanbn init --name 'Workflow & Tooling'
  --description 'Local repository workflow and tooling' --column Backlog
  --column Todo --column 'In Progress' --column Done` if `.kanbn/index.md` is
  missing. This leaves the existing shared feature boards intact.
- Give each task one primary feature board. For changes spanning groups, choose
  the main feature being changed and describe the secondary impact on the card.
  Use multiple memberships only when separate workflows are deliberately needed;
  never duplicate every task onto `index` as an overview.
- Reuse these groups before adding another. A new board must cover a broad,
  durable area and its purpose must be added to this table.
- Every board uses `Backlog`, `Todo`, `In Progress`, and `Done`, in that order,
  with `In Progress` started and `Done` completed in the native workflow options.
  The `started` and `completed` dates belong to the task across feature groups;
  reclassification must not restart or recomplete it. The validator's warning
  about boards sharing the `completed` field is expected for this convention.
- Always pass `--board <slug>` when creating or moving cards. `index` is for
  Workflow & Tooling, not a general inbox. Work sessions still link to the exact
  task ID; moving a task between boards does not require a new ID or rewritten log.
- To reclassify an existing card, first add it to the destination in its current
  status with `kanbn move <task-id> --board <destination> --column '<status>'`.
  Then remove only the old membership with
  `kanbn remove <task-id> --board <source> --index --force`. Never delete/recreate
  the task file or use `--all-boards` for reclassification. Preserve lifecycle
  dates, prior history, and the task's actual status, then validate all boards.

Example board creation:

```sh
kanbn init --board <slug> --name '<Feature Group>' --description '<Broad purpose>' \
  --column Backlog --column Todo --column 'In Progress' --column Done
```

Example session start, run from the workspace root:

```sh
uv run kanitor work begin --workspace "$PWD" --input - <<'JSON'
{
  "request_id": "<new unique request ID>",
  "label": "<current work>",
  "subject": {"provider": "kanbn", "ref": "<exact-task-id>"}
}
JSON
```

The native boards and cards live in `.kanbn/`. The durable work log is
`.kanitor/work/events.jsonl`. Preserve both as project tracking data. The
work log, lock, and recovery files are local-only and ignored by Git because
they can contain machine paths and unrelated project details. Keep feature
boards/cards shareable except the local Workflow & Tooling board described above,
and never add real work logs or raw diagnostic traces
to the public repository. Use sanitized fixtures for regression coverage.
Use `uv run kanitor` to browse tasks and
`uv run kanitor work read --workspace "$PWD"` to query recorded work.

## Validation

Run checks appropriate to the change. `make check` runs the Python suite through
uv, including the optional MCP adapter, and checks the JavaScript bridges.
Use `kanbn validate --all-boards` to validate tracking files. Documentation-only
or tracking-only changes do not require the full application suite.
