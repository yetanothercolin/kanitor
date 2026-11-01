"""Pane geometry and keyboard/mouse resizing, using absolute terminal rows."""
import curses
from dataclasses import dataclass

from .keybindings import key_token
from .mouse import is_left_drag


@dataclass(frozen=True)
class PaneGeometry:
    names: tuple
    starts: tuple
    heights: tuple
    dividers: tuple


def pane_geometry(height, activity, preview, positions=(), *, sizes=None):
    """Default lower panes hug eight rows; explicit dividers are absolute."""
    available = height - 5
    preview = preview and height >= (25 if activity else 19)
    preferred = sizes or {}
    names, sizes = ['main'], []
    if activity:
        names.append('activity')
        preview_size = min(preferred.get('preview', 8), available - 12) if preview else 0
        sizes.append(min(preferred.get('activity', 8), available - 6 - (preview_size + 1 if preview else 0)))
    if preview:
        names.append('preview')
        sizes.append(min(preferred.get('preview', 8), available - (12 if activity else 6)))
    heights = [available - sum(sizes) - len(sizes), *sizes]
    starts, dividers = [3], []
    for size in heights[:-1]:
        dividers.append(starts[-1] + size)
        starts.append(dividers[-1] + 1)
    if len(positions) == len(dividers) and all(type(y) is int for y in positions):
        minima = [3 if name == 'preview' else 5 for name in names]
        floor = 3 + minima[0]
        for index, value in enumerate(positions):
            ceiling = height - 2 - sum(minima[index + 1:]) - (len(dividers) - index)
            dividers[index] = max(floor, min(ceiling, value))
            floor = dividers[index] + 1 + minima[index + 1]
        starts = [3, *(y + 1 for y in dividers)]
        ends = [*dividers, height - 2]
        heights = [end - start for start, end in zip(starts, ends)]
    return PaneGeometry(tuple(names), tuple(starts), tuple(heights), tuple(dividers))


class PaneLayoutState:
    """Shared absolute anchors, with preferred sizes for currently hidden panes."""
    def __init__(self, store):
        self.store = store
        data = store.mapping('paneLayout').get('shared', {})
        data = data if isinstance(data, dict) else {}
        sizes = data.get('sizes', {})
        sizes = sizes if isinstance(sizes, dict) else {}
        self.sizes = {name: sizes[name] if type(sizes.get(name)) is int and sizes[name] >= low else 8
                      for name, low in (('activity', 5), ('preview', 3))}
        names, positions = data.get('names'), data.get('dividers')
        self.names, self.dividers = (), []
        if names in (['activity'], ['preview'], ['activity', 'preview']) and isinstance(positions, list):
            if len(positions) == len(names) and all(type(y) is int for y in positions):
                self.names, self.dividers = tuple(names), positions
        self.legacy = store.mapping('paneDividers') if not self.names else {}

    def migrate(self, view, height, activity, preview):
        if not self.legacy:
            return
        names = pane_geometry(height, activity, preview).names[1:]
        positions = self.legacy.get(view + ':' + ','.join(names))
        self.legacy = {}
        if isinstance(positions, list) and len(positions) == len(names) and all(type(y) is int for y in positions):
            self.names, self.dividers = names, positions

    def effective_sizes(self, height):
        sizes = dict(self.sizes)
        if self.names:
            geometry = pane_geometry(height, 'activity' in self.names, 'preview' in self.names,
                                     self.dividers, sizes=self.sizes)
            sizes.update(zip(geometry.names[1:], geometry.heights[1:]))
        return sizes

    def geometry(self, height, activity, preview):
        return pane_geometry(height, activity, preview, sizes=self.effective_sizes(height))

    def update(self, height, geometry, positions):
        self.sizes = self.effective_sizes(height)
        geometry = pane_geometry(height, 'activity' in geometry.names, 'preview' in geometry.names, positions)
        self.sizes.update(zip(geometry.names[1:], geometry.heights[1:]))
        self.names, self.dividers = geometry.names[1:], list(geometry.dividers)
        return geometry

    def save(self):
        return self.store.set_mapping_entry('paneLayout', 'shared', {
            'sizes': self.sizes, 'names': list(self.names), 'dividers': self.dividers})


class PaneUI:
    def init_panes(self):
        self.resize_mode = False
        self.resize_active = None
        self.resize_drag = None
        self.pane_layout_state = PaneLayoutState(self.view_state)
        self.pane_geometry = None
        self.preview_height = 8

    def pane_layout(self, preview):
        height = self.screen.getmaxyx()[0]
        default = pane_geometry(height, self.activity_visible, preview)
        self.pane_key = self.view + ':' + ','.join(default.names[1:])
        if self.resize_drag and (self.resize_drag['key'] != self.pane_key
                                 or self.resize_drag['size'] != self.screen.getmaxyx()):
            self.end_resize_drag()
        self.pane_layout_state.migrate(self.view, height, self.activity_visible, preview)
        geometry = self.pane_geometry = self.pane_layout_state.geometry(height, self.activity_visible, preview)
        names = geometry.names
        if self.resize_active not in names[1:]:
            self.resize_active = names[1] if len(names) > 1 else None
        activity = None
        preview_top = None
        if 'activity' in names:
            index = names.index('activity')
            activity = geometry.starts[index], geometry.heights[index]
        if 'preview' in names:
            index = names.index('preview')
            preview_top, self.preview_height = geometry.starts[index], geometry.heights[index]
        return geometry.heights[0], activity, preview_top

    def handle_resize_key(self, key):
        self.end_resize_drag()
        action = self.bindings.action(key)
        if action == 'toggleResize':
            self.resize_mode = not self.resize_mode
            if self.resize_mode and self.pane_geometry:
                names = self.pane_geometry.names[1:]
                self.resize_active = names[0] if names else None
            return True
        if not self.resize_mode:
            return False
        if action in ('back', 'quit', 'open'):
            self.resize_mode = False
        elif (self.screen.getmaxyx()[0] >= 16 and self.screen.getmaxyx()[1] >= 60
              and self.pane_geometry and self.pane_geometry.dividers):
            geometry = self.pane_geometry
            index = geometry.names[1:].index(self.resize_active)
            if action == 'focusPane':
                step = -1 if key_token(key) == 'shift+tab' else 1
                self.resize_active = geometry.names[1:][(index + step) % len(geometry.dividers)]
            elif action in ('up', 'down'):
                self.move_resizer(geometry.dividers[index] + (-1 if action == 'up' else 1))
        return True

    def save_resizers(self):
        error = self.pane_layout_state.save()
        if error:
            self.notice = error
            self.needs_redraw = True

    def end_resize_drag(self):
        drag, self.resize_drag = self.resize_drag, None
        if drag and drag['changed']:
            self.save_resizers()

    def move_resizer(self, row, *, dragging=False):
        geometry = self.pane_geometry
        index = geometry.names[1:].index(self.resize_active)
        positions = list(geometry.dividers)
        floor = geometry.starts[index] + 5
        minimum = 3 if geometry.names[index + 1] == 'preview' else 5
        end = geometry.starts[index + 1] + geometry.heights[index + 1]
        value = max(floor, min(end - minimum - 1, row))
        if value == positions[index]:
            return
        positions[index] = value
        self.pane_geometry = self.pane_layout_state.update(self.screen.getmaxyx()[0], geometry, positions)
        if dragging:
            self.resize_drag['changed'] = True
        else:
            self.save_resizers()
        self.needs_redraw = True

    def resize_mouse(self, x, y, buttons):
        if not self.resize_mode:
            return False
        if self.screen.getmaxyx()[0] < 16 or self.screen.getmaxyx()[1] < 60:
            self.end_resize_drag()
            return True
        release = bool(buttons & curses.BUTTON1_RELEASED)
        if self.resize_drag:
            drag = self.resize_drag
            if drag['key'] != self.pane_key or drag['size'] != self.screen.getmaxyx():
                self.end_resize_drag()
                return True
            if release or is_left_drag(buttons):
                self.resize_active = drag['name']
                self.move_resizer(y, dragging=True)
                if release:
                    self.end_resize_drag()
                return True
        if buttons & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON3_PRESSED):
            self.end_resize_drag()
        if self.pane_geometry and buttons & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
            for name, row in zip(self.pane_geometry.names[1:], self.pane_geometry.dividers):
                if y == row and 1 <= x < self.screen.getmaxyx()[1] - 1:
                    self.interrupt_wheel()
                    self._square_click = self._last_click = None
                    self.resize_active = name
                    self.needs_redraw = True
                    if buttons & curses.BUTTON1_PRESSED:
                        self.resize_drag = dict(key=self.pane_key, name=name,
                                                size=self.screen.getmaxyx(), changed=False)
                    break
        return True

    def draw_resizers(self):
        if not self.resize_mode or self.popup or not self.pane_geometry:
            return
        width = self.screen.getmaxyx()[1]
        geometry = self.pane_geometry
        for index, row in enumerate(geometry.dividers):
            active = geometry.names[index + 1] == self.resize_active
            attr = self.attr('cyan' if active else 'dim')
            self.put(row, 1, '─' * (width - 2), attr)
            label = f' ↕ {geometry.names[index].title()} / {geometry.names[index + 1].title()} '
            self.put(row, 4, label, attr | (curses.A_REVERSE | curses.A_BOLD if active else 0), width - 9)

    def resize_footer(self):
        toggle = self.bindings.label('toggleResize', True)
        cycle = self.bindings.label('focusPane')
        move = self.bindings.label('up', True) + '/' + self.bindings.label('down', True)
        return f'Resize · drag or {move} move · {cycle} divider · {toggle} finish'

    def resize_status(self):
        geometry = self.pane_geometry
        if not geometry or not geometry.dividers:
            return 'Resize · no dividers; show Activity or Preview to resize panes.'
        sizes = ' · '.join(f'{name.title()}: {height} rows' for name, height in zip(geometry.names, geometry.heights))
        return sizes + (' · ' + self.notice if self.notice else '')
