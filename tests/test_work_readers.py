"""Work snapshot reads used by Task Squares; no interactive Work views."""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from kanitor.model import find_root
from kanitor.work.reader import WorkReader
from kanitor.work.service import WorkService
from test_reader import wait_for
from test_work import Clock


def fixture(root, extra=0):
    clock = Clock()
    service = WorkService(clock=clock, subject_resolver=lambda root, subject: {'state': 'active'})
    counter = [0]
    def call(name, **args):
        counter[0] += 1
        args['request_id'] = f'fixture-{counter[0]}'
        return service.execute('work_' + name, root, args)
    first = call('begin', label='Adjust inventory spacing', subject={'provider': 'kanbn', 'ref': 'one'},
                 metadata={'owner': 'Alex', 'literal.dot': ['Sam', 'Morgan'], 'value': False})
    sid = first['session_id']
    clock.seconds = 5
    phase = call('transition', session_id=sid, label='changing', metadata={'activity': 'edit'})
    clock.seconds = 6
    parent = call('span_begin', session_id=sid, label='Build')
    clock.seconds = 7
    child = call('span_begin', session_id=sid, label='Compile 日本語', parent_span_id=parent['span_id'])
    clock.seconds = 10
    call('span_end', span_id=child['span_id'])
    clock.seconds = 11
    call('span_end', span_id=parent['span_id'])
    call('transition', session_id=sid, label='verifying')
    call('span_record', session_id=sid, label='Old observation', reported_start='2026-10-22T23:59:55Z',
         reported_end='2026-10-23T00:00:02Z', measured_duration_ms=6500, clock={'kind': 'monotonic'})
    call('note', session_id=sid, text='Latest note: keep the border aligned.\nA second line.', metadata={'kept': [0, False]})
    clock.seconds = 20
    call('end', session_id=sid, outcome='verified', evidence={'capture': 'file.png'})
    clock.seconds = 30
    second = call('begin', label='Research café 日本語', subject={'provider': 'issue', 'ref': 'external'},
                  metadata={'owner': 'Morgan', 'value': 'false'})
    for index in range(extra):
        clock.seconds += 1
        call('begin', label=f'Extra session {index}', metadata={'owner': str(index)})
    return service, clock, service.viewer_snapshot(root), first, second, phase, parent, child


class WorkReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def files(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob('*') if path.is_file()}

    def reader(self):
        reader = WorkReader(self.root, interval=.01)
        self.addCleanup(reader.close)
        return reader

    def test_empty_work_workspace_reads_without_creating_files_or_using_node(self):
        reader = self.reader()
        with patch.dict('os.environ', {'PATH': ''}):
            wait_for(reader, lambda: reader.revision == 1)
        self.assertEqual(reader.snapshot['sessions'], [])
        self.assertEqual(self.files(), {})
        self.assertIsNone(reader.process)

    def test_live_refresh_valid_prefix_errors_and_readonly_bytes(self):
        service, clock, data, first, *_ = fixture(self.root)
        before = self.files()
        reader = self.reader()
        wait_for(reader, lambda: reader.revision == 1)
        self.assertEqual(self.files(), before)
        self.assertEqual(len(reader.snapshot['sessions']), 2)
        service.execute('work_note', self.root, {'session_id': first['session_id'], 'text': 'live', 'request_id': 'live'})
        wait_for(reader, lambda: reader.revision == 2)
        self.assertEqual(reader.snapshot['sessions'][0]['notes'][-1]['text'], 'live')
        log = self.root / '.kanitor/work/events.jsonl'
        with log.open('ab') as stream:
            stream.write(b'{partial')
        wait_for(reader, lambda: reader.revision == 3)
        self.assertEqual(reader.snapshot['warnings'][0]['code'], 'recovery_required')
        good = reader.snapshot
        data = log.read_bytes()
        log.write_bytes(data.replace(b'Adjust', b'Adjuxt', 1))
        wait_for(reader, lambda: bool(reader.error))
        self.assertIs(reader.snapshot, good)
        self.assertEqual(reader.revision, 3)

    def test_read_only_snapshot_is_not_limited_to_one_api_page_or_bulk_subject_lookups(self):
        service = WorkService()
        for index in range(1005):
            service.execute('work_begin', self.root, {'label': str(index), 'request_id': str(index)})
        service.subject_resolver = Mock(side_effect=AssertionError('no bulk lookup'))
        before = self.files()
        snapshot = service.viewer_snapshot(self.root)
        self.assertEqual(len(snapshot['sessions']), 1005)
        self.assertEqual(snapshot['as_of_seq'], 1005)
        self.assertEqual(self.files(), before)

    def test_append_while_snapshot_is_read_does_not_discard_the_committed_prefix(self):
        service, _, data, first, *_ = fixture(self.root)
        reader = self.reader()
        reader._reading = reader.fingerprint()
        service.execute('work_note', self.root, {'session_id': first['session_id'], 'text': 'later', 'request_id': 'append'})
        self.assertTrue(reader.accept(data))
        self.assertNotEqual(reader._signature, reader.fingerprint())

    def test_work_root_discovery_from_a_nested_directory(self):
        fixture(self.root)
        nested = self.root / 'nested/subdir'
        nested.mkdir(parents=True)
        self.assertEqual(find_root(nested), self.root)

    def test_invalid_live_configuration_still_publishes_new_committed_data(self):
        service, _, _, first, *_ = fixture(self.root)
        reader = self.reader()
        wait_for(reader, lambda: reader.revision == 1)
        service.execute('work_note', self.root, {'session_id': first['session_id'], 'text': 'fresh note', 'request_id': 'fresh'})
        (self.root / '.kanitor.json').write_text('{"workTracking":{"sessionColumns":[]}}')
        before = self.files()
        wait_for(reader, lambda: reader.revision == 2)
        self.assertIsNone(reader.snapshot['config'])
        self.assertEqual(reader.snapshot['warnings'][0]['code'], 'invalid_config')
        self.assertEqual(reader.snapshot['sessions'][0]['notes'][-1]['text'], 'fresh note')
        self.assertEqual(self.files(), before)


    def test_stalled_background_reader_times_out_and_can_be_closed_immediately(self):
        reader = self.reader()
        reader.timeout = .02
        with patch.object(reader, 'make_command', return_value=[sys.executable, '-c', 'import time; time.sleep(20)']):
            wait_for(reader, lambda: bool(reader.error))
            self.assertIn('exceeded', reader.error)
            self.assertIsNone(reader.process)
            reader.refresh()
            reader.poll()
            self.assertIsNotNone(reader.process)
            started = time.monotonic()
            reader.close()
            self.assertLess(time.monotonic() - started, 1)

