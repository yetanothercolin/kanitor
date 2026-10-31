import asyncio
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from kanitor.__main__ import main
from kanitor.work.common import WorkError
from kanitor.work.service import WorkService

REPO = Path(__file__).parents[1]
MCP_AVAILABLE = importlib.util.find_spec('mcp') is not None


class CLIWorkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def cli(self, operation, arguments=None):
        path = self.root / 'input.json'
        path.write_text(json.dumps(arguments or {}))
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(['work', operation, '--workspace', str(self.root), '--input', str(path)])
        return code, json.loads(output.getvalue())

    def test_cli_and_library_return_same_original_receipt(self):
        args = {'label': 'CLI', 'metadata': {'anything': [0, False]}, 'request_id': 'cli-begin'}
        code, result = self.cli('begin', args)
        self.assertEqual(code, 0)
        self.assertEqual(WorkService().execute('work_begin', self.root, args), result)
        code, read = self.cli('read', {'view': 'sessions'})
        self.assertEqual(read['items'][0]['id'], result['session_id'])

    def test_cli_records_work_with_invalid_view_configuration(self):
        (self.root / '.kanitor.yml').write_text('activityColumns: []\ncolumns: []\nfutureView: true\n')
        code, begin = self.cli('begin', {'label': 'Independent work', 'request_id': 'begin'})
        self.assertEqual(code, 0)
        code, end = self.cli('end', {'session_id': begin['session_id'], 'request_id': 'end'})
        self.assertEqual((code, end['state']), (0, 'closed'))

    def test_cli_ignores_unreadable_unrelated_ancestor(self):
        parent = self.root
        (parent / '.kanitor.yml').write_text('projects: [other]\ncolumns: [')
        self.root = parent / 'unlisted'
        self.root.mkdir()
        code, begin = self.cli('begin', {'label': 'Independent', 'request_id': 'begin'})
        self.assertEqual(code, 0)
        code, end = self.cli('end', {'session_id': begin['session_id'], 'request_id': 'end'})
        self.assertEqual((code, end['state']), (0, 'closed'))

    def test_cli_errors_are_json_and_stdin_works_without_a_terminal(self):
        output = io.StringIO()
        with redirect_stdout(output), patch('sys.stdin', io.StringIO('{"label":"stdin","request_id":"stdin"}')):
            code = main(['work', 'begin', '--workspace', str(self.root), '--input', '-'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['state'], 'open')
        code, result = self.cli('begin', {'label': 'missing ID'})
        self.assertEqual(code, 1)
        self.assertEqual(result['error']['code'], 'validation_error')
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(['work', 'read'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['error']['code'], 'invalid_arguments')

    def test_process_restart_leaves_session_open_and_retry_is_durable(self):
        arguments = {'label': 'restart', 'request_id': 'process'}
        command = [sys.executable, '-m', 'kanitor', 'work', 'begin', '--workspace', str(self.root), '--input', '-']
        first = subprocess.run(command, input=json.dumps(arguments), text=True, capture_output=True, cwd=REPO, check=True)
        second = subprocess.run(command, input=json.dumps(arguments), text=True, capture_output=True, cwd=REPO, check=True)
        self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))
        summary = WorkService().execute('work_read', self.root, {'view': 'sessions'})['items'][0]
        self.assertEqual(summary['state'], 'open')
        self.assertEqual(summary['revision'], 1)

    @unittest.skipUnless(shutil.which('node') and shutil.which('kanbn'), 'native Node/kanbn required')
    def test_native_subjects_custom_paths_archives_moves_and_deletions_are_read_only(self):
        demo = REPO / 'examples/demo/.kanbn'
        shutil.copytree(demo, self.root / 'planning')
        (self.root / 'planning/tasks').rename(self.root / 'planning/cards')
        (self.root / 'planning/archive').mkdir(exist_ok=True)
        (self.root / 'kanbn.json').write_text(json.dumps({'mainFolder': 'planning', 'taskFolder': 'cards'}))
        task = self.root / 'planning/cards/explore-native-boards.md'
        task_data = task.read_bytes()
        archive = self.root / 'planning/archive/explore-native-boards.md'
        service = WorkService()
        def files():
            return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*')
                    if p.is_file() and '.kanitor' not in p.parts}
        original = files()
        subject = {'provider': 'kanbn', 'ref': 'explore-native-boards'}
        begin = service.execute('work_begin', self.root, {'label': 'linked', 'subject': subject, 'request_id': 'native'})
        self.assertEqual(files(), original)
        self.assertEqual(service.execute('work_read', self.root, {'view': 'sessions'})['items'][0]['subject_resolution']['state'], 'active')
        task.rename(archive)
        before = files()
        summary = service.execute('work_read', self.root, {'view': 'sessions'})['items'][0]
        self.assertEqual(summary['subject_resolution']['state'], 'archived')
        self.assertEqual(files(), before)
        archive.unlink()
        summary = service.execute('work_read', self.root, {'view': 'sessions'})['items'][0]
        self.assertEqual(summary['subject_resolution']['state'], 'unresolved')
        self.assertEqual(summary['id'], begin['session_id'])
        self.assertIn('unresolved_subject', [w['code'] for w in summary['warnings']])
        with self.assertRaises(WorkError) as caught:
            service.execute('work_begin', self.root, {'label': 'missing', 'subject': subject, 'request_id': 'missing'})
        self.assertEqual(caught.exception.code, 'unknown_subject')
        # A successful original request still retries after its subject disappears.
        self.assertEqual(service.execute('work_begin', self.root,
            {'label': 'linked', 'subject': subject, 'request_id': 'native'}), begin)
        renamed = self.root / 'planning/cards/renamed-task.md'
        renamed.write_bytes(task_data.replace(b'assigned: Alex', b'assigned: Morgan'))
        before = files()
        service.execute('work_amend', self.root, {'request_id': 'rebind',
            'target': {'kind': 'session', 'id': begin['session_id']}, 'expected_revision': 1,
            'correction': {'subject': {'provider': 'kanbn', 'ref': 'renamed-task'}}, 'reason': 'explicit rename'})
        rebound = service.execute('work_read', self.root, {'view': 'sessions'})['items'][0]
        self.assertEqual(rebound['subject']['ref'], 'renamed-task')
        self.assertEqual(rebound['original_subject'], subject)
        self.assertEqual(rebound['metadata'], {})
        self.assertEqual(files(), before)


@unittest.skipUnless(MCP_AVAILABLE, 'install the optional mcp extra for protocol integration tests')
class MCPWorkTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_ignores_unreadable_unrelated_ancestor(self):
        async def scenario(session):
            (self.root / '.kanitor.yml').write_text('projects: [other]\ncolumns: [')
            child = self.root / 'unlisted'
            child.mkdir()
            begin = await session.call_tool('work_begin',
                {'workspace': str(child), 'label': 'Independent', 'request_id': 'begin'})
            self.assertFalse(begin.isError, begin.content)
            end = await session.call_tool('work_end',
                {'workspace': str(child), 'session_id': begin.structuredContent['session_id'], 'request_id': 'end'})
            self.assertFalse(end.isError, end.content)
        await asyncio.wait_for(self.connect(scenario), timeout=20)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    async def connect(self, callback):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=sys.executable, args=['-m', 'kanitor', 'mcp'], cwd=REPO)
        with tempfile.TemporaryFile(mode='w+') as errors:
            async with stdio_client(params, errlog=errors) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    return await callback(session)

    async def test_running_mcp_ignores_new_and_invalid_view_settings_but_enforces_work_rules(self):
        async def scenario(session):
            # Edit after the server connects: recorder policy reloads per operation.
            (self.root / '.kanitor.yml').write_text('''futureView: true
activityColumns: []
workTracking:
  metadataSchemas:
    session: {type: object, required: [owner]}
''')
            args = {'workspace': str(self.root), 'label': 'Independent recorder', 'request_id': 'begin'}
            missing = await session.call_tool('work_begin', args)
            self.assertTrue(missing.isError)
            self.assertEqual(missing.structuredContent['error']['code'], 'validation_error')
            result = await session.call_tool('work_begin', dict(args, metadata={'owner': 'Alex'}))
            self.assertFalse(result.isError, result.content)
            sid = result.structuredContent['session_id']
            (self.root / '.kanitor.yml').write_text('columns: []\nkeybindings: {quit: [down]}\n')
            end = await session.call_tool('work_end',
                {'workspace': str(self.root), 'session_id': sid, 'request_id': 'end'})
            self.assertFalse(end.isError, end.content)
            self.assertEqual(end.structuredContent['state'], 'closed')
        await asyncio.wait_for(self.connect(scenario), timeout=20)

    async def test_real_stdio_discovery_equivalence_restart_and_structured_errors(self):
        args = {'workspace': str(self.root), 'label': 'MCP', 'request_id': 'mcp-begin'}
        async def first(session):
            tools = await session.list_tools()
            self.assertEqual(len(tools.tools), 10)
            self.assertTrue(all('workspace' in tool.inputSchema['required'] for tool in tools.tools))
            result = await session.call_tool('work_begin', args)
            self.assertFalse(result.isError)
            self.assertEqual(json.loads(result.content[0].text), result.structuredContent)
            bad = await session.call_tool('work_begin', {'workspace': '.', 'label': 'bad', 'request_id': 'bad'})
            self.assertTrue(bad.isError)
            self.assertEqual(bad.structuredContent['error']['code'], 'invalid_workspace')
            return result.structuredContent
        receipt = await asyncio.wait_for(self.connect(first), timeout=20)
        direct = WorkService().execute('work_begin', self.root, {k: v for k, v in args.items() if k != 'workspace'})
        self.assertEqual(receipt, direct)
        async def second(session):
            retry = await session.call_tool('work_begin', args)
            self.assertEqual(retry.structuredContent, receipt)
            read = await session.call_tool('work_read', {'workspace': str(self.root), 'view': 'sessions'})
            self.assertEqual(read.structuredContent['items'][0]['state'], 'open')
            self.assertEqual(read.structuredContent['items'][0]['revision'], 1)
            conflict = await session.call_tool('work_begin', dict(args, label='different'))
            self.assertTrue(conflict.isError)
            self.assertEqual(conflict.structuredContent['error']['code'], 'request_conflict')
        await asyncio.wait_for(self.connect(second), timeout=20)

    async def test_all_protocol_operations_share_lifecycle_and_corrections(self):
        async def scenario(session):
            async def call(name, **arguments):
                if name not in ('read', 'capabilities'):
                    arguments.setdefault('request_id', str(uuid.uuid4()))
                result = await session.call_tool('work_' + name, {'workspace': str(self.root), **arguments})
                self.assertFalse(result.isError, result.content)
                return result.structuredContent
            caps = await call('capabilities')
            self.assertEqual(caps['schema_versions'], [1])
            begin = await call('begin', label='protocol lifecycle')
            sid = begin['session_id']
            await call('transition', session_id=sid, label='changing')
            parent = await call('span_begin', session_id=sid, label='build')
            child = await call('span_begin', session_id=sid, label='compile', parent_span_id=parent['span_id'])
            await call('note', session_id=sid, span_id=child['span_id'], text='observation', metadata={'new.key': [False, 0]})
            await call('span_end', span_id=child['span_id'])
            await call('span_end', span_id=parent['span_id'])
            await call('span_record', session_id=sid, label='earlier operation',
                       reported_start='2026-10-23T00:00:00Z', reported_end='2026-10-23T00:00:01Z',
                       measured_duration_ms=999, clock={'kind': 'monotonic'})
            end = await call('end', session_id=sid, outcome='unsuccessful')
            await call('amend', target={'kind': 'session', 'id': sid}, expected_revision=end['revision'],
                       correction={'label': 'corrected protocol label'}, reason='clarify')
            read = await call('read', view='sessions', session_id=sid)
            self.assertEqual(read['items'][0]['label'], 'corrected protocol label')
            self.assertEqual(read['items'][0]['state'], 'closed')
            self.assertEqual(len(read['items'][0]['spans']), 3)
        await asyncio.wait_for(self.connect(scenario), timeout=20)
