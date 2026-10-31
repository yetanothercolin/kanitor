# Scroll diagnostics

For work-recording overhead, use `uv run python dev/benchmark_work.py`.
It measures cold CLI, warm library, and warm MCP calls using temporary logs,
with an empty and a 1,000-event fixture. Install the MCP extra for protocol
measurements. This benchmark is excluded from distributions.

Run from the checkout using the same terminal and workspace where scrolling
rebounds:

```sh
uv run python dev/trace_scroll.py -- --root /path/to/project
```

Normal Kanitor options follow `--`; omit `--root` to discover the current
workspace. The development launcher runs the actual application in a PTY and
installs tracing subclasses/wrappers only in its child process. No diagnostic
imports, flags, or logging branches are added to `kanitor/`. The dev launcher
and its instrumentation are excluded from built distributions.
Project-list workspaces are supported too: traces identify the Projects list
and the active project's root while drilling into its views.

The launcher prints a trace filename under this checkout's ignored `.local/`
directory. Use `--log .local/rebound.jsonl` before `--` to choose a filename.
Logs append, so use a fresh filename for each reproduction.

1. Open the boards list, a board's cards, or card details.
2. Press Home to reach the top.
3. Perform the forceful upward trackpad gesture and wait for it to settle.
4. Repeat in each affected component. Also try the bottom with End and a
   downward gesture.
5. Quit normally (`q` closes details, then `q` again quits).

A JSON summary prints after exit. Analyze it again without a terminal:

```sh
uv run python dev/trace_scroll.py --analyze .local/rebound.jsonl
```

The JSONL records include:

- `terminal_input`: exact input bytes in hex, before ncurses decoding.
- `raw_mouse`: parsed xterm SGR/classic packets, direction, modifiers, and cursor
  coordinates. Non-wheel movement/clicks are also recorded.
- `curses_mouse`: decoded mouse flags and the direction Kanitor sees. The
  `decoder` field distinguishes native ncurses from the SGR adapter.
- `wheel`: requested delta and state before/after, including component,
  selected index, viewport, top/bottom bounds, and redraw state.
- `key` / `mouse_handled`: state transitions, including mouse reports consumed
  while draining a wheel burst. `cancelled_wheel` marks remaining momentum
  ignored after explicit keyboard/click navigation; the summary counts these.
- `render`: frame timing and scrollbar thumb positions, with state before/after
  layout/clamping. No screen contents or descriptions are logged.
- Session details: terminal, Python/ncurses versions, actual mouse bit constants,
  dimensions, and reader revisions.

The terminal protocol exposes discrete wheel reports, not physical gesture
phases. `burst` groups input separated by at most 150ms; it is a diagnostic
estimate. `boundary_reversals` in the summary identifies an inward scroll less
than 150ms after an outward event at a boundary. This can also be an intentional
direction change; it is evidence to inspect, not proof of a bug.

Compare `raw_mouse` and `curses_mouse` around a reversal. If raw input reverses,
the change arrives before Kanitor. If only decoded direction reverses, inspect
ncurses interpretation. If both remain outward while positions or scrollbar
thumbs move inward, inspect app state and rendering. App-side logging adds
overhead, so timing is diagnostic rather than a benchmark.

A physical Ghostty trace confirmed the cause of the upward rebound: 689
wheel-up reports, 8 horizontal-left reports, and no wheel-down reports became
687 decoded up events and 7 decoded down events in legacy macOS ncurses. The
horizontal axis was aliased to `REPORT_MOUSE_POSITION`, the same bit used for
wheel-down on that ABI. A synthetic motion probe exposed the same ambiguity.

Runtimes without `BUTTON5_PRESSED` now request SGR mouse packets and decode
them before ncurses loses axis information. Horizontal gestures and motion are
ignored; true wheel-down still responds immediately. Keyboard decoding stays
with ncurses. The button-code sequence from the physical trace is preserved in
`tests/fixtures/trackpad-up.json` for regression coverage; it contains no task
data. Diagnostic logging remains entirely in `dev/`.

A subsequent profile captured Down-arrow presses being counteracted by the
remaining upward momentum: the terminal delivered 552 upward reports and no
downward reports, with raw-to-decoded delays below 7ms. Keyboard input and
clicks now cancel the ongoing wheel direction. Its tail stays ignored until a
200ms quiet gap or a genuine opposite wheel report starts fresh navigation.
Terminal wheel protocols expose no physical gesture phases, so the quiet gap
is inferred from arrival times. The sanitized timed sequence is preserved in
`tests/fixtures/trackpad-keyboard-interruption.json`.
