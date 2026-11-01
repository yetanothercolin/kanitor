"""Visible text selection, isolated from explorer navigation and task data."""
import base64
import curses
import os
import shutil
import subprocess
import sys

from .mouse import is_left_drag
from .text import cells


class ClipboardError(Exception):
    pass


def copy_text(text, output=None):
    """Use the macOS clipboard, or request the terminal's OSC 52 clipboard."""
    if sys.platform == 'darwin' and (command := shutil.which('pbcopy')):
        try:
            subprocess.run([command], input=text.encode('utf-8'), check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=2)
        except (OSError, subprocess.SubprocessError) as error:
            raise ClipboardError('Clipboard copy failed; selection kept. Try again or use terminal selection.') from error
        return 'Copied selection to clipboard.'
    output = output if output is not None else sys.stdout
    if not output.isatty():
        raise ClipboardError('Clipboard requires a terminal with OSC 52 support; selection kept.')
    encoded = base64.b64encode(text.encode('utf-8')).decode('ascii')
    sequence = '\x1b]52;c;' + encoded + '\x07'
    if os.environ.get('TMUX'):
        sequence = '\x1bPtmux;' + sequence.replace('\x1b', '\x1b\x1b') + '\x1b\\'
    try:
        output.write(sequence)
        output.flush()
    except OSError as error:
        raise ClipboardError('Terminal clipboard request failed; selection kept.') from error
    return 'Sent selection to terminal clipboard (OSC 52).'


class TextFrame:
    """A terminal-cell grid preserving plain text and the drawn attributes."""
    def __init__(self, height, width):
        self.height, self.width = height, max(0, width - 1)
        self.text = [[' '] * self.width for _ in range(height)]
        self.attrs = [[0] * self.width for _ in range(height)]

    def write(self, y, x, text, attr):
        previous = None
        for char in text:
            size = cells(char)
            if not size:
                if previous is not None:
                    self.text[y][previous] += char
                continue
            if not (0 <= x < self.width) or x + size > self.width:
                break
            # Erasing either half of a wide glyph erases the other half too.
            for offset in range(size):
                at = x + offset
                if self.text[y][at] == '' and at:
                    self.text[y][at - 1] = ' '
                elif at + 1 < self.width and self.text[y][at + 1] == '':
                    self.text[y][at + 1] = ' '
            self.text[y][x] = char
            self.attrs[y][x] = attr
            for offset in range(1, size):
                self.text[y][x + offset] = ''
                self.attrs[y][x + offset] = attr
            previous = x
            x += size

    def clamp(self, point):
        x, y = point
        return max(0, min(self.width - 1, x)), max(0, min(max(0, self.height - 3), y))

    def bounds(self, anchor, end):
        points = [self.clamp(point) for point in (anchor, end)]
        return sorted(y * self.width + x for x, y in points)

    def selected_text(self, anchor, end):
        start, stop = self.bounds(anchor, end)
        lines = []
        for y in range(start // self.width, stop // self.width + 1):
            left = start % self.width if y == start // self.width else 0
            right = stop % self.width + 1 if y == stop // self.width else self.width
            if self.text[y][left] == '' and left:
                left -= 1
            lines.append(''.join(self.text[y][left:right]).rstrip())
        return '\n'.join(lines)


class SelectionUI:
    def selection_put(self, y, x, text, attr):
        try:
            self.screen.addstr(y, x, text, attr)
        except curses.error:
            pass  # A terminal resize may race a repaint.

    def init_selection(self):
        self.text_frame = None
        self.selecting_text = False
        self.text_anchor = self.text_end = None
        self.text_dragging = False
        self.selection_notice = ''

    def begin_text_frame(self):
        self.text_frame = TextFrame(*self.screen.getmaxyx())

    def finish_text_selection(self):
        self.selecting_text = self.text_dragging = False
        self.text_anchor = self.text_end = None
        self.selection_notice = ''
        self.needs_redraw = True

    def handle_text_selection_key(self, key):
        action = self.bindings.action(key)
        if not self.selecting_text:
            if (action != 'toggleSelection' or self.searching or self.column_menu
                    or self.resize_mode or self.text_frame is None):
                return False
            if self.text_frame.width < 1 or self.text_frame.height < 3:
                return False
            self.selecting_text = True
            self.text_anchor = self.text_end = None
            self.selection_notice = ''
            return True
        if action in ('toggleSelection', 'back', 'quit') or key == curses.KEY_RESIZE:
            self.finish_text_selection()
        elif action in ('copySelection', 'open'):
            if self.text_anchor is None:
                self.selection_notice = 'Drag over text to select it first.'
            else:
                text = self.text_frame.selected_text(self.text_anchor, self.text_end)
                if not text.strip():
                    self.selection_notice = 'Selection contains no text.'
                    return True
                try:
                    self.notice = copy_text(text)
                except ClipboardError as error:
                    self.selection_notice = str(error)
                else:
                    self.finish_text_selection()
        else:
            moves = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1),
                     'jumpLeft': (-5, 0), 'jumpRight': (5, 0),
                     'jumpUp': (0, -10), 'jumpDown': (0, 10),
                     'pageUp': (0, -max(1, self.text_frame.height - 2)),
                     'pageDown': (0, max(1, self.text_frame.height - 2))}
            if action in moves or action in ('first', 'last'):
                self.text_anchor = self.text_anchor or (0, 0)
                x, y = self.text_end or self.text_anchor
                if action in ('first', 'last'):
                    x = 0 if action == 'first' else self.text_frame.width - 1
                else:
                    dx, dy = moves[action]
                    x, y = x + dx, y + dy
                self.text_end = self.text_frame.clamp((x, y))
        return True

    def text_selection_mouse(self, x, y, buttons):
        if not self.selecting_text:
            return False
        point = self.text_frame.clamp((x, y))
        if buttons & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
            if y >= self.text_frame.height - 2:
                return True
            self.text_anchor = self.text_end = point
            self.text_dragging = bool(buttons & curses.BUTTON1_PRESSED)
            self.selection_notice = ''
        elif self.text_dragging and (is_left_drag(buttons) or buttons & curses.BUTTON1_RELEASED):
            self.text_end = point
            if buttons & curses.BUTTON1_RELEASED:
                self.text_dragging = False
        self.needs_redraw = True
        return True

    def draw_text_selection(self):
        if not self.selecting_text:
            return False
        frame = self.text_frame
        height, width = self.screen.getmaxyx()
        if (height, max(0, width - 1)) != (frame.height, frame.width):
            self.finish_text_selection()
            return False
        bounds = frame.bounds(self.text_anchor, self.text_end) if self.text_anchor is not None else None
        self.screen.erase()
        for y in range(max(0, height - 2)):
            run, run_x, run_attr = '', 0, None
            for x, text in enumerate(frame.text[y]):
                if text == '':
                    continue
                attr = frame.attrs[y][x]
                if bounds and y * frame.width + x <= bounds[1] and y * frame.width + x + cells(text) - 1 >= bounds[0]:
                    attr = (attr & ~curses.A_DIM) | curses.A_REVERSE | curses.A_BOLD | curses.A_UNDERLINE
                if attr != run_attr and run:
                    self.selection_put(y, run_x, run, run_attr)
                    run = ''
                if not run:
                    run_x, run_attr = x, attr
                run += text
            if run:
                self.selection_put(y, run_x, run, run_attr)
        # Keep instructions outside the captured/selected content.
        status = self.selection_notice or 'TEXT SELECTION · Drag to highlight · Arrows extend selection · View frozen'
        footer = f"{self.bindings.label('copySelection')} / {self.bindings.label('open')} copy · {self.bindings.label('toggleSelection')} / {self.bindings.label('back')} cancel"
        for y, text in ((height - 2, status), (height - 1, footer)):
            from .ui import clip
            self.selection_put(y, 0, clip(text, max(0, width - 1)), self.attr('cyan'))
        self.screen.refresh()
        return True
