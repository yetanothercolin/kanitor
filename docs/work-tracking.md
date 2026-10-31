# Work recording

Kanitor records producer-declared work independently of the viewer. A work
session is not proof of activity, verification, or task completion. No worker
identity, activity category, model, or framework is required or inferred.
Recording never edits kanbn cards, statuses, assignments, history, or dates.

This alpha has been tested on macOS with Python 3.14. Python 3.11–3.13 and Linux
may work but have not been tested. Use uv for installation. The CLI/library use JSON
Schema validation; the MCP SDK is an optional extra:

```sh
uv sync --extra mcp
uv run kanitor work --help
uv run kanitor mcp --help
# Editable command installation, including MCP:
uv tool install --reinstall --editable '.[mcp]'
```

The Boards view and native subject resolution require Node/kanbn. Generic work
recording does not require either, or the MCP SDK. The stdio server is launched by an MCP host as
`kanitor mcp`; no daemon, sampler, viewer, or host configuration is installed.

MCP servers keep Python modules loaded for their lifetime. After changing or
updating Kanitor code, reconnect/restart the server in its host to load that
code. Editable installation changes apply to new processes. Configuration edits
are read on each operation and do not require reconnection. If an agent rejects
a current configuration option while a fresh CLI accepts it, check for an older
MCP process or a different installation. Refresh dependencies with the install
command above when needed, then reconnect the server.

## Read recorded work

Use the CLI or MCP read operation to query sessions and original events:

```sh
uv run kanitor work read --workspace /path/to/project
uv run kanitor work read --workspace /path/to/project --input - <<'JSON'
{"view":"sessions"}
JSON
```

Activity shows live elapsed time for the latest open session linked to a task.
Task Squares use linked work events to indicate recent or possibly stale activity.

## Shared operations

CLI calls use `kanitor work OPERATION --workspace ROOT --input FILE|-`.
`--input -` reads JSON from stdin; read operations can omit input for `{}`.
The CLI resolves relative workspace paths locally. MCP tools always require an
explicit absolute `workspace` in their arguments; other fields are identical.
Results are JSON, errors are `{"error":{"code":...,"message":...}}`, and CLI
errors exit with status 1. MCP errors set `isError` and include the same object
in structured content. MCP stdout contains protocol messages only.

| CLI operation | MCP tool | Required operation fields, in addition to mutation request IDs |
| --- | --- | --- |
| capabilities | work_capabilities | None |
| begin | work_begin | label; optional subject and metadata |
| transition | work_transition | session_id, label; optional metadata and note |
| span-begin | work_span_begin | session_id, label; optional parent_span_id and metadata |
| span-end | work_span_end | span_id; optional outcome and evidence |
| span-record | work_span_record | session_id, label, reported_start, reported_end; optional parent_span_id, measured_duration_ms, clock, metadata, outcome, evidence |
| note | work_note | session_id, text; optional span_id and metadata |
| end | work_end | session_id; optional outcome and evidence |
| amend | work_amend | target, expected_revision, correction, reason |
| read | work_read | Optional session_id, subject, view, after_seq, as_of_seq, limit |

The CLI-only `recover` maintenance operation also takes `request_id` and `reason`.

Run capabilities to discover exact schemas and local requirements. The
versioned schema bundle ships as `kanitor/work/schema-v1.json`. Its operation
schemas describe CLI payloads; MCP adds `workspace` as a required input field.

Every mutation requires a caller-generated, nonempty `request_id`. Use a new
ID for a new operation, and retain the same ID and exact arguments for a retry.
Object key order does not matter. IDs are unique across operations within a
workspace. A retry returns the original receipt even if work subsequently
ended, configuration changed, or the subject disappeared. Changing a payload
while reusing its ID is a conflict. Event/session/span/phase/note IDs are UUIDs.

Receipts contain `event_id`, `request_id`, `seq`, `session_id`, `recorded_at`,
`revision`, and resulting lifecycle `state`, plus the created entity ID when
applicable. A span receipt's state describes the span. `revision` always refers
to the entire session, including its spans, notes, and amendments.

## Record a session

```sh
kanitor work begin --workspace /path/to/project --input - <<'JSON'
{
  "request_id": "session-request-001",
  "label": "Adjust inventory spacing",
  "subject": {"provider": "kanbn", "ref": "adjust-inventory-spacing"},
  "metadata": {"AGENT": "!A", "SCOPE": "polish"}
}
JSON
```

Replace the example request ID. Reuse the returned session ID in subsequent
payloads; it is not the request ID:

```json
{"request_id":"phase-request-001","session_id":"<returned UUID>","label":"changing","metadata":{"ACTIVITY":"changing"}}
```

A transition ends the preceding phase and begins the new phase at one timestamp.
Time before the first phase is unclassified. Labels have no built-in vocabulary.
Operations have independent timelines: a build may overlap investigation or
another test. A parent span cannot close with open children; a session cannot
close with open spans. Ending a session closes its current phase and does not
complete its subject. Notes may be appended to finished sessions. Completed
operations may also be recorded retrospectively after session closure.

Metadata is a JSON object. Keys are exact and case-sensitive, including literal
dots. Unknown fields, arrays, objects, booleans, and null values are retained.
Phase/span effective context inherits session metadata; nested spans inherit
their parent's context, with child keys overriding it. Local metadata schemas
validate each record's own metadata, not that merged reporting context.

## Local requirements and subjects

Add `workTracking` to the workspace's `.kanitor.json`, `.kanitor.yml`, or
`.kanitor.yaml`, preserving table rules. All formats use the same validation;
JSON takes precedence, then YML, then YAML. `kanitor --init-yml` creates an
annotated default configuration when none exists. Work recording, capabilities,
and Task Squares work reads use the selected file.
Declared projects without a local Kanitor config inherit their workspace's work
settings, including metadata schemas and evidence requirements.
An explicit project config replaces this fallback as a whole.
Only readable ancestor files explicitly declaring the project can supply work
settings. Unreadable/unrelated ancestors are skipped; without an applicable
declaration, built-in defaults apply. Local file errors and invalid recording
rules in an applicable decoded ancestor remain errors.
Recording and capabilities validate `workTracking` independently of all TUI
settings: unknown top-level display options and invalid columns/keybindings do
not block recording.
Metadata schemas and outcome/evidence rules remain enforced. The selected
configuration must still parse as a YAML/JSON object, and recording rules must
be valid; Kanitor does not silently substitute defaults for unreadable policy.
The TUI retains its own strict validation and reports its view errors normally.
For example, in JSON:

```json
{
  "workTracking": {
    "metadataSchemas": {
      "session": {
        "type": "object",
        "properties": {"AGENT": {"type": "string", "minLength": 1}},
        "required": ["AGENT"],
        "additionalProperties": true
      },
      "phase": {
        "type": "object",
        "properties": {"ACTIVITY": {"enum": ["investigating", "changing", "building", "verifying", "reporting"]}},
        "required": ["ACTIVITY"]
      }
    },
    "outcomes": {
      "verified": {"label": "Producer reports verification", "requiresEvidence": true}
    }
  }
}
```

Use JSON Schema Draft 2020-12, with local fragment references only; no remote
schemas are fetched. Session, phase, span, and note schemas are optional.
Requirements apply to newly supplied or amended metadata. Historical records
remain readable and receive compatibility warnings when requirements change.
Known outcomes may require nonempty evidence; unconfigured outcome values are
retained. Outcomes do not change lifecycle states or prove acceptance.

Subjects are optional `{provider, ref}` pairs scoped by workspace. A kanbn
reference is an exact task ID, independent of board. Native read APIs resolve
active and archived cards, including custom folders. New kanbn associations
must resolve; other providers are opaque and marked unverified. Missing or
unavailable historical subjects retain their records and show a warning.

Card edits never alter recorded session metadata. After a task rename, rebind
individual sessions with an audited session-subject amendment. The original
reference remains in `original_subject` and raw events. Reads filter on the
current effective subject. There are no automatic rename guesses or global
subject aliases.

## Queries and timing

`read` defaults to raw events ordered by `seq`, with 100 items per page (maximum
1,000). Set `view` to `sessions` for derived summaries ordered by `created_seq`.
Use returned `next_after_seq` as `after_seq`. Carry the returned `as_of_seq`
through subsequent pages to freeze the snapshot. Without it, each request sees
the latest complete prefix. Subject and session filters work with both views.

Summaries include phases, spans, notes, amendments, metadata, outcomes, subject
resolution, and timing warnings. They report `confirmed_session_elapsed_ms`,
`confirmed_phase_ms`, and `confirmed_unclassified_ms` separately. Span durations
are never added to phase totals. Concurrent sessions are not unique worker-hours;
this release does not produce aggregate productivity scores or grouped reports.

Server timestamps are UTC and measure acceptance of declarations. For recorded
operations, `reported_start` and `reported_end` must include a UTC offset. An
optional nonnegative `measured_duration_ms` and `clock` object preserve a
producer's measurement and claimed provenance. These remain producer-reported.
Both timestamp and reported durations, plus their difference, remain inspectable.

Open/interrupted intervals with unknown ends have null duration; elapsed age
is not credited. Negative timestamp intervals remain unresolved with clock
warnings. Retrospective spans outside their session window are allowed, flagged,
and kept separate from session/phase totals. No inconsistent timing is silently
clamped or converted into an observed measurement.

## Amendments and interruption

```json
{
  "request_id": "correction-request-001",
  "target": {"kind": "phase", "id": "<phase UUID>"},
  "expected_revision": 7,
  "reason": "The transition was recorded late",
  "correction": {"started_at": "2026-10-23T16:01:00Z"}
}
```

Use the latest session revision; stale revisions reject without committing an
event. Every correction is a new event and preserves its reason and original
values. Permitted fields depend on the target:

| Target kind | Correctable fields |
| --- | --- |
| session | label, metadata, subject (or null), outcome, evidence, started_at, ended_at |
| span | label, metadata, outcome, evidence, started_at, ended_at, an existing measured_duration_ms |
| phase | label, metadata, started_at, ended_at |
| note | text, metadata |

`event` can also identify an original phase-transition or note event. Changing
a phase boundary moves both adjacent phase endpoints. Changing the last phase
end also changes the session end, and vice versa. The resulting corrected
timeline must remain ordered and phases must stay within the session. Nested
span corrections must respect their parent's known bounds. Open work cannot
be closed through a timing correction; use the normal end operation.

`{"state":"interrupted"}` is a separate correction for an open session/span.
It atomically interrupts its open descendants with unknown ends. It does not
invent a stop time, discard previous confirmed phases, or reopen finished work.
An interrupted interval can later receive a producer-corrected known end.
Clock provenance cannot be overwritten, nor can a declaration gain an alleged
independent measurement through amendment.

## Durability and recovery

Authoritative events live in `.kanitor/work/events.jsonl`. All writers use an
adjacent stable interprocess lock. Sequence allocation, duplicate detection,
state validation, and append occur while locked. Successful receipts follow
file sync; new storage and recovery replacements also sync their directories.
Each event includes a schema version and chained hash to detect accidental
modification. This is an integrity check, not authentication of producer claims.
In-memory indexes are disposable and verified against file bytes.

Local macOS filesystems have been tested. Linux filesystem locking and durability
have not been tested. Distributed writers, NFS locking,
and merging separately edited log copies are not supported. The log is ordinary
workspace data: copy or version it deliberately. Lock and recovery files should
not be manually replaced while writers run.

An incomplete final record is excluded from reads with a warning. New writes
stop until explicit recovery; existing acknowledged request retries still work.
Middle corruption and incompatible event versions are hard errors, not skipped
records. Raw export remains available despite invalid current display/config
rules, with warnings; new writes fail those rules.

```sh
kanitor work recover --workspace /path/to/project --input - <<'JSON'
{"request_id":"repair-request-001","reason":"Producer crashed during append"}
JSON
```

Recovery preserves original bytes under `.kanitor/work/recovery/`, writes a
durable manifest, and removes only an incomplete final suffix while locked. Its
receipt identifies the backup and manifest. It is restart-safe and retryable
with the same request ID, including after replacement but before acknowledgement.
Recovery never repairs middle corruption automatically.

## Verification and overhead

Run `make check` for the real stdio protocol
tests as well as CLI, storage, lifecycle, concurrency, fault-injection, native
subject, and Task Squares regression checks. This target installs the MCP extra.
When running unittest directly without that extra, MCP-specific tests are
explicitly skipped. Run the checkout-only benchmark with:

```sh
uv run python dev/benchmark_work.py --events 1000 --samples 10
```

It measures cold CLI and warm library/MCP recording separately on temporary
workspaces. It does not instrument shipped modules or write to your project.
Read-only background snapshot tests also cover live updates, complete prefixes,
recovery warnings, and stale-data preservation for Task Squares.
