"""Projects above independent, reusable board/task explorers."""
import curses
from datetime import datetime
from pathlib import Path
import time

from .config import DEFAULT_PROJECT_COLUMNS, layout_columns
from .model import Explorer
from .reader import warning_summary
from .ui import App, pad
from .table_state import TableState


PROJECT_COLUMNS = DEFAULT_PROJECT_COLUMNS


class ProjectsApp(App):
    def __init__(self, screen, root, catalog, explorer=None, start_in_board=False, selected_project=None):
        super().__init__(screen, root, Explorer())
        self.view = 'projects'
        self.catalog = catalog
        self.project_state = TableState()
        self.children = {}
        self.active = None
        self.selected_project = None
        self.project_top = 0
        self.project_height = 1
        self._catalog_checked = None
        self.sync_projects()
        if selected_project:
            key = str(selected_project.root)
            child = self.children[key]
            child.explorer = explorer or Explorer()
            child.requested_board = child.explorer.board_slug
            child.view = 'tasks' if start_in_board else 'boards'
            self.open_project(key)

    def sync_projects(self):
        keys = [str(project.root) for project in self.catalog.projects]
        old_keys = self.summary_ids or list(self.children)
        old_index = old_keys.index(self.selected_project) if self.selected_project in old_keys else 0
        for key in list(self.children):
            if key not in keys:
                child = self.children.pop(key)
                if self.active is child:
                    self.show_projects()
                child.close()
        for project in self.catalog.projects:
            key = str(project.root)
            if key not in self.children:
                child = App(self.screen, project.root, Explorer())
                child.colors = self.colors
                child.on_projects = self.show_projects
                child.pane_layout_state = self.pane_layout_state
                self.children[key] = child
            self.children[key].project_label = project.path
        self.children = {key: self.children[key] for key in keys}
        if self.selected_project not in keys:
            displayed = [row['id'] for row in self.rows()]
            self.selected_project = displayed[min(old_index, len(displayed) - 1)] if displayed else None

    def show_projects(self):
        if self.active and self.active.popup_return:
            self.active.close_popup()
            return
        self.square_view.enter(None)
        self.active = None
        self._square_scroll_request = bool(self.selected_square)
        self._last_click = None
        self.needs_redraw = True

    def open_project(self, key=None):
        key = key or self.selected_project
        if key not in self.children:
            return
        self.selected_project = key
        self.active = self.children[key]
        self.square_view.enter(None)
        self.active.square_view.enter(None)
        self.active.mouse_input = self.mouse_input
        self.active.needs_redraw = self.needs_redraw = True
        self._last_click = None

    def rows(self):
        self.project_state.reconcile(self.catalog.rules.project_columns)
        return self.project_state.apply(self.project_universe(), self.catalog.rules.project_columns)

    def project_universe(self):
        rows = []
        for project in self.catalog.projects:
            key = str(project.root)
            child = self.children[key]
            reader = child.reader
            snapshot = reader.snapshot
            warning = warning_summary(snapshot)
            state = 'STALE' if reader.error and snapshot else 'Unavailable' if reader.error else 'Partial' if warning else 'Live' if snapshot else 'Loading'
            boards = snapshot.get('boards', []) if snapshot else []
            row = {'id': key, 'name': Path(project.path).name, 'path': project.path, 'root': str(project.root),
                         'boards': len(boards) if snapshot else None,
                         'cards': len({card['id'] for board in boards for card in board['tasks']}) if snapshot else None,
                         'state': state, 'error': reader.error, 'warning': warning}
            if any(column.field == 'task_squares' for column in self.catalog.rules.project_columns):
                row['task_squares'] = self.square_view.bundle(key,
                    child.square_data(child.explorer.column_rules.square_rules)[1],
                    freeze=child.work_reader.snapshot is not None or bool(child.work_reader.error))
                if child.work_reader.error and not row['error']:
                    row.update(state='Work stale', error=child.work_reader.error)
            rows.append(row)
        return rows

    def poll(self):
        if self.catalog.poll():
            self.needs_redraw = True
        if self._catalog_checked != self.catalog._checked:
            self._catalog_checked = self.catalog._checked
            self.sync_projects()
        # Keep readers independent and bound background starts. The active view
        # remains responsive even while another project's reader is stalled.
        children = list(self.children.values())
        if self.active in children:
            children.remove(self.active)
            children.insert(0, self.active)
        running = sum(bool(child.reader.process or child.work_reader.process)
                      for child in children)
        for child in children:
            pending = bool(child.reader.process or child.work_reader.process)
            if pending or child is self.active or running < 4:
                before = (child.reader.revision, child.reader.error, child.work_reader.revision, child.work_reader.error)
                child.poll(watch_squares=any(
                    column.field == 'task_squares' for column in self.catalog.rules.project_columns) or self.activity.shown)
                now_pending = bool(child.reader.process or child.work_reader.process)
                running += int(now_pending) - int(pending)
                after = (child.reader.revision, child.reader.error, child.work_reader.revision, child.work_reader.error)
                if before != after or (child is self.active and child.needs_redraw):
                    self.needs_redraw = True
        signature = datetime.now().astimezone().date(), int(time.time()) if self.squares_visible else None, int(time.monotonic() / .35) if self.squares_animated else None
        if not self.active and self._square_signature is not None and signature != self._square_signature:
            self.needs_redraw = True
        self._square_signature = signature
        self.poll_activity_clock()

    def close(self):
        try:
            for child in self.children.values():
                child.close()
        finally:
            super().close()

    def draw(self):
        self.begin_square_frame()
        if self.active:
            self.square_view.enter(None)
            self.active.draw()
            self.active.needs_redraw = False
            return
        if self.draw_text_selection():
            return
        self.screen.erase()
        self.begin_text_frame()
        self.hits, self.scrollbars, self.square_hits = [], [], []
        self.cell_hits, self.header_hits = [], []
        self.preview_rect = None
        self.activity.rect = None
        height, width = self.screen.getmaxyx()
        if width < 60 or height < 16:
            self.put(0, 0, 'KANITOR · terminal needs at least 60 × 16', self.attr('cyan'))
            self.screen.refresh()
            return
        self.square_view.enter('projects')
        self.refresh_activity()
        rows = self.rows()
        columns, self.hidden_columns = layout_columns(self.catalog.rules.project_columns, width, width - 7, rows, filtered=self.table_state.filters, sorting=self.table_state.sort)
        self.table_setup(columns)
        self.prepare_square_focus(rows)
        preview = self.square_preview() if not self.popup else None
        wants_preview = self.activity.preview_shown if self.activity.focused else self.square_preview_shown and height >= 19
        list_height, activity_rect, preview_top = self.pane_layout(wants_preview)
        project_name = self.root.name if any(
            (self.root / name).exists() for name in ('.kanbn', 'kanbn.json', 'kanbn.yml')) else ''
        self.put(0, 2, 'KANITOR / ' + project_name, self.attr('cyan') | curses.A_BOLD, width - 28)
        partial = any((child.reader.snapshot or {}).get('warnings') for child in self.children.values())
        self.put(0, width - 23, 'READ ONLY · ' + ('STALE' if self.catalog.error else 'PARTIAL' if partial else 'LIVE'), self.attr('error' if self.catalog.error else 'cyan'))
        self.put(1, 2, f"Projects · {len(rows)} project{'s' if len(rows) != 1 else ''}", self.attr('cyan'))
        self.put(2, 2, str(self.root), self.attr('dim'), width - 5)
        if self.popup:
            self.draw_popup()
        else:
            self.frame(3, list_height, 'Projects', self.main_pane_focused)
            x = 3
            for column_index, (column, size) in enumerate(columns):
                self.put(4, x, pad(self.heading(column), size, right=column.field in ('boards', 'cards')), self.header_attr(column_index))
                self.add_header_hit(4, x, size, column_index)
                x += size + 1
            self.project_height = max(1, list_height - 4)
            index = next((i for i, row in enumerate(rows) if row['id'] == self.selected_project), 0)
            self.project_top = self.draw_summary_rows(rows, columns, 5, self.project_height,
                index, self.project_top, 'id', 'project')
            if not rows:
                self.put(5, 3, 'No projects configured. Add paths to the Kanitor configuration projects list.', self.attr('dim'), width - 7)
            self.draw_scrollbar(5, width - 3, self.project_height, self.summary_table.total, self.project_height, self.project_top, 'projects')
        selected = next((row for row in rows if row['id'] == self.selected_project), {})
        if selected and not self.popup:
            self.put(3 + list_height - 2, 3, selected['root'], self.attr('dim'), width - 7)
        if not self.popup:
            if activity_rect:
                self.draw_activity(*activity_rect)
            if preview_top is not None:
                if self.activity.focused:
                    self.activity_preview(preview_top)
                else:
                    self.draw_square_preview(preview_top, preview)
        status = self.catalog.error or selected.get('error') or self.notice or f"Select a project and press {self.bindings.label('open')}."
        if self.hidden_columns and not self.popup:
            status = f'{self.hidden_columns} columns hidden; widen terminal · ' + status
        if self.selected_square and not self.popup:
            status = self.square_navigation_hint()
            needed = 25 if self.activity.shown else 19
            if height < needed and self.square_preview_shown:
                status = f'Task preview needs {needed} rows · ' + status
        if self.activity.focused and not self.popup:
            status = self.catalog.error or selected.get('error') or self.notice or self.activity_status()
        if self.column_menu and self.column_menu.get('table') != 'activity':
            status = self.menu_navigation_hint()
        if not self.activity.focused:
            status = self.table_status() + (' · ' if self.table_status() else '') + status
        if selected.get('warning') and not self.column_menu:
            status = self.catalog.error or selected.get('error') or selected['warning']
        if self.resize_mode and not self.popup:
            self.draw_resizers()
            status = self.resize_status()
        self.put(height - 2, 2, status, self.attr('error' if self.catalog.error or selected.get('error') else 'cyan'), width - 5)
        footer = self.resize_footer() if self.resize_mode and not self.popup else self.table_footer()
        self.put(height - 1, 2, footer, self.attr('cyan'), width - 4)
        if self.column_menu and not self.popup:
            self.draw_column_menu()
        self.screen.refresh()

    def navigate(self, delta):
        self.selected_square = None
        keys = [row['id'] for row in self.rows()]
        if keys:
            index = keys.index(self.selected_project) if self.selected_project in keys else 0
            self.selected_project = keys[max(0, min(len(keys) - 1, index + delta))]
            if abs(delta) >= 10**9 and self.summary_table.multiline:
                self.project_top = 0 if delta < 0 else self.summary_table.maximum

    def scroll(self, delta, page=False):
        if self.popup:
            super().scroll(delta, page)
        elif page and self.summary_table.multiline:
            keys = [row['id'] for row in self.rows()]
            index = keys.index(self.selected_project) if self.selected_project in keys else 0
            index, self.project_top = self.summary_table.move(index, self.project_top, delta, page=True)
            if keys:
                self.selected_project = keys[index]
        else:
            self.navigate(delta)
            if page:
                self.project_top = max(0, self.project_top + delta)

    def scroll_table_wheel(self, delta):
        before = self.selected_project, self.project_top, self.popup_scroll
        if not self.popup and self.summary_table.multiline:
            keys = [row['id'] for row in self.rows()]
            index = keys.index(self.selected_project) if self.selected_project in keys else 0
            index, self.project_top = self.summary_table.move(index, self.project_top, delta)
            if keys:
                self.selected_project = keys[index]
        else:
            self.scroll(delta)
        if self.selected_square and self.selected_square[0] != self.selected_project:
            self.selected_square = None
        self.needs_redraw |= before != (self.selected_project, self.project_top, self.popup_scroll)

    def current_summary_id(self):
        return self.selected_project

    def select_summary_row(self, identity):
        self.selected_project = identity

    def resolve_square(self, row, square):
        child = self.children.get(row)
        return child.resolve_square(square.board, square) if child else None

    def focused_square(self):
        if not self.selected_square:
            return None
        if self.selected_square[0] != self.selected_project:
            self.selected_square = None
            return None
        row, identity = self.selected_square
        child = self.children.get(row)
        columns = layout_columns(self.catalog.rules.project_columns, self.screen.getmaxyx()[1],
                                 self.screen.getmaxyx()[1] - 7)[0]
        if child and any(column.field == 'task_squares' for column, _ in columns):
            square = next((square for square in child.square_data(child.explorer.column_rules.square_rules)[1] if square.id == identity), None)
            if square:
                return square
        self.selected_square = None
        return None

    def open_square(self, row, square):
        source = self.resolve_square(row, square)
        if not source:
            return
        child, board, task = source
        original = child.explorer
        saved = child.view, child.popup, child.popup_scroll, child.requested_board
        page = Explorer(board['slug'])
        page.boards, page.column_rules = original.boards, original.column_rules
        page.reconcile()
        self.open_project(row)
        child.explorer = page
        child.view = 'boards'
        child.requested_board = None
        child.popup, child.popup_scroll = ('card', task['id']), 0
        def restore():
            original.boards, original.column_rules = child.explorer.boards, child.explorer.column_rules
            original.reconcile()
            child.explorer = original
            child.view, child.popup, child.popup_scroll, child.requested_board = saved
            self.show_projects()
        child.popup_return = restore
        self._last_click = self._square_click = None

    def mouse(self):
        if self.active:
            child = self.active
            child.mouse_input = self.mouse_input
            child.mouse()
            self._wheel_input = child._wheel_input
            self.needs_redraw |= child.needs_redraw
            return
        super().mouse()

    def handle(self, key):
        if self.active:
            child = self.active
            if key == curses.KEY_MOUSE:
                self.mouse()
                return True
            result = child.handle(key)
            self._wheel_input = child._wheel_input
            self.needs_redraw |= child.needs_redraw
            return result
        if key == curses.KEY_RESIZE:
            self.finish_text_selection()
            self.end_resize_drag()
            self.needs_redraw = True
            return True
        self._wheel_input = False
        if key == curses.KEY_MOUSE:
            self.mouse()
            return True
        self.interrupt_wheel()
        self._square_click = None
        self.needs_redraw = True
        action = self.bindings.action(key)
        if self.handle_text_selection_key(key):
            return True
        size = self.popup_height if self.popup else self.project_height
        move = self.key_movement(key, size)
        if self.popup:
            if action in ('quit', 'back', 'left'):
                self.popup = None
            elif move:
                self.scroll(*move)
            elif action == 'open' and key == ' ':
                self.scroll(size, page=True)
            elif action in ('first', 'last'):
                self.popup_scroll = 0 if action == 'first' else self.popup_max
        elif self.column_menu:
            self.handle_column_menu(key)
        elif self.handle_resize_key(key):
            pass
        elif self.handle_activity_key(key):
            pass
        elif self.handle_table_key(key):
            pass
        elif action == 'quit':
            return False
        elif action == 'refresh':
            self.catalog.poll(force=True)
            self.sync_projects()
            for child in self.children.values():
                child.reader.refresh()
                child.work_reader.refresh()
        elif action == 'help':
            self.popup, self.popup_scroll = 'help', 0
        return True
