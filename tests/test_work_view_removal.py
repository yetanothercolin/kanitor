"""Removing Work screens must preserve the independent recording subsystem."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from kanitor.__main__ import main
from kanitor.config_file import load_document
from kanitor.config_template import init_yml
from kanitor.model import Explorer
from kanitor.projects import ProjectCatalog
from kanitor.projects_ui import ProjectsApp
from kanitor.ui import App
from kanitor.work.service import WorkService
from test_explorer import snapshot
import test_ui


class WorkViewRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_removed_flag_and_modules_are_absent_but_recording_cli_reads_original_events(self):
        for module in ('kanitor.work.ui', 'kanitor.work.view'):
            self.assertIsNone(importlib.util.find_spec(module))
        help_output = io.StringIO()
        with redirect_stdout(help_output), self.assertRaises(SystemExit) as exit:
            main(['--help'])
        self.assertEqual(exit.exception.code, 0)
        self.assertNotIn('--work', help_output.getvalue())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit:
            main(['--work'])
        self.assertEqual(exit.exception.code, 2)

        service = WorkService()
        receipt = service.execute('work_begin', self.root, {'request_id': 'begin', 'label': 'Preserved work'})
        log = self.root / '.kanitor/work/events.jsonl'
        original = log.read_bytes()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['work', 'read', '--workspace', str(self.root)]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data['items'][0]['session_id'], receipt['session_id'])
        self.assertEqual(data['items'][0]['payload']['label'], 'Preserved work')
        self.assertEqual(log.read_bytes(), original)

    def test_shortcuts_tabs_and_task_work_summary_are_removed_without_touching_the_log(self):
        service = WorkService()
        service.execute('work_begin', self.root, {'request_id': 'begin', 'label': 'Preserved work'})
        log = self.root / '.kanitor/work/events.jsonl'
        original = log.read_bytes()
        explorer = Explorer()
        explorer.apply(snapshot())
        app = App(test_ui.Screen(), self.root, explorer, start_in_board=True)
        self.addCleanup(app.close)
        for key in ('w', 'W'):
            app.handle(key)
            self.assertEqual(app.view, 'tasks')
            self.assertIsNone(app.popup)
        app.handle('\n')
        for key in ('w', 'W'):
            app.handle(key)
            self.assertEqual(app.popup, ('card', 'one'))
        app.draw()
        self.assertNotIn('[Work]', app.screen.text())
        self.assertNotIn('W sessions', app.screen.text())
        self.assertNotIn('Work:', app.screen.text())
        self.assertFalse(hasattr(app, 'work'))
        self.assertEqual(log.read_bytes(), original)

    def test_project_shortcuts_do_not_open_work_and_new_yaml_omits_view_settings(self):
        init_yml(self.root)
        config, path = load_document(self.root)
        self.assertNotIn('sessionColumns', config['workTracking'])
        self.assertNotIn('sessionColumns:', path.read_text())
        path.write_text('projects: [child]\n')
        (self.root / 'child').mkdir()
        catalog = ProjectCatalog(self.root)
        catalog.poll(force=True)
        app = ProjectsApp(test_ui.Screen(), self.root, catalog)
        self.addCleanup(app.close)
        app.handle('w')
        app.handle('W')
        self.assertIsNone(app.active)
        app.draw()
        self.assertNotIn('w Work', app.screen.text())
        app.handle('\n')
        app.draw()
        left, _ = app.active.project_link
        from unittest.mock import patch
        import curses
        with patch('kanitor.ui.curses.getmouse', return_value=(0, left, 1, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.assertIsNone(app.active)
