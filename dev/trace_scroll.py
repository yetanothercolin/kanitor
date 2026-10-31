#!/usr/bin/env python3
"""Checkout-only scroll diagnostics. No hooks are imported by the shipped app."""
import argparse
from collections import Counter
import curses
from datetime import datetime, timezone
import errno
import fcntl
import json
import os
from pathlib import Path
import platform
import pty
import re
import selectors
import signal
import sys
import termios
import time
import tty
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
BURST_GAP = 0.15


class Trace:
    def __init__(self, path, source):
        self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self.source = source

    def emit(self, event, **values):
        record = dict(event=event, source=self.source, pid=os.getpid(),
                      time_ns=time.monotonic_ns(), **values)
        os.write(self.fd, (json.dumps(record, ensure_ascii=True) + '\n').encode())

    def close(self):
        os.close(self.fd)


class MousePackets:
    """Incrementally observe SGR and classic xterm packets, without changing input."""
    def __init__(self):
        self.pending = b''

    def feed(self, data):
        self.pending += data
        events = []
        while self.pending:
            start = self.pending.find(b'\x1b[')
            if start < 0:
                self.pending = b'\x1b' if self.pending.endswith(b'\x1b') else b''
                break
            self.pending = self.pending[start:]
            if len(self.pending) < 3:
                break
            release = False
            if self.pending.startswith(b'\x1b[M'):
                if len(self.pending) < 6:
                    break
                code, x, y = (self.pending[3] - 32, self.pending[4] - 33, self.pending[5] - 33)
                packet, self.pending = self.pending[:6], self.pending[6:]
                protocol = 'x10'
            elif self.pending.startswith(b'\x1b[<'):
                match = re.match(rb'\x1b\[<(\d+);(\d+);(\d+)([Mm])', self.pending)
                if not match:
                    if len(self.pending) < 100 and re.fullmatch(rb'\x1b\[<[0-9;]*', self.pending):
                        break
                    self.pending = self.pending[3:]
                    continue
                code, x, y = int(match[1]), int(match[2]) - 1, int(match[3]) - 1
                release = match[4] == b'm'
                packet, self.pending = self.pending[:match.end()], self.pending[match.end():]
                protocol = 'sgr'
            else:
                self.pending = self.pending[2:]
                continue
            direction = ('up', 'down', 'left', 'right')[code & 3] if code & 64 else None
            events.append(dict(protocol=protocol, code=code, x=x, y=y, release=release,
                               direction=direction, motion=bool(code & 32), shift=bool(code & 4), alt=bool(code & 8),
                               ctrl=bool(code & 16), hex=packet.hex()))
        return events


def app_state(app):
    if getattr(app, 'catalog', None) is not None:
        if app.active:
            return dict(app_state(app.active), project_root=str(app.active.root))
        keys = [row['id'] for row in app.rows()]
        position = keys.index(app.selected_project) if app.selected_project in keys else 0
        maximum = max(0, len(keys) - 1)
        if app.summary_table.multiline:
            position, maximum = app.project_top, app.summary_table.maximum
        component = 'projects'
        top, capacity = app.project_top, app.project_height
        if app.column_menu:
            menu = app.column_menu
            component, position, maximum = 'filter', menu['index'], max(0, len(app.menu_entries()) - 1)
            top, capacity = menu['top'], menu.get('capacity', 1)
        elif app.popup:
            component = 'help'
            position, maximum = app.popup_scroll, app.popup_max
            top, capacity = position, app.popup_height
        return dict(component=component, position=position, maximum=maximum,
                    at_top=position == 0, at_bottom=position == maximum,
                    viewport_top=top, capacity=capacity,
                    board=None, selected_id=app.selected_project,
                    selected_square=app.selected_square,
                    header_selected=app.focus.header, focused_column=app.focus.slot, needs_redraw=app.needs_redraw,
                    reader_revision=app.catalog.revision, app_revision=app.catalog.revision,
                    terminal_size=list(app.screen.getmaxyx()))
    explorer = app.explorer
    rows = explorer.rows
    board_index = next((i for i, b in enumerate(explorer.display_boards) if b['slug'] == explorer.board_slug), 0)
    task_index = next((i for i, c in enumerate(rows) if c['id'] == explorer.selected_id), 0)
    if app.column_menu:
        menu = app.column_menu
        component, position, maximum = 'filter', menu['index'], max(0, len(app.menu_entries()) - 1)
        top, capacity = menu['top'], menu.get('capacity', 1)
    elif app.popup:
        component = 'help' if app.popup == 'help' else 'details'
        position, maximum = app.popup_scroll, app.popup_max
        top, capacity = position, app.popup_height
    elif app.view == 'boards':
        component, position, maximum = 'boards', board_index, max(0, len(explorer.display_boards) - 1)
        top, capacity = app.board_top, app.board_height
        if app.summary_table.multiline:
            position, maximum = top, app.summary_table.maximum
    else:
        component, position, maximum = 'tasks', task_index, max(0, len(rows) - 1)
        top, capacity = app.task_top, app.task_height
    return dict(component=component, position=position, maximum=maximum,
                at_top=position == 0, at_bottom=position == maximum,
                viewport_top=top, capacity=capacity, board=explorer.board_slug,
                selected_id=app.popup[1] if isinstance(app.popup, tuple) and app.popup[0] == 'card' else explorer.selected_id,
                task_index=task_index,
                selected_square=app.selected_square,
                header_selected=app.focus.header, focused_column=app.focus.slot, needs_redraw=app.needs_redraw,
                reader_revision=app.reader.revision, app_revision=app.revision,
                terminal_size=list(app.screen.getmaxyx()))


def traced_app(base, trace):
    """Subclass the real App in the child process; production has no debug branches."""
    class TracedApp(base):
        def setup(self):
            super().setup()
            trace.emit('setup', state=app_state(self))

        def handle(self, key):
            before = app_state(self)
            result = super().handle(key)
            trace.emit('key', key=key, before=before, after=app_state(self), keep_running=result)
            return result

        def mouse(self):
            before = app_state(self)
            super().mouse()
            gesture = self.wheel_gesture
            trace.emit('mouse_handled', before=before, after=app_state(self), wheel=self._wheel_input,
                       cancelled_wheel=bool(self._wheel_input and gesture.cancelled is not None
                                            and gesture.direction == gesture.cancelled))

        def get_mouse(self):
            from kanitor.mouse import WHEEL_DOWN, WHEEL_UP
            try:
                event = super().get_mouse()
            except curses.error as error:
                trace.emit('curses_mouse_error', message=str(error))
                raise
            buttons = event[4]
            up, down = bool(buttons & WHEEL_UP), bool(buttons & WHEEL_DOWN)
            trace.emit('curses_mouse', mouse=list(event),
                       decoder='sgr' if self.mouse_input else 'ncurses',
                       flags=[name for name in dir(curses) if name.startswith(('BUTTON', 'REPORT_MOUSE'))
                              and isinstance(getattr(curses, name), int) and buttons & getattr(curses, name)],
                       direction='both' if up and down else 'up' if up else 'down' if down else None)
            return event

        def scroll_wheel(self, delta):
            before = app_state(self)
            super().scroll_wheel(delta)
            trace.emit('wheel', delta=delta, before=before, after=app_state(self))

        def draw(self):
            before = app_state(self)
            started = time.monotonic_ns()
            super().draw()
            trace.emit('render', before=before, after=app_state(self),
                       duration_ns=time.monotonic_ns() - started, scrollbars=self.scrollbars)
    return TracedApp


def trace_child(log_path, argv):
    sys.path.insert(0, str(REPO))
    from kanitor import ui
    from kanitor import projects_ui
    from kanitor.__main__ import main
    trace = Trace(log_path, 'app')
    trace.emit('app_start', python=sys.version, platform=platform.platform(), argv=argv,
               ncurses=list(curses.ncurses_version),
               wheel_up=ui.WHEEL_UP, wheel_down=ui.WHEEL_DOWN,
               mouse_flags={name: getattr(curses, name) for name in dir(curses)
                            if name.startswith(('BUTTON', 'REPORT_MOUSE'))})
    try:
        app_class = traced_app(ui.App, trace)
        with patch.object(ui, 'App', app_class), \
                patch.object(projects_ui, 'App', app_class), \
                patch.object(projects_ui, 'ProjectsApp', traced_app(projects_ui.ProjectsApp, trace)):
            result = main(argv)
        trace.emit('app_exit', exit_code=result)
        return result
    except BaseException as error:
        trace.emit('app_exception', type=type(error).__name__, message=str(error))
        raise
    finally:
        trace.close()


def write_all(fd, data):
    while data:
        size = os.write(fd, data)
        data = data[size:]


def run_proxy(log_path, argv):
    """Keep the real terminal's raw input visible before ncurses decodes it."""
    trace = Trace(log_path, 'terminal')
    trace.emit('session_start', schema=1, utc=datetime.now(timezone.utc).isoformat(),
               terminal={name: os.environ.get(name) for name in
                         ('TERM', 'TERM_PROGRAM', 'TERM_PROGRAM_VERSION', 'COLORTERM', 'LANG')},
               argv=argv, burst_gap_ms=BURST_GAP * 1000)
    print(f'Scroll trace: {log_path}\nReproduce the rebound, then quit normally with q.', flush=True)
    original_terminal = termios.tcgetattr(sys.stdin.fileno())
    child, master = pty.fork()
    if child == 0:
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()),
                                '--trace-child', str(log_path), '--'] + argv)

    def resize(*_):
        size = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, b'\0' * 8)
        fcntl.ioctl(master, termios.TIOCSWINSZ, size)
        trace.emit('resize', winsize_hex=size.hex())

    previous_resize = signal.signal(signal.SIGWINCH, resize)

    def forward_signal(signum, _):
        trace.emit('signal', signal=signum)
        try:
            os.kill(child, signum)
        except ProcessLookupError:
            pass

    previous_signals = {signum: signal.signal(signum, forward_signal)
                        for signum in (signal.SIGTERM, signal.SIGHUP)}
    parser = MousePackets()
    burst, last_wheel = 0, None
    selector = selectors.DefaultSelector()
    reaped = False
    try:
        resize()
        tty.setraw(sys.stdin.fileno())
        selector.register(sys.stdin, selectors.EVENT_READ, 'input')
        selector.register(master, selectors.EVENT_READ, 'output')
        finished = False
        while not finished:
            for key, _ in selector.select():
                try:
                    data = os.read(key.fd, 4096)
                except OSError as error:
                    if key.data == 'output' and error.errno == errno.EIO:
                        finished = True
                        break
                    raise
                if not data:
                    finished = True
                    break
                if key.data == 'output':
                    write_all(sys.stdout.fileno(), data)
                else:
                    trace.emit('terminal_input', hex=data.hex())
                    for event in parser.feed(data):
                        if event['direction']:
                            now = time.monotonic()
                            gap = now - last_wheel if last_wheel is not None else None
                            if gap is None or gap > BURST_GAP:
                                burst += 1
                            event.update(burst=burst, gap_ms=round(gap * 1000, 3) if gap is not None else None)
                            last_wheel = now
                        trace.emit('raw_mouse', **event)
                    write_all(master, data)
        _, status = os.waitpid(child, 0)
        reaped = True
        result = os.waitstatus_to_exitcode(status)
        trace.emit('session_exit', exit_code=result)
        return result if result >= 0 else 128 - result
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_terminal)
        signal.signal(signal.SIGWINCH, previous_resize)
        for signum, handler in previous_signals.items():
            signal.signal(signum, handler)
        selector.close()
        os.close(master)
        if not reaped:
            try:
                os.kill(child, signal.SIGTERM)
                os.waitpid(child, 0)
            except ProcessLookupError:
                os.waitpid(child, 0)
        trace.close()


def summarize(log_path):
    with log_path.open(encoding='utf-8') as stream:
        events = sorted((json.loads(line) for line in stream if line.strip()), key=lambda event: event['time_ns'])
    raw, decoded, wheels = Counter(), Counter(), Counter()
    reversals, renders, clamped, motion, cancelled = [], 0, 0, 0, 0
    last_boundary = None
    for event in events:
        kind = event['event']
        if kind == 'raw_mouse' and event['direction']:
            raw[event['direction']] += 1
        elif kind == 'raw_mouse' and event.get('motion', bool(event.get('code', 0) & 32)):
            motion += 1
        elif kind == 'curses_mouse':
            decoded[event['direction'] or 'non-wheel'] += 1
        elif kind == 'render':
            renders += 1
        elif kind == 'mouse_handled' and event.get('cancelled_wheel'):
            cancelled += 1
        elif kind == 'wheel':
            before, after, delta = event['before'], event['after'], event['delta']
            component = before['component']
            wheels[component] += 1
            outward = (before['at_top'] and delta < 0) or (before['at_bottom'] and delta > 0)
            clamped += int(outward and before['position'] == after['position'])
            identity = (component, before['board'], before.get('session_id'),
                        before['selected_id'] if component in ('details', 'work-entity', 'work-event') else None)
            if last_boundary:
                previous, target = last_boundary
                gap_ms = (event['time_ns'] - previous['time_ns']) / 1_000_000
                if (target == identity and delta * previous['delta'] < 0
                        and before['position'] != after['position'] and gap_ms <= BURST_GAP * 1000):
                    reversals.append(dict(component=component, gap_ms=round(gap_ms, 3),
                                          position_before=before['position'], position_after=after['position'],
                                          time_ns=event['time_ns']))
            last_boundary = (event, identity) if outward else None
    return dict(events=len(events), raw_wheel=dict(raw), raw_motion=motion, curses_mouse=dict(decoded),
                wheel_by_component=dict(wheels), renders=renders, clamped_events=clamped,
                cancelled_wheel_events=cancelled,
                boundary_reversals=reversals)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # The child gets a fresh interpreter and its own hooks, never a shipped flag.
    if argv[:1] == ['--trace-child']:
        return trace_child(argv[1], argv[3:])
    parser = argparse.ArgumentParser(description=__doc__, epilog='Pass normal Kanitor options after --.')
    parser.add_argument('--log', type=Path, help='JSONL output (default: .local/scroll-<timestamp>.jsonl in checkout).')
    parser.add_argument('--analyze', type=Path, metavar='LOG', help='Summarize a completed trace without a terminal.')
    options, kanitor_args = parser.parse_known_args(argv)
    if options.analyze:
        print(json.dumps(summarize(options.analyze), indent=2))
        return 0
    if kanitor_args[:1] == ['--']:
        kanitor_args.pop(0)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('capture requires an interactive terminal')
    log_path = (options.log or REPO / '.local' / f'scroll-{datetime.now():%Y%m%d-%H%M%S-%f}.jsonl').expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    result = run_proxy(log_path, kanitor_args)
    print(f'\nSaved scroll trace: {log_path}')
    print(json.dumps(summarize(log_path), indent=2))
    return result


if __name__ == '__main__':
    sys.exit(main())
