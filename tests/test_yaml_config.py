from contextlib import redirect_stderr, redirect_stdout
import builtins
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from kanitor.__main__ import main
from kanitor.config import (CONFIG_NAMES, ConfigError,
                            layout_columns, parse_config)
from kanitor.config_file import config_path, load_document
from kanitor.config_template import EXAMPLES, init_yml, render_yml
from kanitor.model import Explorer, find_root
from kanitor.projects import ProjectCatalog
from kanitor.reader import LiveReader, ReadError, command, decode
from kanitor.work.common import WorkError
from kanitor.work.reader import WorkReader
from kanitor.work.service import WorkService
from test_reader import wait_for


DEMO = Path(__file__).resolve().parents[1] / 'examples/demo/.kanbn'


class YAMLFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()


class YAMLConfigTests(YAMLFixture):
    def test_explicit_name_column_anchors_can_be_shared_with_activity(self):
        path = self.root / '.kanitor.yml'
        path.write_text('''projectColumns:
  - &project {title: Project, field: project, width: hug}
boardColumns:
  - &board {title: Board, field: board, width: hug}
columns:
  - &task {title: Task, field: task, width: fill}
activityColumns:
  - *project
  - *board
  - *task
''')
        data, _ = load_document(self.root)
        rules = parse_config(data)
        self.assertEqual([c.field for c in rules.activity_columns], ['project', 'board', 'task'])
        for column, context, value in zip(rules.activity_columns,
            (rules.project_columns, rules.board_columns, rules.columns), ('Worker', 'Review', 'Fix')):
            self.assertEqual(column.key, context[0].key)
            row = {'name': value} if column.field == 'task' else {column.field: value}
            self.assertEqual(column.value(row), value)
            self.assertEqual(context[0].value({'name': value}), value)

    def test_missing_yaml_reports_refresh_instructions_without_creating_a_config(self):
        original_import = builtins.__import__

        def missing_yaml(name, *args, **kwargs):
            if name == 'yaml':
                raise ModuleNotFoundError("No module named 'yaml'", name='yaml')
            return original_import(name, *args, **kwargs)

        errors = io.StringIO()
        with patch('builtins.__import__', side_effect=missing_yaml), redirect_stderr(errors):
            self.assertEqual(main(['--root', str(self.root), '--init-yml']), 1)
            self.assertEqual(list(self.root.iterdir()), [])
            path = self.root / '.kanitor.yml'
            path.write_text('columns:\n  - {title: Task, field: name}\n')
            with self.assertRaisesRegex(ConfigError, 'PyYAML is missing'):
                load_document(self.root)
            self.assertEqual(main(['--root', str(self.root), '--once']), 1)
            path.unlink()
            (self.root / '.kanitor.json').write_text('{}')
            self.assertEqual(load_document(self.root)[0], {}, 'JSON remains usable')
        self.assertIn('uv tool install --reinstall --editable', errors.getvalue())
        self.assertIn("'.[mcp]'", errors.getvalue())
        self.assertNotIn('Traceback', errors.getvalue())

    def test_formats_have_shared_values_and_deterministic_precedence_without_merging(self):
        self.assertEqual(load_document(self.root)[0], {})
        yaml_path = self.root / '.kanitor.yaml'
        yaml_path.write_text('columns:\n  - {title: Owner, metadata: assignee, width: hug, filterable: true}\n')
        yml_path = self.root / '.kanitor.yml'
        yml_path.write_text('columns:\n  - {title: Work, field: name, width: fill}\n')
        json_path = self.root / '.kanitor.json'
        json_path.write_text('{"taskSquares":{"recentWork":"30m"}}')
        self.assertEqual(load_document(self.root)[0], {'taskSquares': {'recentWork': '30m'}})
        json_path.write_text('{bad')
        with self.assertRaisesRegex(ConfigError, '.kanitor.json:'):
            load_document(self.root)
        json_path.unlink()
        self.assertEqual(config_path(self.root), yml_path)
        self.assertEqual(parse_config(load_document(self.root)[0]).columns[0].title, 'Work')
        yml_path.unlink()
        rules = parse_config(load_document(self.root)[0])
        self.assertEqual(rules.columns[0].metadata, 'assignee')
        self.assertTrue(rules.columns[0].can_filter)
        yaml_path.write_text('# comments only\n')
        self.assertEqual(load_document(self.root)[0], {})

    def test_yaml_anchors_merges_timestamps_and_quoted_keys_preserve_json_values(self):
        path = self.root / '.kanitor.yml'
        path.write_text('''columns:
  - &base {title: Owner, metadata: assignee, width: hug}
  - {<<: *base, title: Other owner}
workTracking:
  metadataSchemas:
    session:
      type: object
      properties:
        "123": {const: 2026-10-23T16:01:00Z}
        "true": {const: 2026-10-23}
''')
        data, selected = load_document(self.root)
        self.assertEqual(selected, path)
        self.assertEqual(data['columns'][1], {'title': 'Other owner', 'metadata': 'assignee', 'width': 'hug'})
        props = data['workTracking']['metadataSchemas']['session']['properties']
        self.assertEqual(props['123']['const'], '2026-10-23T16:01:00Z')
        self.assertEqual(props['true']['const'], '2026-10-23')
        json.dumps(data, allow_nan=False)

    def test_yaml_errors_name_the_selected_file_and_do_not_crash(self):
        for name in CONFIG_NAMES[1:]:
            path = self.root / name
            for text in ('columns: [', 'columns: []', 'columns: []\ncolumns: []',
                         'boards: {12: {columns: []}}', 'columns: !!python/object:evil {}',
                         'workTracking: {outcomes: {test: {requiresEvidence: nope}}}',
                         'workTracking: {metadataSchemas: {session: {const: .nan}}}',
                         'workTracking: {metadataSchemas: {session: {const: !!binary Zm9v}}}',
                         'workTracking: &cycle {metadataSchemas: *cycle}'):
                with self.subTest(name=name, text=text):
                    path.write_text(text)
                    with self.assertRaises(ConfigError) as caught:
                        load_document(self.root)
                    self.assertIn(name + ':', str(caught.exception))
                    self.assertNotIn('.kanitor.json', str(caught.exception))
            path.unlink()

    def test_board_slug_anchor_can_be_reused_in_activity_columns(self):
        path = self.root / '.kanitor.yml'
        path.write_text('''boardColumns:
  - &board_column
    title: BOARD
    field: slug
    width: 12,hug,16
activityColumns:
  - *board_column
  - {title: Task, field: name}
''')
        data, _ = load_document(self.root)
        rules = parse_config(data)
        board, activity = rules.board_columns[0], rules.activity_columns[0]
        self.assertEqual((board.field, activity.field), ('slug', 'slug'))
        self.assertEqual((board.width, activity.width), ('12,hug,16', '12,hug,16'))
        self.assertEqual(activity.scope, 'activity')
        self.assertTrue(activity.can_filter and activity.can_sort)

    def test_generated_file_reproduces_default_layouts_at_all_terminal_widths(self):
        path = init_yml(self.root)
        data, _ = load_document(self.root)
        rules, defaults = parse_config(data), parse_config({})
        self.assertEqual(rules, defaults)
        self.assertIsNone(rules.projects, 'initializing must not enable the Projects view')
        self.assertNotIn('sessionColumns', data['workTracking'])
        for width in (50, 79, 80, 89, 90, 99, 100, 109, 110, 160):
            for actual, expected in ((rules.columns, defaults.columns),
                                     (rules.board_columns, defaults.board_columns),
                                     (rules.project_columns, defaults.project_columns)):
                self.assertEqual(layout_columns(actual, width, width - 5),
                                 layout_columns(expected, width, width - 5))
        self.assertIn('# projects:', path.read_text())
        service = WorkService()
        session = service.execute('work_begin', self.root, {'request_id': 'begin', 'label': 'No required identity'})
        service.execute('work_end', self.root, {'request_id': 'end', 'session_id': session['session_id']})

    def test_commented_examples_each_form_a_valid_configuration(self):
        path = self.root / '.kanitor.yml'
        count = 0
        for block in EXAMPLES.split('\n\n'):
            lines = block.splitlines()
            starts = [index for index, line in enumerate(lines) if line.startswith(tuple(
                '# ' + key + ':' for key in ('projects', 'columns', 'boards', 'boardColumns', 'taskSquares', 'workTracking')))]
            if starts:
                path.write_text('\n'.join(line[2:] for line in lines[starts[0]:]))
                load_document(self.root)
                count += 1
        self.assertEqual(count, 6)

    def test_minimum_terminal_width_is_validated_in_task_board_project_and_work_rules(self):
        for section in ('columns', 'boardColumns', 'projectColumns', 'sessionColumns'):
            field = 'label' if section == 'sessionColumns' else 'name'
            for minimum in (-1, True, '90'):
                value = {section: [{'title': 'Test', 'field': field, 'minTerminalWidth': minimum}]}
                if section == 'sessionColumns':
                    value = {'workTracking': value}
                with self.subTest(section=section, minimum=minimum), self.assertRaises(ConfigError):
                    parse_config(value)

    def test_initializer_works_without_native_tools_in_current_directory_or_explicit_root(self):
        output = io.StringIO()
        with patch('kanitor.__main__.Path.cwd', return_value=self.root), \
                patch('kanitor.__main__.read_once', side_effect=AssertionError('no native reads')), \
                redirect_stdout(output):
            self.assertEqual(main(['--init-yml']), 0)
        self.assertIn(str(self.root / '.kanitor.yml'), output.getvalue())
        child = self.root / 'child'
        child.mkdir()
        with patch('kanitor.__main__.Path.cwd', return_value=child), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--init-yml']), 0)
        self.assertTrue((child / '.kanitor.yml').exists(), 'must not discover or edit a parent config')
        other = self.root / 'other'
        other.mkdir()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--root', str(other), '--init-yml']), 0)
        self.assertEqual((other / '.kanitor.yml').read_text(), render_yml())

    def test_initializer_preserves_all_existing_config_formats_and_handles_invalid_destination(self):
        for name in CONFIG_NAMES:
            path = self.root / name
            path.write_text('original bytes')
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(main(['--root', str(self.root), '--init-yml']), 1)
            self.assertIn(name, errors.getvalue())
            self.assertEqual(path.read_text(), 'original bytes')
            self.assertEqual(list(self.root.iterdir()), [path])
            path.unlink()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--root', str(self.root / 'missing'), '--init-yml']), 1)

    def test_yaml_project_catalog_and_recording_rules_reload_and_keep_local_settings(self):
        (self.root / '.kanitor.yml').write_text('projects: [one, two]\n')
        one, two = self.root / 'one', self.root / 'two'
        one.mkdir()
        two.mkdir()
        (one / '.kanitor.yaml').write_text('workTracking:\n  sessionColumns:\n    - {title: One work, field: label}\n')
        (two / '.kanitor.json').write_text('{"workTracking":{"sessionColumns":[{"title":"Two work","field":"label"}]}}')
        self.assertEqual(find_root(one / 'nested'), one)
        catalog = ProjectCatalog(self.root, interval=0)
        catalog.poll()
        self.assertFalse(catalog.error)
        service = WorkService()
        configs = [service.viewer_snapshot(p.root)['config'] for p in catalog.projects]
        self.assertEqual([config['sessionColumns'][0]['title'] for config in configs],
                         ['One work', 'Two work'])
        (self.root / '.kanitor.yml').write_text('projects: [two]\n')
        catalog.poll()
        self.assertEqual([p.path for p in catalog.projects], ['two'])
        (self.root / '.kanitor.yml').write_text('projects: nope\n')
        catalog.poll()
        self.assertIn('.kanitor.yml:', catalog.error)
        self.assertEqual([p.path for p in catalog.projects], ['two'])
        (self.root / '.kanitor.yml').unlink()
        catalog.poll()
        self.assertFalse(catalog.declared)

    def test_work_reader_reloads_yaml_and_writer_enforces_yaml_rules(self):
        service = WorkService()
        reader = WorkReader(self.root, interval=.01)
        self.addCleanup(reader.close)
        wait_for(reader, lambda: reader.revision == 1)
        path = self.root / '.kanitor.yml'
        path.write_text('''workTracking:
  sessionColumns:
    - {title: Owner, metadata: assignee, filterable: true, minTerminalWidth: 60}
  metadataSchemas:
    session: {type: object, required: [assignee]}
  outcomes:
    verified: {requiresEvidence: true}
''')
        wait_for(reader, lambda: reader.revision == 2)
        self.assertEqual(reader.snapshot['config']['sessionColumns'][0]['title'], 'Owner')
        caps = service.execute('work_capabilities', self.root)
        self.assertEqual(caps['session_columns'], reader.snapshot['config']['sessionColumns'])
        with self.assertRaises(WorkError):
            service.execute('work_begin', self.root, {'request_id': 'missing', 'label': 'Needs owner'})
        session = service.execute('work_begin', self.root, {'request_id': 'begin', 'label': 'Owned', 'metadata': {'assignee': 'Alex'}})
        with self.assertRaises(WorkError) as caught:
            service.execute('work_end', self.root, {'request_id': 'missing-evidence', 'session_id': session['session_id'], 'outcome': 'verified'})
        self.assertEqual(caught.exception.code, 'evidence_required')
        wait_for(reader, lambda: len(reader.snapshot['sessions']) == 1)
        path.write_text('workTracking: {sessionColumns: []}')
        wait_for(reader, lambda: bool(reader.snapshot['warnings']))
        self.assertIn('.kanitor.yml:', reader.snapshot['warnings'][0]['message'])
        path.unlink()
        wait_for(reader, lambda: reader.snapshot['config'] == {})


@unittest.skipUnless(shutil.which('node') and shutil.which('kanbn'), 'native Node/kanbn installation required')
class NativeYAMLTests(YAMLFixture):
    def setUp(self):
        super().setUp()
        shutil.copytree(DEMO, self.root / '.kanbn')

    def test_yaml_native_settings_reload_recover_switch_extensions_and_restore_defaults(self):
        reader = LiveReader(self.root, interval=.01)
        self.addCleanup(reader.close)
        wait_for(reader, lambda: reader.revision == 1)
        original = {p: p.read_bytes() for p in (self.root / '.kanbn').rglob('*') if p.is_file()}
        path = self.root / '.kanitor.yml'
        path.write_text('columns:\n  - {title: Owner, metadata: assignee, filterable: true}\nboardColumns:\n  - {title: Plan, field: slug}\n')
        wait_for(reader, lambda: reader.revision == 2)
        explorer = Explorer()
        explorer.apply(reader.snapshot)
        self.assertEqual(explorer.column_rules.board_columns[0].title, 'Plan')
        self.assertTrue(explorer.column_rules.columns[0].can_filter)
        path.write_text('columns: []')
        wait_for(reader, lambda: bool(reader.error))
        self.assertIn('.kanitor.yml:', reader.error)
        self.assertEqual(reader.snapshot['customization']['columns'][0]['title'], 'Owner')
        revision = reader.revision
        path.unlink()
        yaml_path = self.root / '.kanitor.yaml'
        yaml_path.write_text('columns:\n  - {title: New task, field: name}\n')
        wait_for(reader, lambda: reader.revision > revision and not reader.error)
        self.assertEqual(reader.snapshot['customization']['columns'][0]['title'], 'New task')
        revision = reader.revision
        yaml_path.unlink()
        wait_for(reader, lambda: reader.revision > revision)
        self.assertEqual(reader.snapshot['customization'], {})
        self.assertEqual({p: p.read_bytes() for p in original}, original)

    def test_native_decode_discards_configuration_changed_after_bridge_snapshot(self):
        raw = subprocess.run(command(self.root), text=True, capture_output=True, check=True)
        (self.root / '.kanitor.yml').write_text('columns: []')
        with self.assertRaisesRegex(ReadError, 'changed during the read'):
            decode(raw.stdout, raw.stderr, raw.returncode)

    def test_initialized_yaml_is_loaded_by_snapshot_cli(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--root', str(self.root), '--init-yml']), 0)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--root', str(self.root), '--json']), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(parse_config(data['customization']), parse_config({}))
        self.assertTrue(data['boards'])
