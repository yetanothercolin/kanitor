"""Task previews with fixed context and a scrollable description body."""
import curses
import time

from .mouse import WHEEL_DOWN, WHEEL_UP


class PreviewUI:
    def init_preview(self):
        self.preview_rect = None
        self.preview_top = 0
        self.preview_max = 0
        self.preview_capacity = 1
        self._preview_identity = None
        self._preview_lines_key = None
        self._preview_lines = []

    def draw_task_preview(self, y, source, *, title=None, empty='No task selected.'):
        from .ui import wrap_lines
        width = self.screen.getmaxyx()[1]
        height = self.preview_height
        identity = (str(source[0].root), source[1]['slug'], source[2]['id']) if source else None
        if identity != self._preview_identity:
            self.preview_top = 0
        self._preview_identity = identity
        self.preview_rect = y, 1, height, width - 2
        if source is None:
            self.preview_top = self.preview_max = 0
            self.frame(y, height, title or 'Task preview')
            self.put(y + 1, 4, empty, self.attr('dim'), width - 9)
            return
        _, board, task = source
        self.frame(y, height, title or 'Task · ' + task['name'])
        body_y = y + 1
        # Keep at least one readable body row even at the minimum pane height.
        if height >= 5:
            context = f"{board['slug']} · {task['id']} · {task['column']}"
            self.put(y + 1, 4, context, self.attr('dim'), width - 9)
            self.put(y + 2, 3, '─' * (width - 6), self.attr('cyan') | curses.A_DIM)
            body_y += 2
        self.preview_capacity = y + height - 1 - body_y
        text = task.get('description') or 'No description.'
        key = text, width - 9
        if key != self._preview_lines_key:
            self._preview_lines = wrap_lines(text, width - 9)
            self._preview_lines_key = key
        lines = self._preview_lines
        self.preview_max = max(0, len(lines) - self.preview_capacity)
        self.preview_top = max(0, min(self.preview_top, self.preview_max))
        for offset, line in enumerate(lines[self.preview_top:self.preview_top + self.preview_capacity]):
            self.put(body_y + offset, 4, line, width=width - 9)
        self.draw_scrollbar(body_y, width - 3, self.preview_capacity, len(lines),
                            self.preview_capacity, self.preview_top, 'preview')

    def scroll_preview(self, delta):
        top = max(0, min(self.preview_max, self.preview_top + delta))
        self.needs_redraw |= top != self.preview_top
        self.preview_top = top

    def handle_preview_mouse(self, x, y, buttons):
        if not self.preview_rect:
            return False
        top, left, height, width = self.preview_rect
        if not (top <= y < top + height and left <= x < left + width):
            return False
        up, down = bool(buttons & WHEEL_UP), bool(buttons & WHEEL_DOWN)
        if up or down:
            self._wheel_input = True
            if up != down:
                delta = -3 if up else 3
                if self.wheel_gesture.accept(delta, time.monotonic()):
                    self.scroll_preview(delta)
        elif buttons & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
            self.interrupt_wheel()
            self._last_click = self._square_click = None
            for bar in self.scrollbars:
                if bar['kind'] == 'preview' and x == bar['x'] and bar['y'] <= y < bar['y'] + bar['height']:
                    position = y - bar['y']
                    if position < bar['thumb_top']:
                        self.scroll_preview(-bar['visible'])
                    elif position >= bar['thumb_top'] + bar['thumb_size']:
                        self.scroll_preview(bar['visible'])
                    break
        return True
