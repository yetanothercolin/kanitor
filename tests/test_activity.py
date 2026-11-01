from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import shutil
import unittest
from unittest.mock import Mock, patch
import curses

from kanitor.activity import activity_rows
from kanitor.config import ConfigError, parse_config
from kanitor.model import Explorer
from kanitor.mouse import WHEEL_UP, WHEEL_DOWN
from kanitor.reader import read_once
from kanitor.ui import App
from kanitor.work.service import WorkService
from test_explorer import snapshot
from test_projects import ProjectFixture
import test_ui

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc).timestamp()


def date(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def session(task='two', started=NOW - 5, **extra):
    return dict({'id': 'session', 'subject': {'provider': 'kanbn', 'ref': task},
                 'state': 'open', 'started_at': date(started), 'label': 'Implementing',
                 'phases': [], 'created_seq': 1}, **extra)


class ActivityTests(ProjectFixture):
    def task_app(self, view='boards', height=28, width=110):
        explorer = Explorer()
        explorer.apply(snapshot())
        app = App(test_ui.StyledScreen(height, width), self.root, explorer, view == 'tasks')
        app.work_reader.snapshot = {'sessions': [session()], 'events': []}
        self.addCleanup(app.close)
        return app

    def draw(self, app, now=NOW):
        with patch('kanitor.activity.time.time', return_value=now):
            app.draw()

    def action(self, app, name):
        app.column_menu['index'] = next(i for i, (_, key) in enumerate(app.menu_entries()) if key == name)
        app.handle('\n')

    def cell_app(self):
        app = self.task_app()
        data = snapshot()
        template = data['boards'][0]['tasks'][1]
        data['boards'][0]['tasks'] = [dict(template, id=identity, name=name, metadata=metadata)
            for identity, name, metadata in (
                ('two', 'First task', {'assigned': 'Morgan', 'updated': '2026-10-28T12:00:00'}),
                ('other', 'Second task', {'assigned': 'Alex', 'updated': '2026-10-29T12:00:00'}),
                ('missing', 'Third task', {}))]
        data['customization'] = {'activityColumns': [
            {'title': 'Task', 'field': 'name', 'width': 'fill'},
            {'title': 'Owner', 'metadata': 'assigned', 'width': 'hug'},
            {'title': 'Updated', 'metadata': 'updated', 'width': 'hug', 'format': '%Y-%m-%d'},
            {'title': 'Elapsed', 'field': 'elapsed', 'width': 'hug'}]}
        app.explorer.apply(data)
        app.handle('a')
        app.handle('\t')
        self.draw(app)
        return app

    def test_activity_arrows_focus_cells_and_headers_without_drilling(self):
        app = self.cell_app()
        self.assertEqual(app.activity.focus.index, 0)
        app.handle(curses.KEY_RIGHT)
        self.draw(app)
        self.assertEqual(app.activity.focus.index, 1)
        self.assertIsNone(app.column_menu)
        self.assertIsNone(app.popup)
        for y, x, _, identity, index in app.activity.cell_hits:
            self.assertEqual(bool(app.screen.attributes[y][x] & curses.A_REVERSE),
                             identity == app.activity.selected and index == 1)
        app.handle(curses.KEY_UP)
        self.draw(app)
        self.assertTrue(app.activity.focus.header)
        for y, x, _, index in app.activity.header_hits:
            self.assertEqual(bool(app.screen.attributes[y][x] & curses.A_REVERSE), index == 1)
        app.handle(curses.KEY_RIGHT)
        self.assertIsNone(app.column_menu)
        app.handle('\n')
        self.draw(app)
        self.assertEqual(app.column_menu['table'], 'activity')
        self.assertEqual(app.column_menu['column'].metadata, 'updated')
        app.handle('\x1b')
        app.handle(curses.KEY_DOWN)
        self.assertFalse(app.activity.focus.header)
        self.assertEqual(app.activity.current['id'], 'two')

    def test_focused_activity_draws_context_and_shortcuts_on_separate_rows(self):
        for view in ('boards', 'projects'):
            app = self.cell_app() if view == 'boards' else self.app()
            if view == 'projects':
                self.fill(app)
                if not app.activity.shown:
                    app.handle('a')
                app.handle('\t')
            for width in (60, 110, 160):
                with self.subTest(view=view, width=width):
                    app.screen = test_ui.StyledScreen(28, width)
                    self.draw(app)
                    lines = app.screen.text().splitlines()
                    status, footer = lines[-2].strip(), lines[-1].strip()
                    self.assertTrue(status.startswith('Activity ·'))
                    self.assertIn('active', status)
                    self.assertIn('cells', footer)
                    self.assertNotIn('cells', status)
                    self.assertNotIn('Sort:', footer)
                    self.assertNotEqual(status, footer)
                    app.activity.focus.header = True
                    self.draw(app)
                    self.assertIn('column menu', app.screen.text().splitlines()[-1])
            app.handle('\n')
            self.draw(app)
            self.assertIsNotNone(app.column_menu)
            status, footer = app.screen.text().splitlines()[-2:]
            self.assertIn('Activity ·', status)
            self.assertNotEqual(status.strip(), footer.strip())

    def test_activity_status_retains_its_filters_sort_warnings_and_reader_errors(self):
        from kanitor.table_state import Criterion
        app = self.cell_app()
        app.screen = test_ui.StyledScreen(28, 160)
        task, owner = [column for column, _ in app.activity.columns[:2]]
        app.activity.state.filters[owner.key] = Criterion('only', owner.filter_token(app.activity.rows[1]))
        app.activity.state.sort = task.key, True
        app.explorer.board_state.sort = (('field', 'updated'), False)
        self.draw(app)
        status, footer = app.screen.text().splitlines()[-2:]
        self.assertIn('1 active', status)
        self.assertIn('1 filter', status)
        self.assertIn('Sort: Task ↓', status)
        self.assertNotIn('Sort: UPDATED', status)
        self.assertNotIn('filter', footer)
        self.assertNotIn('Sort:', footer)
        app.reader.error = 'Native reader unavailable'
        self.draw(app)
        self.assertIn(app.reader.error, app.screen.text().splitlines()[-2])
        self.assertIn('cells', app.screen.text().splitlines()[-1])
        app.reader.error = ''
        app.notice = 'Could not save view preferences'
        self.draw(app)
        self.assertIn(app.notice, app.screen.text().splitlines()[-2])
        app.notice = ''
        app.screen = test_ui.StyledScreen(24, 160)
        self.draw(app)
        self.assertIn('Preview needs 25 rows', app.screen.text().splitlines()[-2])
        self.assertNotIn('Preview needs', app.screen.text().splitlines()[-1])

    def test_activity_in_projects_does_not_hide_catalog_errors(self):
        app = self.app()
        self.fill(app)
        app.handle('a')
        app.handle('\t')
        app.catalog.error = 'Configuration unavailable'
        self.draw(app)
        self.assertIn('Configuration unavailable', app.screen.text().splitlines()[-2])
        self.assertIn('cells', app.screen.text().splitlines()[-1])

    def test_assigned_enter_and_context_filters_are_independent_of_main_table(self):
        app = self.cell_app()
        app.explorer.search('Second task')
        app.handle(curses.KEY_RIGHT)
        app.handle('\n')
        self.draw(app)
        self.assertEqual([r['id'] for r in app.activity.rows], ['two'])
        self.assertEqual([r['id'] for r in app.explorer.rows], ['other'])
        header = app.screen.text().splitlines()[app.activity.rect[0] + 1]
        self.assertIn('Owner▾', header)
        self.assertFalse(app.explorer.task_state.filters)
        app.handle('f')
        self.action(app, 'exclude')
        self.draw(app)
        self.assertEqual([r['id'] for r in app.activity.rows], ['other', 'missing'])
        template = app.explorer.board['tasks'][1]
        app.explorer.board['tasks'].append(dict(template, id='future', metadata={'assigned': 'Future owner'}))
        self.draw(app)
        self.assertIn('future', [r['id'] for r in app.activity.rows])
        app.handle('f')
        self.action(app, 'filter')
        self.draw(app)
        self.assertEqual(app.column_menu['mode'], 'enum')
        self.assertEqual({label for _, label in app.column_options(app.column_menu['column'])},
                         {'Morgan', 'Alex', 'Future owner', '(Missing)'})
        app.handle('\x1b')
        app.handle('f')
        self.action(app, 'clear')
        self.draw(app)
        self.assertEqual(len(app.activity.rows), 4)
        self.assertFalse(app.activity.state.filters)

    def test_activity_string_and_date_editors_validate_and_recover_empty_results(self):
        app = self.cell_app()
        geometry = app.preview_rect, app.activity.rect, app.task_height
        app.handle('f')
        self.action(app, 'filter')
        for key in 'NATIVE metadata':
            app.handle(key)
        app.handle('\n')
        self.assertEqual(len(app.activity.rows), 3)
        app.handle('f')
        self.action(app, 'filter')
        app.handle('\x15')
        for key in 'nothing matches':
            app.handle(key)
        app.handle('\n')
        self.draw(app)
        self.assertEqual(app.activity.rows, [])
        self.assertTrue(app.activity.focus.header)
        self.assertIn('No tickets match Activity filters.', app.screen.text())
        self.assertIn('No Activity ticket selected.', app.screen.text())
        self.assertEqual((app.preview_rect, app.activity.rect, app.task_height), geometry)
        app.handle('\n')
        self.action(app, 'clear')
        self.draw(app)
        self.assertEqual(len(app.activity.rows), 3)
        app.handle(curses.KEY_RIGHT)
        app.handle(curses.KEY_RIGHT)
        app.handle('\n')
        self.action(app, 'filter')
        self.action(app, 'On')
        for key in 'invalid':
            app.handle(key)
        app.handle('\n')
        self.assertTrue(app.column_menu['error'])
        app.handle('\x15')
        for key in '2026-10-29':
            app.handle(key)
        app.handle('\n')
        self.draw(app)
        self.assertEqual([r['id'] for r in app.activity.rows], ['other'])
        self.assertFalse(app.explorer.task_state.filters)

    def test_activity_elapsed_sort_keeps_selection_and_live_values_with_missing_last(self):
        app = self.cell_app()
        app.work_reader.snapshot['sessions'].append(session('other', started=NOW - 30, id='older'))
        self.draw(app)
        selected = app.activity.selected
        app.activity_focus_column(3)
        app.handle(curses.KEY_UP)
        app.handle('\n')
        self.assertNotIn('filter', [action for _, action in app.menu_entries()])
        self.action(app, 'desc')
        self.draw(app, NOW + 1)
        self.assertEqual([r['id'] for r in app.activity.rows], ['other', 'two', 'missing'])
        self.assertEqual(app.activity.selected, selected)
        self.assertEqual(app.activity.current['elapsed'], 6000)
        self.assertIn('Elapsed↓', app.screen.text())
        self.assertIsNone(app.explorer.task_state.sort)
        app.handle('\n')
        self.action(app, 'asc')
        self.draw(app)
        self.assertEqual([r['id'] for r in app.activity.rows], ['two', 'other', 'missing'])
        app.handle('\n')
        self.action(app, 'reset')
        self.assertIsNone(app.activity.state.sort)

    def test_activity_mouse_focus_context_menu_and_header_activation(self):
        app = self.cell_app()
        y, x, _, _, _ = next(hit for hit in app.activity.cell_hits if hit[3][1] == 'other' and hit[4] == 1)
        with patch('kanitor.ui.curses.getmouse', return_value=(0, x, y, 0, curses.BUTTON3_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.draw(app)
        self.assertEqual(app.column_menu['row']['id'], 'other')
        menu_y, menu_index = next((y, index) for y, index in app.column_menu['hits']
                                 if app.menu_entries()[index][1] == 'only')
        menu_x = app.column_menu['rect'][1] + 2
        with patch('kanitor.ui.curses.getmouse', return_value=(0, menu_x, menu_y, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.draw(app)
        self.assertEqual([r['id'] for r in app.activity.rows], ['other'])
        y, x, _, _ = app.activity.header_hits[1]
        with patch('kanitor.ui.curses.getmouse', return_value=(0, x, y, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.assertIsNone(app.column_menu['row'])
        self.assertTrue(app.activity.focus.header)
        self.action(app, 'clear')
        self.draw(app)
        self.assertEqual(len(app.activity.rows), 3)

    def test_activity_project_and_board_cells_resolve_exact_project_and_native_board(self):
        app = self.app()
        self.fill(app)
        for child in app.children.values():
            # Display names collide; navigation must retain project root and board slug.
            child.project_label = 'Same project'
            child.explorer.boards[0]['name'] = 'Same board'
            child.work_reader.snapshot = {'sessions': [session()], 'events': []}
        child = app.children[str(self.root / 'two')]
        app.handle('a')
        app.handle('\t')
        self.draw(app)
        app.activity.selected = (str(child.root), 'two')
        app.activity_focus_column(0)
        app.handle('\n')
        self.assertIs(app.active, child)
        self.assertEqual(child.view, 'boards')
        self.assertFalse(child.activity.focused)
        app.show_projects()
        app.activity.focused = True
        self.draw(app)
        app.activity.selected = (str(child.root), 'two')
        app.activity_focus_column(1)
        app.handle('f')
        self.assertIn('openBoard', [action for _, action in app.menu_entries()])
        self.action(app, 'openBoard')
        self.assertIs(app.active, child)
        self.assertEqual(child.view, 'tasks')
        self.assertEqual(child.explorer.board_slug, 'index')
        self.assertIsNone(app.column_menu)

    def test_activity_slug_displays_filters_sorts_and_opens_native_board(self):
        app = self.task_app('boards')
        data = snapshot()
        other = dict(data['boards'][0]['tasks'][1], id='other', board='review')
        data['boards'][0]['name'] = 'Same board'
        data['boards'][1].update(name='Same board', options={'startedColumns': ['Building']},
                                 columns=['Building'], tasks=[other])
        data['customization'] = {'activityColumns': [
            {'title': 'Board ID', 'field': 'slug', 'width': 'hug'},
            {'title': 'Board name', 'field': 'board', 'width': 'hug'},
            {'title': 'Task', 'field': 'name', 'width': 'fill'}]}
        app.explorer.apply(data)
        app.handle('a')
        app.handle('\t')
        self.draw(app)
        self.assertEqual([r['slug'] for r in app.activity.rows], ['index', 'review'])
        self.assertEqual([r['board'] for r in app.activity.rows], ['Same board', 'Same board'])
        for y, x, size, identity, index in app.activity.cell_hits:
            if index == 0:
                expected = 'index' if identity[1] == 'two' else 'review'
                self.assertEqual(''.join(app.screen.grid[y][x:x + size]).strip(), expected)
        app.activity_focus_column(0)
        self.assertIn('Enter/Space board', app.activity_footer())
        app.handle(curses.KEY_UP)
        app.handle('\n')
        self.action(app, 'desc')
        self.draw(app)
        self.assertEqual([r['slug'] for r in app.activity.rows], ['review', 'index'])
        app.handle('\n')
        self.action(app, 'filter')
        self.assertEqual(app.column_menu['mode'], 'enum')
        self.assertEqual([label for _, label in app.column_options(app.column_menu['column'])], ['index', 'review'])
        self.action(app, '"index"')
        app.handle('\x1b')
        self.draw(app)
        self.assertEqual([r['slug'] for r in app.activity.rows], ['review'])
        self.assertFalse(app.explorer.board_state.filters)
        app.handle(curses.KEY_DOWN)
        app.handle('f')
        self.action(app, 'openBoard')
        self.draw(app)
        self.assertEqual((app.view, app.explorer.board_slug), ('tasks', 'review'))
        self.assertFalse(app.activity.focused)
        self.assertFalse(app.activity_visible)
        self.assertIsNone(app.activity.rect)

    def test_activity_slug_opens_board_in_exact_project(self):
        app = self.app()
        self.fill(app)
        self.config(['one', 'two'], activityColumns=[
            {'title': 'Board', 'field': 'slug', 'width': 'hug'},
            {'title': 'Task', 'field': 'name'}])
        app.catalog.poll(force=True)
        for child in app.children.values():
            task = child.explorer.boards[0]['tasks'][1]
            child.explorer.boards[1].update(name=child.explorer.boards[0]['name'],
                options={'startedColumns': ['Building']}, columns=['Building'],
                tasks=[dict(task, id='review-task', board='review')])
        app.handle('a')
        app.handle('\t')
        self.draw(app)
        child = app.children[str(self.root / 'two')]
        app.activity.selected = (str(child.root), 'review-task')
        app.activity_focus_column(0)
        app.handle('\n')
        self.assertIs(app.active, child)
        self.assertEqual((child.view, child.explorer.board_slug), ('tasks', 'review'))
        self.assertFalse(child.activity.focused)
        self.assertIsNone(child.popup)

    def test_activity_filters_and_focus_follow_sources_across_configuration_edits(self):
        app = self.cell_app()
        app.activity_focus_column(1)
        app.handle('\n')
        self.draw(app)
        key = app.activity.columns[1][0].key
        selected = app.activity.selected
        columns = [
            {'title': 'Owner renamed', 'metadata': 'assigned', 'width': 'hug'},
            {'title': 'Task', 'field': 'name'}]
        app.explorer.column_rules = parse_config({'activityColumns': columns})
        self.draw(app)
        self.assertEqual(app.activity.focus.index, 0)
        self.assertEqual(app.activity.selected, selected)
        self.assertIn(key, app.activity.state.filters)
        app.handle('f')
        self.action(app, 'filter')
        columns[0]['filterable'] = False
        app.explorer.column_rules = parse_config({'activityColumns': columns})
        self.draw(app)
        self.assertIsNone(app.column_menu)
        self.assertFalse(app.activity.state.filters)
        self.assertEqual(len(app.activity.rows), 3)
        # A disabled header remains selectable, while main table menus keep their own scope.
        columns[0]['sortable'] = False
        app.explorer.column_rules = parse_config({'activityColumns': columns})
        app.handle(curses.KEY_UP)
        app.handle('\n')
        self.draw(app)
        self.assertEqual(app.menu_entries(), [('No actions available', 'none')])
        app.handle('\x1b')
        app.handle('\t')
        app.focus.header = True
        app.focus_column(1)
        app.handle('\n')
        self.draw(app)
        self.assertNotEqual(app.column_menu.get('table'), 'activity')
        self.assertEqual(app.column_menu['column'].field, 'board')

    def test_activity_capabilities_can_be_configured(self):
        self.assertEqual(parse_config({}).activity_columns[-1].field, 'task')
        rules = parse_config({'activityColumns': [
            {'title': 'Task', 'field': 'name'},
            {'title': 'Owner', 'metadata': 'assignee', 'filterType': 'string', 'sortable': False},
            {'title': 'Time', 'field': 'elapsed', 'sortable': False},
            {'title': 'Start', 'field': 'started_at', 'filterable': False}]})
        task, owner, elapsed, start = rules.activity_columns
        self.assertTrue(task.can_filter and task.can_sort)
        self.assertEqual(task.filter_kind, 'string')
        self.assertTrue(owner.can_filter)
        self.assertFalse(owner.can_sort)
        self.assertEqual(owner.filter_kind, 'string')
        self.assertFalse(elapsed.can_filter or elapsed.can_sort)
        self.assertTrue(start.can_sort)
        self.assertFalse(start.can_filter)
        self.assertEqual(start.filter_kind, 'date')

    def test_nested_projects_have_consistent_names_in_projects_and_activity(self):
        app = self.app(paths=('apps/worker', 'tools/worker'))
        self.fill(app)
        project = parse_config({'projectColumns': [{'title': 'Project', 'field': 'project'}]}).project_columns[0]
        names = {row['id']: project.value(row) for row in app.project_universe()}
        self.assertEqual(set(names.values()), {'worker'})
        for row in activity_rows(app.children.values(), now=NOW):
            self.assertEqual(row['project'], names[row['key'][0]])

    def test_activity_name_alias_can_reload_as_task_without_losing_focus_or_filter(self):
        app = self.cell_app()
        app.handle('f')
        self.action(app, 'filter')
        for key in 'First task':
            app.handle(key)
        app.handle('\n')
        self.draw(app)
        selected, slot = app.activity.selected, app.activity.focus.slot
        app.explorer.column_rules = parse_config({'activityColumns': [
            {'title': 'Owner', 'metadata': 'assigned', 'width': 'hug'},
            {'title': 'Task', 'field': 'task'}]})
        self.draw(app)
        self.assertEqual(app.activity.focus.slot, slot)
        self.assertEqual(app.activity.focus.index, 1)
        self.assertEqual(app.activity.selected, selected)
        self.assertEqual([r['id'] for r in app.activity.rows], ['two'])
        app.handle('\n')
        self.assertEqual(app.popup, ('card', 'two'))

    def test_native_workflow_scope_deduplication_and_exact_project_subjects(self):
        app = self.task_app('boards')
        data = deepcopy(snapshot())
        shared = deepcopy(data['boards'][0]['tasks'][1])
        shared['board'] = 'review'
        data['boards'][1].update(options={'startedColumns': ['Building']}, columns=['Building'], tasks=[shared])
        app.explorer.apply(data)
        rows = activity_rows([app], now=NOW)
        self.assertEqual([r['id'] for r in rows], ['two'])
        self.assertEqual(rows[0]['native_board']['slug'], 'index')
        self.assertEqual(activity_rows([app], board_slug='review', now=NOW)[0]['native_board']['slug'], 'review')
        other = self.task_app('boards')
        other.root = self.root / 'different-project'
        other.work_reader.snapshot = {'sessions': [session(started=NOW - 15)], 'events': []}
        rows = activity_rows([app, other], now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['elapsed'] for r in rows], [5000, 15000])
        self.assertNotEqual(rows[0]['key'], rows[1]['key'])

    def test_recent_completions_follow_active_tasks_using_native_dates_and_history(self):
        app = self.task_app()
        template = app.explorer.board['tasks'][1]
        def done(identity, completed, **extra):
            return dict(template, id=identity, column='Shipped', metadata={'completed': completed}, **extra)
        app.explorer.board['tasks'] = [done('older', date(NOW - 50)),
            dict(template, id='idle-active'), done('newest', date(NOW - 1)), template,
            done('cutoff', date(NOW - 86400)), done('future', date(NOW + 1)),
            done('invalid', 'not a date'), done('missing', None),
            done('history', None, history=[{'board': 'index', 'type': 'moved',
                'fromColumn': 'Building', 'toColumn': 'Shipped', 'date': date(NOW - 2)}]),
            dict(template, id='paused', column='Queue', metadata={'completed': date(NOW - 1)})]
        app.work_reader.snapshot['sessions'].append(session('newest'))
        before = deepcopy(app.explorer.boards)
        rows = activity_rows([app], now=NOW)
        self.assertEqual([r['id'] for r in rows], ['two', 'idle-active', 'newest', 'history', 'older'])
        for row in rows[2:]:
            self.assertTrue(row['historical'])
            self.assertFalse(row['live'])
            self.assertIsNone(row['elapsed'])
            self.assertEqual(row['activity'], 'Completed')
        self.assertEqual(app.explorer.boards, before)

    def test_completions_deduplicate_prefer_active_and_respect_scope_and_project_rules(self):
        app = self.task_app('boards')
        data = snapshot()
        active = data['boards'][0]['tasks'][1]
        done = dict(active, column='Shipped', metadata={'completed': date(NOW - 20)})
        data['boards'][0]['tasks'] = [active]
        data['boards'][1].update(options={'completedColumns': ['Shipped']}, tasks=[done])
        data['boards'].reverse()  # Completed membership arrives first.
        app.explorer.apply(data)
        rows = activity_rows([app], now=NOW)
        self.assertEqual([(r['id'], r['historical'], r['slug']) for r in rows], [('two', False, 'index')])
        rows = activity_rows([app], board_slug='review', now=NOW)
        self.assertEqual([(r['id'], r['historical']) for r in rows], [('two', True)])
        other = self.task_app('boards')
        other.root = self.root / 'another'
        other.explorer.apply({'boards': [data['boards'][0]], 'customization': {'taskSquares': {'recentCompleted': '10s'}}})
        self.assertEqual(activity_rows([other], now=NOW), [])
        other.explorer.column_rules = parse_config({'taskSquares': {'recentCompleted': '1h'}})
        rows = activity_rows([app, other], board_slug='review', now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]['key'], rows[1]['key'])

    def test_history_stays_below_column_sorted_active_rows_and_keeps_context_actions(self):
        app = self.cell_app()
        original = app.explorer
        template = app.explorer.board['tasks'][0]
        for identity, name, seconds in [('new', 'A completed task', 1), ('old', 'Z completed task', 20)]:
            app.explorer.board['tasks'].append(dict(template, id=identity, name=name, column='Shipped',
                description='Full historical description', metadata={'completed': date(NOW - seconds), 'assigned': 'Alex'}))
        app.activity.state.sort = (app.activity.columns[0][0].key, True)
        self.draw(app)
        self.assertEqual([r['id'] for r in app.activity.rows], ['missing', 'other', 'two', 'new', 'old'])
        app.activity.selected = str(app.root), 'new'
        self.draw(app)
        self.assertIn('Full historical description', app.screen.text())
        for y, x, _, identity, index in app.activity.cell_hits:
            attr = app.screen.attributes[y][x]
            if identity[1] == 'old' or (identity[1] == 'new' and index != 0):
                self.assertTrue(attr & curses.A_DIM)
            if identity[1] == 'new' and index == 0:
                self.assertTrue(attr & curses.A_REVERSE)
                self.assertFalse(attr & curses.A_DIM)
        app.activity_focus_column(1)
        with patch('kanitor.activity.time.time', return_value=NOW):
            app.handle('\n')  # Assigned only Alex, without hiding historical entries.
        self.draw(app)
        self.assertEqual([r['id'] for r in app.activity.rows], ['other', 'new', 'old'])
        app.activity_focus_column(0)
        app.handle('\n')
        self.assertEqual(app.popup, ('card', 'new'))
        app.handle('\x1b')
        self.assertIs(app.explorer, original)
        self.assertEqual(app.activity.selected, (str(app.root), 'new'))

    def test_completion_ages_out_without_file_changes_and_reopening_restores_live_clock(self):
        app = self.task_app()
        task = app.explorer.board['tasks'][1]
        task['column'] = 'Shipped'
        task['metadata']['completed'] = date(NOW - 86399)
        app.handle('a')
        app.handle('\t')
        self.draw(app)
        self.assertTrue(app.activity.current['historical'])
        self.assertIsNone(app.activity.current['elapsed'])
        geometry = app.preview_rect, app.activity.rect
        app.reader.poll = app.work_reader.poll = Mock()
        with patch('kanitor.activity.time.time', return_value=NOW):
            app.poll()
        app.needs_redraw = False
        with patch('kanitor.activity.time.time', return_value=NOW + 1):
            app.poll()
        self.assertTrue(app.needs_redraw)
        self.draw(app, NOW + 1)
        self.assertIsNone(app.activity.current)
        self.assertEqual((app.preview_rect, app.activity.rect), geometry)
        task['column'] = 'Building'
        self.draw(app, NOW + 2)
        self.assertFalse(app.activity.current['historical'])
        self.assertEqual(app.activity.current['elapsed'], 7000)

    def test_completed_elapsed_sums_all_confirmed_sessions_and_marks_unknown_parts(self):
        app = self.task_app()
        task = app.explorer.board['tasks'][1]
        task['column'] = 'Shipped'
        task['metadata']['completed'] = date(NOW - 1)
        app.work_reader.snapshot['sessions'] = [
            session(state='closed', confirmed_session_elapsed_ms=60000),
            session(id='second', state='closed', confirmed_session_elapsed_ms=120000),
            session(id='zero', state='closed', confirmed_session_elapsed_ms=0),
            session(id='other', task='different', state='closed', confirmed_session_elapsed_ms=999999)]
        row = activity_rows([app], now=NOW)[0]
        self.assertEqual(row['elapsed'], 180000)
        self.assertFalse(row['live'] or row['elapsed_partial'])
        elapsed_column = next(c for c in app.explorer.column_rules.activity_columns if c.field == 'elapsed')
        self.assertEqual(elapsed_column.value(row).strip(), '3m  0s')
        app.work_reader.snapshot['sessions'] += [session(id='unfinished'),
            session(id='interrupted', state='interrupted', confirmed_session_elapsed_ms=None)]
        row = activity_rows([app], now=NOW)[0]
        self.assertEqual(row['elapsed'], 180000)
        self.assertTrue(row['elapsed_partial'])
        self.assertTrue(elapsed_column.value(row).startswith('≥'))
        app.work_reader.error = 'Unavailable'
        self.assertIsNone(activity_rows([app], now=NOW)[0]['elapsed'])

    def test_completed_elapsed_zero_unknown_and_recorded_boundaries(self):
        app = self.task_app()
        task = app.explorer.board['tasks'][1]
        task.update(column='Shipped', metadata={'completed': date(NOW - 1)})
        for record, expected in ((session(state='closed', confirmed_session_elapsed_ms=0), 0),
                                 (session(state='closed', started=NOW - 5, ended_at=date(NOW - 2)), 3000),
                                 (session(state='interrupted'), None),
                                 (session(state='closed', confirmed_session_elapsed_ms=-1), None),
                                 (session(state='closed', confirmed_session_elapsed_ms=True), None)):
            app.work_reader.snapshot['sessions'] = [record]
            row = activity_rows([app], now=NOW)[0]
            self.assertEqual(row['elapsed'], expected)
            self.assertFalse(row['live'])

    def test_elapsed_is_latest_open_session_not_phase_status_age_or_closed_work(self):
        app = self.task_app()
        app.explorer.board['tasks'][1]['metadata']['started'] = date(NOW - 100000)
        app.work_reader.snapshot['sessions'] = [session(started=NOW - 100),
            session(started=NOW - 10, id='new', created_seq=2, phases=[
                {'state': 'open', 'label': 'Reviewing', 'started_at': date(NOW - 2)}]),
            session(started=NOW - 1, id='closed', state='closed', created_seq=3),
            session(started=NOW - 1, id='interrupted', state='interrupted', created_seq=4)]
        row = activity_rows([app], now=NOW)[0]
        self.assertEqual(row['elapsed'], 10000)
        self.assertEqual(row['activity'], 'Reviewing')
        for sessions in ([], [session(state='closed')], [session(state='interrupted')],
                         [session(started=NOW + 1)], [session(started_at='invalid')],
                         [session(subject={'provider': 'other', 'ref': 'two'})]):
            app.work_reader.snapshot['sessions'] = sessions
            self.assertIsNone(activity_rows([app], now=NOW)[0]['elapsed'])
        app.work_reader.snapshot['sessions'] = [session()]
        app.work_reader.error = 'Unavailable'
        row = activity_rows([app], now=NOW)[0]
        self.assertIsNone(row['elapsed'])
        self.assertTrue(row['stale'])

    def test_toggle_tab_focus_preview_and_cell_highlight_are_shared(self):
        app = self.task_app()
        self.draw(app)
        self.assertNotIn('Activity', app.screen.text())
        app.handle('a')
        self.draw(app)
        self.assertTrue(app.activity.shown)
        self.assertFalse(app.activity.focused)
        self.assertIn('ELAPSED', app.screen.text())
        main_id = app.explorer.selected_id
        app.handle('\t')
        self.draw(app)
        self.assertTrue(app.activity.focused)
        self.assertIn('Inspect native metadata', app.screen.text())
        self.assertEqual(app.preview_rect[2], 8)
        self.assertFalse(any(attr & curses.A_REVERSE for attr in app.screen.attributes[5]))
        selected_y = app.activity.hits[0][0]
        self.assertEqual(app.screen.grid[selected_y][2], '⟦')
        self.assertTrue(any(attr & curses.A_REVERSE for attr in app.screen.attributes[selected_y]))
        self.assertEqual(app.explorer.selected_id, main_id)
        app.handle(curses.KEY_BTAB)
        self.assertFalse(app.activity.focused)
        app.handle('\t')
        app.handle('a')
        self.assertFalse(app.activity.shown)
        self.assertFalse(app.activity.focused)

    def test_live_clock_uses_background_work_and_stops_when_session_ends(self):
        app = self.task_app()
        app.reader.poll = Mock()
        app.work_reader.poll = Mock()
        app.handle('a')
        self.draw(app)
        with patch('kanitor.activity.time.time', return_value=NOW), patch('kanitor.ui.time.monotonic', return_value=100):
            app.poll()
            app.needs_redraw = False
            app.poll()
            self.assertFalse(app.needs_redraw)
        with patch('kanitor.activity.time.time', return_value=NOW + 1), patch('kanitor.ui.time.monotonic', return_value=100):
            app.poll()
            self.assertTrue(app.needs_redraw)
            app.draw()
        self.assertEqual(app.activity.current['elapsed'], 6000)
        app.work_reader.poll.assert_called()
        app.work_reader.snapshot['sessions'][0]['state'] = 'closed'
        self.draw(app, NOW + 2)
        self.assertIsNone(app.activity.current['elapsed'])
        self.assertEqual(app.activity.current['activity'], 'No open session')

    def test_details_open_exact_board_and_restore_main_browsing_state(self):
        app = self.task_app('boards')
        data = deepcopy(snapshot())
        task = dict(data['boards'][0]['tasks'][1], id='other', name='Other board ticket', board='review')
        data['boards'][1].update(options={'startedColumns': ['Building']}, columns=['Building'], tasks=[task])
        app.explorer.apply(data)
        app.explorer.search('retained query')
        original = app.explorer
        app.work_reader.snapshot['sessions'] = [session('other')]
        app.handle('a')
        app.handle('\t')
        self.draw(app)
        self.assertEqual(app.activity.current['id'], 'other')
        app.handle(' ')
        self.assertEqual(app.popup, ('card', 'other'))
        self.assertEqual(app.explorer.board_slug, 'review')
        self.draw(app)
        self.assertIn('ID: other', app.screen.text())
        app.handle('\x1b')
        self.assertIs(app.explorer, original)
        self.assertEqual(app.explorer.board_slug, 'index')
        self.assertEqual(app.explorer.query, 'retained query')
        self.assertTrue(app.activity.focused)

    def test_projects_show_all_project_sessions_and_restore_project_context(self):
        app = self.app()
        self.fill(app)
        for index, child in enumerate(app.children.values()):
            child.work_reader.snapshot = {'sessions': [session(started=NOW - 10 + index)], 'events': []}
        original_project = app.selected_project
        selected_child = app.children[str(self.root / 'two')]
        original = selected_child.explorer
        app.handle('a')
        app.handle('\t')
        self.draw(app)
        self.assertEqual(len(app.activity.rows), 2)
        self.assertIn('PROJECT', app.screen.text())
        self.assertIn('BOARD', app.screen.text())
        self.assertEqual(app.activity.current['project'], 'two')
        app.handle('\n')
        self.assertIs(app.active, selected_child)
        self.assertEqual(app.active.popup, ('card', 'two'))
        app.handle('\x1b')
        self.assertIsNone(app.active)
        self.assertIs(selected_child.explorer, original)
        self.assertEqual(app.selected_project, original_project)
        self.assertTrue(app.activity.focused)

    def test_selection_scrollbar_modified_keys_and_live_removal(self):
        app = self.task_app()
        template = app.explorer.board['tasks'][1]
        app.explorer.board['tasks'] = [dict(template, id=f'task-{i}', name=f'Task {i}') for i in range(30)]
        app.explorer.reconcile()
        app.handle('a')
        app.handle('\t')
        self.draw(app)
        app.handle(curses.KEY_SF)
        self.draw(app)
        self.assertEqual(app.activity.current['id'], 'task-10')
        self.assertGreater(app.activity.top, 0)
        self.assertIn('activity', [bar['kind'] for bar in app.scrollbars])
        app.handle(curses.KEY_END)
        self.draw(app)
        self.assertEqual(app.activity.current['id'], 'task-29')
        app.explorer.board['tasks'][-1]['column'] = 'Shipped'
        self.draw(app)
        self.assertEqual(app.activity.current['id'], 'task-28')
        app.explorer.board['tasks'].reverse()
        self.draw(app)
        self.assertEqual(app.activity.current['id'], 'task-28')
        app.handle(curses.KEY_HOME)
        self.assertEqual(app.activity.top, 0)

    def test_layout_resizes_empty_state_and_header_visibility(self):
        for view in ('boards',):
            app = self.task_app(view)
            if not app.activity.shown:
                app.handle('a')
            app.handle('\t')
            for height, width in ((16, 60), (24, 80), (25, 100), (28, 110), (40, 160)):
                with self.subTest(view=view, height=height):
                    app.screen = test_ui.StyledScreen(height, width)
                    self.draw(app)
                    self.assertIn('Activity', app.screen.text())
                    self.assertEqual(app.preview_rect is not None, height >= 25)
                    self.assertIn('BOARD', app.screen.text()) if view == 'boards' else self.assertNotIn('BOARD', app.screen.text())
                    self.assertNotIn('PROJECT', app.screen.text())
            for task in app.explorer.board['tasks']:
                task['column'] = 'Shipped'
            self.draw(app)
            self.assertIn('No active or recently completed tickets', app.screen.text())
            self.assertIsNone(app.activity.selected)

    def test_mouse_preview_double_click_and_inert_preview(self):
        app = self.task_app('boards')
        app.handle('a')
        self.draw(app)
        y, x, _, _, _ = next(hit for hit in app.activity.cell_hits
                        if app.activity.columns[hit[4]][0].canonical_field == 'task')
        event = (0, x, y, 0, curses.BUTTON1_PRESSED)
        with patch('kanitor.ui.curses.getmouse', return_value=event), patch('kanitor.ui.time.monotonic', return_value=100):
            app.handle(curses.KEY_MOUSE)
        self.draw(app)
        self.assertTrue(app.activity.focused)
        self.assertIn('Inspect native metadata', app.screen.text())
        top, left, _, _ = app.preview_rect
        with patch('kanitor.ui.curses.getmouse', return_value=(0, left + 3, top + 2, 0, curses.BUTTON5_PRESSED if hasattr(curses, 'BUTTON5_PRESSED') else curses.REPORT_MOUSE_POSITION)):
            app.handle(curses.KEY_MOUSE)
        self.assertTrue(app.activity.focused)
        self.assertIsNone(app.popup)
        # The preview reflow may move the pane; the original click target survives.
        with patch('kanitor.ui.curses.getmouse', return_value=event), patch('kanitor.ui.time.monotonic', return_value=100.1):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.popup, ('card', 'two'))

    def test_activity_wheel_clamps_without_velocity_and_reverses_immediately(self):
        app = self.task_app()
        template = app.explorer.board['tasks'][1]
        app.explorer.board['tasks'] = [dict(template, id=f'task-{i}', name=f'Task {i}') for i in range(20)]
        app.handle('a')
        app.handle('\t')
        self.draw(app)
        y = app.activity.rect[0] + 2
        for end, outward, inward, expected in ((False, WHEEL_UP, WHEEL_DOWN, 'task-3'),
                                                  (True, WHEEL_DOWN, WHEEL_UP, 'task-16')):
            if end:
                app.handle(curses.KEY_END)
                self.draw(app)
            app.needs_redraw = False
            with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, y, 0, outward)), patch('kanitor.ui.time.monotonic', return_value=100):
                for _ in range(100):
                    app.handle(curses.KEY_MOUSE)
            self.assertFalse(app.needs_redraw)
            with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, y, 0, inward)), patch('kanitor.ui.time.monotonic', return_value=100.01):
                app.handle(curses.KEY_MOUSE)
            self.assertEqual(app.activity.current['id'], expected)
            self.assertTrue(app.needs_redraw)

    def test_projects_poll_activity_work_without_any_task_square_columns(self):
        app = self.app()
        self.config(['one', 'two'], projectColumns=[{'title': 'Project', 'field': 'name'}],
                    boardColumns=[{'title': 'Board', 'field': 'name'}])
        app.catalog.poll(force=True)
        for child in app.children.values():
            child.explorer.apply(dict(snapshot(), customization={'boardColumns': [{'title': 'Board', 'field': 'name'}]}))
            child.reader.poll = Mock()
            child.work_reader.poll = Mock()
        app.handle('a')
        app.poll()
        for child in app.children.values():
            child.work_reader.poll.assert_called_once()

    def test_activity_column_rules_and_keybindings(self):
        app = self.task_app()
        data = deepcopy(snapshot())
        data['customization'] = {'activityColumns': [
            {'title': '', 'metadata': 'assigned', 'width': 'hug'},
            {'title': 'Time', 'field': 'elapsed', 'width': 'hug'},
            {'title': 'Details', 'field': 'description'}],
            'keybindings': {'toggleActivity': ['A'], 'focusPane': ['F6']}}
        app.explorer.apply(data)
        app.handle('a')
        self.assertFalse(app.activity.shown)
        app.handle('A')
        app.handle(curses.KEY_F0 + 6)
        self.draw(app)
        self.assertTrue(app.activity.focused)
        self.assertIn('Morgan', app.screen.text())
        self.assertIn('Details', app.screen.text())
        self.assertIn('Inspect native metadata', app.screen.text())
        for rules in ([], [{'title': 'Bad', 'field': 'task_squares'}],
                      [{'title': 'Bad', 'field': 'elapsed', 'filterable': True}]):
            with self.assertRaises(ConfigError):
                parse_config({'activityColumns': rules})

    @unittest.skipUnless(shutil.which('kanbn') and shutil.which('node'), 'native tools required')
    def test_native_work_log_browsing_remains_read_only(self):
        demo = Path(__file__).resolve().parents[1] / 'examples/demo/.kanbn'
        shutil.copytree(demo, self.root / '.kanbn')
        data = read_once(self.root)
        task = next(task for board in data['boards'] for task in board['tasks']
                    if task['column'] in board['options'].get('startedColumns', ()))
        service = WorkService()
        service.execute('work_begin', self.root, {'request_id': 'begin', 'label': 'Real session',
                                                'subject': {'provider': 'kanbn', 'ref': task['id']}})
        explorer = Explorer()
        explorer.apply(data)
        app = App(test_ui.Screen(), self.root, explorer)
        self.addCleanup(app.close)
        app.work_reader.snapshot = service.viewer_snapshot(self.root)
        log = self.root / '.kanitor/work/events.jsonl'
        before = {path: path.read_bytes() for path in (*self.root.joinpath('.kanbn').rglob('*.md'), log)}
        app.handle('a')
        app.handle('\t')
        app.draw()
        self.assertEqual(app.activity.current['id'], task['id'])
        self.assertIsNotNone(app.activity.current['elapsed'])
        app.handle('\n')
        app.draw()
        app.handle('\x1b')
        app.draw()
        self.assertEqual({path: path.read_bytes() for path in before}, before)
