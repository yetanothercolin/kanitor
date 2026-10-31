"""Read-only in-progress tickets, live work-session timing, and pane interaction."""
import curses
import time
from collections import Counter
from pathlib import Path

from .config import layout_columns
from .cell_ui import CellFocus
from .model import Explorer, state
from .mouse import WHEEL_DOWN, WHEEL_UP
from .squares import date_seconds
from .table_state import Criterion, TableState


def activity_rows(sources, board_slug=None, now=None):
    """One row per project/task, with the newest declared open session only."""
    now = time.time() if now is None else now
    result = []
    for source in sources:
        work = source.work_reader
        sessions = {}
        for session in (work.snapshot or {}).get('sessions', ()):
            subject = session.get('subject') or {}
            if session.get('state') != 'open' or subject.get('provider') != 'kanbn':
                continue
            started = date_seconds(session.get('started_at'))
            rank = (started if started is not None else float('-inf'), session.get('created_seq', 0))
            ref = subject.get('ref')
            if ref not in sessions or rank > sessions[ref][0]:
                sessions[ref] = rank, session
        seen = set()
        for board in source.explorer.boards:
            if board_slug is not None and board['slug'] != board_slug:
                continue
            for task in board['tasks']:
                if task['id'] in seen or state(board, task['column']) != 'active':
                    continue
                seen.add(task['id'])
                entry = sessions.get(task['id'])
                session = entry[1] if entry else None
                start = date_seconds(session.get('started_at')) if session else None
                elapsed = (now - start) * 1000 if start is not None and now >= start and not work.error else None
                phases = session.get('phases', ()) if session else ()
                phase = next((phase for phase in reversed(phases) if phase.get('state') == 'open'), None)
                label = (phase or session or {}).get('label') or 'No open session'
                if work.error:
                    label = 'Work unavailable'
                result.append({
                    'key': (str(source.root), task['id']), 'id': task['id'],
                    'project': Path(source.project_label or source.root.name).name,
                    'board': board.get('name') or board['slug'], 'slug': board['slug'], 'name': task['name'],
                    'description': task.get('description') or '', 'status': task['column'],
                    'metadata': task.get('metadata', {}), 'assigned': task.get('metadata', {}).get('assigned'),
                    'activity': label, 'session': session.get('label', '') if session else '',
                    'started_at': session.get('started_at') if session else None,
                    'elapsed': elapsed, 'live': session is not None and not work.error,
                    'source': source, 'native_board': board, 'task': task,
                    'stale': bool(work.error or source.reader.error),
                })
    # Stable native/project ties, without reshuffling rows on each clock tick.
    return sorted(result, key=lambda row: (not row['live'], -(date_seconds(row['started_at']) or 0)))


class ActivityPane:
    def __init__(self):
        self.shown = False
        self.focused = False
        self.preview_shown = True
        self.rows = []
        self.selected = None
        self.top = 0
        self.capacity = 1
        self.scope = None
        self.rect = None
        self.hits = []
        self.last_click = None
        self.focus = CellFocus()
        self.columns = []
        self.cell_hits = []
        self.header_hits = []
        self.universe = []
        self.state = TableState()

    def reconcile(self, rows, scope):
        old = next((i for i, row in enumerate(self.rows) if row['key'] == self.selected), 0)
        if scope != self.scope:
            self.selected, self.top, old = None, 0, 0
        self.rows, self.scope = rows, scope
        if not any(row['key'] == self.selected for row in rows):
            self.selected = rows[min(old, len(rows) - 1)]['key'] if rows else None
        self.ensure_visible()

    @property
    def current(self):
        return next((row for row in self.rows if row['key'] == self.selected), None)

    def ensure_visible(self):
        index = next((i for i, row in enumerate(self.rows) if row['key'] == self.selected), 0)
        self.top = max(0, min(self.top, max(0, len(self.rows) - self.capacity)))
        self.top = min(self.top, index)
        self.top = max(self.top, index - self.capacity + 1)

    def move(self, delta):
        if self.rows:
            index = next((i for i, row in enumerate(self.rows) if row['key'] == self.selected), 0)
            self.selected = self.rows[max(0, min(len(self.rows) - 1, index + delta))]['key']
            self.ensure_visible()


class ActivityUI:
    @property
    def main_pane_focused(self):
        return not self.activity.focused

    def activity_sources(self):
        return list(self.children.values()) if self.view == 'projects' else [self]

    def activity_columns(self):
        rules = self.catalog.rules if self.view == 'projects' else self.explorer.column_rules
        return [c for c in rules.activity_columns
                if not (c.canonical_field == 'project' and self.view != 'projects')
                and not (c.canonical_field in ('board', 'slug') and self.view == 'tasks')]

    def refresh_activity(self):
        if self.activity.shown and not self.popup:
            board = self.explorer.board_slug if self.view == 'tasks' else None
            pane = self.activity
            scope = (self.view, board)
            if pane.scope != scope:
                pane.state = TableState()
            columns = self.activity_columns()
            pane.state.reconcile(columns)
            pane.universe = activity_rows(self.activity_sources(), board)
            pane.reconcile(pane.state.apply(pane.universe, columns), scope)
            if not pane.rows:
                pane.focus.header = True
            if self.column_menu and self.column_menu.get('table') == 'activity':
                column = next((c for c in columns if c.key == self.column_menu['column'].key), None)
                if column is None or (self.column_menu['mode'] != 'actions' and not column.can_filter):
                    self.column_menu = None
                else:
                    self.column_menu['column'] = column

    def activity_focus_column(self, index):
        pane = self.activity
        if pane.columns:
            pane.focus.index = max(0, min(len(pane.columns) - 1, index))
            column = pane.columns[pane.focus.index][0]
            occurrence = sum(c.key == column.key for c, _ in pane.columns[:pane.focus.index])
            pane.focus.slot = column.key, occurrence

    def activity_context_entries(self, column, row):
        if row is None:
            return []
        if column.canonical_field == 'project':
            return [('Open project', 'openProject')]
        if column.canonical_field in ('board', 'slug'):
            return [('Open board', 'openBoard')]
        if column.canonical_field in ('task', 'description', 'id'):
            return [('Open task', 'openTask')]
        return []

    def open_activity_menu(self, row=None, anchor=None, editor=False):
        pane = self.activity
        if not pane.columns:
            return
        column = pane.columns[pane.focus.index][0]
        if anchor is None:
            anchor = next(((y, x) for y, x, _, i in pane.header_hits if i == pane.focus.index), (4, 5))
        self.column_menu = {'table': 'activity', 'column': column, 'row': row, 'anchor': anchor,
                            'mode': 'actions', 'index': 0, 'top': 0, 'error': '', 'draft': '', 'second': ''}
        if editor:
            self.edit_column_filter()

    def apply_activity_change(self, column, criterion=None, sorting=None, reset_sort=False):
        pane = self.activity
        if reset_sort or sorting is not None:
            pane.state.sort = None if reset_sort else (column.key, sorting)
        elif criterion is None:
            pane.state.filters.pop(column.key, None)
        else:
            pane.state.filters[column.key] = criterion
        self.refresh_activity()
        self.needs_redraw = True

    def activate_activity_cell(self, column, row):
        pane = self.activity
        row = next((current for current in pane.universe if row and current['key'] == row['key']), None)
        if row is None:
            return
        source = row['source']
        if column.canonical_field in ('project', 'board', 'slug'):
            if self.view == 'projects':
                if str(source.root) not in self.children:
                    return
                self.open_project(str(source.root))
            pane.focused = source.activity.focused = False
            source.column_menu = None
            if column.canonical_field in ('board', 'slug'):
                source.explorer.select_board(row['native_board']['slug'])
                source.view = 'tasks'
            else:
                source.view = 'boards'
            source.selected_square = None
            source.cell_columns = []
            source.needs_redraw = self.needs_redraw = True
        elif column.canonical_field in ('task', 'description', 'id'):
            pane.selected = row['key']
            self.open_activity_task()
        elif column.can_filter:
            self.apply_activity_change(column, Criterion('only', column.filter_token(row)))
        else:
            self.open_activity_menu(row=row)

    def poll_activity_clock(self):
        current = None
        if self.activity.shown and not self.popup:
            rules = self.catalog.rules if self.view == 'projects' else self.explorer.column_rules
            if any(row['live'] for row in self.activity.rows) or any(column.is_date for column in rules.activity_columns):
                current = int(time.time())
        if current != self._activity_clock:
            self.needs_redraw = True
            self._activity_clock = current

    def pane_layout(self, preview):
        """Keep the existing eight-row preview, shrinking Activity on short screens."""
        available = self.screen.getmaxyx()[0] - 5
        if not self.activity.shown:
            return available - 9 if preview else available, None, 3 + available - 8 if preview else None
        preview = preview and available >= 20  # Five rows each for the two lists.
        activity_height = min(8, available - 6 - (9 if preview else 0))
        main_height = available - activity_height - 1 - (9 if preview else 0)
        activity_top = 3 + main_height + 1
        preview_top = activity_top + activity_height + 1 if preview else None
        return main_height, (activity_top, activity_height), preview_top

    def draw_activity(self, y, height):
        from .ui import pad
        pane = self.activity
        width = self.screen.getmaxyx()[1]
        pane.rect = y, 1, height, width - 2
        pane.hits = []
        stale = any(row['stale'] for row in pane.rows)
        self.frame(y, height, 'Activity' + (' · STALE' if stale else ''), pane.focused)
        pane.cell_hits, pane.header_hits = [], []
        columns, _ = layout_columns(self.activity_columns(), width, width - 7, pane.rows,
                                    filtered=pane.state.filters, sorting=pane.state.sort)
        counts, slots = Counter(), []
        for column, _ in columns:
            slots.append((column.key, counts[column.key]))
            counts[column.key] += 1
        if pane.focus.slot is None:
            pane.focus.index = next((i for i, (c, _) in enumerate(columns) if c.canonical_field in ('task', 'description', 'id')), 0)
        elif pane.focus.slot in slots:
            pane.focus.index = slots.index(pane.focus.slot)
        pane.columns = columns
        self.activity_focus_column(pane.focus.index)
        x = 3
        for index, (column, size) in enumerate(columns):
            order = pane.state.sort[1] if pane.state.sort and pane.state.sort[0] == column.key else None
            label = column.heading(column.key in pane.state.filters, order)
            attr = self.attr('cyan') | curses.A_BOLD
            if pane.focused and pane.focus.header and pane.focus.index == index:
                attr |= curses.A_REVERSE
            self.put(y + 1, x, pad(label, size, right=column.is_duration), attr)
            pane.header_hits.append((y + 1, x, size, index))
            x += size + 1
        pane.capacity = max(1, height - 3)
        pane.ensure_visible()
        for offset, row in enumerate(pane.rows[pane.top:pane.top + pane.capacity]):
            screen_y = y + 2 + offset
            focused = pane.focused and not pane.focus.header and row['key'] == pane.selected
            if focused:
                self.put(screen_y, 2, '⟦', self.attr('cyan'))
                self.put(screen_y, width - 4, '⟧', self.attr('cyan'))
            x = 3
            for index, (column, size) in enumerate(columns):
                value = column.value(row)
                if column.is_duration:
                    value = value.lstrip()
                color = self.attr('cyan') if column.is_duration else 0
                attr = color | (curses.A_REVERSE | curses.A_BOLD if focused and index == pane.focus.index else 0)
                self.put(screen_y, x, pad(value, size, right=column.is_duration), attr)
                pane.cell_hits.append((screen_y, x, size, row['key'], index))
                x += size + 1
            pane.hits.append((screen_y, row['key']))
        if not pane.rows:
            self.put(y + 2, 3, 'No tickets match Activity filters.' if pane.state.filters else 'No tickets in progress.', self.attr('dim'), width - 7)
        self.draw_scrollbar(y + 2, width - 3, pane.capacity, len(pane.rows), pane.capacity, pane.top, 'activity')

    def activity_preview(self, y):
        row = self.activity.current
        if row:
            self.draw_square_preview(y, (row['source'], row['native_board'], row['task']))
        else:
            self.frame(y, 8, 'Task preview')
            self.preview_rect = y, 1, 8, self.screen.getmaxyx()[1] - 2
            self.put(y + 1, 4, 'No in-progress ticket selected.', self.attr('dim'))

    def open_activity_task(self):
        row = self.activity.current
        if not row:
            return
        child, board, task = row['source'], row['native_board'], row['task']
        original = child.explorer
        saved = child.view, child.popup, child.popup_scroll, child.requested_board
        page = Explorer(board['slug'])
        page.boards, page.column_rules = original.boards, original.column_rules
        page.reconcile()
        projects = self.view == 'projects'
        selected_project = self.selected_project if projects else None
        if projects:
            self.open_project(str(child.root))
        child.explorer = page
        child.view = 'boards'
        child.requested_board = None
        child.popup, child.popup_scroll = ('card', task['id']), 0

        def restore():
            original.boards, original.column_rules = child.explorer.boards, child.explorer.column_rules
            original.reconcile()
            child.explorer = original
            child.view, child.popup, child.popup_scroll, child.requested_board = saved
            if projects:
                self.show_projects()
                if selected_project in self.children:
                    self.selected_project = selected_project
        child.popup_return = restore
        self.activity.last_click = None
        self._last_click = self._square_click = None

    def activity_scroll(self, delta):
        before = self.activity.selected, self.activity.top
        self.activity.move(delta)
        self.needs_redraw |= before != (self.activity.selected, self.activity.top)

    def handle_activity_key(self, key):
        pane = self.activity
        pane.last_click = None
        action = self.bindings.action(key)
        if action == 'toggleActivity':
            pane.shown = not pane.shown
            if not pane.shown:
                pane.focused = False
                pane.rect = None
            self.refresh_activity()
            return True
        if action == 'focusPane':
            if pane.shown:
                pane.focused = not pane.focused
                if pane.focused:
                    pane.preview_shown = True
            return True
        if not pane.focused:
            return False
        if action in ('quit', 'help', 'refresh', 'previousBoard', 'nextBoard'):
            return False
        if action == 'search':
            pane.focused = False
            return False
        if action in ('left', 'right', 'jumpLeft', 'jumpRight'):
            self.activity_focus_column(pane.focus.index + (-1 if action in ('left', 'jumpLeft') else 1))
            return True
        if action == 'columnMenu':
            self.open_activity_menu(row=None if pane.focus.header else pane.current)
            return True
        move = self.key_movement(key, pane.capacity)
        if move:
            if pane.focus.header:
                if move[0] > 0 and pane.rows:
                    pane.focus.header = False
                    pane.selected = pane.rows[min(move[0] - 1, len(pane.rows) - 1)]['key']
                    pane.ensure_visible()
            elif move[0] < 0 and not move[1] and pane.rows and pane.selected == pane.rows[0]['key']:
                pane.focus.header = True
            else:
                self.activity_scroll(move[0])
        elif action in ('first', 'last'):
            self.activity_scroll(-10**9 if action == 'first' else 10**9)
            pane.focus.header = not bool(pane.rows)
        elif action == 'open':
            if pane.focus.header:
                self.open_activity_menu()
            elif pane.columns:
                self.activate_activity_cell(pane.columns[pane.focus.index][0], pane.current)
        elif action == 'back':
            pane.focused = False
        elif action == 'togglePreview':
            pane.preview_shown = not pane.preview_shown
        return True

    def activity_status(self):
        key = self.bindings.label
        status = (f"{key('up', True)} {key('down', True)} tickets · {key('open')} opens · "
                  f"{key('focusPane', True)} main table · {key('toggleActivity', True)} hide")
        pane = self.activity
        if pane.columns:
            column = pane.columns[pane.focus.index][0]
            verb = ('column menu' if pane.focus.header else 'project' if column.canonical_field == 'project' else
                    'board' if column.canonical_field in ('board', 'slug') else 'task' if column.canonical_field in ('task', 'description', 'id') else
                    'filter value' if column.can_filter else 'column menu')
            status = f"{key('left', True)} {key('right', True)} cells · {key('open')} {verb} · {key('columnMenu', True)} actions · {key('focusPane', True)} table"
        if pane.state.filters:
            status = f'{len(pane.state.filters)} Activity filters · ' + status
        if pane.state.sort:
            column = next((c for c in self.activity_columns() if c.key == pane.state.sort[0]), None)
            if column:
                status = f"Sort: {column.label} {'↓' if pane.state.sort[1] else '↑'} · " + status
        if self.activity.focused and self.activity.preview_shown and self.screen.getmaxyx()[0] < 25:
            status = 'Preview needs 25 rows with Activity · ' + status
        return status

    def handle_activity_mouse(self, x, y, buttons):
        pane = self.activity
        if not pane.shown or not pane.rect:
            return False
        top, left, height, width = pane.rect
        inside = left <= x < left + width and top <= y < top + height
        left_click = bool(buttons & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED))
        if left_click and pane.last_click:
            previous_x, previous_y, identity, slot, at = pane.last_click
            if (x, y) == (previous_x, previous_y) and pane.selected == identity and pane.focus.slot == slot and time.monotonic() - at <= .3:
                self.interrupt_wheel()
                if pane.columns:
                    self.activate_activity_cell(pane.columns[pane.focus.index][0], pane.current)
                self.needs_redraw = True
                return True
        up, down = bool(buttons & WHEEL_UP), bool(buttons & WHEEL_DOWN)
        if up or down:
            if not inside:
                if 3 <= y < top - 1:
                    self.needs_redraw |= pane.focused
                    pane.focused = False
                return False
            self._wheel_input = True
            before = pane.focused, pane.preview_shown
            pane.focused = pane.preview_shown = True
            self.needs_redraw |= before != (pane.focused, pane.preview_shown)
            if up != down:
                delta = -3 if up else 3
                if self.wheel_gesture.accept(delta, time.monotonic()):
                    self.activity_scroll(delta)
            return True
        if not inside:
            if left_click and 3 <= y < top - 1:
                pane.focused = False
            return False
        right_click = bool(buttons & (curses.BUTTON3_PRESSED | curses.BUTTON3_CLICKED))
        if not left_click and not right_click:
            return True
        self.interrupt_wheel()
        pane.focused = pane.preview_shown = True
        self.needs_redraw = True
        self._last_click = self._square_click = None
        bar = next((bar for bar in self.scrollbars if bar['kind'] == 'activity' and bar['x'] == x), None)
        if bar and bar['y'] <= y < bar['y'] + bar['height']:
            position = y - bar['y']
            if position < bar['thumb_top']:
                self.activity_scroll(-pane.capacity)
            elif position >= bar['thumb_top'] + bar['thumb_size']:
                self.activity_scroll(pane.capacity)
            return True
        for row_y, x_left, size, index in pane.header_hits:
            if row_y == y and x_left <= x < x_left + size:
                pane.focus.header = True
                self.activity_focus_column(index)
                self.open_activity_menu(anchor=(y, x_left))
                return True
        for row_y, x_left, size, identity, index in pane.cell_hits:
            if row_y == y and x_left <= x < x_left + size:
                pane.selected = identity
                pane.focus.header = False
                self.activity_focus_column(index)
                if right_click:
                    self.open_activity_menu(row=pane.current, anchor=(y, x))
                else:
                    pane.last_click = x, y, identity, pane.focus.slot, time.monotonic()
                    if buttons & curses.BUTTON1_DOUBLE_CLICKED:
                        self.activate_activity_cell(pane.columns[index][0], pane.current)
                return True
        return True
