import curses
from datetime import datetime, timedelta
from unittest.mock import patch

from kanitor.config import parse_config
from kanitor.mouse import WHEEL_UP, WHEEL_DOWN, decode_sgr
from kanitor.table_state import Criterion
from test_projects import ProjectFixture
import test_ui


class CellTests(ProjectFixture):
    def tasks(self):
        app = test_ui.UITests().app()
        self.addCleanup(app.close)
        app.draw()
        return app

    def action(self, app, name):
        app.column_menu['index'] = next(i for i, (_, key) in enumerate(app.menu_entries()) if key == name)
        app.handle('\n')

    def test_arrows_select_every_cell_and_header_without_drilling_or_tab(self):
        app = self.tasks()
        app.screen = test_ui.StyledScreen()
        app.colors['cyan'] = 1 << 8
        app.draw()
        self.assertEqual((app.screen.grid[5][2], app.screen.grid[5][96]), ('⟦', '⟧'))
        self.assertEqual(app.screen.attributes[5][2], app.colors['cyan'])
        self.assertTrue(app.screen.attributes[5][5] & curses.A_REVERSE)
        self.assertFalse(app.screen.attributes[5][22] & curses.A_REVERSE)
        app.handle(curses.KEY_LEFT)
        self.assertEqual(app.focus.index, 0)
        self.assertEqual(app.view, 'tasks')
        app.handle(curses.KEY_RIGHT)
        app.draw()
        self.assertEqual(app.focus.index, 1)
        self.assertFalse(app.screen.attributes[5][5] & curses.A_REVERSE)
        self.assertTrue(app.screen.attributes[5][22] & curses.A_REVERSE)
        self.assertIsNone(app.popup)
        app.handle(curses.KEY_UP)
        app.draw()
        self.assertTrue(app.focus.header)
        self.assertEqual((app.screen.grid[5][2], app.screen.grid[5][96]), (' ', ' '))
        self.assertFalse(any(attr & curses.A_REVERSE for attr in app.screen.attributes[5]))
        for key in ('\t', curses.KEY_BTAB):
            app.handle(key)
            self.assertEqual(app.focus.index, 1)
            self.assertTrue(app.focus.header)
        app.handle(curses.KEY_RIGHT)
        self.assertEqual(app.focus.index, 2)
        self.assertIsNone(app.column_menu)
        app.handle(' ')
        self.assertEqual(app.column_menu['mode'], 'actions')
        self.assertEqual(app.column_menu['column'].metadata, 'assigned')
        app.handle('\x1b')
        app.handle(curses.KEY_DOWN)
        app.handle(' ')
        self.assertEqual(app.popup, ('card', 'one'))
        app.handle(curses.KEY_LEFT)
        app.handle('\x1b')
        self.assertEqual(app.view, 'boards')

    def test_click_other_row_focuses_cell_then_any_cell_in_row_opens(self):
        app = self.tasks()
        y, x, _, identity, index = next(hit for hit in app.cell_hits if hit[3] == 'two' and hit[4] == 2)
        app.table_mouse(x, y, curses.BUTTON1_PRESSED)
        self.assertEqual((app.explorer.selected_id, app.focus.index), ('two', 2))
        self.assertIsNone(app.popup)
        y, x, *_ = next(hit for hit in app.cell_hits if hit[3] == 'two' and hit[4] == 0)
        app.table_mouse(x, y, curses.BUTTON1_PRESSED)
        self.assertEqual(app.popup, ('card', 'two'))

    def test_right_click_and_f_use_raw_cell_value_and_keep_predicate_for_new_values(self):
        app = self.tasks()
        event = decode_sgr('\x1b[<2;6;6M')
        self.assertEqual(event[4], curses.BUTTON3_PRESSED)
        app.table_mouse(event[1], event[2], event[4])
        self.assertIn('Only this value', [label for label, _ in app.menu_entries()])
        self.action(app, 'exclude')
        self.assertEqual([r['id'] for r in app.explorer.rows], ['two', 'three'])
        app.explorer.board['tasks'].append(dict(app.explorer.board['tasks'][1], id='future', column='Future'))
        self.assertIn('future', [r['id'] for r in app.explorer.rows])
        app.handle('f')
        self.action(app, 'clear')
        app.draw()
        self.assertNotIn('▾', app.screen.text().splitlines()[4])

    def test_enum_menu_string_editor_cancel_and_active_markers(self):
        app = self.tasks()
        app.handle(curses.KEY_UP)
        app.handle('\n')
        self.action(app, 'filter')
        app.handle(curses.KEY_END)
        app.handle(' ')
        app.handle('\x1b')
        app.draw()
        self.assertEqual([r['id'] for r in app.explorer.rows], ['one', 'two'])
        self.assertIn('STATUS▾', app.screen.text().splitlines()[4])
        app.focus_column(3)
        app.handle('\n')
        self.action(app, 'filter')
        for key in 'native metadata':
            app.handle(key)
        app.handle('\x1b')
        self.assertEqual(len(app.explorer.rows), 2)
        app.handle('\n')
        self.action(app, 'filter')
        for key in 'native metadata':
            app.handle(key)
        app.handle('\n')
        self.assertEqual([r['id'] for r in app.explorer.rows], ['two'])

    def test_date_editor_validation_between_and_cancel(self):
        app = self.tasks()
        app.explorer.board['tasks'][0]['metadata']['updated'] = '2026-10-28T09:00:00'
        app.focus.header = True
        app.focus_column(1)
        app.handle('\n')
        self.action(app, 'filter')
        self.action(app, 'Between')
        for key in '2026-10-28':
            app.handle(key)
        app.handle('\n')
        for key in '2026-10-27':
            app.handle(key)
        app.handle('\n')
        self.assertTrue(app.column_menu['error'])
        self.assertFalse(app.explorer.task_state.filters)
        app.handle('\x15')
        for key in '2026-10-28':
            app.handle(key)
        app.handle('\n')
        self.assertEqual([r['id'] for r in app.explorer.rows], ['one'])

    def test_sort_keeps_selection_reset_and_disabled_header_no_actions(self):
        app = self.tasks()
        app.explorer.selected_id = 'two'
        app.focus.header = True
        app.focus_column(2)
        app.handle('\n')
        self.action(app, 'desc')
        self.assertEqual([r['id'] for r in app.explorer.rows], ['two', 'one', 'three'])
        self.assertEqual(app.explorer.selected_id, 'two')
        app.draw()
        self.assertIn('ASSIGNED↓', app.screen.text().splitlines()[4])
        app.handle('\n')
        self.action(app, 'reset')
        self.assertEqual([r['id'] for r in app.explorer.rows], ['one', 'two', 'three'])
        data = {'boards': app.explorer.boards, 'customization': {'columns': [{'title': 'ID', 'field': 'id'}]}}
        app.explorer.apply(data)
        app.draw()
        app.handle('\n')
        self.assertEqual(app.menu_entries(), [('No actions available', 'none')])

    def test_wheel_pauses_beneath_headers_for_all_three_tables(self):
        for view in ('tasks', 'boards', 'projects'):
            with self.subTest(view=view):
                app = self.app() if view == 'projects' else self.tasks()
                app.view = view
                app.draw()
                for now in (1, 1.01, 1.05, 1.10, 1.29):
                    with patch('kanitor.cell_ui.time.monotonic', return_value=now):
                        app.scroll_wheel(-3)
                    self.assertFalse(app.focus.header)
                with patch('kanitor.cell_ui.time.monotonic', return_value=1.50):
                    app.scroll_wheel(-3)
                self.assertTrue(app.focus.header)
                with patch('kanitor.cell_ui.time.monotonic', return_value=1.51):
                    app.scroll_wheel(3)
                self.assertFalse(app.focus.header)
                self.assertEqual(app.focused_row_id(), app.row_id(app.table_rows()[0]))

    def test_projects_share_menus_filter_sort_and_declared_order_reset(self):
        app = self.app(paths=('one', 'two', 'three'))
        app.screen = test_ui.StyledScreen(28, 110)
        app.catalog.rules = parse_config({'projectColumns': [{'title': 'Project', 'field': 'name', 'filterable': True, 'sortable': True}]})
        app.draw()
        self.assertEqual((app.screen.grid[5][2], app.screen.grid[5][106]), ('⟦', '⟧'))
        self.assertTrue(app.screen.attributes[5][3] & curses.A_REVERSE)
        self.assertFalse(app.screen.attributes[6][3] & curses.A_REVERSE)
        app.handle('f')
        self.action(app, 'exclude')
        self.assertEqual([r['name'] for r in app.rows()], ['two', 'three'])
        app.draw()
        app.handle('f')
        self.action(app, 'clear')
        app.handle(curses.KEY_HOME)
        app.handle(curses.KEY_UP)
        app.handle('\n')
        self.action(app, 'desc')
        self.assertEqual([r['name'] for r in app.rows()], ['two', 'three', 'one'])
        app.handle('\n')
        self.action(app, 'reset')
        self.assertEqual([r['name'] for r in app.rows()], ['one', 'two', 'three'])

    def test_board_date_filter_and_sort_reset_use_computed_updated(self):
        app = self.tasks()
        app.explorer.boards[0]['updated'] = '2026-10-27T12:00:00'
        app.explorer.boards[1]['updated'] = '2026-10-28T12:00:00'
        app.explorer.apply({'boards': app.explorer.boards, 'customization': {'boardColumns': [
            {'title': 'Board', 'field': 'slug', 'filterable': True, 'sortable': True},
            {'title': 'Updated', 'field': 'updated'}]}})
        app.view = 'boards'
        app.draw()
        self.assertEqual([r['slug'] for r in app.explorer.board_rows], ['review', 'index'])
        app.focus.header = True
        app.focus_column(1)
        app.handle('\n')
        self.action(app, 'filter')
        self.action(app, 'On')
        for key in '2026-10-28':
            app.handle(key)
        app.handle('\n')
        self.assertEqual([r['slug'] for r in app.explorer.board_rows], ['review'])
        self.assertEqual(app.explorer.board_slug, 'review')
        self.assertEqual(len(app.column_options(app.cell_columns[0][0])), 2)
        app.handle('\n')
        self.action(app, 'clear')
        app.focus_column(0)
        app.handle('\n')
        self.action(app, 'asc')
        self.assertEqual([r['slug'] for r in app.explorer.board_rows], ['index', 'review'])
        app.handle('\n')
        self.action(app, 'reset')
        self.assertEqual([r['slug'] for r in app.explorer.board_rows], ['review', 'index'])

    def test_focus_identity_survives_config_reordering_and_menu_resize(self):
        app = self.tasks()
        app.focus_column(2)
        rules = app.explorer.column_rules.columns
        app.explorer.column_rules = parse_config({'columns': [{'title': c.title, 'metadata' if c.metadata else 'field': c.metadata or c.field} for c in reversed(rules)]})
        app.draw()
        self.assertEqual(app.cell_columns[app.focus.index][0].metadata, 'assigned')
        app.handle('f')
        self.action(app, 'filter')
        app.handle(curses.KEY_END)
        for height, width in ((16, 60), (28, 100), (18, 70)):
            app.screen = test_ui.Screen(height, width)
            app.draw()
            self.assertIn('(Missing)', app.screen.text())

    def test_live_removal_preserves_nearest_row_and_empty_header(self):
        app = self.tasks()
        app.explorer.selected_id = 'two'
        data = {'boards': app.explorer.boards}
        app.explorer.board['tasks'] = [row for row in app.explorer.board['tasks'] if row['id'] != 'two']
        app.explorer.apply(data)
        app.draw()
        self.assertIsNotNone(app.explorer.selected_id)
        app.handle('f')
        self.action(app, 'filter')
        app.handle(' ')
        app.handle('\x1b')
        app.draw()
        self.assertTrue(app.focus.header)
        self.assertFalse(app.explorer.rows)

    def test_clock_driven_predicate_changes_choose_nearest_surviving_row(self):
        app = self.tasks()
        app.explorer.selected_id = 'two'
        app.draw()
        column = app.cell_columns[0][0]
        # A live predicate can change its results without apply_column_change,
        # for example when a relative date boundary advances at midnight.
        app.explorer.task_state.filters[column.key] = Criterion('exclude', column.filter_token(app.explorer.selected))
        app.draw()
        self.assertEqual(app.explorer.selected_id, 'three')

    def test_relative_date_filter_refreshes_at_midnight_without_display_format(self):
        app = self.tasks()
        app.explorer.apply({'boards': app.explorer.boards, 'customization': {'columns': [
            {'title': 'Due', 'metadata': 'due', 'filterable': True, 'filterType': 'date'}]}})
        column = app.explorer.column_rules.columns[0]
        app.explorer.task_state.filters[column.key] = Criterion('date', ('Today', ''))
        now = datetime(2026, 10, 28, 23, 59).astimezone()
        app.explorer.board['tasks'][0]['metadata']['due'] = '2026-10-28T09:00:00'
        with patch.object(app.reader, 'poll'), patch('kanitor.ui.datetime') as clock, patch('kanitor.table_state.datetime', wraps=datetime) as predicate_clock:
            clock.now.return_value = predicate_clock.now.return_value = now
            app.poll()
            self.assertEqual([row['id'] for row in app.explorer.rows], ['one'])
            app.needs_redraw = False
            app._date_checked = 0
            clock.now.return_value = predicate_clock.now.return_value = now + timedelta(minutes=2)
            app.poll()
            self.assertTrue(app.needs_redraw)
            self.assertFalse(app.explorer.rows)
