from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from datetime import datetime
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from kanitor.__main__ import main
from kanitor.model import Explorer, counts, state
from kanitor.reader import LiveReader, ReadError, read_once

DEMO = Path(__file__).resolve().parents[1] / 'examples' / 'demo'


def wait_for(reader, condition, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reader.poll()
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError(f'Reader did not reach expected state: {reader.error}')


@unittest.skipUnless(shutil.which('node') and shutil.which('kanbn'), 'native Node/kanbn installation required')
class NativeReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(DEMO / '.kanbn', self.root / '.kanbn')

    def files(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_snapshot_is_read_only_and_shared_cards_have_board_local_states(self):
        before = self.files()
        data = read_once(self.root)
        self.assertEqual(self.files(), before)
        self.assertTrue(data['readOnly'])
        main_board, review = data['boards']
        self.assertEqual(counts(main_board), {'done': 2, 'active': 2, 'remaining': 2})
        self.assertEqual(counts(review), {'done': 1, 'active': 1, 'remaining': 1})
        card = next(c for c in review['tasks'] if c['id'] == 'read-native-kanbn-data')
        self.assertIn('completed', card['metadata'])
        self.assertEqual(state(review, card['column']), 'active')
        card = next(c for c in main_board['tasks'] if c['id'] == 'explore-native-boards')
        self.assertEqual(len(card['history']), 2)
        self.assertEqual(card['comments'][0]['author'], 'Alex')
        self.assertEqual(len(card['subTasks']), 3)

    def test_computed_board_updated_combines_file_mtime_and_task_dates(self):
        index = self.root / '.kanbn/index.md'
        release = self.root / '.kanbn/releases.md'
        os.utime(index, (1700000000, 1700000000))
        os.utime(release, (1700000001, 1700000001))
        data = read_once(self.root)
        for board in data['boards']:
            values = [Path(board['path']).stat().st_mtime]
            for task in board['tasks']:
                try:
                    values.append(datetime.fromisoformat(task['metadata'].get('updated', '').replace('Z', '+00:00')).timestamp())
                except ValueError:
                    pass
            self.assertAlmostEqual(datetime.fromisoformat(board['updated'].replace('Z', '+00:00')).timestamp(), max(values), places=3)
        before = self.files()
        explorer = Explorer()
        explorer.apply(data)
        self.assertEqual(self.files(), before)
        self.assertEqual([b['slug'] for b in explorer.board_rows],
                         [b['slug'] for b in sorted(data['boards'], key=lambda b: b['updated'], reverse=True)])

    def test_custom_paths_order_exclusion_and_board_settings(self):
        (self.root / '.kanbn').rename(self.root / 'planning')
        (self.root / 'planning/tasks').rename(self.root / 'planning/cards')
        (self.root / 'planning/index.md').rename(self.root / 'planning/roadmap.md')
        config = {'mainFolder': 'planning', 'taskFolder': 'cards', 'indexFile': 'roadmap.md',
                  'boards': {'order': ['releases', 'roadmap'], 'roadmap': {'startedColumns': []}}}
        config_path = self.root / 'kanbn.json'
        config_path.write_text(json.dumps(config))
        data = read_once(self.root)
        self.assertEqual([b['slug'] for b in data['boards']], ['releases', 'roadmap'])
        self.assertIn(str(self.root / 'planning/cards'), data['watch']['folders'])
        config['boards']['exclude'] = ['releases']
        config_path.write_text(json.dumps(config))
        self.assertEqual([b['slug'] for b in read_once(self.root)['boards']], ['roadmap'])

    def test_malformed_history_is_omitted_with_actionable_warning_without_modification(self):
        card = self.root / '.kanbn/tasks/search-cards.md'
        malformed = card.read_text() + '\n## History\n\n- type: moved\n  date: 2026-10-30T12:00:00Z\n  toColumn: Done\n'
        card.write_text(malformed)
        before = self.files()
        data = read_once(self.root)
        self.assertEqual(self.files(), before)
        self.assertEqual(len(data['boards']), 2)
        self.assertNotIn('search-cards', [task['id'] for task in data['boards'][0]['tasks']])
        self.assertEqual(data['warnings'], [{'task': 'search-cards', 'board': 'index',
            'error': 'Unable to parse task: moved history event is missing fromColumn or toColumn'}])
        for flag in ('--once', '--json'):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(['--root', str(self.root), flag]), 1)
            self.assertIn('search-cards', output.getvalue())
            self.assertIn('missing fromColumn or toColumn', output.getvalue())
            if flag == '--json':
                self.assertEqual(len(json.loads(output.getvalue())['boards']), 2)
            else:
                self.assertIn('PARTIAL', output.getvalue())

    def test_live_refresh_error_recovery_and_unchanged_frames(self):
        reader = LiveReader(self.root, interval=0.01)
        self.addCleanup(reader.close)
        wait_for(reader, lambda: reader.revision == 1)
        before = self.files()
        for _ in range(5):
            reader.poll()
        self.assertIsNone(reader.process)
        self.assertEqual(reader.revision, 1)
        self.assertEqual(self.files(), before)
        card = self.root / '.kanbn/tasks/search-cards.md'
        original = card.read_text()
        card.write_text('Not a native card')
        revision = reader.revision
        wait_for(reader, lambda: reader.revision > revision)
        self.assertFalse(reader.error)
        self.assertEqual(reader.snapshot['warnings'][0]['task'], 'search-cards')
        self.assertIsNotNone(reader.snapshot)
        self.assertEqual(reader.revision, 2)
        card.write_text(original.replace('Search titles', 'Search all titles'))
        wait_for(reader, lambda: reader.revision == 3)
        self.assertFalse(reader.error)
        self.assertEqual(reader.snapshot['warnings'], [])
        self.assertIn('Search all titles', reader.snapshot['boards'][0]['tasks'][1]['description'])
        reader.refresh()
        wait_for(reader, lambda: reader.revision == 4)

    def test_initial_read_is_usable_when_all_tasks_fail_including_shared_memberships(self):
        for card in (self.root / '.kanbn/tasks').glob('*.md'):
            card.write_text('Not a native card')
        before = self.files()
        reader = LiveReader(self.root, interval=.01)
        self.addCleanup(reader.close)
        wait_for(reader, lambda: reader.revision == 1)
        self.assertFalse(reader.error)
        data = reader.snapshot
        self.assertEqual([board['tasks'] for board in data['boards']], [[], []])
        self.assertEqual(len(data['warnings']), 9)
        self.assertEqual({item['board'] for item in data['warnings']
                          if item['task'] == 'read-native-kanbn-data'}, {'index', 'releases'})
        self.assertEqual(self.files(), before)
        card = self.root / '.kanbn/tasks/read-native-kanbn-data.md'
        shutil.copy(DEMO / '.kanbn/tasks/read-native-kanbn-data.md', card)
        wait_for(reader, lambda: reader.revision == 2)
        self.assertEqual(len(reader.snapshot['warnings']), 7)
        self.assertTrue(all(board['tasks'][0]['id'] == card.stem for board in reader.snapshot['boards']))

    def test_live_reader_follows_new_boards_and_deletions(self):
        reader = LiveReader(self.root, interval=0.01)
        self.addCleanup(reader.close)
        wait_for(reader, lambda: reader.revision == 1)
        board = self.root / '.kanbn/new.md'
        board.write_text('# New board\n\n## Open\n')
        wait_for(reader, lambda: reader.revision == 2)
        self.assertEqual(len(reader.snapshot['boards']), 3)
        board.unlink()
        wait_for(reader, lambda: reader.revision == 3)
        self.assertEqual(len(reader.snapshot['boards']), 2)

    def test_keybindings_reload_and_invalid_conflicts_retain_last_good_settings(self):
        reader = LiveReader(self.root, interval=.01)
        self.addCleanup(reader.close)
        explorer = Explorer()
        path = self.root / '.kanitor.yml'
        path.write_text('keybindings:\n  open: [o]\n  help: [F1]\n')
        wait_for(reader, lambda: reader.revision == 1)
        explorer.apply(reader.snapshot)
        self.assertEqual(explorer.column_rules.keybindings.action('o'), 'open')
        path.write_text('keybindings:\n  open: [q]\n')
        wait_for(reader, lambda: bool(reader.error))
        self.assertIn('keybindings', reader.error)
        self.assertEqual(reader.revision, 1)
        explorer.apply(reader.snapshot)
        self.assertEqual(explorer.column_rules.keybindings.action('o'), 'open')
        path.write_text('keybindings:\n  open: [e]\n')
        wait_for(reader, lambda: reader.revision == 2)
        explorer.apply(reader.snapshot)
        self.assertIsNone(explorer.column_rules.keybindings.action('o'))
        self.assertEqual(explorer.column_rules.keybindings.action('e'), 'open')
        path.unlink()
        wait_for(reader, lambda: reader.revision == 3)
        explorer.apply(reader.snapshot)
        self.assertEqual(explorer.column_rules.keybindings.action('\n'), 'open')

    def test_initial_custom_folder_edit_before_snapshot_application_is_discarded(self):
        (self.root / '.kanbn').rename(self.root / 'planning')
        (self.root / 'kanbn.json').write_text(json.dumps({'mainFolder': 'planning'}))
        reader = LiveReader(self.root, interval=0.01)
        self.addCleanup(reader.close)
        reader.poll()
        reader.process.wait(timeout=8)
        card = self.root / 'planning/tasks/search-cards.md'
        card.write_text(card.read_text().replace('Search titles', 'Search all titles'))
        reader.poll()
        self.assertEqual(reader.revision, 0, 'Changed initial snapshot must not be applied')
        wait_for(reader, lambda: reader.revision == 1)
        self.assertIn('Search all titles', reader.snapshot['boards'][0]['tasks'][1]['description'])

    def test_read_timeout_cleans_up_process(self):
        reader = LiveReader(self.root, timeout=0.000001)
        self.addCleanup(reader.close)
        reader.poll()
        reader.poll()
        self.assertIsNone(reader.process)
        self.assertIn('exceeded', reader.error)
        self.assertIsNone(reader.snapshot)

    def test_custom_column_rules_reload_recover_and_never_write_cards(self):
        reader = LiveReader(self.root, interval=0.01)
        self.addCleanup(reader.close)
        wait_for(reader, lambda: reader.revision == 1)
        before = self.files()
        path = self.root / '.kanitor.json'
        rules = {'columns': [{'title': 'Owner', 'metadata': 'assignee'}, {'title': 'Task', 'field': 'name'}],
                 'boardColumns': [{'title': 'Board', 'field': 'name', 'width': 'fill'},
                                  {'title': 'Cards', 'field': 'cards', 'width': 'hug'}]}
        path.write_text(json.dumps(rules))
        wait_for(reader, lambda: reader.revision == 2)
        self.assertEqual(reader.snapshot['customization'], rules)
        for invalid in ('{invalid', '{"columns": [{"title": "Owner", "field": "assignee"}]}',
                        '{"boardColumns": [{"title": "Board", "field": "status"}]}'):
            path.write_text(invalid)
            wait_for(reader, lambda: bool(reader.error))
            self.assertIn('.kanitor.json', reader.error)
            self.assertEqual(reader.snapshot['customization'], rules)
            path.write_text(json.dumps(rules))
            revision = reader.revision
            wait_for(reader, lambda: reader.revision > revision and not reader.error)
        path.unlink()
        revision = reader.revision
        wait_for(reader, lambda: reader.revision > revision)
        self.assertEqual(reader.snapshot['customization'], {})
        self.assertEqual(self.files(), before)

    def test_board_columns_read_native_frontmatter_and_counts_without_writes(self):
        index = self.root / '.kanbn/index.md'
        index.write_text(index.read_text().replace('---\n',
            '---\nowner: Alex\nreview.owner: [Sam, Morgan]\nupdated: "2026-10-23T16:01:00"\n', 1))
        rules = {'boardColumns': [
            {'title': 'Owner', 'metadata': 'owner'},
            {'title': 'Review', 'metadata': 'review.owner'},
            {'title': 'Updated', 'metadata': 'updated', 'format': '%H:%M'},
            {'title': 'Cards', 'field': 'cards'}, {'title': 'Active', 'field': 'active'},
            {'title': 'Done', 'field': 'done'}, {'title': 'Remaining', 'field': 'remaining'}]}
        (self.root / '.kanitor.json').write_text(json.dumps(rules))
        before = self.files()
        data = read_once(self.root)
        explorer = Explorer()
        explorer.apply(data)
        values = [column.value(explorer.board_rows[0]) for column in explorer.column_rules.board_columns]
        self.assertEqual(values, ['Alex', '["Sam", "Morgan"]', '16:01', '6', '2', '2', '2'])
        self.assertNotIn('cards', data['boards'][0])
        self.assertEqual(self.files(), before)

    def test_missing_workspace_fails_but_missing_card_is_isolated(self):
        (self.root / '.kanbn/index.md').unlink()
        with self.assertRaisesRegex(ReadError, 'No initialized kanbn workspace'):
            read_once(self.root)
        shutil.copy(DEMO / '.kanbn/index.md', self.root / '.kanbn/index.md')
        (self.root / '.kanbn/tasks/keyboard-shortcuts.md').unlink()
        data = read_once(self.root)
        self.assertEqual(len(data['boards']), 2)
        self.assertEqual(data['warnings'][0]['task'], 'keyboard-shortcuts')
        self.assertIn('No task file', data['warnings'][0]['error'])

    def test_cli_snapshots_and_error_exit(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(['--root', str(self.root), '--board', 'releases', '--search', 'integration', '--once'])
        self.assertEqual(code, 0)
        self.assertIn('releases * All statuses', output.getvalue())
        self.assertNotIn('[Proposed]', output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--root', str(self.root), '--json']), 0)
        self.assertEqual(len(json.loads(output.getvalue())['boards']), 2)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--root', str(self.root), '--board', 'missing', '--once']), 1)
