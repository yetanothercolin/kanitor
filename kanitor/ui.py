"""A single-pane curses explorer for boards, native tasks, and details."""
import curses
from datetime import datetime
from pathlib import Path
import textwrap
import time

from .model import card_details, counts, display, state
from .reader import LiveReader
from .config import BOARD_COUNTS, Column, layout_columns
from .mouse import SgrMouseInput, WHEEL_DOWN, WHEEL_UP, WheelGesture
from .text import cells, clean
from .work.reader import WorkReader
from .squares import SquareView, board_squares, latest_work, merge_project_squares
from .table import RowViewport
from .cell_ui import CellUI
from .activity import ActivityPane, ActivityUI
from .keybindings import ACTION_DESCRIPTIONS, DEFAULT_BINDINGS, key_token

PREVIEW_HEIGHT = 8

HELP = '''TABLES AND MENUS

Move between cells and rows in Projects, Boards, and Tasks. Moving up from
the first data row selects that column's header. Open activates the focused
row, square, or header menu. Back closes menus or returns to the parent view;
Left also closes details. Clicking another row focuses its cell; clicking the
focused row opens it. Click a header or right-click a cell for column actions.
Disabled headers remain selectable. ▾ marks a filter; ↑/↓ marks a sort.

Enum filters: navigation selects an option; Open toggles it; Back closes.
String filters search case-insensitive substrings; Description searches name
and body. Date filters offer Today, Yesterday, Last 7/30 days, On, Before,
After, Between. Custom dates use YYYY-MM-DD and local calendar boundaries.
Before/After exclude that day; Between includes both ends. Relative filters
update at midnight. Columns combine with AND; enum values use OR.
One runtime sort per table, missing values last. Reset restores native tasks,
declared projects, or newest-first boards. Board updated is the latest of
its file mtime and valid task updated dates. Filters/sorts never edit files.

TEXT ENTRY

In search and text/date editors, printable keys type text, including keys
bound to actions elsewhere. Enter applies, Escape cancels, Backspace deletes,
and Ctrl+U clears. Up/Down selects the two fields in a Between date editor.
These editing keys are fixed. Space pages details/help while bound to Open;
other Open keys have no action there. Use Page Down to configure scrolling.
Tab and Shift+Tab switch focus when the Activity pane is shown.

MOUSE AND PREVIEWS

Wheel scrolling pauses below headers at the first row. Wait 200 ms without
wheel input, then scroll up again to reach headers. Opposite direction responds
immediately. Scrollbars show position; click above/below the thumb to page.
Task description previews occupy eight rows, accept no input, and hide when
the terminal is shorter than 19 rows.

ACTIVITY

Toggle Activity shows in-progress tickets; Switch Pane moves focus between
the main table and Activity. Activity spans all projects in Projects, all boards
in Boards, and the current board in Tasks, independently of table filters.
Its elapsed counter follows the latest open task-linked work session, not time
in status. Tickets without an open session show an unknown elapsed value.
Activity shows the current work phase/session label and project/board context.
Navigate tickets to preview descriptions. Move horizontally to select cells;
Open on Project/Board goes there, on Task reads details, and on Assigned filters
Activity to that value. Up from the first row selects headers. Header Open/click
or Column Menu/right-click opens filter/sort actions. Back returns focus to the table.
Activity is eight rows when space permits. With Activity, previews need at least
25 terminal rows. Activity columns use activityColumns in configuration.

TASK SQUARES

Move horizontally into Task Status from either side to select a square. Horizontal moves
select squares, then adjacent cells. Vertical moves follow wrapping and rows,
maintaining the preferred position. Click previews; double-click or Open reads
that task. Toggle Preview shows/hides its description. Cyan brackets surround
the focused row; a reverse highlight marks only the focused cell or square.
Jump Left/Right moves five squares, clamping at the ends; a further jump exits
to the adjacent cell. In other table cells and headers, it moves one cell.
Solid green: recent completion. Pulsing hollow green: recent active work.
Pulsing yellow: possibly stale active work. Dim hollow green: paused.
White hollow: recently created, never started; dim white: older, never started.
Old completions are hidden. Active positions stay stable within this view.

Change cards through kanbn. Kanitor follows files and configuration live.
Errors mark the last successful snapshot STALE until a fresh read succeeds.
'''




def clip(text, width):
    result, used = [], 0
    for char in clean(text):
        size = cells(char)
        if used + size > width:
            break
        result.append(char)
        used += size
    return ''.join(result)


def pad(text, width, right=False):
    text = clip(text, width)
    space = ' ' * max(0, width - cells(text))
    return space + text if right else text + space


def wrap_lines(text, width):
    # textwrap breaks long words; the second pass also handles wide Unicode glyphs.
    result = []
    for line in text.expandtabs(4).splitlines():
        for part in textwrap.wrap(clean(line), max(1, width), replace_whitespace=False, drop_whitespace=False) or ['']:
            while cells(part) > width:
                prefix = clip(part, width)
                result.append(prefix)
                part = part[len(prefix):]
            result.append(part)
    return result


def movement(key, page_size):
    """Normalize basic and terminal-specific modified vertical navigation."""
    return DEFAULT_BINDINGS.movement(key, page_size)


class App(ActivityUI, CellUI):
    def __init__(self, screen, root, explorer, start_in_board=False):
        self.screen, self.root, self.explorer = screen, root, explorer
        self.reader = LiveReader(root)
        self.revision = -1
        self.view = 'tasks' if start_in_board else 'boards'
        self.task_top = self.board_top = 0
        self.task_height = self.board_height = 1
        self.task_visible_ids = []
        self.popup = None
        self.popup_scroll = 0
        self.searching = False
        self.search_before = ''
        self.hits = []
        self.popup_max = 0
        self.popup_height = 1
        self.colors = {}
        self.notice = ''
        self.requested_board = explorer.board_slug
        self._last_click = None
        self.task_header_selected = False
        self.status_header = None
        self.filter_headers = []
        self.scrollbars = []
        self.hidden_columns = 0
        self.task_header_y = 4
        self.show_preview = True
        self.preview_rect = None
        self.needs_redraw = True
        self._wheel_input = False
        self.mouse_input = None
        self.wheel_gesture = WheelGesture()
        self.work_reader = WorkReader(root)
        self.project_link = None
        self.on_projects = None
        self.project_label = None
        self._reader_state = None
        self._date_state = None
        self._date_checked = 0
        self.square_view = SquareView()
        self.summary_table = RowViewport()
        self.summary_ids = []
        self.squares_visible = self.squares_animated = False
        self._square_signature = None
        self._square_work_key = None
        self._square_work = {}
        self._square_data_key = None
        self._square_data = {}, []
        self.selected_square = None
        self.square_column_goal = None
        self.square_preview_shown = True
        self.square_hits = []
        self.square_positions = {}
        self._square_scroll_request = False
        self.popup_return = None
        self._square_click = None
        self.init_cells()
        self.activity = ActivityPane()
        self._activity_clock = None

    def help_text(self):
        lines = ['KANITOR · read-only kanbn explorer', '', 'KEY BINDINGS (CURRENT PROJECT / WORKSPACE)', '']
        lines.extend(f'{self.bindings.label(action):<30} {description}'
                     for action, description in ACTION_DESCRIPTIONS.items())
        return '\n'.join(lines) + '\n\n' + HELP

    def table_footer(self):
        key = self.bindings.label
        if self.popup:
            return (f"{key('up', True)} {key('down', True)} scroll · {key('pageUp', True)} {key('pageDown', True)} page · "
                    f"{key('back', True)} back · {key('quit', True)} close")
        if self.searching:
            return 'Enter applies · Esc cancels · Backspace deletes · Ctrl+U clears'
        if self.column_menu:
            return self.menu_navigation_hint()
        if self.activity.focused:
            return self.activity_status()
        pane_hint = f" · {key('focusPane', True)} pane" if self.activity.shown else ''
        return (f"{key('left', True)} {key('right', True)} cells · "
                f"{key('up', True)} {key('down', True)} rows · {key('open')} open · "
                f"{key('toggleActivity', True)} activity{pane_hint} · "
                f"{key('columnMenu', True)} columns · {key('back', True)} back · "
                f"{key('help', True)} help · {key('quit', True)} quit")

    def square_navigation_hint(self):
        key = self.bindings.label
        return (f"{key('left', True)} {key('right', True)} / {key('up', True)} {key('down', True)} select task · "
                f"{key('open')} opens · {key('back', True)} back · {key('togglePreview', True)} preview")

    def menu_navigation_hint(self):
        if self.column_menu and self.column_menu['mode'] in ('string', 'date_input'):
            return 'Enter applies · Esc cancels'
        key = self.bindings.label
        return f"{key('up', True)} {key('down', True)} select · {key('open')} apply · {key('back', True)} close"

    def draw_summary(self, summary):
        self.project_link = None
        x = 2
        if self.on_projects:
            self.put(1, x, '‹ Projects', self.attr('cyan'))
            self.project_link = x, 10
            x += 12
        self.put(1, x, summary, width=self.screen.getmaxyx()[1] - x - 3)

    def breadcrumb(self):
        project = Path(self.project_label).name if self.project_label else self.root.name
        parts = ['KANITOR', project]
        task_id = self.popup[1] if isinstance(self.popup, tuple) and self.popup[0] == 'card' else None
        board = self.explorer.board
        if board and (self.view == 'tasks' or task_id):
            parts.append(board.get('name') or board['slug'])
            if task_id:
                parts.append(task_id)
        return ' / '.join(parts)

    def setup(self):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.screen.keypad(True)
        # A lone Escape must not wait for ncurses' one-second key-sequence timeout.
        curses.set_escdelay(25)
        self.screen.timeout(100)
        if curses.has_colors():
            curses.start_color()
            background = -1
            try:
                curses.use_default_colors()
            except curses.error:
                background = curses.COLOR_BLACK
            # Teal structure, mauve borders, and green/yellow status marks.
            palette = {'cyan': curses.COLOR_CYAN, 'focus': curses.COLOR_MAGENTA,
                       'done': curses.COLOR_GREEN, 'active': curses.COLOR_YELLOW,
                       'error': curses.COLOR_RED, 'dim': curses.COLOR_WHITE}
            if curses.COLORS >= 256:
                palette.update(cyan=116, focus=181, done=150, active=222, error=210, dim=244)
                palette.update(square_green0=65, square_green1=107, square_green2=150,
                               square_yellow0=136, square_yellow1=178, square_yellow2=222,
                               square_white=252)
            for number, (name, foreground) in enumerate(palette.items(), 1):
                curses.init_pair(number, foreground, background)
                self.colors[name] = curses.color_pair(number)
        try:
            # Get presses immediately; recognize double clicks ourselves without
            # delaying selection while curses waits for another click.
            curses.mouseinterval(0)
            if hasattr(curses, 'BUTTON5_PRESSED'):
                mask = (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED |
                        curses.BUTTON1_DOUBLE_CLICKED | curses.BUTTON3_PRESSED | curses.BUTTON3_CLICKED | WHEEL_UP | WHEEL_DOWN)
                curses.mousemask(mask)
            else:
                self.mouse_input = SgrMouseInput(self.screen)
                self.mouse_input.start()
        except curses.error:
            pass

    def read_key(self):
        return self.mouse_input.get_wch() if self.mouse_input else self.screen.get_wch()

    def get_mouse(self):
        return self.mouse_input.getmouse() if self.mouse_input else curses.getmouse()

    def set_input_timeout(self, delay):
        if self.mouse_input:
            self.mouse_input.timeout(delay)
        else:
            self.screen.timeout(delay)

    def interrupt_wheel(self):
        self._wheel_boundary_armed = False
        self._wheel_boundary_stopped = False
        if self.wheel_gesture.last_at is not None:
            self.wheel_gesture.interrupt(time.monotonic())

    def attr(self, name):
        return self.colors.get(name, curses.A_DIM if name == 'dim' else 0)

    def put(self, y, x, text, attr=0, width=None):
        height, columns = self.screen.getmaxyx()
        if not (0 <= y < height and 0 <= x < columns):
            return
        text = clip(text, max(0, min(columns - x - 1, width if width is not None else columns)))
        try:
            self.screen.addstr(y, x, text, attr)
        except curses.error:
            pass  # Some terminals reject the bottom-right cell during resize.

    def frame(self, y, height, title, focus=False):
        _, width = self.screen.getmaxyx()
        color = self.attr('focus' if focus else 'cyan')
        self.put(y, 1, '┌' + '─' * (width - 4) + '┐', color)
        for row in range(y + 1, y + height - 1):
            self.put(row, 1, '│', color)
            self.put(row, width - 2, '│', color)
        self.put(y + height - 1, 1, '└' + '─' * (width - 4) + '┘', color)
        self.put(y, 4, f' {clip(title, width - 9)} ', color | curses.A_BOLD)

    def draw_scrollbar(self, y, x, height, total, visible, offset, kind):
        if total <= visible or height < 1:
            return
        offset = max(0, min(offset, total - visible))
        thumb_size = max(1, min(height - 1, height * visible // total))
        thumb_top = round(offset * (height - thumb_size) / (total - visible))
        for row in range(height):
            thumb = thumb_top <= row < thumb_top + thumb_size
            self.put(y + row, x, '█' if thumb else '░', self.attr('cyan' if thumb else 'dim'))
        self.scrollbars.append({'kind': kind, 'y': y, 'x': x, 'height': height,
                                'thumb_top': thumb_top, 'thumb_size': thumb_size,
                                'visible': visible})

    def scroll(self, delta, page=False):
        if self.popup:
            self.popup_scroll = max(0, min(self.popup_max, self.popup_scroll + delta))
        elif page and self.view == 'boards' and self.summary_table.multiline:
            index = next((i for i, board in enumerate(self.explorer.display_boards) if board['slug'] == self.explorer.board_slug), 0)
            index, self.board_top = self.summary_table.move(index, self.board_top, delta, page=True)
            if self.explorer.boards:
                self.explorer.select_board(self.explorer.display_boards[index]['slug'])
        else:
            self.navigate(delta)
            if page and self.view == 'boards':
                self.board_top = max(0, min(len(self.explorer.display_boards) - self.board_height, self.board_top + delta))
            elif page:
                self.task_top = max(0, min(len(self.explorer.rows) - self.task_height, self.task_top + delta))

    def scroll_wheel(self, delta):
        if self.activity.focused and not self.popup and not self.column_menu:
            self.activity_scroll(delta)
            return
        before = (self.popup_scroll, self.focused_row_id(), self.focus.header,
                  self.board_top, self.task_top, self.selected_square,
                  self.column_menu['index'] if self.column_menu else None)
        if not self.popup:
            self.table_wheel(delta)
        else:
            self.scroll(delta)
        after = (self.popup_scroll, self.focused_row_id(), self.focus.header,
                 self.board_top, self.task_top, self.selected_square,
                 self.column_menu['index'] if self.column_menu else None)
        self.needs_redraw |= before != after

    def scroll_table_wheel(self, delta):
        if self.view == 'boards' and self.summary_table.multiline:
            rows = self.explorer.board_rows
            index = next((i for i, row in enumerate(rows) if row['slug'] == self.explorer.board_slug), 0)
            index, self.board_top = self.summary_table.move(index, self.board_top, delta)
            if rows:
                self.explorer.select_board(rows[index]['slug'])
        elif self.view == 'tasks':
            self.explorer.move_task(delta)
        else:
            self.scroll(delta)
        if self.selected_square and self.selected_square[0] != self.focused_row_id():
            self.selected_square = None

    def drain_wheel_burst(self):
        """Process already queued wheel input before repainting; preserve the next key."""
        deadline = time.monotonic() + 0.008
        self.set_input_timeout(0)
        try:
            while time.monotonic() < deadline:
                try:
                    key = self.read_key()
                except curses.error:
                    break
                if key != curses.KEY_MOUSE:
                    return key
                self.mouse()
                if not self._wheel_input:
                    break
        finally:
            self.set_input_timeout(100)
        return None

    def click_scrollbar(self, x, y):
        kind = 'popup' if self.popup else self.view
        for bar in self.scrollbars:
            if bar['kind'] != kind or x != bar['x'] or not bar['y'] <= y < bar['y'] + bar['height']:
                continue
            position = y - bar['y']
            if position < bar['thumb_top']:
                self.scroll(-bar['visible'], page=True)
            elif position >= bar['thumb_top'] + bar['thumb_size']:
                self.scroll(bar['visible'], page=True)
            self._last_click = None
            return True
        return False

    def draw(self):
        self.square_view.enter('boards' if self.view == 'boards' and not self.popup else None)
        self.squares_visible = self.squares_animated = False
        self.screen.erase()
        self.hits = []
        self.square_hits = []
        self.scrollbars = []
        self.status_header = None
        self.filter_headers = []
        self.hidden_columns = 0
        self.preview_rect = None
        self.project_link = None
        self.activity.rect = None
        height, width = self.screen.getmaxyx()
        if width < 60 or height < 16:
            self.put(0, 0, 'KANITOR · terminal needs at least 60 × 16', self.attr('cyan'))
            self.put(2, 0, f'Current size: {width} × {height}. Resize, or q to quit.')
            self.screen.refresh()
            return
        board = self.explorer.board
        self.put(0, 2, self.breadcrumb(), self.attr('cyan') | curses.A_BOLD, width - 28)
        error = self.reader.error
        loaded = bool(board)
        status = 'STALE' if error else 'LIVE' if loaded else 'LOADING'
        self.put(0, width - 23, 'READ ONLY · ' + status, self.attr('error' if error else 'cyan'))
        if board and self.view == 'tasks':
            totals = counts(board)
            summary = f"{totals['done']} done  │  {totals['active']} active  │  {totals['remaining']} remaining  │  {len(self.explorer.boards)} boards"
        elif board:
            summary = f'{len(self.explorer.boards)} boards'
        else:
            summary = 'Reading native kanbn boards…'
        self.draw_summary(summary)
        self.put(2, 2, str(self.root), self.attr('dim'), width - 5)
        self.refresh_activity()
        if self.popup:
            self.draw_popup()
        else:
            source = None
            if self.view == 'boards':
                rows, columns = self.board_layout()
                self.table_setup(columns)
                self.prepare_square_focus(rows)
                source = self.square_preview()
                preview = bool(source) and height >= 19
            else:
                preview = self.show_preview and height >= 19
            if self.activity.focused:
                preview = self.activity.preview_shown
            list_height, activity_rect, preview_top = self.pane_layout(preview)
            if self.view == 'boards':
                self.draw_boards(3, list_height, rows, columns)
            else:
                self.draw_tasks(3, list_height)
            if activity_rect:
                self.draw_activity(*activity_rect)
            if preview_top is not None:
                if self.activity.focused:
                    self.activity_preview(preview_top)
                elif self.view == 'boards':
                    self.draw_square_preview(preview_top, source)
                else:
                    self.draw_preview(preview_top)
        status = self.reader.error or self.notice
        if not status:
            status = f"Select a board and press {self.bindings.label('open')} to open." if self.view == 'boards' else f"Filters: {self.explorer.filter_summary}  ·  Search: {self.explorer.query or '—'}"
            if self.hidden_columns and not self.popup:
                status = f'{self.hidden_columns} columns hidden; widen terminal · ' + status
            needed = 25 if self.activity.shown else 19
            if self.view == 'tasks' and self.show_preview and height < needed and not self.popup:
                status = f"Preview needs {needed} rows; resize or {self.bindings.label('togglePreview', True)} to hide · " + status
        if self.squares_visible and self.work_reader.error and not self.reader.error:
            status = 'Work unavailable; active squares may be stale · ' + status
        if self.view == 'boards' and self.selected_square and not self.popup:
            status = self.square_navigation_hint()
            needed = 25 if self.activity.shown else 19
            if height < needed and self.square_preview_shown:
                status = f'Task preview needs {needed} rows · ' + status
        if self.activity.focused and not self.popup:
            status = self.reader.error or self.activity_status()
        if self.searching:
            status = '/' + self.explorer.query + '▏  (Enter applies · Esc cancels)'
        elif self.column_menu:
            status = self.menu_navigation_hint()
        if not self.popup and not self.searching:
            status = self.table_status() + (' · ' if self.table_status() else '') + status
        self.put(height - 2, 2, status, self.attr('error' if self.reader.error and not self.searching else 'cyan'), width - 5)
        footer = self.table_footer()
        self.put(height - 1, 2, footer, self.attr('cyan'), width - 4)
        if self.column_menu and not self.popup:
            self.draw_column_menu()
        self.screen.refresh()

    def board_layout(self):
        width = self.screen.getmaxyx()[1]
        rows = self.explorer.board_rows
        if any(column.field == 'task_squares' for column in self.explorer.column_rules.board_columns):
            badges, _ = self.square_data(self.explorer.column_rules.square_rules)
            for row in rows:
                row['task_squares'] = self.square_view.bundle(row['slug'],
                    badges.get(row['slug'], []),
                    freeze=self.work_reader.snapshot is not None or bool(self.work_reader.error))
        columns, self.hidden_columns = layout_columns(self.explorer.column_rules.board_columns, width, width - 7, rows, filtered=self.table_state.filters, sorting=self.table_state.sort)
        return rows, columns

    def draw_boards(self, y, height, rows=None, columns=None):
        width = self.screen.getmaxyx()[1]
        self.frame(y, height, 'Boards', self.main_pane_focused)
        if rows is None:
            rows, columns = self.board_layout()
        self.table_setup(columns)
        x = 3
        for column_index, (column, column_width) in enumerate(columns):
            self.put(y + 1, x, pad(self.heading(column), column_width, right=column.field in BOARD_COUNTS), self.header_attr(column_index))
            self.add_header_hit(y + 1, x, column_width, column_index)
            x += column_width + 1
        capacity = max(1, height - 4)
        self.board_height = capacity
        index = next((i for i, b in enumerate(self.explorer.display_boards) if b['slug'] == self.explorer.board_slug), 0)
        self.board_top = self.draw_summary_rows(rows, columns, y + 2, capacity, index, self.board_top, 'slug', 'board')
        if not rows:
            self.put(y + 2, 3, 'No boards match the filters.', self.attr('dim'))
        selected_board = self.explorer.board
        if selected_board:
            self.put(y + height - 2, 3, selected_board.get('description') or selected_board['name'], self.attr('dim'), width - 7)
        self.draw_scrollbar(y + 2, width - 3, capacity, self.summary_table.total, capacity, self.board_top, 'boards')

    def square_work(self):
        key = self.work_reader.revision, self.work_reader.error
        if key != self._square_work_key:
            self._square_work_key = key
            self._square_work = latest_work(self.work_reader.snapshot) if not self.work_reader.error else {}
        return self._square_work

    def square_data(self, rules):
        now = time.time()
        key = (id(self.explorer.boards), self.reader.revision, self.work_reader.revision,
               self.work_reader.error, int(now), rules)
        if key != self._square_data_key:
            self._square_data_key = key
            work = self.square_work()
            boards = {board['slug']: board_squares(board, work, now, rules) for board in self.explorer.boards}
            self._square_data = boards, merge_project_squares(boards.values())
        return self._square_data

    def square_attr(self, square, phase):
        if square.pulse:
            color = 'green' if square.kind == 'active' else 'yellow'
            key = f'square_{color}{phase}'
            if key in self.colors:
                return self.colors[key]
            return self.attr('done' if color == 'green' else 'active') | (curses.A_DIM if phase == 0 else curses.A_BOLD if phase == 2 else 0)
        if square.kind in ('done', 'paused'):
            return self.attr('done') | (curses.A_DIM if square.kind == 'paused' else 0)
        return self.colors.get('square_white', self.colors.get('dim', 0)) | (curses.A_DIM if square.kind == 'old' else 0)

    def draw_summary_rows(self, rows, columns, y, capacity, selected, top, identity, kind):
        width = self.screen.getmaxyx()[1]
        prepared, heights = [], []
        for row in rows:
            wrapped = {index: row['task_squares'].lines(size) for index, (column, size) in enumerate(columns)
                       if column.field == 'task_squares'}
            prepared.append(wrapped)
            heights.append(max((len(lines) for lines in wrapped.values()), default=1))
        old = self.summary_table
        table = RowViewport(heights, capacity)
        keys = [row[identity] for row in rows]
        self.square_positions = {}
        first_square = next((index for index, (column, _) in enumerate(columns) if column.field == 'task_squares'), None)
        for index, row in enumerate(rows):
            if first_square is not None:
                self.square_positions[row[identity]] = [(table.starts[index] + line, position * 2, square)
                    for line, squares in enumerate(prepared[index][first_square]) for position, square in enumerate(squares)]
        if self.selected_square and not any(square.id == self.selected_square[1]
                for _, _, square in self.square_positions.get(self.selected_square[0], [])):
            self.selected_square = None
        if old.heights and self.summary_ids:
            anchor = old.index(top)
            if self.summary_ids[anchor] in keys:
                top = table.starts[keys.index(self.summary_ids[anchor])] + top - old.starts[anchor]
        top = table.ensure(selected, top)
        if self._square_scroll_request and self.selected_square:
            line = next((line for line, _, square in self.square_positions.get(self.selected_square[0], [])
                         if square.id == self.selected_square[1]), None)
            if line is not None:
                top = max(0, min(table.maximum, min(top, line) if line < top else max(top, line - capacity + 1)))
            self._square_scroll_request = False
        self.summary_table, self.summary_ids = table, keys
        # Three color levels over a slow triangular cycle; never terminal blink.
        phase = (0, 0, 1, 1, 2, 2, 1, 1)[int(time.monotonic() / .35) % 8]
        for index, row in enumerate(rows):
            start, end = table.starts[index:index + 2]
            if end <= top or start >= top + capacity:
                continue
            for line in range(max(start, top), min(end, top + capacity)):
                screen_y = y + line - top
                self.put(screen_y, 3, ' ' * (width - 7))
                if index == selected:
                    self.draw_row_focus(screen_y, line - start, end - start)
                x = 3
                for column_index, (column, size) in enumerate(columns):
                    self.add_cell_hit(screen_y, x, size, row[identity], column_index)
                    if column.field == 'task_squares':
                        self.squares_visible = True
                        if self.selected_square is None:
                            self.put(screen_y, x, ' ' * size, self.cell_attr(column_index, index == selected))
                        lines = prepared[index][column_index]
                        if line - start < len(lines):
                            for position, square in enumerate(lines[line - start]):
                                self.squares_animated |= square.pulse
                                focused = (self.main_pane_focused and not self.focus.header and self.focus.index == column_index
                                           and self.selected_square == (row[identity], square.id))
                                square_attr = self.square_attr(square, phase)
                                if focused:
                                    square_attr = (square_attr & ~curses.A_DIM) | curses.A_REVERSE | curses.A_BOLD
                                self.put(screen_y, x + position * 2, square.glyph,
                                    square_attr, 1)
                                self.square_hits.append((screen_y, x + position * 2, row[identity], square))
                    elif line == max(start, top):
                        color = (self.attr('error') if column.field == 'state' and row.get('error') else
                                 self.attr('cyan') if column.field == 'slug' or column.metadata is not None else
                                 self.attr(column.field) if column.field in ('active', 'done') else 0)
                        self.put(screen_y, x, pad(column.value(row), size, right=column.field in (*BOARD_COUNTS, 'boards')), color | self.cell_attr(column_index, index == selected))
                    x += size + 1
                self.hits.append((screen_y, kind, row[identity]))
        return top

    def current_summary_id(self):
        return self.explorer.board_slug

    def select_summary_row(self, identity):
        self.explorer.select_board(identity)

    def resolve_square(self, row, square):
        board = next((board for board in self.explorer.boards if board['slug'] == (square.board or row)), None)
        task = next((task for task in board['tasks'] if task['id'] == square.id), None) if board else None
        return (self, board, task) if task else None

    def focused_square(self):
        if not self.selected_square:
            return None
        if self.selected_square[0] != self.current_summary_id():
            self.selected_square = None
            return None
        row, identity = self.selected_square
        columns = layout_columns(self.explorer.column_rules.board_columns, self.screen.getmaxyx()[1],
                                 self.screen.getmaxyx()[1] - 7)[0]
        squares = self.square_data(self.explorer.column_rules.square_rules)[0].get(row, [])
        square = next((square for square in squares if square.id == identity), None)
        if square and any(column.field == 'task_squares' for column, _ in columns):
            return square
        self.selected_square = None
        return None

    def select_square(self, row, square, preserve_column=False):
        self.select_summary_row(row)
        if not preserve_column:
            self.square_column_goal = None
        self.selected_square = row, square.id
        self.square_preview_shown = True
        self._square_scroll_request = True

    def square_preview(self):
        square = self.focused_square()
        return self.resolve_square(self.selected_square[0], square) if square and self.square_preview_shown else None

    def draw_square_preview(self, y, source):
        _, board, task = source
        width = self.screen.getmaxyx()[1]
        self.frame(y, PREVIEW_HEIGHT, 'Task · ' + task['name'])
        self.preview_rect = y, 1, PREVIEW_HEIGHT, width - 2
        lines = [f"{board['slug']} · {task['id']} · {task['column']}"]
        lines += wrap_lines(task.get('description') or 'No description.', width - 9)
        for offset, line in enumerate(lines[:PREVIEW_HEIGHT - 2]):
            if offset == PREVIEW_HEIGHT - 3 and len(lines) > PREVIEW_HEIGHT - 2:
                line = clip(line, width - 11) + ' …'
            self.put(y + 1 + offset, 4, line, width=width - 9)

    def open_square(self, row, square):
        source = self.resolve_square(row, square)
        if source:
            _, board, task = source
            self.explorer.select_board(board['slug'])
            self.popup, self.popup_scroll = ('card', task['id']), 0
            self._last_click = None
            self._square_click = None

    def close_popup(self):
        self.popup = None
        self._square_scroll_request = bool(self.selected_square)
        callback, self.popup_return = self.popup_return, None
        if callback:
            callback()

    def click_square(self, x, y, buttons):
        for row, left, identity, square in self.square_hits:
            if row == y and x == left:
                now = time.monotonic()
                target = 'square', identity, square.id
                double = bool(buttons & curses.BUTTON1_DOUBLE_CLICKED)
                if self._last_click:
                    previous, at = self._last_click
                    double |= previous == target and now - at <= .3
                self._last_click = target, now
                self._square_click = x, y, identity, square.id, now
                self.select_square(identity, square)
                if double:
                    self.open_square(identity, square)
                return True
        return False

    def repeat_square_click(self, x, y, buttons):
        # Opening the preview may reflow the list between two presses. Preserve
        # the original hit target for a double-click at those same coordinates.
        if not self._square_click or not buttons & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
            return False
        left, row, identity, task_id, at = self._square_click
        if (x, y) != (left, row) or time.monotonic() - at > .3 or self.selected_square != (identity, task_id):
            return False
        square = self.focused_square()
        if square:
            self.interrupt_wheel()
            self.needs_redraw = True
            self._square_click = None
            self.open_square(identity, square)
            return True
        return False

    def handle_square_key(self, key):
        action = self.bindings.action(key)
        row = self.current_summary_id()
        positions = self.square_positions.get(row, [])
        if not self.selected_square:
            return False
        square = self.focused_square()
        if not square:
            return False
        if action == 'back':
            self.selected_square = None
            self.square_column_goal = None
            return True
        if action == 'open':
            self.open_square(self.selected_square[0], square)
            return True
        if action == 'togglePreview':
            self.square_preview_shown = not self.square_preview_shown
            return True
        index = next((i for i, (_, _, item) in enumerate(positions) if item.id == square.id), None)
        if index is None:
            return False
        if action in ('left', 'right', 'first', 'last'):
            target = (0 if action == 'first' else len(positions) - 1 if action == 'last'
                      else max(0, min(len(positions) - 1, index + (-1 if action == 'left' else 1))))
        else:
            move = self.key_movement(key, self.project_height if self.view == 'projects' else self.board_height)
            if move is None:
                return False
            delta, page = move
            if page:
                attribute = 'project_top' if self.view == 'projects' else 'board_top'
                setattr(self, attribute, max(0, min(self.summary_table.maximum, getattr(self, attribute) + delta)))
            if abs(delta) == 10 and not page:
                target = max(0, min(len(positions) - 1, index + delta))
            else:
                line, column, _ = positions[index]
                destination = line + delta
                if not page and not 0 <= destination < self.summary_table.total:
                    return True
                destination = max(0, min(self.summary_table.total - 1, destination))
                destination_row = self.summary_ids[self.summary_table.index(destination)]
                candidates = [item for item in self.square_positions.get(destination_row, []) if item[0] == destination]
                if not candidates:
                    self.select_summary_row(destination_row)
                    self.selected_square = None
                    self.square_column_goal = column if self.square_column_goal is None else self.square_column_goal
                    return True
                goal = column if self.square_column_goal is None else self.square_column_goal
                target_square = min(candidates, key=lambda item: abs(item[1] - goal))[2]
                self.select_square(destination_row, target_square, preserve_column=True)
                self.square_column_goal = goal
                return True
        self.select_square(row, positions[target][2])
        return True

    def draw_tasks(self, y, height):
        width = self.screen.getmaxyx()[1]
        rows = self.explorer.rows
        board = self.explorer.board
        index = next((i for i, card in enumerate(rows) if card['id'] == self.explorer.selected_id), 0)
        self.frame(y, height, f"{self.explorer.board_slug or 'KANBN'} * {self.explorer.filter_summary}", self.main_pane_focused)
        columns, self.hidden_columns = self.table_layout()
        self.task_header_y = y + 1
        self.table_setup(columns)
        x = 5
        for column_index, (column, column_width) in enumerate(columns):
            self.filter_headers.append((y + 1, x, column_width, column))
            if column.field == 'status':
                self.status_header = (y + 1, x, column_width)
            self.put(y + 1, x, pad(self.heading(column), column_width), self.header_attr(column_index))
            self.add_header_hit(y + 1, x, column_width, column_index)
            x += column_width + 1
        capacity = max(1, height - 4)
        self.task_height = capacity
        identities = [row['id'] for row in rows]
        if self.task_visible_ids and self.task_top < len(self.task_visible_ids):
            anchor = self.task_visible_ids[self.task_top]
            if identities != self.task_visible_ids and anchor in identities:
                self.task_top = identities.index(anchor)
        self.task_visible_ids = identities
        self.task_top = max(0, min(self.task_top, index))
        self.task_top = max(self.task_top, index - capacity + 1)
        self.task_top = min(self.task_top, max(0, len(rows) - capacity))
        for offset, card in enumerate(rows[self.task_top:self.task_top + capacity]):
            row = y + 2 + offset
            selected = card['id'] == self.explorer.selected_id
            self.put(row, 3, ' ' * (width - 7))
            if selected:
                self.draw_row_focus(row)
            status = state(board, card['column'])
            self.put(row, 3, '□' if status == 'remaining' else '■', self.attr('dim' if status == 'remaining' else status))
            x = 5
            for column_index, (column, column_width) in enumerate(columns):
                self.add_cell_hit(row, x, column_width, card['id'], column_index)
                value_attr = self.cell_attr(column_index, selected)
                if column.metadata is not None:
                    value_attr |= self.attr('cyan')
                self.put(row, x, pad(column.value(card), column_width), value_attr)
                x += column_width + 1
            self.hits.append((row, 'task', card['id']))
        if not rows:
            message = 'No tasks match the current search / filters.' if self.explorer.query or self.explorer.statuses is not None or self.explorer.column_filters else 'This board has no tasks yet. Add cards through kanbn.'
            self.put(y + 3, 4, message if board else 'Waiting for a readable board…', self.attr('dim'), width - 9)
        if self.explorer.selected:
            card = self.explorer.selected
            checks = card.get('subTasks', [])
            summary = card['id']
            if checks:
                summary += f"  ·  checklist {sum(bool(c.get('completed')) for c in checks)}/{len(checks)}"
            tags = card.get('metadata', {}).get('tags')
            if tags:
                summary += '  ·  ' + display(tags)
            self.put(y + height - 2, 3, summary, self.attr('dim'), width - 7)
        self.draw_scrollbar(y + 2, width - 3, capacity, len(rows), capacity, self.task_top, 'tasks')

    def draw_preview(self, y):
        width = self.screen.getmaxyx()[1]
        card = self.explorer.selected
        title = f"Description · {card['name']}" if card else 'Description'
        self.frame(y, PREVIEW_HEIGHT, title)
        self.preview_rect = (y, 1, PREVIEW_HEIGHT, width - 2)
        text = (card.get('description') or 'No description.') if card else 'No task selected.'
        lines = wrap_lines(text, width - 9)
        capacity = PREVIEW_HEIGHT - 2
        for offset, line in enumerate(lines[:capacity]):
            if offset == capacity - 1 and len(lines) > capacity:
                line = clip(line, width - 11) + ' …'
            self.put(y + 1 + offset, 4, line, width=width - 9)

    def table_layout(self):
        width = self.screen.getmaxyx()[1]
        rules = self.explorer.column_rules.for_board(self.explorer.board_slug)
        filtered = {column.key for column in rules if self.explorer.is_filtered(column)}
        return layout_columns(rules, width, width - 9, self.explorer.rows, filtered=filtered, sorting=self.table_state.sort)

    def date_display_signature(self):
        """Detect clock-driven display changes without repainting unchanged tables."""
        if self.popup:
            return ()
        now = datetime.now().astimezone()
        columns = (self.explorer.column_rules.board_columns if self.view == 'boards'
                   else self.explorer.column_rules.for_board(self.explorer.board_slug))
        date_columns = [column for column in columns if column.is_date]
        if not date_columns:
            return (now.date(),) if self.table_state.filters else ()
        rows = self.explorer.board_rows if self.view == 'boards' else self.explorer.rows
        signature = tuple(tuple(column.value(card, now=now) for card in rows)
                          for column in date_columns)
        return (now.date(), signature) if self.table_state.filters else signature

    def open_status_menu(self):
        if self.view != 'tasks':
            return
        index = next((i for i, (c, _) in enumerate(self.cell_columns) if c.field == 'status' and c.can_filter), None)
        if index is not None:
            self.open_cell_menu(index=index, editor=True)
        elif self.explorer.status_filter_column:
            self.column_menu = {'column': self.explorer.status_filter_column, 'row': None,
                                'anchor': (4, 5), 'mode': 'enum', 'index': 0, 'top': 0,
                                'error': '', 'draft': '', 'second': ''}

    def draw_popup(self):
        height, width = self.screen.getmaxyx()
        top, bottom = 3, height - 2
        for row in range(top, bottom):
            self.put(row, 1, ' ' * (width - 3))
        title = 'Help'
        text = self.help_text()
        if self.popup != 'help':
            board = self.explorer.board
            card = next((c for c in board['tasks'] if c['id'] == self.popup[1]), None) if board else None
            text = card_details(card) if card else 'This card is no longer on the selected board.'
            title = f"{self.explorer.board_slug or 'KANBN'} * {card['name'] if card else self.popup[1]}"
        lines = wrap_lines(text, width - 9)
        capacity = bottom - top - 3
        self.popup_height = capacity
        self.popup_max = max(0, len(lines) - capacity)
        self.popup_scroll = min(max(0, self.popup_scroll), self.popup_max)
        self.frame(top, bottom - top, title, True)
        for offset, line in enumerate(lines[self.popup_scroll:self.popup_scroll + capacity]):
            self.put(top + 1 + offset, 4, line, self.attr('cyan') if line.isupper() else 0, width - 9)
        self.put(bottom - 2, 4, f"{self.bindings.label('up', True)} {self.bindings.label('down', True)} scroll · {self.bindings.label('pageDown', True)} page · {self.bindings.label('back', True)} back", self.attr('cyan'))
        self.draw_scrollbar(top + 1, width - 3, capacity, len(lines), capacity, self.popup_scroll, 'popup')

    def navigate(self, delta):
        self.selected_square = None
        if self.view == 'boards':
            rows = self.explorer.board_rows
            if rows:
                index = next((i for i, row in enumerate(rows) if row['slug'] == self.explorer.board_slug), 0)
                self.explorer.select_board(rows[max(0, min(len(rows) - 1, index + delta))]['slug'])
                if abs(delta) >= 10**9 and self.summary_table.multiline:
                    self.board_top = 0 if delta < 0 else self.summary_table.maximum
        else:
            self.explorer.move_task(delta)

    def enter_item(self):
        self._last_click = None
        if self.view == 'boards':
            if not self.explorer.board:
                return
            self.view = 'tasks'
            self.square_view.enter(None)
            self.focus.header = not bool(self.explorer.rows)
            self.task_header_selected = self.focus.header
            self.cell_columns = []
        elif self.explorer.selected:
            self.popup, self.popup_scroll = ('card', self.explorer.selected_id), 0

    def back_to_boards(self):
        if self.view == 'boards' and self.on_projects:
            self.square_view.enter(None)
            self.on_projects()
            return
        self.view = 'boards'
        self.task_header_selected = self.focus.header
        self.column_menu = None
        self.cell_columns = []
        self._last_click = None

    def mouse(self):
        self._wheel_input = False
        try:
            _, x, y, _, buttons = self.get_mouse()
        except curses.error:
            return
        if not self.popup and not self.column_menu and self.handle_activity_mouse(x, y, buttons):
            return
        if not self.popup and not self.column_menu and self.repeat_square_click(x, y, buttons):
            return
        if not self.popup and not self.column_menu and self.preview_rect:
            top, left, height, width = self.preview_rect
            if top <= y < top + height and left <= x < left + width:
                return
        up, down = bool(buttons & WHEEL_UP), bool(buttons & WHEEL_DOWN)
        if up or down:
            self._wheel_input = True
            if up != down:
                delta = -3 if up else 3
                if self.wheel_gesture.accept(delta, time.monotonic()):
                    self.scroll_wheel(delta)
            return
        if not buttons & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED | curses.BUTTON3_PRESSED | curses.BUTTON3_CLICKED):
            return
        self.interrupt_wheel()
        self.needs_redraw = True
        if self.column_menu:
            self.table_mouse(x, y, buttons)
            return
        if self.project_link and y == 1:
            left, width = self.project_link
            if left <= x < left + width:
                self.on_projects()
                return
        if self.popup:
            self.click_scrollbar(x, y)
            return
        if self.click_scrollbar(x, y):
            return
        self.table_mouse(x, y, buttons)

    def handle(self, key):
        if key == curses.KEY_RESIZE:
            self.needs_redraw = True
            return True
        if key == curses.KEY_MOUSE:
            self.mouse()
            return True
        self.interrupt_wheel()
        self._square_click = None
        self._wheel_input = False
        self.needs_redraw = True
        action = self.bindings.action(key)
        page_size = (self.popup_height if self.popup
                     else self.board_height if self.view == 'boards' else self.task_height)
        move = self.key_movement(key, page_size)
        delta, page = move if move is not None else (None, False)
        if self.popup:
            if action in ('quit', 'back', 'left'):
                self.close_popup()
            elif delta is not None:
                self.scroll(delta, page)
            elif action == 'open' and key_token(key) == 'space':
                self.scroll(page_size, page=True)
            elif action == 'first':
                self.popup_scroll = 0
            elif action == 'last':
                self.popup_scroll = self.popup_max
            return True
        if self.column_menu:
            self.handle_column_menu(key)
            return True
        if self.searching:
            if key in ('\n', '\r', curses.KEY_ENTER):
                self.searching = False
            elif key == '\x1b':
                self.explorer.search(self.search_before)
                self.searching = False
            elif key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
                self.explorer.search(self.explorer.query[:-1])
            elif key == '\x15':
                self.explorer.search('')
            elif isinstance(key, str) and key.isprintable():
                self.explorer.search(self.explorer.query + key)
            return True
        if self.handle_activity_key(key):
            return True
        if self.handle_table_key(key):
            return True
        if action == 'quit':
            return False
        if action == 'help':
            self.popup, self.popup_scroll = 'help', 0
        elif action == 'search':
            if self.view == 'boards':
                self.enter_item()
            if self.explorer.board:
                self.search_before, self.searching = self.explorer.query, True
        elif action in ('previousBoard', 'nextBoard'):
            self.explorer.move_board(-1 if action == 'previousBoard' else 1)
        elif action == 'statusFilter':
            self.open_status_menu()
        elif action == 'togglePreview' and self.view == 'tasks':
            self.show_preview = not self.show_preview
        elif action == 'refresh':
            self.reader.refresh()
        return True

    def poll(self, watch_squares=False):
        self.reader.poll()
        current_reader_state = (self.reader.revision, self.reader.error)
        if current_reader_state != self._reader_state:
            self.needs_redraw = True
            self._reader_state = current_reader_state
        if self.reader.revision != self.revision:
            self.revision = self.reader.revision
            if self.reader.snapshot:
                self.explorer.apply(self.reader.snapshot)
                if self.requested_board and self.requested_board != self.explorer.board_slug:
                    self.notice = f'Board {self.requested_board!r} is unavailable; showing {self.explorer.board_slug}.'
                self.requested_board = None
        need_squares = watch_squares or self.activity.shown or (self.view == 'boards'
            and any(column.field == 'task_squares' for column in self.explorer.column_rules.board_columns))
        if (need_squares and self.root.is_dir()) or self.work_reader.process:
            before = self.work_reader.revision, self.work_reader.error
            self.work_reader.poll()
            if before != (self.work_reader.revision, self.work_reader.error):
                self.needs_redraw = True
        clock = time.monotonic()
        signature = int(time.time()), int(clock / .35) if self.squares_animated else None
        if self.squares_visible and self._square_signature is not None and signature != self._square_signature:
            self.needs_redraw = True
        self._square_signature = signature
        self.poll_activity_clock()
        if clock >= self._date_checked:
            current_dates = self.date_display_signature()
            if current_dates != self._date_state:
                self.needs_redraw = True
                self._date_state = current_dates
            self._date_checked = clock + 1

    def close(self):
        try:
            self.reader.close()
        finally:
            self.work_reader.close()

    def loop(self):
        pending_key = None
        try:
            self.setup()
            while True:
                self.poll()
                if self.needs_redraw:
                    self.draw()
                    self.needs_redraw = False
                if pending_key is not None:
                    key, pending_key = pending_key, None
                else:
                    try:
                        key = self.read_key()
                    except curses.error:
                        continue
                if not self.handle(key):
                    break
                if self._wheel_input:
                    pending_key = self.drain_wheel_burst()
        finally:
            try:
                if self.mouse_input:
                    self.mouse_input.close()
            finally:
                self.close()


def run(root, explorer, start_in_board=False, catalog=None, selected_project=None):
    try:
        if catalog is not None:
            from .projects_ui import ProjectsApp
            curses.wrapper(lambda screen: ProjectsApp(screen, root, catalog, explorer,
                start_in_board, selected_project).loop())
        else:
            curses.wrapper(lambda screen: App(screen, root, explorer, start_in_board).loop())
    except curses.error as error:
        raise OSError(f'Cannot initialize terminal: {error}') from error
