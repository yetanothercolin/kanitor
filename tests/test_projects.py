from contextlib import redirect_stderr, redirect_stdout
import curses
import io
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from kanitor.__main__ import main
from kanitor.config import ConfigError, parse_config
from kanitor.model import find_root
from kanitor.mouse import WHEEL_DOWN, WHEEL_UP
from kanitor.projects import ProjectCatalog, plain_projects, read_projects
from kanitor.projects_ui import ProjectsApp
from kanitor.work.service import WorkService
import test_ui
from test_explorer import snapshot


DEMO = Path(__file__).resolve().parents[1] / 'examples/demo/.kanbn'


def wait_for(app, condition, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.poll()
        if condition():
            return
        time.sleep(.02)
    raise AssertionError(f'Project readers did not reach expected state: {app.rows()}')


class ProjectFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def config(self, paths, **rules):
        (self.root / '.kanitor.json').write_text(json.dumps(dict(projects=paths, **rules)))

    def app(self, paths=('one', 'two'), height=28, width=110):
        self.config(list(paths))
        for path in paths:
            (self.root / path).mkdir(parents=True, exist_ok=True)
        catalog = ProjectCatalog(self.root, interval=.01)
        catalog.poll(force=True)
        app = ProjectsApp(test_ui.Screen(height, width), self.root, catalog)
        self.addCleanup(app.close)
        return app

    def fill(self, app):
        service = WorkService()
        for project in app.catalog.projects:
            child = app.children[str(project.root)]
            tag = project.path.title()
            config = {'columns': [{'title': tag + ' Task', 'field': 'name', 'width': 'fill'}],
                      'boardColumns': [{'title': tag + ' Board', 'field': 'name', 'width': 'fill'}],
                      'workTracking': {'sessionColumns': [{'title': tag + ' Work', 'field': 'label', 'width': 'fill'}]}}
            (project.root / '.kanitor.json').write_text(json.dumps(config))
            data = snapshot()
            data['customization'] = config
            child.reader.snapshot = data
            child.reader.revision = child.revision = 1
            child.explorer.apply(data)
            service.execute('work_begin', project.root, {'label': tag + ' session', 'request_id': 'session'})
            work = service.viewer_snapshot(project.root)
            child.work_reader.snapshot = work
            child.work_reader.revision = 1


class ProjectTests(ProjectFixture):
    def test_projects_configuration_is_explicit_ordered_and_relative(self):
        self.assertIsNone(parse_config({}).projects)
        self.assertEqual(parse_config({'projects': []}).projects, ())
        self.assertEqual(parse_config({'projects': ['one', 'packages/two/']}).projects, ('one', 'packages/two'))
        for value in ('one', [None], [''], ['.'], ['../one'], ['/tmp'], ['one/../../two'], ['one', './one'], ['bad\npath']):
            with self.subTest(value=value), self.assertRaisesRegex(ConfigError, 'projects'):
                parse_config({'projects': value})

    def test_catalog_reload_retains_last_good_list_and_rejects_symlink_escape_and_aliases(self):
        self.config(['one'])
        catalog = ProjectCatalog(self.root, interval=0)
        self.assertTrue(catalog.poll())
        self.assertEqual(catalog.projects[0].root, self.root / 'one')
        before = catalog.projects
        (self.root / '.kanitor.json').write_text('{bad')
        catalog.poll()
        self.assertIs(catalog.projects, before)
        self.assertIn('.kanitor.json', catalog.error)
        (self.root / 'outside').symlink_to(self.root.parent, target_is_directory=True)
        self.config(['outside'])
        catalog.poll()
        self.assertIn('must stay under', catalog.error)
        (self.root / 'alias').symlink_to(self.root / 'one', target_is_directory=True)
        self.config(['one', 'alias'])
        catalog.poll()
        self.assertIn('duplicates', catalog.error)
        self.config(['two', 'one'])
        catalog.poll()
        self.assertFalse(catalog.error)
        self.assertEqual([p.path for p in catalog.projects], ['two', 'one'])
        (self.root / '.kanitor.json').unlink()
        catalog.poll()
        self.assertFalse(catalog.declared)
        self.assertEqual(catalog.projects, [])

    def test_project_local_board_task_rules_and_view_state_remain_separate(self):
        app = self.app()
        self.fill(app)
        app.draw()
        self.assertIn('Projects', app.screen.text())
        app.handle('\n')
        one = app.active
        app.draw()
        self.assertIn('One Board', app.screen.text())
        app.handle('\n')
        app.draw()
        self.assertIn('One Task', app.screen.text())
        one.explorer.search('reopened')
        one.show_preview = False
        app.handle('\x1b')
        self.assertIs(app.active, one)
        app.handle('\x1b')
        self.assertIsNone(app.active)
        app.handle(curses.KEY_DOWN)
        app.handle('\n')
        two = app.active
        app.draw()
        self.assertIn('Two Board', app.screen.text())
        app.handle('\n')
        app.draw()
        self.assertIn('Two Task', app.screen.text())
        self.assertEqual(two.explorer.query, '')
        self.assertTrue(two.show_preview)
        app.handle('\x1b')
        app.handle('\x1b')
        app.handle(curses.KEY_UP)
        app.handle('\n')
        self.assertIs(app.active, one)
        self.assertEqual(one.explorer.query, 'reopened')
        self.assertFalse(one.show_preview)

    def test_project_navigation_mouse_scroll_and_modified_keys_use_visible_bounds(self):
        app = self.app(paths=tuple(f'project-{i}' for i in range(45)), height=16, width=60)
        app.draw()
        self.assertTrue(app.scrollbars)
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 8, 0, WHEEL_UP)):
            app.needs_redraw = False
            for _ in range(50):
                app.handle(curses.KEY_MOUSE)
            self.assertEqual(app.selected_project, str(self.root / 'project-0'))
            self.assertFalse(app.needs_redraw)
        app.handle(curses.KEY_SF)
        self.assertEqual(app.selected_project, str(self.root / 'project-10'))
        app.draw()
        with patch('kanitor.ui.curses.keyname', return_value=b'kDN6'):
            app.handle(9001)
        self.assertEqual(app.selected_project, str(self.root / f'project-{10 + app.project_height}'))
        app.handle(curses.KEY_END)
        app.draw()
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 20, 8, 0, WHEEL_DOWN)):
            for _ in range(50):
                app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.selected_project, str(self.root / 'project-44'))
        bar = app.scrollbars[0]
        with patch('kanitor.ui.curses.getmouse', return_value=(0, bar['x'], bar['y'], 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.selected_project, str(self.root / f'project-{44 - app.project_height}'))
        app.handle(curses.KEY_HOME)
        app.draw()
        row, _, target = app.hits[1]
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 10, row, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
            self.assertIsNone(app.active)
            app.handle(curses.KEY_MOUSE)
        self.assertIs(app.active, app.children[target])
        app.draw()
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 4, 1, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.assertIsNone(app.active)

    def test_removing_active_project_closes_readers_and_retains_surviving_context(self):
        app = self.app()
        app.open_project()
        one = app.active
        two = app.children[str(self.root / 'two')]
        two.explorer.query = 'kept'
        with patch.object(one, 'close', wraps=one.close) as close:
            self.config(['two', 'three'])
            app.catalog.poll(force=True)
            app.sync_projects()
            close.assert_called_once()
        self.assertIsNone(app.active)
        self.assertEqual(list(app.children), [str(self.root / 'two'), str(self.root / 'three')])
        self.assertIs(app.children[str(self.root / 'two')], two)
        self.assertEqual(two.explorer.query, 'kept')

    def test_empty_and_invalid_catalogs_render_without_node_or_workspace_writes(self):
        app = self.app(paths=())
        before = (self.root / '.kanitor.json').read_bytes()
        with patch('kanitor.reader.subprocess.Popen', side_effect=AssertionError('no native parent read')):
            app.poll()
            app.draw()
            self.assertIn('No projects configured', app.screen.text())
            app.handle('\n')
            app.handle('\x1b')
            self.assertIsNone(app.active)
        self.assertEqual((self.root / '.kanitor.json').read_bytes(), before)
        self.assertFalse((self.root / '.kanitor').exists())
        (self.root / '.kanitor.json').write_text('{bad')
        app.catalog.poll(force=True)
        app.draw()
        self.assertIn('STALE', app.screen.text())
        self.assertIn('.kanitor.json', app.screen.text())


@unittest.skipUnless(shutil.which('node') and shutil.which('kanbn'), 'native Node/kanbn required')
class NativeProjectsTests(ProjectFixture):
    def app(self, paths=('one', 'two'), height=28, width=110):
        app = super().app(paths, height, width)
        for path in paths:
            shutil.copytree(DEMO, self.root / path / '.kanbn')
        return app

    def test_native_readers_watch_inactive_projects_and_isolate_invalid_settings(self):
        app = self.app()
        wait_for(app, lambda: all(child.reader.snapshot for child in app.children.values()))
        one, two = app.children.values()
        app.open_project()
        one_before = one.reader.revision
        path = two.root / '.kanitor.json'
        path.write_text(json.dumps({'columns': [{'title': 'Second Project', 'field': 'name'}]}))
        wait_for(app, lambda: two.explorer.column_rules.columns[0].title == 'Second Project')
        self.assertEqual(one.reader.revision, one_before)
        self.assertNotEqual(one.explorer.column_rules.columns[0].title, 'Second Project')
        path.write_text('{bad')
        wait_for(app, lambda: bool(two.reader.error))
        self.assertFalse(one.reader.error)
        self.assertEqual(app.rows()[1]['state'], 'STALE')
        self.assertEqual(two.explorer.column_rules.columns[0].title, 'Second Project')
        path.unlink()
        wait_for(app, lambda: not two.reader.error)
        self.assertEqual(two.explorer.column_rules.columns[0].title, 'STATUS')
        board = two.root / '.kanbn/extra.md'
        board.write_text('# Extra\n\n## Todo\n')
        wait_for(app, lambda: len(two.explorer.boards) == 3)
        self.assertEqual(len(one.explorer.boards), 2)
        third = self.root / 'nested/third'
        shutil.copytree(DEMO, third / '.kanbn')
        self.config(['two', 'nested/third'])
        wait_for(app, lambda: len(app.children) == 2 and str(third) in app.children)
        self.assertIsNone(app.active)
        self.assertIsNone(one.reader.process)
        self.assertIs(app.children[str(two.root)], two)
        wait_for(app, lambda: app.children[str(third)].reader.snapshot is not None)

    def test_stalled_reader_does_not_block_other_projects_or_navigation(self):
        import sys
        app = self.app()
        one, two = app.children.values()
        one.reader.timeout = 10
        with patch.object(one.reader, 'make_command', return_value=[sys.executable, '-c', 'import time; time.sleep(20)']):
            wait_for(app, lambda: two.reader.snapshot is not None)
            self.assertIsNotNone(one.reader.process)
            started = time.monotonic()
            app.handle(curses.KEY_DOWN)
            app.handle('\n')
            app.draw()
            self.assertIs(app.active, two)
            self.assertLess(time.monotonic() - started, .5)
            self.assertIn('Boards', app.screen.text())


    def test_task_squares_read_linked_work_without_per_task_subject_processes(self):
        app = self.app()
        wait_for(app, lambda: all(child.reader.snapshot and child.work_reader.snapshot for child in app.children.values()))
        one, two = app.children.values()
        from kanitor.model import state
        task = next(task for task in one.explorer.boards[0]['tasks'] if state(one.explorer.boards[0], task['column']) == 'active')
        service = WorkService()
        service.execute('work_begin', one.root, {'label': 'Live activity', 'request_id': 'square-begin',
            'subject': {'provider': 'kanbn', 'ref': task['id']}})
        wait_for(app, lambda: one.work_reader.snapshot['as_of_seq'] == 1)
        rows = app.rows()
        self.assertEqual(next(square for square in rows[0]['task_squares'].flat if square.id == task['id']).kind, 'active')
        log = one.root / '.kanitor/work/events.jsonl'
        log.write_bytes(log.read_bytes().replace(b'Live activity', b'Live activitx'))
        wait_for(app, lambda: bool(one.work_reader.error))
        self.assertEqual(next(square for square in app.rows()[0]['task_squares'].flat if square.id == task['id']).kind, 'stale')
        self.assertFalse(two.work_reader.error)

    def test_parent_snapshots_inherit_missing_configs_preserve_overrides_and_remain_read_only(self):
        app = self.app(paths=('one', 'missing', 'two'))
        shutil.rmtree(self.root / 'missing')
        self.config(['one', 'missing', 'two'], columns=[{'title': 'Parent only', 'field': 'id'}])
        (self.root / 'one/.kanitor.json').write_text(json.dumps({'columns': [{'title': 'Child only', 'field': 'name'}]}))
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        data = read_projects(app.catalog)
        self.assertFalse(data['projects'][0]['error'])
        self.assertTrue(data['projects'][1]['error'])
        self.assertFalse(data['projects'][2]['error'])
        self.assertIn('one: 2 boards', plain_projects(data))
        self.assertEqual(data['projects'][0]['snapshot']['customization']['columns'][0]['title'], 'Child only')
        self.assertEqual(data['projects'][2]['snapshot']['customization'],
                         {'columns': [{'title': 'Parent only', 'field': 'id'}]})
        self.assertEqual(before, {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()})
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--root', str(self.root), '--json']), 1)
        self.assertEqual(len(json.loads(output.getvalue())['projects']), 3)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--root', str(self.root), '--project', 'one', '--board', 'releases', '--once']), 0)
        self.assertIn('releases * All statuses', output.getvalue())
