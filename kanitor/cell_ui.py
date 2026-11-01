"""Shared, runtime-only cell navigation and column menus for explorer tables."""
from collections import Counter
import curses
from dataclasses import dataclass
import json
import time

from .config import MISSING_VALUE
from .mouse import WHEEL_GESTURE_GAP
from .table_state import Criterion, date_bounds
from .text import cells


@dataclass
class CellFocus:
    header: bool = False
    slot: object = None
    index: int = 0


class CellUI:
    @property
    def bindings(self):
        rules = self.catalog.rules if self.view == 'projects' else self.explorer.column_rules
        return rules.keybindings

    def key_movement(self, key, page_size):
        return self.bindings.movement(key, page_size)

    def init_cells(self):
        self.cell_focus = {}
        self.cell_columns = []
        self.cell_hits = []
        self.header_hits = []
        self._table_ids = {}
        self.column_menu = None
        self._wheel_boundary_at = None
        self._wheel_boundary_stopped = False
        self._wheel_boundary_armed = False

    @property
    def focus(self):
        return self.cell_focus.setdefault(self.view, CellFocus())

    @property
    def table_state(self):
        if self.view == 'projects':
            return self.project_state
        return self.explorer.board_state if self.view == 'boards' else self.explorer.task_state

    def configured_columns(self):
        if self.view == 'projects':
            return self.catalog.rules.project_columns
        if self.view == 'boards':
            return self.explorer.column_rules.board_columns
        return self.explorer.column_rules.for_board(self.explorer.board_slug)

    def table_rows(self):
        if self.view == 'projects':
            return self.rows()
        return self.explorer.board_rows if self.view == 'boards' else self.explorer.rows

    def table_universe(self):
        if self.view == 'projects':
            return self.project_universe()
        if self.view == 'boards':
            return self.explorer.board_universe
        return self.explorer.board['tasks'] if self.explorer.board else []

    def row_id(self, row):
        return row['slug' if self.view == 'boards' else 'id']

    def focused_row_id(self):
        return self.explorer.selected_id if self.view == 'tasks' else self.current_summary_id()

    def select_cell_row(self, identity):
        if self.view == 'tasks':
            self.explorer.selected_id = identity
        else:
            self.select_summary_row(identity)

    def table_setup(self, columns):
        self.cell_columns = columns
        self.cell_hits, self.header_hits = [], []
        counts, slots = Counter(), []
        for column, _ in columns:
            slots.append((column.key, counts[column.key]))
            counts[column.key] += 1
        focus = self.focus
        focus.index = slots.index(focus.slot) if focus.slot in slots else min(focus.index, max(0, len(slots) - 1))
        focus.slot = slots[focus.index] if slots else None
        self.task_header_selected = focus.header
        rows = self.table_rows()
        identities = [self.row_id(row) for row in rows]
        previous = self._table_ids.get(self.view, [])
        if not rows:
            focus.header = self.task_header_selected = True
            self.selected_square = None
        elif self.focused_row_id() not in identities:
            index = previous.index(self.focused_row_id()) if self.focused_row_id() in previous else 0
            self.select_cell_row(identities[min(index, len(identities) - 1)])
        self._table_ids[self.view] = identities
        if self.selected_square and (focus.header or not columns or columns[focus.index][0].field != 'task_squares'):
            self.selected_square = None
        if self.column_menu and self.column_menu.get('table') != 'activity':
            column = next((c for c in self.configured_columns() if c.key == self.column_menu['column'].key), None)
            if column is None and self.view == 'tasks' and self.column_menu['column'].field == 'status':
                column = self.explorer.status_filter_column
            if column is None:
                self.column_menu = None
            else:
                self.column_menu['column'] = column
                if self.column_menu['mode'] != 'actions' and not column.can_filter:
                    self.column_menu = None

    def heading(self, column):
        filtered = column.key in self.table_state.filters
        if self.view == 'tasks':
            filtered |= self.explorer.is_filtered(column)
        sorting = self.table_state.sort
        return column.heading(filtered, sorting[1] if sorting and sorting[0] == column.key else None)

    def header_attr(self, index):
        return self.attr('cyan') | curses.A_BOLD | (curses.A_REVERSE if self.main_pane_focused and self.focus.header and self.focus.index == index else 0)

    def cell_attr(self, index, selected):
        return curses.A_REVERSE | curses.A_BOLD if self.main_pane_focused and selected and not self.focus.header and self.focus.index == index else 0

    def draw_row_focus(self, y, offset=0, height=1):
        if self.focus.header or not self.main_pane_focused:
            return
        if height == 1:
            left, right = '⟦', '⟧'
        elif offset == 0:
            left, right = '╭', '╮'
        elif offset == height - 1:
            left, right = '╰', '╯'
        else:
            left = right = '│'
        self.put(y, 2, left, self.attr('cyan'))
        self.put(y, self.screen.getmaxyx()[1] - 4, right, self.attr('cyan'))

    def add_header_hit(self, y, x, size, index):
        self.header_hits.append((y, x, size, index))

    def add_cell_hit(self, y, x, size, identity, index):
        self.cell_hits.append((y, x, size, identity, index))

    def prepare_square_focus(self, rows):
        if self.selected_square or self.focus.header or not self.cell_columns:
            return
        if self.cell_columns[self.focus.index][0].field == 'task_squares':
            row = next((row for row in rows if self.row_id(row) == self.focused_row_id()), None)
            bundle = row.get('task_squares') if row else None
            if bundle and bundle.flat:
                self.select_square(self.row_id(row), bundle.flat[0])

    def focus_column(self, index, from_right=False, preserve_goal=False):
        if not self.cell_columns:
            return
        self.focus.index = max(0, min(len(self.cell_columns) - 1, index))
        column = self.cell_columns[self.focus.index][0]
        occurrence = sum(c.key == column.key for c, _ in self.cell_columns[:self.focus.index])
        self.focus.slot = column.key, occurrence
        self.selected_square = None
        if not self.focus.header and column.field == 'task_squares':
            positions = self.square_positions.get(self.focused_row_id(), [])
            if positions:
                target = positions[-1 if from_right else 0][2]
                goal = self.square_column_goal
                if preserve_goal and goal is not None:
                    line = positions[-1 if from_right else 0][0]
                    target = min((item for item in positions if item[0] == line), key=lambda item: abs(item[1] - goal))[2]
                self.select_square(self.focused_row_id(), target, preserve_column=preserve_goal)

    def focus_row_index(self, index):
        rows = self.table_rows()
        if rows:
            self.select_cell_row(self.row_id(rows[max(0, min(len(rows) - 1, index))]))

    def reconcile_cell_rows(self, previous, selected):
        rows = self.table_rows()
        if not any(self.row_id(row) == selected for row in rows):
            old_index = next((i for i, row in enumerate(previous) if self.row_id(row) == selected), 0)
            self.focus_row_index(old_index)
        self.focus.header |= not bool(rows)
        self.task_header_selected = self.focus.header
        if self.selected_square and self.selected_square[0] != self.focused_row_id():
            self.selected_square = None

    def apply_column_change(self, column, criterion=None, sorting=None, reset_sort=False):
        previous, selected = self.table_rows(), self.focused_row_id()
        if sorting is not None or reset_sort:
            self.table_state.sort = self.table_state.default_sort if reset_sort else (column.key, sorting)
        else:
            if self.view == 'tasks':
                if column.field == 'status':
                    self.explorer.statuses = None
                self.explorer.column_filters.pop(column.key, None)
            if criterion is None:
                self.table_state.filters.pop(column.key, None)
            else:
                self.table_state.filters[column.key] = criterion
        self.reconcile_cell_rows(previous, selected)
        self.needs_redraw = True

    def menu_state(self):
        return self.activity.state if self.column_menu and self.column_menu.get('table') == 'activity' else self.table_state

    def apply_menu_change(self, column, criterion=None, sorting=None, reset_sort=False):
        if self.column_menu and self.column_menu.get('table') == 'activity':
            self.apply_activity_change(column, criterion, sorting, reset_sort)
        else:
            self.apply_column_change(column, criterion, sorting, reset_sort)

    def column_options(self, column):
        activity = column.scope == 'activity'
        if not activity and self.view == 'tasks' and column.field == 'status' and self.explorer.board:
            return [(column.filter_token({'column': name}), name) for name in self.explorer.board['columns']]
        universe = self.activity.universe if activity else self.table_universe()
        options = {column.filter_token(row): column.value(row) for row in universe}
        if MISSING_VALUE in options:
            options[MISSING_VALUE] = '(Missing)'
        counts = Counter(options.values())
        for token, label in list(options.items()):
            if token != MISSING_VALUE and counts[label] > 1:
                value = json.loads(token)
                kind = 'text' if isinstance(value, str) else 'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (int, float)) else 'array' if isinstance(value, list) else 'object'
                options[token] = f'{label} ({kind})'
        return sorted(options.items(), key=lambda item: (item[0] == MISSING_VALUE, item[1].casefold(), item[0]))

    def open_cell_menu(self, index=None, row=None, anchor=None, editor=False):
        if index is not None:
            self.focus_column(index)
        if not self.cell_columns:
            return
        column = self.cell_columns[self.focus.index][0]
        if anchor is None:
            anchor = next(((y, x) for y, x, _, i in self.header_hits if i == self.focus.index), (4, 5))
        self.column_menu = {'column': column, 'row': row, 'anchor': anchor,
                            'mode': 'actions', 'index': 0, 'top': 0, 'error': '', 'draft': '', 'second': ''}
        if editor:
            self.edit_column_filter()

    def edit_column_filter(self):
        menu = self.column_menu
        column = menu['column']
        if not column.can_filter:
            return
        current = self.menu_state().filters.get(column.key)
        menu.update(mode=column.filter_kind, index=0, top=0, error='')
        if column.filter_kind == 'string':
            menu['draft'] = current.value if current and current.kind == 'string' else ''
        elif column.filter_kind == 'date' and current and current.kind == 'date':
            menu['index'] = next((i for i, (_, action) in enumerate(self.menu_entries()) if action == current.value[0]), 0)

    def menu_entries(self):
        menu = self.column_menu
        column = menu['column']
        if menu['mode'] == 'actions':
            entries = self.activity_context_entries(column, menu['row']) if menu.get('table') == 'activity' else []
            if column.can_filter:
                if menu['row'] is not None:
                    entries += [('Only this value', 'only'), ('Exclude this value', 'exclude')]
                entries += [('Filter…', 'filter'), ('Clear filter', 'clear')]
            if column.can_sort:
                entries += [('Sort ascending', 'asc'), ('Sort descending', 'desc'), ('Reset sort', 'reset')]
            return entries or [('No actions available', 'none')]
        if menu['mode'] == 'enum':
            criterion = self.menu_state().filters.get(column.key)
            options = self.column_options(column)
            def enabled(token):
                if criterion is None:
                    return True
                if criterion.kind == 'enum':
                    return token in criterion.value
                if criterion.kind in ('only', 'exclude'):
                    return (token == criterion.value) == (criterion.kind == 'only')
                return False
            label = 'All statuses' if column.field == 'status' else 'All values'
            entries = [(f"[{'x' if criterion is None else '-' if any(enabled(token) for token, _ in options) else ' '}] {label}", 'all')]
            return entries + [(f"[{'x' if enabled(token) else ' '}] {label}", token) for token, label in options]
        if menu['mode'] == 'date':
            return [(label, label) for label in ('Today', 'Yesterday', 'Last 7 days', 'Last 30 days', 'On', 'Before', 'After', 'Between', 'Clear filter')]
        return []

    def menu_activate(self):
        menu = self.column_menu
        column = menu['column']
        entries = self.menu_entries()
        if not entries:
            return
        action = entries[menu['index']][1]
        if menu['mode'] == 'enum':
            options = self.column_options(column)
            current = self.menu_state().filters.get(column.key)
            if action == 'all':
                criterion = Criterion('enum', set()) if current is None else None
            else:
                available = {token for token, _ in options}
                if current and current.kind == 'enum':
                    selected = set(current.value)
                elif current and current.kind in ('only', 'exclude'):
                    selected = {token for token in available if (token == current.value) == (current.kind == 'only')}
                else:
                    selected = available.copy()
                selected.symmetric_difference_update({action})
                criterion = None if selected == available else Criterion('enum', selected)
            self.apply_menu_change(column, criterion)
            return
        if menu['mode'] == 'date':
            if action == 'Clear filter':
                self.apply_menu_change(column)
                self.column_menu = None
            elif action in ('On', 'Before', 'After', 'Between'):
                current = self.menu_state().filters.get(column.key)
                first, second = ('', '') if not current or current.kind != 'date' or current.value[0] != action else (current.value[1], current.second)
                menu.update(mode='date_input', operator=action, draft=first, second=second, field=0, error='')
            else:
                self.apply_menu_change(column, Criterion('date', (action, '')))
                self.column_menu = None
            return
        if menu.get('table') == 'activity' and action in ('openProject', 'openBoard', 'openTask'):
            self.column_menu = None
            self.activate_activity_cell(column, menu['row'])
            return
        if action == 'filter':
            self.edit_column_filter()
            return
        if action in ('only', 'exclude'):
            self.apply_menu_change(column, Criterion(action, column.filter_token(menu['row'])))
        elif action == 'clear':
            self.apply_menu_change(column)
        elif action in ('asc', 'desc', 'reset'):
            self.apply_menu_change(column, sorting=action == 'desc', reset_sort=action == 'reset')
        self.column_menu = None

    def handle_column_menu(self, key):
        menu = self.column_menu
        editing = menu['mode'] in ('string', 'date_input')
        action = self.bindings.action(key)
        if (editing and key == '\x1b') or (not editing and action in ('back', 'quit')):
            self.column_menu = None
            return
        if menu['mode'] in ('string', 'date_input'):
            name = 'second' if menu.get('field') == 1 else 'draft'
            if key in ('\n', '\r', curses.KEY_ENTER):
                if menu['mode'] == 'date_input':
                    if menu['operator'] == 'Between' and menu['field'] == 0:
                        menu['field'] = 1
                        return
                    try:
                        date_bounds(menu['operator'], menu['draft'], menu['second'])
                    except (ValueError, OverflowError, OSError):
                        menu['error'] = 'Use YYYY-MM-DD; end must not precede start.'
                        return
                    criterion = Criterion('date', (menu['operator'], menu['draft']), menu['second'])
                else:
                    criterion = Criterion('string', menu['draft']) if menu['draft'] else None
                self.apply_menu_change(menu['column'], criterion)
                self.column_menu = None
            elif key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
                menu[name] = menu[name][:-1]
            elif key == '\x15':
                menu[name] = ''
            elif menu['mode'] == 'date_input' and key in (curses.KEY_UP, curses.KEY_DOWN) and menu['operator'] == 'Between':
                menu['field'] = 0 if key == curses.KEY_UP else 1
            elif isinstance(key, str) and key.isprintable():
                menu[name] += key
            return
        move = self.key_movement(key, menu.get('capacity', 5))
        if move:
            menu['index'] = max(0, min(len(self.menu_entries()) - 1, menu['index'] + move[0]))
            if move[1]:
                menu['top'] = max(0, min(len(self.menu_entries()) - menu.get('capacity', 5), menu['top'] + move[0]))
        elif action == 'open':
            self.menu_activate()
        elif action in ('first', 'last'):
            menu['index'] = 0 if action == 'first' else len(self.menu_entries()) - 1

    def draw_column_menu(self):
        from .ui import pad
        menu = self.column_menu
        if not menu:
            return
        height, width = self.screen.getmaxyx()
        entries = self.menu_entries()
        text = []
        if menu['mode'] == 'string':
            text = ['Search: ' + menu['draft'] + '▏', 'Enter applies · Esc cancels']
        elif menu['mode'] == 'date_input':
            text = [menu['operator'] + ' (YYYY-MM-DD)',
                    ('From: ' if menu['operator'] == 'Between' else 'Date: ') + menu['draft'] + ('▏' if menu['field'] == 0 else '')]
            if menu['operator'] == 'Between':
                text.append('To: ' + menu['second'] + ('▏' if menu['field'] == 1 else ''))
            text += [menu['error'] or 'Enter applies · Esc cancels']
        capacity = max(1, min(len(entries) or len(text), height - 7))
        menu['capacity'] = capacity
        labels = [label for label, _ in entries] or text
        size = min(width - 6, max(30, cells(menu['column'].label) + 6, max((cells(label) + 4 for label in labels), default=30)))
        y, x = menu['anchor']
        x = max(3, min(x, width - size - 3))
        y = max(3, min(y + 1, height - capacity - 4))
        menu['rect'] = y, x, capacity + 2, size
        menu['hits'] = []
        if entries:
            menu['index'] = min(menu['index'], len(entries) - 1)
            menu['top'] = max(0, min(menu['top'], menu['index'], len(entries) - capacity))
            menu['top'] = max(menu['top'], menu['index'] - capacity + 1)
        self.put(y, x, '┌' + '─' * (size - 2) + '┐', self.attr('focus'))
        self.put(y, x + 2, ' ' + menu['column'].label + ' ', self.attr('focus') | curses.A_BOLD, size - 4)
        for offset in range(capacity):
            index = menu['top'] + offset
            label = labels[index] if entries else text[offset]
            attr = curses.A_REVERSE if entries and index == menu['index'] else 0
            self.put(y + 1 + offset, x, '│' + ' ' * (size - 2) + '│', self.attr('focus'))
            self.put(y + 1 + offset, x + 1, pad(' ' + label, size - 3), attr)
            menu['hits'].append((y + 1 + offset, index))
        self.put(y + capacity + 1, x, '└' + '─' * (size - 2) + '┘', self.attr('focus'))
        if entries:
            self.draw_scrollbar(y + 1, x + size - 2, capacity, len(entries), capacity, menu['top'], 'column_menu')

    def table_status(self):
        parts = []
        by_key = {c.key: c for c in self.configured_columns()}
        for key, criterion in self.table_state.filters.items():
            if key in by_key:
                parts.append(by_key[key].label + ': ' + criterion.label())
        sorting = self.table_state.sort
        if sorting:
            column = by_key.get(sorting[0])
            label = column.label if column else sorting[0][1].title()
            parts.append(f"Sort: {label} {'↓' if sorting[1] else '↑'}")
        elif self.view == 'tasks':
            parts.append('Sort: Status, Updated ↓')
        return ' · '.join(parts)

    def handle_table_key(self, key):
        if self.column_menu:
            self.handle_column_menu(key)
            return True
        action = self.bindings.action(key)
        if not self.cell_columns:
            width = self.screen.getmaxyx()[1]
            from .config import layout_columns
            columns = layout_columns(self.configured_columns(), width, width - 9, self.table_rows())[0]
            self.table_setup(columns)
        focus = self.focus
        if action == 'columnMenu':
            row = None if focus.header else next((row for row in self.table_rows() if self.row_id(row) == self.focused_row_id()), None)
            anchor = next(((y, x) for y, x, _, index in self.header_hits if index == focus.index), (4, 5))
            self.open_cell_menu(row=row, anchor=anchor)
            return True
        if action == 'back':
            if self.view == 'projects' or (self.view == 'boards' and not self.on_projects):
                return True
            self.selected_square = None
            self.back_to_boards()
            return True
        if action in ('left', 'right', 'jumpLeft', 'jumpRight'):
            direction = -1 if action in ('left', 'jumpLeft') else 1
            step = 5 if action in ('jumpLeft', 'jumpRight') else 1
            if self.selected_square and not focus.header:
                positions = self.square_positions.get(self.focused_row_id(), [])
                index = next((i for i, (_, _, square) in enumerate(positions) if square.id == self.selected_square[1]), 0)
                if 0 <= index + direction < len(positions):
                    target = max(0, min(len(positions) - 1, index + direction * step))
                    self.select_square(self.focused_row_id(), positions[target][2])
                    return True
            if 0 <= focus.index + direction < len(self.cell_columns):
                self.focus_column(focus.index + direction, from_right=direction < 0)
            return True
        if action == 'open':
            if focus.header:
                self.open_cell_menu()
            elif self.selected_square:
                square = self.focused_square()
                if square:
                    self.open_square(self.selected_square[0], square)
            elif self.view == 'projects':
                self.open_project()
            else:
                self.enter_item()
            return True
        size = self.project_height if self.view == 'projects' else self.board_height if self.view == 'boards' else self.task_height
        move = self.key_movement(key, size)
        if move or action in ('first', 'last'):
            delta, page = move or (-10**9 if action == 'first' else 10**9, False)
            rows = self.table_rows()
            index = next((i for i, row in enumerate(rows) if self.row_id(row) == self.focused_row_id()), 0)
            if self.selected_square and move and not focus.header:
                positions = self.square_positions.get(self.focused_row_id(), [])
                line = next((line for line, _, square in positions if square.id == self.selected_square[1]), 0)
                if delta < 0 and line == 0:
                    focus.header = True
                    self.selected_square = None
                else:
                    self.handle_square_key(key)
                self.task_header_selected = focus.header
                return True
            if self.selected_square and action in ('first', 'last'):
                self.handle_square_key(key)
                return True
            if focus.header:
                if delta > 0 and rows:
                    focus.header = False
                    self.focus_row_index(delta - 1 if abs(delta) < 10**9 else len(rows) - 1)
                    self.focus_column(focus.index)
            elif delta < 0 and index == 0 and not page and action != 'first':
                focus.header = True
                self.selected_square = None
            else:
                self.scroll(delta, page)
                focus.header = False
                self.focus_column(focus.index, from_right=delta < 0, preserve_goal=True)
            self.task_header_selected = focus.header
            return True
        if self.view in ('boards', 'projects') and action == 'togglePreview':
            self.square_preview_shown = not self.square_preview_shown
            return True
        return False

    def table_wheel(self, delta):
        """Stop each upward gesture at the first row before admitting headers."""
        now = time.monotonic()
        fresh = self._wheel_boundary_at is None or now - self._wheel_boundary_at >= WHEEL_GESTURE_GAP
        self._wheel_boundary_at = now
        if fresh or delta > 0:
            self._wheel_boundary_stopped = False
        if self.column_menu:
            menu = self.column_menu
            if self.menu_entries():
                menu['index'] = max(0, min(len(self.menu_entries()) - 1, menu['index'] + delta))
            return
        rows = self.table_rows()
        if not rows:
            return
        index = next((i for i, row in enumerate(rows) if self.row_id(row) == self.focused_row_id()), 0)
        top = self.project_top if self.view == 'projects' else self.board_top if self.view == 'boards' else self.task_top
        if delta < 0 and self._wheel_boundary_stopped:
            return
        if self.focus.header:
            if delta > 0:
                self.focus.header = False
                self.focus_row_index(0)
                self.focus_column(self.focus.index)
        elif delta < 0 and index == 0 and top == 0:
            if fresh and getattr(self, '_wheel_boundary_armed', False):
                self.focus.header = True
                self.selected_square = None
            self._wheel_boundary_stopped = True
            self._wheel_boundary_armed = True
        else:
            self.scroll_table_wheel(delta)
            if delta < 0 and self.focused_row_id() == self.row_id(rows[0]):
                if self.view == 'tasks':
                    self.task_top = 0
                top = self.project_top if self.view == 'projects' else self.board_top if self.view == 'boards' else self.task_top
                if top == 0:
                    self._wheel_boundary_stopped = True
                    self._wheel_boundary_armed = True
            elif delta > 0:
                self._wheel_boundary_armed = False
        self.task_header_selected = self.focus.header

    def table_mouse(self, x, y, buttons):
        """Dispatch header/cell clicks; return whether the table consumed them."""
        right = bool(buttons & (curses.BUTTON3_PRESSED | curses.BUTTON3_CLICKED))
        if self.column_menu:
            menu = self.column_menu
            if 'rect' in menu:
                top, left, height, width = menu['rect']
                if not (left <= x < left + width and top <= y < top + height):
                    self.column_menu = None
                else:
                    bar = next((bar for bar in self.scrollbars if bar['kind'] == 'column_menu' and bar['x'] == x and bar['y'] <= y < bar['y'] + bar['height']), None)
                    if bar and self.menu_entries():
                        menu['index'] = max(0, min(len(self.menu_entries()) - 1, menu['index'] + (-bar['visible'] if y - bar['y'] < bar['thumb_top'] else bar['visible'])))
                    else:
                        for row, index in menu['hits']:
                            if row == y and self.menu_entries():
                                menu['index'] = index
                                self.menu_activate()
                                break
            return True
        for row, left, size, index in self.header_hits:
            if row == y and left <= x < left + size:
                self.focus.header = True
                self.open_cell_menu(index, anchor=(y, left))
                self.task_header_selected = True
                return True
        for row, left, size, identity, index in self.cell_hits:
            if row == y and left <= x < left + size:
                was_focused = not self.focus.header and self.focused_row_id() == identity
                self.focus.header = False
                self.task_header_selected = False
                self.select_cell_row(identity)
                self.focus_column(index)
                if right:
                    value = next((row for row in self.table_rows() if self.row_id(row) == identity), None)
                    self.open_cell_menu(row=value, anchor=(y, x))
                elif self.cell_columns[index][0].field == 'task_squares':
                    self.click_square(x, y, buttons)
                elif was_focused:
                    if self.view == 'projects':
                        self.open_project()
                    else:
                        self.enter_item()
                return True
        return False
