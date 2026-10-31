import curses
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from kanitor.model import Explorer
from kanitor.ui import App, WHEEL_DOWN, WHEEL_UP, cells, wrap_lines
from test_explorer import snapshot


class Screen:
    """A terminal grid that rejects writes outside its dimensions."""
    def __init__(self, height=28, width=100):
        self.height, self.width = height, width
        self.erase()

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.grid = [[' '] * self.width for _ in range(self.height)]

    def addstr(self, y, x, text, attr=0):
        if y < 0 or y >= self.height or x < 0 or x + cells(text) >= self.width:
            raise AssertionError(f'Out of bounds: {y}, {x}, {text!r}')
        for char in text:
            size = cells(char)
            if size:
                self.grid[y][x] = char
                if size == 2:
                    self.grid[y][x + 1] = ''
                x += size

    def refresh(self):
        pass

    def text(self):
        return '\n'.join(''.join(row) for row in self.grid)


class StyledScreen(Screen):
    def erase(self):
        super().erase()
        self.attributes = [[0] * self.width for _ in range(self.height)]

    def addstr(self, y, x, text, attr=0):
        super().addstr(y, x, text, attr)
        for char in text:
            size = cells(char)
            for offset in range(size):
                self.attributes[y][x + offset] = attr
            x += size


class UITests(unittest.TestCase):
    def app(self, height=28, width=100, start_in_board=True):
        explorer = Explorer()
        explorer.apply(snapshot())
        return App(Screen(height, width), Path('/example'), explorer, start_in_board)

    def test_top_bar_breadcrumb_follows_navigation_and_uses_names_and_exact_task_id(self):
        app = self.app(start_in_board=False)
        app.draw()
        self.assertIn('KANITOR / example', app.screen.text().splitlines()[0])
        self.assertNotIn(' / Example', app.screen.text().splitlines()[0])
        app.handle('\n')
        app.draw()
        self.assertIn('KANITOR / example / Example', app.screen.text().splitlines()[0])
        app.handle('\n')
        app.draw()
        self.assertIn('KANITOR / example / Example / one', app.screen.text().splitlines()[0])
        self.assertIn('READ ONLY · LIVE', app.screen.text().splitlines()[0])
        app.handle('\x1b')
        app.draw()
        self.assertNotIn(' / one', app.screen.text().splitlines()[0])
        app.explorer.select_board('review')
        app.project_label = 'packages/web'
        app.handle('\n')
        app.draw()
        self.assertIn('KANITOR / web / Review / one', app.screen.text().splitlines()[0])
        app.screen.width = 60
        app.draw()
        self.assertIn('READ ONLY · LIVE', app.screen.text().splitlines()[0])

    def test_layout_at_minimum_and_large_terminal_sizes(self):
        for height, width in ((16, 60), (28, 100), (60, 180), (10, 40)):
            with self.subTest(size=(height, width)):
                app = self.app(height, width)
                app.draw()
                self.assertIn('KANITOR', app.screen.text())
                if width >= 60 and height >= 16:
                    self.assertNotIn('PROGRESS', app.screen.text())
                    self.assertNotIn('TASKS', app.screen.text())
                    self.assertIn('index * All statuses', app.screen.text())
                    self.assertNotRegex(app.screen.text().splitlines()[3], r'\d+/\d+')
                    app.handle('\n')
                    app.draw()
                    self.assertIn('index * Reopened card', app.screen.text())

    def test_default_updated_column_renders_after_status(self):
        app = self.app()
        app.explorer.board['tasks'][0]['metadata']['updated'] = '2026-10-23T16:01:00'
        app.draw()
        header = app.screen.text().splitlines()[app.task_header_y]
        self.assertLess(header.index('STATUS'), header.index('UPDATED'))
        self.assertLess(header.index('UPDATED'), header.index('ASSIGNED'))
        self.assertIn('2026-10-23 16:01', app.screen.text())

    def test_idle_clock_refreshes_date_thresholds_without_file_changes(self):
        app = self.app()
        now = datetime(2026, 10, 23, 16, 1).astimezone()
        app.explorer.board['tasks'][0]['metadata']['updated'] = now.isoformat()
        data = snapshot()
        data['boards'] = app.explorer.boards
        data['customization'] = {'columns': [
            {'title': 'Updated', 'metadata': 'updated', 'format': '%d %b',
             'thresholds': [{'under': '1d', 'format': '%H:%M'}]},
            {'title': 'Task', 'field': 'name'}]}
        app.explorer.apply(data)
        # Idle input timeouts must still notice threshold transitions. An
        # unchanged third tick must not repaint, even without reader revisions.
        app.screen.get_wch = Mock(side_effect=[curses.error(), curses.error(), 'q'])
        with patch.object(app, 'setup'), patch.object(app.reader, 'poll'), \
                patch.object(app, 'draw') as draw, patch('kanitor.ui.datetime') as clock, \
                patch('kanitor.ui.time.monotonic', side_effect=[0, 2, 4]):
            clock.now.side_effect = [now, now + timedelta(days=1), now + timedelta(days=1)]
            app.loop()
        self.assertEqual(draw.call_count, 2)

    def test_search_cancel_and_board_navigation(self):
        app = self.app()
        app.back_to_boards()
        app.handle(curses.KEY_DOWN)
        self.assertEqual(app.explorer.board_slug, 'review')
        app.handle('[')
        app.handle('\n')
        self.assertEqual(app.view, 'tasks')
        app.handle('/')
        for key in 'no matches':
            app.handle(key)
        self.assertEqual(app.explorer.rows, [])
        app.handle('\x1b')
        self.assertEqual(app.explorer.query, '')
        app.handle('\x1b')
        self.assertEqual(app.view, 'boards')

    def test_details_scrolling_and_stale_error_are_visible(self):
        app = self.app()
        app.reader.error = 'Read failed; snapshot is stale'
        app.draw()
        self.assertIn('STALE', app.screen.text())
        self.assertIn('Read failed', app.screen.text())
        app.handle('?')
        app.draw()
        app.handle(curses.KEY_END)
        app.draw()
        self.assertEqual(app.popup_scroll, app.popup_max)
        app.handle('q')
        self.assertIsNone(app.popup)
        self.assertFalse(app.handle('q'))

    def test_trackpad_scrolls_card_in_both_directions_within_bounds(self):
        app = self.app(16, 60)
        app.explorer.selected['description'] = '\n'.join(f'Description line {i}' for i in range(60))
        app.handle('\n')
        app.draw()
        initial = app.screen.text()
        self.assertGreater(app.popup_max, 3)
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 8, 0, WHEEL_DOWN)):
            app.handle(curses.KEY_MOUSE)
            app.draw()
            self.assertEqual(app.popup_scroll, 3)
            self.assertNotEqual(app.screen.text(), initial)
            for _ in range(30):
                app.handle(curses.KEY_MOUSE)
                app.draw()
            self.assertEqual(app.popup_scroll, app.popup_max)
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 8, 0, WHEEL_UP)):
            for _ in range(30):
                app.handle(curses.KEY_MOUSE)
                app.draw()
            self.assertEqual(app.popup_scroll, 0)
            self.assertEqual(app.screen.text(), initial)
        self.assertEqual(app.explorer.selected_id, 'one')

    def test_trackpad_scrolls_board_list_and_status_dropdown(self):
        app = self.app(start_in_board=False)
        app.draw()
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 8, 0, WHEEL_DOWN)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.explorer.board_slug, 'review')
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 8, 0, WHEEL_UP)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.explorer.board_slug, 'index')
        app.handle('\n')
        app.draw()
        app.handle('s')
        app.draw()
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 8, 0, WHEEL_DOWN)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.column_menu['index'], 3)
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 8, 0, WHEEL_UP)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.column_menu['index'], 0)

    def test_wheel_bursts_stay_at_card_boundaries_and_allow_immediate_reversal(self):
        app = self.app(16, 60)
        app.explorer.selected['description'] = '\n'.join(f'Line {i}' for i in range(100))
        app.handle('\n')
        app.draw()
        for boundary, outward, inward in ((0, WHEEL_UP, WHEEL_DOWN), (app.popup_max, WHEEL_DOWN, WHEEL_UP)):
            with self.subTest(boundary=boundary):
                app.popup_scroll = boundary
                app.draw()
                app.needs_redraw = False
                with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 8, 0, outward)):
                    for _ in range(300):
                        app.handle(curses.KEY_MOUSE)
                        self.assertEqual(app.popup_scroll, boundary)
                        self.assertFalse(app.needs_redraw)
                with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 8, 0, inward)):
                    app.handle(curses.KEY_MOUSE)
                self.assertEqual(app.popup_scroll, boundary + (3 if boundary == 0 else -3))
                self.assertTrue(app.needs_redraw)

    def test_one_wheel_gesture_at_list_top_pauses_beneath_headers(self):
        app = self.long_app()
        app.needs_redraw = False
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 6, 0, WHEEL_UP)):
            for _ in range(300):
                app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.explorer.selected_id, 'task-0')
        self.assertFalse(app.task_header_selected)
        self.assertFalse(app.needs_redraw)
        app.handle(curses.KEY_UP)
        self.assertTrue(app.task_header_selected)  # Keyboard navigation still reaches filters.

    def test_ambiguous_wheel_reports_do_not_reverse_scroll_direction(self):
        app = self.long_app()
        app.explorer.move_task(20)
        app.needs_redraw = False
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 6, 0, WHEEL_UP | WHEEL_DOWN)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.explorer.selected_id, 'task-20')
        self.assertFalse(app.needs_redraw)

    def test_wheel_input_is_batched_and_preserves_the_next_keyboard_action(self):
        app = self.long_app()
        keys = [curses.KEY_MOUSE] * 100 + ['p']
        with patch.object(app.screen, 'get_wch', create=True, side_effect=keys), \
                patch.object(app.screen, 'timeout', create=True) as timeout, \
                patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 6, 0, WHEEL_DOWN)), \
                patch('kanitor.ui.time.monotonic', return_value=1.0):
            app.handle(curses.KEY_MOUSE)
            pending = app.drain_wheel_burst()
        self.assertEqual(app.explorer.selected_id, 'task-59')
        self.assertEqual(pending, 'p')
        self.assertEqual([call.args[0] for call in timeout.call_args_list], [0, 100])
        app.handle(pending)
        self.assertFalse(app.show_preview)

    def test_main_loop_does_not_repaint_for_outward_wheel_events_at_bottom(self):
        app = self.long_app()
        app.explorer.move_task(1000)
        app.reader = SimpleNamespace(revision=0, error='', snapshot=None, poll=Mock(), close=Mock())
        app.needs_redraw = True
        with patch.object(app, 'setup'), patch.object(app, 'draw', wraps=app.draw) as draw, \
                patch.object(app.screen, 'get_wch', create=True, side_effect=[curses.KEY_MOUSE] * 100 + ['q']), \
                patch.object(app.screen, 'timeout', create=True), \
                patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 6, 0, WHEEL_DOWN)), \
                patch('kanitor.ui.time.monotonic', return_value=1.0):
            app.loop()
        self.assertEqual(draw.call_count, 1)
        self.assertEqual(app.explorer.selected_id, 'task-59')
        app.reader.close.assert_called_once()

    def test_long_unicode_details_wrap_to_terminal_cells(self):
        lines = wrap_lines('日本語' * 50 + '\nhello\x1bworld', 20)
        self.assertTrue(all(cells(line) <= 20 for line in lines))
        self.assertNotIn('\x1b', ''.join(lines))

    def test_card_named_help_opens_its_own_details(self):
        app = self.app()
        app.explorer.board['tasks'][0]['id'] = 'help'
        app.explorer.reconcile()
        app.handle('\n')
        app.draw()
        self.assertIn('index * Reopened card', app.screen.text())
        self.assertIn('ID: help', app.screen.text())

    def test_mouse_press_selects_immediately_and_second_press_opens_details(self):
        app = self.app()
        app.draw()
        row = next(y for y, kind, identity in app.hits if kind == 'task' and identity == 'two')
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, row, 0, curses.BUTTON1_PRESSED)), \
                patch('kanitor.ui.time.monotonic', side_effect=[10.0, 10.2]):
            app.handle(curses.KEY_MOUSE)
            self.assertEqual(app.explorer.selected_id, 'two')
            self.assertIsNone(app.popup)
            app.handle(curses.KEY_MOUSE)
            self.assertEqual(app.popup, ('card', 'two'))

    def test_clicking_a_different_row_focuses_without_opening_it(self):
        app = self.app()
        app.draw()
        rows = {identity: y for y, kind, identity in app.hits if kind == 'task'}
        for identity in ('two', 'three', 'one'):
            with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, rows[identity], 0, curses.BUTTON1_PRESSED)):
                app.handle(curses.KEY_MOUSE)
            self.assertIsNone(app.popup)
            self.assertEqual(app.explorer.selected_id, identity)

    def test_enter_opens_tasks_and_escape_returns_to_boards(self):
        app = self.app()
        app.view = 'boards'
        app.handle('\n')
        self.assertEqual(app.view, 'tasks')
        self.assertIsNone(app.popup)
        app.handle('\n')
        self.assertEqual(app.popup, ('card', 'one'))
        app.handle('\x1b')
        self.assertIsNone(app.popup)
        self.assertEqual(app.view, 'tasks')
        app.handle('\x1b')
        self.assertEqual(app.view, 'boards')
        app.handle('\n')
        app.handle('\n')
        app.handle('\x1b')
        self.assertIsNone(app.popup)
        self.assertEqual(app.view, 'tasks')
        app.handle('\x1b')
        self.assertEqual(app.view, 'boards')
        self.assertIsNone(app.explorer.statuses)

    def test_board_selection_occupies_the_main_pane_and_double_click_enters(self):
        app = self.app(start_in_board=False)
        app.draw()
        self.assertEqual(app.view, 'boards')
        self.assertIsNone(app.status_header)
        self.assertIn('Boards', app.screen.text())
        self.assertIn('Review', app.screen.text())
        self.assertEqual(app.screen.text().count('┌'), 1)
        self.assertTrue(all(kind == 'board' for _, kind, _ in app.hits))
        row = next(y for y, _, identity in app.hits if identity == 'review')
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, row, 0, curses.BUTTON1_PRESSED)), \
                patch('kanitor.ui.time.monotonic', side_effect=[10.0, 10.2]):
            app.handle(curses.KEY_MOUSE)
            self.assertEqual(app.explorer.board_slug, 'review')
            self.assertEqual(app.view, 'boards')
            app.handle(curses.KEY_MOUSE)
        app.draw()
        self.assertEqual(app.view, 'tasks')
        self.assertIn('review * All statuses', app.screen.text())
        self.assertEqual(app.screen.text().count('┌'), 2)
        self.assertTrue(all(kind == 'task' for _, kind, _ in app.hits))
        app.handle('\x1b')
        app.draw()
        self.assertEqual(app.view, 'boards')
        self.assertEqual(app.explorer.board_slug, 'review')
        self.assertIn('Review', app.screen.text())

    def test_keyboard_selects_header_and_filters_multiple_statuses(self):
        app = self.app()
        app.handle(curses.KEY_UP)
        self.assertTrue(app.task_header_selected)
        app.handle('\n')
        self.assertEqual(app.column_menu['mode'], 'actions')
        app.handle('\n')  # Filter editor.
        self.assertEqual(app.column_menu['mode'], 'enum')
        app.handle(curses.KEY_END)
        app.handle(' ')
        self.assertEqual([c['id'] for c in app.explorer.rows], ['one', 'two'])
        app.handle(curses.KEY_UP)
        app.handle('\n')
        self.assertEqual([c['id'] for c in app.explorer.rows], ['one'])
        app.handle('\x1b')
        self.assertIsNone(app.column_menu)
        app.handle(curses.KEY_DOWN)
        self.assertFalse(app.task_header_selected)
        app.handle('s')
        app.handle(' ')
        self.assertEqual(len(app.explorer.rows), 3)

    def test_mouse_header_and_checkbox_use_bounded_hit_targets(self):
        app = self.app()
        app.draw()
        row, x, _ = app.status_header
        with patch('kanitor.ui.curses.getmouse', return_value=(0, x, row, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.column_menu['mode'], 'actions')
        app.handle('\n')  # Filter.
        app.draw()
        row = next(y for y, index in app.column_menu['hits'] if index == 3)
        left = app.column_menu['rect'][1]
        with patch('kanitor.ui.curses.getmouse', return_value=(0, left + 3, row, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual([c['id'] for c in app.explorer.rows], ['one', 'two'])
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 1, row, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.assertIsNone(app.column_menu)
        self.assertEqual([c['id'] for c in app.explorer.rows], ['one', 'two'])

    def test_dropdown_scrolls_and_fits_minimum_terminal_after_resize(self):
        app = self.app(16, 60)
        app.explorer.board['columns'] = [f'Status {i} 日本語' for i in range(30)]
        app.draw()
        app.handle('s')
        app.draw()
        self.assertNotIn('one square = one card', app.screen.text())
        app.handle(curses.KEY_END)
        app.draw()
        self.assertIn('Status 29', app.screen.text())
        app.screen = Screen(28, 100)
        app.draw()
        self.assertIn('Status 29', app.screen.text())

    def long_app(self, start_in_board=True):
        app = self.app(24, 90, start_in_board=start_in_board)
        template = app.explorer.board
        template['tasks'] = [dict(template['tasks'][0], id=f'task-{i}', name=f'Task {i}') for i in range(60)]
        template['columns'] = [f'Status {i}' for i in range(60)]
        app.explorer.boards = [dict(template, slug=f'board-{i}', name=f'Board {i}') for i in range(60)]
        app.explorer.board_slug = 'board-0'
        app.explorer.reconcile()
        app.draw()
        return app

    def test_scrollbars_follow_each_list_and_disappear_when_content_fits(self):
        for view in ('boards', 'tasks'):
            with self.subTest(view=view):
                app = self.long_app(start_in_board=view == 'tasks')
                bar = next(b for b in app.scrollbars if b['kind'] == view)
                self.assertEqual(bar['thumb_top'], 0)
                self.assertIn('█', app.screen.text())
                app.handle(curses.KEY_END)
                app.draw()
                bar = next(b for b in app.scrollbars if b['kind'] == view)
                self.assertEqual(bar['thumb_top'] + bar['thumb_size'], bar['height'])
                if view == 'boards':
                    app.screen = Screen(80, 320)
                else:
                    app.explorer.search('Task 59')
                app.draw()
                self.assertFalse(app.scrollbars)

    def test_details_help_and_dropdown_have_scrollbars(self):
        app = self.long_app()
        app.handle('?')
        app.draw()
        self.assertEqual([bar['kind'] for bar in app.scrollbars], ['popup'])
        app.handle(curses.KEY_END)
        app.draw()
        bar = app.scrollbars[0]
        self.assertEqual(bar['thumb_top'] + bar['thumb_size'], bar['height'])
        app.handle('q')
        app.handle('s')
        app.draw()
        self.assertIn('column_menu', [bar['kind'] for bar in app.scrollbars])
        app.handle(curses.KEY_END)
        app.draw()
        bar = next(bar for bar in app.scrollbars if bar['kind'] == 'column_menu')
        self.assertEqual(bar['thumb_top'] + bar['thumb_size'], bar['height'])

    def test_shift_arrows_jump_ten_items_in_lists_and_dropdown(self):
        for view in ('boards', 'tasks', 'menu', 'popup'):
            with self.subTest(view=view):
                app = self.long_app(start_in_board=view != 'boards')
                if view == 'menu':
                    app.handle('s')
                    app.draw()
                elif view == 'popup':
                    app.explorer.selected['description'] = '\n'.join(f'Line {i}' for i in range(100))
                    app.handle('\n')
                    app.draw()
                app.handle(curses.KEY_SF)
                if view == 'boards':
                    self.assertEqual(app.explorer.board_slug, 'board-10')
                elif view == 'tasks':
                    self.assertEqual(app.explorer.selected_id, 'task-10')
                elif view == 'menu':
                    self.assertEqual(app.column_menu['index'], 10)
                else:
                    self.assertEqual(app.popup_scroll, 10)
                app.handle(curses.KEY_SR)
                if view == 'boards':
                    self.assertEqual(app.explorer.board_slug, 'board-0')
                elif view == 'tasks':
                    self.assertEqual(app.explorer.selected_id, 'task-0')
                elif view == 'menu':
                    self.assertEqual(app.column_menu['index'], 0)
                else:
                    self.assertEqual(app.popup_scroll, 0)

    def test_control_shift_arrows_jump_full_pages_in_each_view(self):
        for view in ('boards', 'tasks', 'menu', 'popup'):
            with self.subTest(view=view):
                app = self.long_app(start_in_board=view != 'boards')
                if view == 'menu':
                    app.handle('s')
                elif view == 'popup':
                    app.explorer.selected['description'] = '\n'.join(f'Line {i}' for i in range(100))
                    app.handle('\n')
                app.draw()
                size = {'boards': app.board_height, 'tasks': app.task_height,
                        'menu': app.column_menu.get('capacity', 1) if app.column_menu else 1, 'popup': app.popup_height}[view]
                with patch('kanitor.ui.curses.keyname', return_value=b'kDN6'):
                    app.handle(999)
                app.draw()
                if view == 'boards':
                    index = int(app.explorer.board_slug.removeprefix('board-'))
                    self.assertLessEqual(app.summary_table.starts[index], size)
                    self.assertGreater(app.summary_table.starts[index + 1], size)
                    self.assertEqual(app.board_top, size)
                elif view == 'tasks':
                    self.assertEqual(app.explorer.selected_id, f'task-{size}')
                    self.assertEqual(app.task_top, size)
                elif view == 'menu':
                    self.assertEqual(app.column_menu['index'], size)
                    self.assertEqual(app.column_menu['top'], size)
                else:
                    self.assertEqual(app.popup_scroll, size)
                with patch('kanitor.ui.curses.keyname', return_value=b'kUP6'):
                    app.handle(999)
                app.draw()
                bar = next(bar for bar in app.scrollbars if bar['kind'] == ('column_menu' if view == 'menu' else view))
                self.assertEqual(bar['thumb_top'], 0)

    def test_scrollbar_track_click_pages_without_opening_an_item(self):
        app = self.long_app()
        bar = app.scrollbars[0]
        event = (0, bar['x'], bar['y'] + bar['height'] - 1, 0, curses.BUTTON1_PRESSED)
        with patch('kanitor.ui.curses.getmouse', return_value=event):
            app.handle(curses.KEY_MOUSE)
        app.draw()
        self.assertEqual(app.explorer.selected_id, f"task-{bar['visible']}")
        self.assertEqual(app.task_top, bar['visible'])
        self.assertIsNone(app.popup)

    def test_custom_metadata_columns_render_in_configured_order(self):
        app = self.app(24, 90)
        card = app.explorer.selected
        card['metadata'].update(assignee='Sam', points=0, enabled=False)
        data = snapshot()
        data['boards'][0]['tasks'][0] = card
        data['customization'] = {'columns': [
            {'title': 'Owner', 'metadata': 'assignee', 'width': 12},
            {'title': 'Points', 'metadata': 'points', 'width': 8},
            {'title': 'Enabled', 'metadata': 'enabled', 'width': 8},
            {'title': 'Stage', 'field': 'status', 'width': 16},
            {'title': 'Work', 'field': 'name'}]}
        app.explorer.apply(data)
        app.draw()
        text = app.screen.text()
        header = text.splitlines()[4]
        self.assertLess(header.index('Owner'), header.index('Stage'))
        self.assertLess(header.index('Stage'), header.index('Work'))
        self.assertNotIn('ASSIGNED', header)
        self.assertIn('Sam', text)
        self.assertIn('false', text)
        self.assertGreater(app.status_header[1], 7)
        app.handle('s')
        app.draw()
        self.assertIn('[x] All statuses', app.screen.text())

    def test_status_filter_still_works_when_status_column_is_omitted(self):
        app = self.app(16, 60)
        data = snapshot()
        data['customization'] = {'columns': [{'title': 'Ticket', 'field': 'name'}]}
        app.explorer.apply(data)
        app.draw()
        self.assertIsNone(app.status_header)
        app.handle(curses.KEY_UP)
        self.assertTrue(app.task_header_selected)
        app.handle('s')
        app.draw()
        self.assertTrue(app.column_menu)
        self.assertIn('[x] All statuses', app.screen.text())
        app.handle(' ')
        self.assertEqual(app.explorer.rows, [])

    def test_empty_hug_headers_and_fill_layout_render_and_resize(self):
        app = self.app(24, 90)
        data = snapshot()
        data['customization'] = {'columns': [
            {'title': '', 'metadata': 'assigned', 'width': 'hug'},
            {'title': '', 'field': 'status', 'width': 'hug'},
            {'title': 'Work', 'field': 'name', 'width': 'fill'}]}
        app.explorer.apply(data)
        app.draw()
        initial = [(c.field or c.metadata, w) for c, w in app.table_layout()[0]]
        self.assertEqual(initial[0], ('assigned', 6))  # Morgan, not an invented header.
        self.assertNotIn('ASSIGNED', app.screen.text().splitlines()[4])
        self.assertNotIn('STATUS', app.screen.text().splitlines()[4])
        self.assertNotIn('▾', app.screen.text().splitlines()[4])
        app.handle(curses.KEY_DOWN)
        app.draw()
        self.assertEqual([(c.field or c.metadata, w) for c, w in app.table_layout()[0]], initial)
        app.screen = Screen(16, 60)
        app.draw()
        narrower = app.table_layout()[0]
        self.assertEqual(narrower[0][1], initial[0][1])
        self.assertLess(narrower[-1][1], initial[-1][1])
        app.handle('s')
        app.draw()
        self.assertIn('[x] All statuses', app.screen.text())

    def filter_app(self):
        app = self.app(28, 100)
        data = snapshot()
        data['customization'] = {'columns': [
            {'title': 'Status', 'field': 'status', 'width': 'hug'},
            {'title': 'Owner', 'metadata': 'assigned', 'filterable': True, 'width': 'hug'},
            {'title': 'Task', 'field': 'name', 'width': 'fill'}]}
        app.explorer.apply(data)
        app.draw()
        return app

    def test_keyboard_navigates_all_headers_and_filters_custom_values(self):
        app = self.filter_app()
        app.handle(curses.KEY_UP)
        app.handle(curses.KEY_RIGHT)
        app.handle('\n')
        app.handle('\n')
        app.draw()
        self.assertEqual(app.column_menu['column'].metadata, 'assigned')
        self.assertIn('[x] All values', app.screen.text())
        app.handle(curses.KEY_DOWN)
        app.handle(' ')
        app.handle('\x1b')
        app.draw()
        self.assertEqual([c['id'] for c in app.explorer.rows], ['two', 'three'])
        self.assertIn('Owner▾', app.screen.text())
        app.handle(curses.KEY_RIGHT)
        self.assertEqual(app.cell_columns[app.focus.index][0].field, 'name')
        app.handle(curses.KEY_DOWN)
        self.assertFalse(app.focus.header)

    def test_mouse_custom_filter_and_live_removal(self):
        app = self.filter_app()
        row, left, _, column = next(h for h in app.filter_headers if h[3].metadata == 'assigned')
        with patch('kanitor.ui.curses.getmouse', return_value=(0, left, row, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        app.handle('\n')
        app.draw()
        self.assertEqual(app.column_menu['column'].key, column.key)
        app.handle(curses.KEY_END)
        app.handle(' ')
        self.assertEqual([c['id'] for c in app.explorer.rows], ['one', 'two'])
        data = snapshot()
        data['customization'] = {'columns': [{'title': 'Name', 'field': 'name'}]}
        app.explorer.apply(data)
        app.draw()
        self.assertIsNone(app.column_menu)
        self.assertFalse(app.explorer.task_state.filters)

    def test_left_right_navigate_all_headers_without_opening_them(self):
        app = self.filter_app()
        app.handle(curses.KEY_UP)
        app.handle(curses.KEY_LEFT)
        self.assertEqual(app.focus.index, 0)
        self.assertEqual(app.view, 'tasks')
        app.handle(curses.KEY_RIGHT)
        self.assertEqual(app.focus.index, 1)
        app.handle(curses.KEY_RIGHT)
        self.assertEqual(app.focus.index, 2)
        self.assertIsNone(app.column_menu)
        app.handle(' ')
        self.assertEqual(app.column_menu['column'].field, 'name')
        app.handle('\x1b')
        app.handle(curses.KEY_DOWN)
        app.handle(curses.KEY_RIGHT)
        self.assertIsNone(app.popup)
        app.handle('\n')
        self.assertEqual(app.popup, ('card', 'one'))

    def test_right_never_opens_a_sole_header(self):
        app = self.app()
        data = snapshot()
        data['customization'] = {'columns': [{'title': 'Status', 'field': 'status'}]}
        app.explorer.apply(data)
        app.draw()
        app.handle(curses.KEY_UP)
        app.handle(curses.KEY_RIGHT)
        self.assertIsNone(app.column_menu)
        app.handle('\n')
        self.assertEqual(app.column_menu['column'].field, 'status')

    def test_preview_has_eight_rows_tracks_selection_and_toggles(self):
        app = self.app(28, 100)
        app.explorer.board['tasks'][0]['description'] = 'First full description.\nA second paragraph.'
        app.draw()
        original_height = app.task_height
        top, _, height, _ = app.preview_rect
        self.assertEqual(height, 8)
        self.assertIn('First full description.', app.screen.text())
        self.assertIn('A second paragraph.', app.screen.text())
        app.handle(curses.KEY_DOWN)
        app.draw()
        self.assertEqual(app.preview_rect[0], top)
        self.assertIn('Inspect native metadata', app.screen.text())
        self.assertNotIn('First full description.', app.screen.text())
        app.handle('p')
        app.draw()
        self.assertIsNone(app.preview_rect)
        self.assertEqual(app.task_height, original_height + 9)
        app.handle('p')
        app.draw()
        self.assertEqual(app.preview_rect[2], 8)

    def test_preview_ignores_mouse_input_and_hides_in_details_and_small_terminals(self):
        app = self.app(28, 100)
        app.draw()
        top, left, _, _ = app.preview_rect
        for buttons in (curses.BUTTON1_PRESSED, WHEEL_DOWN, WHEEL_UP):
            with patch('kanitor.ui.curses.getmouse', return_value=(0, left + 4, top + 2, 0, buttons)):
                app.handle(curses.KEY_MOUSE)
            self.assertEqual(app.explorer.selected_id, 'one')
            self.assertIsNone(app.popup)
            self.assertFalse(app.task_header_selected)
        app.handle('\n')
        app.draw()
        self.assertIsNone(app.preview_rect)
        app.handle('\x1b')
        app.screen = Screen(16, 60)
        app.draw()
        self.assertIsNone(app.preview_rect)
        self.assertIn('Preview needs 19 rows', app.screen.text())
        app.screen = Screen(28, 100)
        app.draw()
        self.assertEqual(app.preview_rect[2], 8)
