"""Unambiguous SGR mouse input for ncurses runtimes with a four-button ABI."""
from collections import deque
import curses
import re
import sys

WHEEL_UP = curses.BUTTON4_PRESSED
# This bit is only a normalized wheel-down value in the SGR adapter. Legacy
# getmouse() aliases wheel-down, horizontal wheels, and motion to this same bit.
WHEEL_DOWN = getattr(curses, 'BUTTON5_PRESSED', curses.REPORT_MOUSE_POSITION)
# Internal SGR flag, outside ncurses' mouse bit range. On four-button builds,
# REPORT_MOUSE_POSITION aliases wheel-down and must never represent a drag.
LEFT_DRAG = 1 << 32
WHEEL_GESTURE_GAP = 0.2


def is_left_drag(buttons):
    native_motion = curses.REPORT_MOUSE_POSITION if hasattr(curses, 'BUTTON5_PRESSED') else 0
    return bool(buttons & (LEFT_DRAG | native_motion))


def native_button_motion(enabled, output=None):
    output = output if output is not None else sys.stdout
    # ncurses requests all motion with REPORT_MOUSE_POSITION. Ask the terminal
    # for held-button motion only, leaving ordinary pointer movement quiet.
    output.write('\x1b[?1003l\x1b[?1002h' if enabled else '\x1b[?1002l')
    output.flush()


class WheelGesture:
    """Let explicit navigation interrupt the tail of an ongoing wheel gesture."""
    def __init__(self):
        self.last_at = None
        self.direction = None
        self.cancelled = None

    def accept(self, delta, now):
        if self.last_at is None or now - self.last_at >= WHEEL_GESTURE_GAP:
            self.cancelled = None
        self.last_at = now
        self.direction = -1 if delta < 0 else 1
        if self.direction == self.cancelled:
            return False
        # A real change of wheel direction is fresh user intent and immediately
        # restores ordinary wheel navigation, including subsequent reversals.
        self.cancelled = None
        return True

    def interrupt(self, now):
        if self.last_at is not None and now - self.last_at < WHEEL_GESTURE_GAP:
            self.cancelled = self.direction


def decode_sgr(sequence):
    """Return a curses-shaped mouse event without conflating axes or motion."""
    match = re.fullmatch(r'\x1b\[<([0-9]+);([0-9]+);([0-9]+)([Mm])', sequence)
    if not match:
        return None
    code, x, y = (int(match[index]) for index in (1, 2, 3))
    if x < 1 or y < 1:
        return None
    button = code & ~28  # Strip Shift/Alt/Ctrl, retaining motion and axis bits.
    buttons = 0
    if match[4] == 'M':
        if button == 64:
            buttons = WHEEL_UP
        elif button == 65:
            buttons = WHEEL_DOWN
        elif button == 0:
            buttons = curses.BUTTON1_PRESSED
        elif button == 2:
            buttons = curses.BUTTON3_PRESSED
        elif button == 32:
            buttons = LEFT_DRAG
    elif button == 0:
        buttons = curses.BUTTON1_RELEASED
    if buttons:
        for bit, modifier in ((4, curses.BUTTON_SHIFT), (8, curses.BUTTON_ALT), (16, curses.BUTTON_CTRL)):
            if code & bit:
                buttons |= modifier
    return (0, x - 1, y - 1, 0, buttons)


class SgrMouseInput:
    """Read SGR mouse packets while ncurses continues decoding keyboard keys."""
    def __init__(self, screen, output=None, delay=100):
        self.screen = screen
        self.output = output if output is not None else sys.stdout
        self.pending = deque()
        self.event = None
        self.sequence = ''
        self.delay = delay

    def timeout(self, delay):
        self.delay = delay
        self.screen.timeout(delay)

    def start(self):
        # Disable the legacy decoder before requesting SGR packets directly.
        curses.mousemask(0)
        self.output.write('\x1b[?1000h\x1b[?1002h\x1b[?1006h')
        self.output.flush()

    def close(self):
        self.output.write('\x1b[?1006l\x1b[?1002l\x1b[?1000l')
        self.output.flush()

    def getmouse(self):
        if self.event is None:
            raise curses.error('No pending SGR mouse event')
        event, self.event = self.event, None
        return event

    def get_wch(self):
        if self.pending:
            return self.pending.popleft()
        prefix, self.sequence = self.sequence, ''
        if not prefix:
            key = self.screen.get_wch()
            if key != '\x1b':
                return key
            prefix = key
        # Keep lone Escape responsive and preserve unrelated Alt/key sequences.
        delay = self.delay
        self.screen.timeout(0 if delay == 0 else 25)
        try:
            while len(prefix) < 3:
                expected = '[' if len(prefix) == 1 else '<'
                try:
                    key = self.screen.get_wch()
                except curses.error:
                    if delay == 0:
                        self.sequence = prefix
                        raise
                    self.pending.extend(prefix[1:])
                    return '\x1b'
                if key != expected:
                    self.pending.extend(prefix[1:])
                    self.pending.append(key)
                    return '\x1b'
                prefix += key
            # Once a mouse prefix is recognized, never leak packet bytes into
            # navigation/search, including malformed or interrupted reports.
            while len(prefix) < 64:
                try:
                    key = self.screen.get_wch()
                except curses.error:
                    self.sequence = prefix
                    raise
                if not isinstance(key, str):
                    self.pending.append(key)
                    raise curses.error('Interrupted SGR mouse packet')
                if key == '\x1b':
                    self.sequence = key
                    raise curses.error('Interrupted SGR mouse packet')
                prefix += key
                if key in ('M', 'm'):
                    self.event = decode_sgr(prefix)
                    if self.event is not None:
                        return curses.KEY_MOUSE
                    break
            raise curses.error('Invalid SGR mouse packet')
        finally:
            self.screen.timeout(delay)
