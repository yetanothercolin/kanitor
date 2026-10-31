from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from kanitor.__main__ import main
from kanitor.config import ConfigError, DEFAULT_COLUMNS, parse_config
from kanitor.config_file import load_document
from kanitor.projects import ProjectCatalog
from kanitor.projects_ui import ProjectsApp
from kanitor.reader import LiveReader, ReadError, command, decode
from kanitor.work.common import WorkError
from kanitor.work.reader import WorkReader
from kanitor.work.service import WorkService
from test_projects import wait_for
from test_reader import wait_for as wait_for_reader
import test_ui


DEMO = Path(__file__).resolve().parents[1] / 'examples/demo/.kanbn'


class InheritanceFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.child = self.root / 'packages/child'
        self.child.mkdir(parents=True)
        self.path = self.root / '.kanitor.yml'
        self.path.write_text('''projects: [packages/child]
keybindings: {help: [F1]}
columns:
  - {title: Workspace task, field: name, width: fill}
boards:
  releases:
    columns:
      - {title: Release ID, field: id}
boardColumns:
  - {title: Workspace board, field: name}
taskSquares: {recentWork: 30m}
workTracking:
  sessionColumns:
    - {title: Workspace work, field: label}
''')


class ConfigurationInheritanceTests(InheritanceFixture):
    def test_unrelated_invalid_and_unreadable_ancestors_do_not_block_independent_workspaces(self):
        self.path.unlink()
        service = WorkService()
        for name, documents in (
            ('.kanitor.json', ('{"projects":["other"],"columns":[]}', '{broken', '[]')),
            ('.kanitor.yml', ('projects: [other]\ncolumns: []', 'workTracking: [', '- not-a-config')),
            ('.kanitor.yaml', ('projects: [other]\nfutureView: true', 'columns: [', 'true'))):
            path = self.root / name
            for index, text in enumerate(documents):
                with self.subTest(name=name, text=text):
                    path.write_text(text)
                    self.assertEqual(load_document(self.child)[0], {})
                    begin = service.execute('work_begin', self.child,
                        {'label': 'Independent work', 'request_id': f'{name}-{index}-begin'})
                    end = service.execute('work_end', self.child,
                        {'session_id': begin['session_id'], 'request_id': f'{name}-{index}-end'})
                    self.assertEqual(end['state'], 'closed')
            path.unlink()

    def test_applicable_ancestor_still_validates_rules_and_recording_policy(self):
        self.path.write_text('projects: [packages/child]\ncolumns: []\n')
        with self.assertRaises(ConfigError):
            load_document(self.child)
        self.path.write_text('projects: [packages/child]\nworkTracking: {metadataSchemas: {session: 42}}\n')
        with self.assertRaises(ConfigError):
            load_document(self.child)
        with self.assertRaises(WorkError) as error:
            WorkService().execute('work_begin', self.child, {'label': 'Invalid policy', 'request_id': 'begin'})
        self.assertEqual(error.exception.code, 'invalid_config')

    def test_recorder_inherits_work_rules_despite_invalid_parent_display_settings(self):
        self.path.write_text('''projects: [packages/child, null, ../outside]
activityColumns: []
futureViewerSetting: {anything: true}
workTracking:
  metadataSchemas:
    session: {type: object, required: [owner]}
  outcomes:
    verified: {requiresEvidence: true}
''')
        service = WorkService()
        with self.assertRaises(ConfigError):
            load_document(self.child)
        caps = service.execute('work_capabilities', self.child)
        self.assertIn('owner', caps['metadata_schemas']['session']['required'])
        with self.assertRaises(WorkError) as error:
            service.execute('work_begin', self.child, {'request_id': 'missing', 'label': 'Needs owner'})
        self.assertEqual(error.exception.code, 'validation_error')
        begin = service.execute('work_begin', self.child,
            {'request_id': 'begin', 'label': 'Record despite invalid UI', 'metadata': {'owner': 'Alex'}})
        with self.assertRaises(WorkError) as error:
            service.execute('work_end', self.child,
                {'request_id': 'needs-evidence', 'session_id': begin['session_id'], 'outcome': 'verified'})
        self.assertEqual(error.exception.code, 'evidence_required')
        service.execute('work_end', self.child,
            {'request_id': 'end', 'session_id': begin['session_id'], 'outcome': 'verified', 'evidence': 'tested'})
        self.assertEqual(service.viewer_snapshot(self.child)['warnings'], [])
        unrelated = self.root / 'unlisted'
        unrelated.mkdir()
        self.assertEqual(service.execute('work_capabilities', unrelated)['metadata_schemas'], {})
        # A local file still replaces inheritance, even when its layout is broken.
        (self.child / '.kanitor.json').write_text('{"columns":[]}')
        self.assertEqual(service.execute('work_capabilities', self.child)['metadata_schemas'], {})

    def test_declared_project_inherits_workspace_settings_without_the_project_roster(self):
        data, source = load_document(self.child)
        self.assertEqual(source, self.path)
        self.assertNotIn('projects', data)
        rules = parse_config(data)
        self.assertEqual(rules.columns[0].title, 'Workspace task')
        self.assertEqual(rules.board_columns[0].title, 'Workspace board')
        self.assertEqual(rules.for_board('index'), rules.columns)
        self.assertEqual(rules.for_board('releases')[0].title, 'Release ID')
        self.assertEqual(rules.square_rules.recent_work, 1800)
        self.assertEqual(rules.keybindings.keys['help'], ('f1',))
        catalog = ProjectCatalog(self.child)
        catalog.poll(force=True)
        self.assertFalse(catalog.declared)
        self.assertEqual(catalog.projects, [])
        self.assertEqual(catalog.rules, rules)

    def test_any_explicit_local_file_replaces_inheritance_including_empty_configs(self):
        for name in ('.kanitor.json', '.kanitor.yml', '.kanitor.yaml'):
            path = self.child / name
            path.write_text('{}')
            data, source = load_document(self.child)
            self.assertEqual((data, source), ({}, path))
            self.assertEqual(parse_config(data).columns, DEFAULT_COLUMNS)
            self.assertEqual(parse_config(data).keybindings.keys['help'], ('?',))
            path.write_text('broken: [')
            with self.assertRaises(ConfigError):
                load_document(self.child)
            path.unlink()
        self.assertEqual(load_document(self.child)[1], self.path)

    def test_only_declared_projects_inherit_and_the_nearest_declaring_workspace_wins(self):
        unrelated = self.root / 'unrelated'
        unrelated.mkdir()
        self.assertEqual(load_document(unrelated)[0], {})
        self.assertEqual(load_document(self.child / 'nested')[0], {})
        nearer = self.child.parent / '.kanitor.json'
        nearer.write_text(json.dumps({'projects': ['child'], 'columns': [{'title': 'Nearer task', 'field': 'id'}]}))
        self.assertEqual(load_document(self.child)[0]['columns'][0]['title'], 'Nearer task')
        # An intervening directory's unrelated config does not supply defaults.
        nearer.write_text('{}')
        self.assertEqual(load_document(self.child)[1], self.path)
        self.path.unlink()
        self.assertEqual(load_document(self.child)[0], {})

    def test_work_recording_and_live_work_reader_share_the_inherited_configuration(self):
        self.path.write_text(self.path.read_text() + '''  metadataSchemas:
    session: {type: object, required: [owner]}
  outcomes:
    verified: {requiresEvidence: true}
''')
        service = WorkService()
        caps = service.execute('work_capabilities', self.child)
        self.assertEqual(caps['session_columns'][0]['title'], 'Workspace work')
        with self.assertRaises(WorkError):
            service.execute('work_begin', self.child, {'request_id': 'missing-owner', 'label': 'Example'})
        session = service.execute('work_begin', self.child,
                                  {'request_id': 'begin', 'label': 'Example', 'metadata': {'owner': 'Alex'}})
        with self.assertRaises(WorkError) as caught:
            service.execute('work_end', self.child,
                            {'request_id': 'missing-evidence', 'session_id': session['session_id'], 'outcome': 'verified'})
        self.assertEqual(caught.exception.code, 'evidence_required')
        reader = WorkReader(self.child, interval=.01)
        self.addCleanup(reader.close)
        wait_for_reader(reader, lambda: reader.snapshot is not None)
        self.assertEqual(reader.snapshot['config']['sessionColumns'][0]['title'], 'Workspace work')
        original = self.path.read_text()
        self.path.write_text(original.replace('Workspace work', 'Updated work'))
        wait_for_reader(reader, lambda: reader.snapshot['config']['sessionColumns'][0]['title'] == 'Updated work')
        local = self.child / '.kanitor.json'
        local.write_text('{"workTracking":{"sessionColumns":[{"title":"Local work","field":"label"}]}}')
        wait_for_reader(reader, lambda: reader.snapshot['config']['sessionColumns'][0]['title'] == 'Local work')
        local.unlink()
        wait_for_reader(reader, lambda: reader.snapshot['config']['sessionColumns'][0]['title'] == 'Updated work')
        self.path.write_text('broken: [')
        wait_for_reader(reader, lambda: reader.snapshot['config'] == {})
        self.path.write_text(original)
        wait_for_reader(reader, lambda: reader.snapshot['config'].get('sessionColumns', [{}])[0].get('title') == 'Workspace work')
        self.path.unlink()
        wait_for_reader(reader, lambda: reader.snapshot['config'] == {})


@unittest.skipUnless(shutil.which('node') and shutil.which('kanbn'), 'native Node/kanbn required')
class NativeInheritanceTests(InheritanceFixture):
    def setUp(self):
        super().setUp()
        shutil.copytree(DEMO, self.child / '.kanbn')

    def app(self):
        catalog = ProjectCatalog(self.root, interval=.01)
        catalog.poll(force=True)
        app = ProjectsApp(test_ui.Screen(), self.root, catalog)
        self.addCleanup(app.close)
        return app

    def test_active_and_background_project_readers_reload_fallback_and_local_overrides(self):
        app = self.app()
        child = app.children[str(self.child)]
        wait_for(app, lambda: child.explorer.column_rules.columns[0].title == 'Workspace task')
        self.assertEqual(child.explorer.column_rules.board_columns[0].title, 'Workspace board')
        self.assertEqual(child.explorer.column_rules.for_board('releases')[0].title, 'Release ID')
        self.assertEqual(child.explorer.column_rules.square_rules.recent_work, 1800)
        original = self.path.read_text()
        self.path.write_text(original.replace('Workspace task', 'Updated task'))
        wait_for(app, lambda: child.explorer.column_rules.columns[0].title == 'Updated task')
        app.open_project()
        local = self.child / '.kanitor.yaml'
        local.write_text('columns:\n  - {title: Local task, field: name}\n')
        wait_for(app, lambda: child.explorer.column_rules.columns[0].title == 'Local task')
        self.path.write_text(original.replace('Workspace task', 'Newest task'))
        # Explicit child rules continue to win when the parent changes.
        app.poll()
        self.assertEqual(child.explorer.column_rules.columns[0].title, 'Local task')
        local.write_text('columns: []')
        wait_for(app, lambda: bool(child.reader.error))
        self.assertEqual(child.explorer.column_rules.columns[0].title, 'Local task')
        local.unlink()
        wait_for(app, lambda: not child.reader.error and child.explorer.column_rules.columns[0].title == 'Newest task')
        self.path.write_text('projects: [packages/child]\ncolumns: []\n')
        wait_for(app, lambda: bool(child.reader.error))
        self.assertEqual(child.explorer.column_rules.columns[0].title, 'Newest task')
        self.path.write_text(original)
        wait_for(app, lambda: not child.reader.error and child.explorer.column_rules.columns[0].title == 'Workspace task')

    def test_snapshots_direct_project_cli_and_standalone_child_are_consistent_and_read_only(self):
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.root.rglob('*') if path.is_file()}
        for args in (['--root', str(self.root), '--json'],
                     ['--root', str(self.root), '--project', 'packages/child', '--json'],
                     ['--root', str(self.child), '--json']):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(args), 0)
            data = json.loads(output.getvalue())
            if data['source'] == 'kanitor-projects':
                data = data['projects'][0]['snapshot']
            self.assertEqual(data['customization']['columns'][0]['title'], 'Workspace task')
            self.assertNotIn('projects', data['customization'])
        self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns)
                                  for path in self.root.rglob('*') if path.is_file()})

    def test_parent_creation_deletion_format_switch_and_snapshot_consistency(self):
        reader = LiveReader(self.child, interval=.01)
        self.addCleanup(reader.close)
        wait_for_reader(reader, lambda: reader.snapshot is not None)
        original = self.path.read_text()
        raw = subprocess.run(command(self.child), capture_output=True, text=True, check=True)
        self.path.unlink()
        with self.assertRaisesRegex(ReadError, 'changed during the read'):
            decode(raw.stdout, raw.stderr, raw.returncode)
        wait_for_reader(reader, lambda: reader.snapshot['customization'] == {})
        json_path = self.root / '.kanitor.json'
        json_path.write_text(json.dumps({'projects': ['packages/child'],
                                        'columns': [{'title': 'JSON fallback', 'field': 'id'}]}))
        wait_for_reader(reader, lambda: reader.snapshot['customization'].get('columns', [{}])[0].get('title') == 'JSON fallback')
        json_path.unlink()
        self.path.write_text(original)
        wait_for_reader(reader, lambda: reader.snapshot['customization'].get('columns', [{}])[0].get('title') == 'Workspace task')
