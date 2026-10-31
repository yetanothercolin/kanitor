from copy import deepcopy
import curses
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from kanitor.config import ConfigError, SquareRules, parse_config
from kanitor.model import Explorer
from kanitor.mouse import WHEEL_DOWN, WHEEL_UP
from kanitor.projects import ProjectCatalog
from kanitor.projects_ui import ProjectsApp
from kanitor.squares import Square, SquareView, board_squares, classify, latest_work, project_squares
from kanitor.ui import App
from kanitor.text import cells
import test_ui
from test_ui import StyledScreen

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc).timestamp()


def at(seconds):
    return datetime.fromtimestamp(NOW + seconds, timezone.utc).isoformat()


def card(identity, column='Queue', **metadata):
    return {'id': identity, 'name': identity, 'board': 'index', 'column': column, 'metadata': metadata, 'history': []}


def board(tasks):
    return {'slug': 'index', 'name': 'Example', 'columns': ['Queue', 'Building', 'Shipped'],
            'options': {'startedColumns': ['Building'], 'completedColumns': ['Shipped']}, 'tasks': tasks}


def fixture():
    tasks = [card('done', 'Shipped', completed=at(-60)), card('done-older', 'Shipped', completed=at(-120)),
             card('hidden', 'Shipped', completed=at(-86400)),
             card('running', 'Building'), card('running-newer', 'Building'), card('stale', 'Building'),
             card('paused', started=at(-100000)), card('new', created=at(-60)), card('old', created=at(-100000))]
    return board(tasks), {'running': NOW - 60, 'running-newer': NOW - 10, 'stale': NOW - 900}


def work_snapshot(work):
    return {'sessions': [{'id': key, 'subject': {'provider': 'kanbn', 'ref': key}} for key in work],
            'events': [{'session_id': key, 'recorded_at': datetime.fromtimestamp(value, timezone.utc).isoformat(),
                        'type': 'note.added'} for key, value in work.items()]}


class SquareModelTests(unittest.TestCase):
    def test_native_states_recency_boundaries_and_unknown_dates(self):
        native, work = fixture()
        original = deepcopy(native)
        squares = board_squares(native, work, NOW, SquareRules())
        self.assertEqual([(square.id, square.kind) for square in squares], [
            ('done', 'done'), ('done-older', 'done'), ('running', 'active'), ('running-newer', 'active'),
            ('stale', 'stale'), ('paused', 'paused'), ('new', 'new'), ('old', 'old')])
        self.assertEqual(native, original)
        self.assertEqual(classify(native, card('future', created=at(100)), work, NOW, SquareRules()).kind, 'old')
        self.assertIsNone(classify(native, card('unknown', 'Shipped', completed='not a date'), work, NOW, SquareRules()))
        self.assertEqual(classify(native, card('reopened', completed=at(-60)), work, NOW, SquareRules()).kind, 'paused')
        self.assertEqual(classify(native, card('boundary', created=at(-86400)), work, NOW, SquareRules()).kind, 'old')
        self.assertEqual(classify(native, card('active', 'Building'), {}, NOW, SquareRules()).kind, 'stale')

    def test_native_history_fills_dates_and_detects_pause_without_named_columns(self):
        native = board([])
        completed = card('done', 'Shipped')
        completed['history'] = [{'type': 'moved', 'toColumn': 'Shipped', 'date': at(-30)}]
        self.assertEqual(classify(native, completed, {}, NOW, SquareRules()).kind, 'done')
        paused = card('paused')
        paused['history'] = [{'type': 'moved', 'fromColumn': 'Building', 'toColumn': 'Queue', 'date': at(-30)}]
        self.assertEqual(classify(native, paused, {}, NOW, SquareRules()).kind, 'paused')
        paused['history'][0]['board'] = 'other'
        self.assertEqual(classify(native, paused, {}, NOW, SquareRules()).kind, 'old')
        created = card('new')
        created['history'] = [{'type': 'created', 'date': at(-60), 'column': 'Queue'}]
        self.assertEqual(classify(native, created, {}, NOW, SquareRules()).kind, 'new')
        native['options'] = {}
        self.assertEqual(classify(native, card('not-done', 'Shipped'), {}, NOW, SquareRules()).kind, 'old')

    def test_work_uses_effective_subjects_and_real_logged_events_not_amendments(self):
        data = work_snapshot({'one': NOW - 120, 'two': NOW - 300})
        data['sessions'][0]['subject']['ref'] = 'rebound'
        data['events'] += [{'session_id': 'two', 'recorded_at': at(-1), 'type': 'work.amended'},
                           {'session_id': 'two', 'recorded_at': at(-50), 'type': 'span.ended'}]
        self.assertEqual(latest_work(data), {'rebound': NOW - 120, 'two': NOW - 50})
        self.assertEqual(latest_work(None), {})

    def test_groups_wrap_at_lane_boundaries_and_active_positions_survive_all_state_changes(self):
        native, work = fixture()
        view = SquareView()
        view.enter('boards')
        bundle = view.bundle('index', board_squares(native, work, NOW, SquareRules()))
        self.assertEqual([[square.id for square in group] for group in bundle.groups], [
            ['running-newer', 'running', 'stale'], ['done', 'done-older'], ['paused', 'new', 'old']])
        self.assertEqual(len(bundle.lines(99)), 1)
        self.assertEqual([[square.id for square in line] for line in bundle.lines(5)], [
            ['running-newer', 'running', 'stale'], ['done', 'done-older'], ['paused', 'new', 'old']])
        self.assertTrue(all(len(line) <= 2 for line in bundle.lines(4)))
        native['tasks'][3].update(column='Shipped', metadata={'completed': at(-1)})
        native['tasks'][4].update(column='Queue', metadata={'started': at(-200)})
        changed = view.bundle('index', board_squares(native, {'stale': NOW}, NOW, SquareRules()))
        self.assertEqual([square.id for square in changed.groups[0]], ['running-newer', 'running', 'stale'])
        self.assertEqual([square.kind for square in changed.groups[0]], ['paused', 'done', 'active'])
        self.assertEqual([square.glyph for square in changed.groups[0]], ['□', '■', '□'])
        view.enter('tasks')
        view.enter('boards')
        refreshed = view.bundle('index', board_squares(native, {'stale': NOW}, NOW, SquareRules()))
        self.assertEqual([square.id for square in refreshed.groups[0]], ['stale'])
        self.assertEqual(refreshed.groups[1][0].id, 'running')

    def test_project_aggregation_counts_shared_tasks_once_with_incomplete_precedence(self):
        done = board([card('shared', 'Shipped', completed=at(-1)), card('finished', 'Shipped', completed=at(-60))])
        active = board([card('shared', 'Building')])
        active['slug'] = 'other'
        squares = project_squares([done, active], {'shared': NOW - 30}, NOW, SquareRules())
        self.assertEqual({square.id: square.kind for square in squares}, {'shared': 'active', 'finished': 'done'})

    def test_initial_order_waits_for_work_snapshot_and_then_freezes(self):
        view = SquareView()
        view.enter('boards')
        provisional = [Square('older', 'stale'), Square('newer', 'stale')]
        view.bundle('index', provisional, freeze=False)
        self.assertNotIn('index', view.active)
        first = view.bundle('index', [Square('older', 'active', work_at=1), Square('newer', 'active', work_at=2)])
        self.assertEqual([item.id for item in first.groups[0]], ['newer', 'older'])
        later = view.bundle('index', [Square('older', 'active', work_at=9), Square('newer', 'stale', work_at=2)])
        self.assertEqual([item.id for item in later.groups[0]], ['newer', 'older'])

    def test_age_transitions_change_appearance_and_hide_old_completions(self):
        native, work = fixture()
        before = {square.id: square.kind for square in board_squares(native, work, NOW, SquareRules())}
        later = {square.id: square.kind for square in board_squares(native, work, NOW + 86400, SquareRules())}
        self.assertEqual(before['running-newer'], 'active')
        self.assertEqual(later['running-newer'], 'stale')
        self.assertEqual(later['new'], 'old')
        self.assertNotIn('done', later)

    def test_column_and_recency_rules_validate_independently(self):
        rules = parse_config({'projectColumns': [{'title': '', 'field': 'task_squares', 'width': 'hug'}],
                              'boardColumns': [{'title': 'Activity', 'field': 'task_squares', 'width': 9}],
                              'taskSquares': {'recentCompleted': '2d', 'recentWork': '1h', 'recentCreated': '3d'}})
        self.assertEqual(rules.square_rules, SquareRules(172800, 3600, 259200))
        self.assertFalse(rules.project_columns[0].can_filter)
        for invalid in ({'taskSquares': {'recentWork': '0m'}}, {'taskSquares': {'recentWork': 10}},
                        {'taskSquares': {'typo': '1d'}}, {'projectColumns': []},
                        {'columns': [{'title': '', 'field': 'task_squares'}]},
                        {'projectColumns': [{'title': '', 'metadata': 'owner'}]},
                        {'boardColumns': [{'title': '', 'field': 'task_squares', 'format': '%H'}]}):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigError):
                parse_config(invalid)

    def test_default_status_headings_preserve_custom_titles_and_field_names(self):
        defaults = parse_config({})
        for columns in (defaults.board_columns, defaults.project_columns):
            self.assertEqual(next(column.title for column in columns if column.field == 'task_squares'), 'TASK STATUS')
        custom = parse_config({'boardColumns': [{'title': 'Tasks', 'field': 'task_squares'}],
                               'projectColumns': [{'title': '', 'field': 'task_squares'}]})
        self.assertEqual(custom.board_columns[0].title, 'Tasks')
        self.assertEqual(custom.project_columns[0].title, '')


class SquareUITests(unittest.TestCase):
    def setUp(self):
        # Key handling also reclassifies squares; keep fixture completion dates
        # recent between draws instead of depending on the actual calendar date.
        self.enterContext(patch('kanitor.ui.time.time', return_value=NOW))

    def app(self, tasks=None, width=70, height=16):
        native, work = fixture()
        if tasks is not None:
            native['tasks'] = tasks
        data = {'boards': [native], 'customization': {'boardColumns': [
            {'title': 'Board', 'field': 'name', 'width': 12}, {'title': 'Squares', 'field': 'task_squares', 'width': 5}]}}
        explorer = Explorer()
        explorer.apply(data)
        app = App(test_ui.Screen(height, width), Path('/missing-square-fixture'), explorer)
        app.work_reader.snapshot = work_snapshot(work)
        app.work_reader.revision = 1
        self.addCleanup(app.close)
        return app

    def draw(self, app):
        with patch('kanitor.ui.time.time', return_value=NOW), patch('kanitor.ui.time.monotonic', return_value=0):
            app.draw()

    def click(self, app, identity, buttons=curses.BUTTON1_PRESSED):
        row, left, _, _ = next(hit for hit in app.square_hits if hit[3].id == identity)
        with patch('kanitor.ui.curses.getmouse', return_value=(0, left, row, 0, buttons)):
            app.handle(curses.KEY_MOUSE)
        return row, left

    def test_only_squares_column_focuses_first_task_and_opens_it(self):
        app = self.app(tasks=[card('single', created=at(-10))], height=28)
        app.explorer.apply({'boards': app.explorer.boards, 'customization': {'boardColumns': [
            {'title': 'Tasks', 'field': 'task_squares'}]}})
        self.draw(app)
        self.assertEqual(app.selected_square, ('index', 'single'))
        self.assertEqual(app.preview_rect[2], 8)
        app.handle(curses.KEY_RIGHT)
        self.assertEqual(app.selected_square, ('index', 'single'))
        app.handle(' ')
        self.assertEqual(app.popup, ('card', 'single'))

    def test_square_edges_continue_into_cells_and_enter_from_right_selects_last(self):
        app = self.app(tasks=[card(str(i), created=at(-10)) for i in range(3)])
        app.explorer.apply({'boards': app.explorer.boards, 'customization': {'boardColumns': [
            {'title': 'Board', 'field': 'name', 'width': 12},
            {'title': 'Tasks', 'field': 'task_squares', 'width': 5},
            {'title': 'Count', 'field': 'cards', 'width': 'hug'}]}})
        self.draw(app)
        app.handle(curses.KEY_RIGHT)
        self.assertEqual(app.selected_square, ('index', '0'))
        for _ in range(3):
            app.handle(curses.KEY_RIGHT)
        self.assertEqual(app.focus.index, 2)
        self.assertIsNone(app.selected_square)
        self.assertIsNone(app.popup)
        app.handle(curses.KEY_LEFT)
        self.assertEqual(app.selected_square, ('index', '2'))

    def test_vertical_square_goal_survives_an_empty_board(self):
        app = self.app(height=28)
        boards = []
        for slug, count in (('top', 3), ('middle', 0), ('bottom', 3)):
            native = board([card(f'{slug}-{i}', created=at(-10)) for i in range(count)])
            native.update(slug=slug, name=slug)
            boards.append(native)
        app.explorer.apply({'boards': boards, 'customization': {'boardColumns': [
            {'title': 'Board', 'field': 'name', 'width': 12},
            {'title': 'Tasks', 'field': 'task_squares', 'width': 5}]}})
        self.draw(app)
        for _ in range(3):
            app.handle(curses.KEY_RIGHT)
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        self.assertEqual(app.explorer.board_slug, 'middle')
        self.assertIsNone(app.selected_square)
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        self.assertEqual(app.selected_square, ('bottom', 'bottom-2'))

    def test_status_cell_background_and_spaces_stay_normal_inside_focus_outline(self):
        app = self.app()
        app.screen = StyledScreen(16, 70)
        app.colors['cyan'] = 1 << 8
        self.draw(app)
        self.assertTrue(app.screen.attributes[5][3] & curses.A_REVERSE)
        lines = app.screen.text().splitlines()
        self.assertEqual((lines[5][2], lines[5][66]), ('╭', '╮'))
        self.assertEqual((lines[6][2], lines[6][66]), ('│', '│'))
        self.assertEqual((lines[7][2], lines[7][66]), ('╰', '╯'))
        for row in (5, 6, 7):
            self.assertEqual(app.screen.attributes[row][2], app.colors['cyan'])
            self.assertEqual(app.screen.attributes[row][66], app.colors['cyan'])
            self.assertTrue(all(not app.screen.attributes[row][column] & curses.A_REVERSE for column in range(15, 22)))
        app.handle(curses.KEY_RIGHT)
        self.draw(app)
        self.assertTrue(app.screen.attributes[5][16] & curses.A_REVERSE)
        self.assertFalse(app.screen.attributes[5][3] & curses.A_REVERSE)
        for row in (5, 6, 7):
            for column in range(15, 22):
                self.assertEqual(bool(app.screen.attributes[row][column] & curses.A_REVERSE), (row, column) == (5, 16))
        app.handle(curses.KEY_RIGHT)
        self.draw(app)
        self.assertFalse(app.screen.attributes[5][16] & curses.A_REVERSE)
        self.assertTrue(app.screen.attributes[5][18] & curses.A_REVERSE)
        app.handle(curses.KEY_UP)
        self.draw(app)
        self.assertEqual(app.screen.text().splitlines()[5][2], ' ')
        self.assertFalse(any(attr & curses.A_REVERSE for attr in app.screen.attributes[5]))

    def test_single_line_focus_outline_keeps_square_geometry_and_colors(self):
        app = self.app(tasks=[card('single', created=at(-10))])
        app.screen = StyledScreen(16, 70)
        self.draw(app)
        line = app.screen.text().splitlines()[5]
        self.assertEqual((line[2], line[66]), ('⟦', '⟧'))
        self.assertEqual(line[15:22], ' □     ')
        self.assertEqual(len(app.square_hits), 1)
        self.assertEqual(app.square_hits[0][:2], (5, 16))
        self.assertTrue(all(not attr & curses.A_REVERSE for attr in app.screen.attributes[5][15:22]))
        self.click(app, 'single', curses.BUTTON1_DOUBLE_CLICKED)
        self.assertEqual(app.popup, ('card', 'single'))

    def test_square_click_previews_exact_task_and_preserves_filters(self):
        app = self.app(height=28)
        app.explorer.board['tasks'][-2]['description'] = 'Description of the selected new task.'
        app.explorer.search('does-not-match')
        self.draw(app)
        self.click(app, 'new')
        self.draw(app)
        self.assertEqual(app.selected_square, ('index', 'new'))
        self.assertEqual(app.preview_rect[2], 8)
        self.assertIn('Description of the selected new task.', app.screen.text())
        self.assertIsNone(app.popup)
        self.assertEqual(app.explorer.query, 'does-not-match')
        app.handle('\n')
        self.assertEqual(app.popup, ('card', 'new'))
        app.handle('\x1b')
        self.assertEqual(app.view, 'boards')
        self.assertEqual(app.explorer.query, 'does-not-match')
        self.assertEqual(app.selected_square, ('index', 'new'))

    def test_double_click_survives_preview_reflow_at_original_coordinates(self):
        app = self.app(tasks=[card(str(i), created=at(-10)) for i in range(100)], height=28)
        self.draw(app)
        with patch('kanitor.ui.time.monotonic', return_value=100):
            row, left = self.click(app, '45')
        self.draw(app)
        self.assertIsNotNone(app.preview_rect)
        self.assertGreaterEqual(row, app.preview_rect[0])
        self.assertNotIn((row, left), [(y, x) for y, x, _, square in app.square_hits if square.id == '45'])
        with patch('kanitor.ui.time.monotonic', return_value=100.1), \
                patch('kanitor.ui.curses.getmouse', return_value=(0, left, row, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.popup, ('card', '45'))

    def test_keyboard_square_navigation_preview_toggle_and_cell_exit(self):
        app = self.app(height=28)
        self.draw(app)
        app.handle(curses.KEY_RIGHT)
        self.draw(app)
        self.assertEqual(app.selected_square, ('index', 'running-newer'))
        app.handle(curses.KEY_RIGHT)
        self.assertEqual(app.selected_square, ('index', 'running'))
        app.handle(curses.KEY_DOWN)
        self.assertEqual(app.selected_square, ('index', 'done-older'))
        app.handle('p')
        self.draw(app)
        self.assertIsNone(app.preview_rect)
        app.handle('p')
        self.draw(app)
        self.assertEqual(app.preview_rect[2], 8)
        app.handle('\n')
        self.assertEqual(app.popup, ('card', 'done-older'))
        app.handle('q')
        self.assertIsNone(app.popup)
        app.handle('\x1b')
        self.assertEqual(app.selected_square, ('index', 'done-older'))  # Root has no parent.
        app.handle(curses.KEY_HOME)
        app.handle(curses.KEY_LEFT)
        self.draw(app)
        self.assertIsNone(app.selected_square)
        self.assertIsNone(app.preview_rect)
        self.assertEqual(app.view, 'boards')

    def test_keyboard_square_pages_and_ten_item_jumps_reach_hidden_squares(self):
        app = self.app(tasks=[card(str(i), created=at(-10)) for i in range(100)], height=28)
        self.draw(app)
        app.handle(curses.KEY_RIGHT)
        self.draw(app)
        page = app.board_height
        app.handle(curses.KEY_NPAGE)
        self.draw(app)
        self.assertEqual(app.board_top, page)
        self.assertEqual(app.selected_square, ('index', str(page * 3)))
        app.handle(curses.KEY_SF)
        self.assertEqual(app.selected_square, ('index', str(page * 3 + 10)))
        app.handle(curses.KEY_END)
        self.draw(app)
        self.assertEqual(app.selected_square, ('index', '99'))
        self.assertIn('99', [square.id for _, _, _, square in app.square_hits])
        app.handle(curses.KEY_HOME)
        self.draw(app)
        self.assertEqual(app.board_top, 0)
        self.assertEqual(app.selected_square, ('index', '0'))

    def test_vertical_square_navigation_crosses_boards_and_keeps_preferred_column(self):
        app = self.app(height=28)
        boards = []
        for slug, count in (('top', 3), ('middle', 2), ('bottom', 3)):
            native = board([card(f'{slug}-{i}', created=at(-10)) for i in range(count)])
            native.update(slug=slug, name=slug)
            boards.append(native)
        data = {'boards': boards, 'customization': {'boardColumns': [
            {'title': 'Board', 'field': 'name', 'width': 12}, {'title': 'Tasks', 'field': 'task_squares', 'width': 5}]}}
        app.explorer.apply(data)
        self.draw(app)
        app.handle(curses.KEY_RIGHT)
        app.handle(curses.KEY_RIGHT)
        app.handle(curses.KEY_RIGHT)
        self.draw(app)
        self.assertEqual(app.selected_square, ('top', 'top-2'))
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        self.assertEqual(app.selected_square, ('middle', 'middle-1'))
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        self.assertEqual(app.selected_square, ('bottom', 'bottom-2'))
        app.handle(curses.KEY_UP)
        self.draw(app)
        app.handle(curses.KEY_UP)
        self.draw(app)
        self.assertEqual(app.selected_square, ('top', 'top-2'))
        app.handle(curses.KEY_LEFT)
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        self.assertEqual(app.selected_square, ('bottom', 'bottom-1'))

    def test_vertical_navigation_crosses_wrapped_boundary_and_focuses_empty_row(self):
        app = self.app(tasks=[card(f'first-{i}', created=at(-10)) for i in range(6)], height=28)
        other = board([card(f'next-{i}', created=at(-10)) for i in range(3)])
        other.update(slug='next', name='Next')
        empty = board([])
        empty.update(slug='empty', name='Empty')
        app.explorer.boards += [other, empty]
        self.draw(app)
        app.handle(curses.KEY_RIGHT)
        app.handle(curses.KEY_RIGHT)
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        self.assertEqual(app.selected_square, ('index', 'first-4'))
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        self.assertEqual(app.selected_square, ('next', 'next-1'))
        app.handle(curses.KEY_UP)
        self.draw(app)
        self.assertEqual(app.selected_square, ('index', 'first-4'))
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        self.assertEqual(app.explorer.board_slug, 'empty')
        self.assertIsNone(app.selected_square)
        self.assertIsNone(app.preview_rect)

    def test_vertical_square_navigation_crosses_projects_and_opens_destination_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = ['top', 'middle', 'bottom']
            for path in paths:
                (root / path).mkdir()
            (root / '.kanitor.json').write_text(json.dumps({'projects': paths, 'projectColumns': [
                {'title': 'Project', 'field': 'name', 'width': 12}, {'title': 'Tasks', 'field': 'task_squares', 'width': 5}]}))
            catalog = ProjectCatalog(root)
            catalog.poll(force=True)
            app = ProjectsApp(test_ui.Screen(28, 70), root, catalog)
            self.addCleanup(app.close)
            for path, count in zip(paths, (3, 2, 3)):
                native = board([card(f'task-{i}', created=at(-10)) for i in range(count)])
                for task in native['tasks']:
                    task['description'] = path + ' project description'
                child = app.children[str(root / path)]
                child.explorer.apply({'boards': [native]})
                child.reader.snapshot = {'boards': [native]}
            self.draw(app)
            app.handle(curses.KEY_RIGHT)
            app.handle(curses.KEY_RIGHT)
            app.handle(curses.KEY_RIGHT)
            self.draw(app)
            app.handle(curses.KEY_DOWN)
            self.draw(app)
            self.assertEqual(app.selected_square, (str(root / 'middle'), 'task-1'))
            self.assertIn('middle project description', app.screen.text())
            app.handle(curses.KEY_DOWN)
            self.draw(app)
            self.assertEqual(app.selected_square, (str(root / 'bottom'), 'task-2'))
            app.handle('\n')
            self.assertIs(app.active, app.children[str(root / 'bottom')])
            self.assertEqual(app.active.popup, ('card', 'task-2'))
            self.draw(app)
            self.assertIn('KANITOR / bottom / Example / task-2', app.screen.text().splitlines()[0])

    def test_task_preview_ignores_mouse_and_deleted_square_clears_selection(self):
        app = self.app(height=28)
        self.draw(app)
        self.click(app, 'new')
        self.draw(app)
        top, left, _, _ = app.preview_rect
        for button in (curses.BUTTON1_PRESSED, WHEEL_DOWN):
            with patch('kanitor.ui.curses.getmouse', return_value=(0, left + 4, top + 2, 0, button)):
                app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.selected_square, ('index', 'new'))
        app.explorer.board['tasks'] = [task for task in app.explorer.board['tasks'] if task['id'] != 'new']
        app.reader.revision += 1
        self.draw(app)
        self.assertIsNone(app.selected_square)
        self.assertIsNone(app.preview_rect)

    def test_project_square_preview_and_details_use_correct_board_and_restore_child_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            child_root = root / 'one'
            child_root.mkdir()
            (root / '.kanitor.json').write_text(json.dumps({'projects': ['one'], 'projectColumns': [
                {'title': 'Project', 'field': 'name', 'width': 12}, {'title': 'Tasks', 'field': 'task_squares', 'width': 5}]}))
            catalog = ProjectCatalog(root)
            catalog.poll(force=True)
            app = ProjectsApp(test_ui.Screen(28, 70), root, catalog)
            self.addCleanup(app.close)
            child = app.children[str(child_root)]
            main = board([card('shared', 'Shipped', completed=at(-10))])
            review = board([card('shared', 'Building')])
            review.update(slug='review', name='Review')
            review['tasks'][0].update(board='review', description='Correct review task description.')
            child.explorer.apply({'boards': [main, review]})
            child.reader.snapshot = {'boards': [main, review]}
            original = child.explorer
            original.search('retained search')
            self.draw(app)
            self.click(app, 'shared')
            self.draw(app)
            self.assertIsNone(app.active)
            self.assertIn('Correct review task description.', app.screen.text())
            self.assertEqual(app.preview_rect[2], 8)
            app.handle('\n')
            self.assertIs(app.active, child)
            self.assertEqual(child.explorer.board_slug, 'review')
            self.assertEqual(child.popup, ('card', 'shared'))
            app.handle('\x1b')
            self.assertIsNone(app.active)
            self.assertIs(child.explorer, original)
            self.assertEqual(original.board_slug, 'index')
            self.assertEqual(original.query, 'retained search')
            self.assertEqual(app.selected_square, (str(child_root), 'shared'))
            self.draw(app)
            self.click(app, 'shared', curses.BUTTON1_DOUBLE_CLICKED)
            self.assertIs(app.active, child)
            self.draw(app)
            with patch('kanitor.ui.curses.getmouse', return_value=(0, 4, 1, 0, curses.BUTTON1_PRESSED)):
                app.handle(curses.KEY_MOUSE)
            self.assertIsNone(app.active)
            self.assertIs(child.explorer, original)
            self.assertIsNone(child.popup_return)

    def test_wrapped_square_double_click_opens_that_task(self):
        app = self.app()
        self.draw(app)
        lines = app.screen.text().splitlines()
        self.assertEqual(lines[5][16:21], '□ □ □')
        self.assertEqual(lines[6][16:21], '■ ■  ')
        self.assertEqual(lines[7][16:21], '□ □ □')
        self.assertEqual(app.summary_table.heights, [3])
        self.assertEqual([hit[0] for hit in app.hits], [5, 6, 7])
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 18, 7, 0, curses.BUTTON1_DOUBLE_CLICKED)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.view, 'boards')
        self.assertEqual(app.popup, ('card', 'new'))

    def test_row_larger_than_the_viewport_can_scroll_to_every_square_without_rebound(self):
        app = self.app(tasks=[card(str(i), created=at(-10)) for i in range(100)])
        self.draw(app)
        self.assertGreater(app.summary_table.total, app.board_height)
        app.handle(curses.KEY_NPAGE)
        self.draw(app)
        self.assertEqual(app.board_top, app.board_height)
        app.handle(curses.KEY_END)
        self.draw(app)
        self.assertEqual(app.board_top, app.summary_table.maximum)
        bar = app.scrollbars[0]
        self.assertEqual(bar['thumb_top'] + bar['thumb_size'], bar['height'])
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 18, 7, 0, WHEEL_UP)):
            for _ in range(100):
                app.handle(curses.KEY_MOUSE)
                self.draw(app)
        self.assertEqual(app.board_top, 0)
        app.needs_redraw = False
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 18, 7, 0, WHEEL_UP)):
            for _ in range(100):
                app.handle(curses.KEY_MOUSE)
        self.assertFalse(app.needs_redraw)
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 18, 7, 0, WHEEL_DOWN)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.board_top, 3)

    def test_pulse_attrs_are_only_for_active_tasks_and_use_three_gentle_levels(self):
        app = self.app()
        app.colors = {'square_green0': 1, 'square_green1': 2, 'square_green2': 3,
                      'square_yellow0': 4, 'square_yellow1': 5, 'square_yellow2': 6,
                      'done': 7, 'square_white': 8}
        self.assertEqual([app.square_attr(Square('a', 'active'), phase) for phase in range(3)], [1, 2, 3])
        self.assertEqual([app.square_attr(Square('a', 'stale'), phase) for phase in range(3)], [4, 5, 6])
        self.assertEqual(app.square_attr(Square('a', 'paused'), 0), 7 | curses.A_DIM)
        self.assertEqual(app.square_attr(Square('a', 'new'), 0), 8)
        self.assertEqual(app.square_attr(Square('a', 'old'), 0), 8 | curses.A_DIM)
        self.draw(app)
        self.assertTrue(app.squares_animated)
        app.handle('\n')
        self.draw(app)
        self.assertFalse(app.squares_animated)

    def test_clock_repaints_pulses_and_age_changes_but_not_an_unchanged_tick(self):
        app = self.app()
        with patch.object(app.reader, 'poll'), patch.object(app.work_reader, 'poll'), \
                patch('kanitor.ui.time.monotonic', return_value=10), patch('kanitor.ui.time.time', return_value=NOW):
            app.poll()
            app.draw()
            app.poll()
            app.needs_redraw = False
            app.poll()
            self.assertFalse(app.needs_redraw)
        with patch.object(app.reader, 'poll'), patch.object(app.work_reader, 'poll'), \
                patch('kanitor.ui.time.monotonic', return_value=10.7), patch('kanitor.ui.time.time', return_value=NOW):
            app.poll()
            self.assertTrue(app.needs_redraw)
        app.needs_redraw = False
        with patch.object(app.reader, 'poll'), patch.object(app.work_reader, 'poll'), \
                patch('kanitor.ui.time.monotonic', return_value=11), patch('kanitor.ui.time.time', return_value=NOW + 1):
            app.poll()
            self.assertTrue(app.needs_redraw)

    def test_project_column_uses_parent_rules_and_pins_until_leaving_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            child_root = root / 'one'
            child_root.mkdir()
            (root / '.kanitor.json').write_text(json.dumps({'projects': ['one'], 'projectColumns': [
                {'title': 'Project', 'field': 'name', 'width': 12}, {'title': 'Squares', 'field': 'task_squares', 'width': 5}]}))
            catalog = ProjectCatalog(root)
            catalog.poll(force=True)
            app = ProjectsApp(test_ui.Screen(16, 70), root, catalog)
            self.addCleanup(app.close)
            child = app.children[str(child_root)]
            native, work = fixture()
            child.explorer.apply({'boards': [native]})
            child.reader.snapshot = {'boards': [native]}
            child.work_reader.snapshot = work_snapshot(work)
            child.work_reader.revision = 1
            self.draw(app)
            self.assertEqual(app.summary_table.heights, [3])
            self.assertEqual([square.id for square in app.rows()[0]['task_squares'].groups[0]],
                             ['running-newer', 'running', 'stale'])
            before = dict(app.square_view.active[str(child_root)])
            native['tasks'][4].update(column='Shipped', metadata={'completed': at(-1)})
            child.reader.revision += 1
            self.draw(app)
            self.assertEqual(app.square_view.active[str(child_root)], before)
            app.open_project()
            app.show_projects()
            self.draw(app)
            self.assertNotIn('running-newer', app.square_view.active[str(child_root)])

    def test_summary_scroll_anchor_survives_rows_growing_above_it(self):
        app = self.app(tasks=[card(str(i), created=at(-10)) for i in range(30)])
        second = board([card('second')])
        second.update(slug='second', name='Second')
        app.explorer.boards.append(second)
        self.draw(app)
        app.handle(curses.KEY_END)
        self.draw(app)
        before = app.board_top
        app.explorer.boards[0]['tasks'] += [card(f'new-{i}', created=at(-10)) for i in range(9)]
        app.reader.revision += 1
        self.draw(app)
        self.assertEqual(app.explorer.board_slug, 'second')
        self.assertEqual(app.board_top, before + 3)
        self.assertEqual(app.hits[-1][2], 'second')
