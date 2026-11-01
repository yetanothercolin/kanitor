import json
from unittest.mock import patch

from kanitor.model import Explorer
from kanitor.ui import App
from kanitor.view_state import ViewState
from kanitor.work.service import WorkService
from test_explorer import snapshot
from test_projects import ProjectFixture
from test_ui import Screen


class ViewStateTests(ProjectFixture):
    def viewer(self):
        explorer = Explorer()
        explorer.apply(snapshot())
        app = App(Screen(), self.root, explorer)
        self.addCleanup(app.close)
        return app

    def test_toggle_is_saved_immediately_and_restored_in_both_directions(self):
        first = self.viewer()
        self.assertFalse(first.activity.shown)
        self.assertFalse((self.root / '.kanitor').exists())
        first.handle('a')
        second = self.viewer()
        self.assertTrue(second.activity.shown)
        self.assertFalse(second.activity.focused)
        second.handle('a')
        # Closing an older viewer must not overwrite a more recent explicit toggle.
        first.close()
        self.assertFalse(self.viewer().activity.shown)

    def test_parent_and_projects_restore_independent_choices(self):
        app = self.app()
        app.handle('a')
        one = app.children[str(self.root / 'one')]
        one.handle('a')
        app.close()
        reopened = self.app()
        self.assertTrue(reopened.activity.shown)
        self.assertTrue(reopened.children[str(self.root / 'one')].activity.shown)
        self.assertFalse(reopened.children[str(self.root / 'two')].activity.shown)

    def test_bad_data_defaults_safely_and_explicit_toggle_repairs_it(self):
        state = ViewState(self.root)
        state.folder.mkdir()
        for text in ('{bad', '[]', '{"version":1,"activityVisible":"true"}',
                     '{"version":1,"activityVisible":1}'):
            with self.subTest(text=text):
                state.path.write_text(text)
                app = self.viewer()
                self.assertFalse(app.activity.shown)
                app.handle('a')
                self.assertTrue(self.viewer().activity.shown)

    def test_future_version_is_not_overwritten(self):
        state = ViewState(self.root)
        state.folder.mkdir()
        original = '{"version":2,"activityVisible":true,"future":42}'
        state.path.write_text(original)
        app = self.viewer()
        self.assertFalse(app.activity.shown)
        app.handle('a')
        self.assertTrue(app.activity.shown)
        self.assertIn('Could not save view preferences', app.notice)
        self.assertEqual(state.path.read_text(), original)

    def test_atomic_save_failure_preserves_file_and_does_not_block_toggle(self):
        state = ViewState(self.root)
        self.assertEqual(state.set_flag('activityVisible', True), '')
        original = state.path.read_bytes()
        app = self.viewer()
        with patch('kanitor.view_state.os.replace', side_effect=PermissionError('read-only')):
            app.handle('a')
        self.assertFalse(app.activity.shown)
        self.assertIn('Could not save view preferences', app.notice)
        self.assertEqual(state.path.read_bytes(), original)
        self.assertEqual(list(state.folder.glob('.view-state.*.tmp')), [])

    def test_symlinked_state_is_ignored_and_never_written(self):
        state = ViewState(self.root)
        state.folder.mkdir()
        target = self.root / 'other.json'
        original = '{"version":1,"activityVisible":true}'
        target.write_text(original)
        state.path.symlink_to(target)
        app = self.viewer()
        self.assertFalse(app.activity.shown)
        app.handle('a')
        self.assertIn('Could not save view preferences', app.notice)
        self.assertEqual(target.read_text(), original)

    def test_other_preferences_native_data_and_work_logs_are_preserved(self):
        service = WorkService()
        service.execute('work_begin', self.root, {'label': 'Fixture', 'request_id': 'begin'})
        log = self.root / '.kanitor/work/events.jsonl'
        native = self.root / '.kanbn/card.md'
        native.parent.mkdir()
        native.write_text('Native task data\n')
        before = log.read_bytes(), native.read_bytes()
        state = ViewState(self.root)
        state.path.write_text('{"version":1,"futurePreference":{"width":8}}')
        self.viewer().handle('a')
        self.assertEqual((log.read_bytes(), native.read_bytes()), before)
        data = json.loads(state.path.read_text())
        self.assertEqual(data['futurePreference'], {'width': 8})
        self.assertTrue(data['activityVisible'])
