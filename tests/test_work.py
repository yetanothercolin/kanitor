from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from kanitor.work.common import WorkError, canonical, loads
from kanitor.work.schemas import CONFIG_SCHEMA, EVENT_SCHEMA, INPUT_SCHEMAS
from kanitor.work.service import WorkService
from kanitor.work import store as storage


class Clock:
    def __init__(self):
        self.seconds = 0

    def __call__(self):
        return (datetime(2026, 10, 23, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)).isoformat().replace('+00:00', 'Z')


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.service = WorkService(clock=self.clock)
        self.log = self.root / '.kanitor/work/events.jsonl'
        self.sid = None

    def call(self, name, **arguments):
        if name not in ('read', 'capabilities'):
            arguments.setdefault('request_id', str(uuid.uuid4()))
        if name in ('transition', 'span_begin', 'span_record', 'note', 'end'):
            arguments.setdefault('session_id', self.sid)
        return self.service.execute('work_' + name, self.root, arguments)

    def begin(self, **args):
        receipt = self.call('begin', label='Work', **args)
        self.sid = receipt['session_id']
        return receipt

    def summary(self):
        return self.call('read', view='sessions', session_id=self.sid)['items'][0]

    def configure(self, tracking):
        (self.root / '.kanitor.json').write_text(json.dumps({'workTracking': tracking}))

    def assert_error(self, code, name, **args):
        with self.assertRaises(WorkError) as caught:
            self.call(name, **args)
        self.assertEqual(caught.exception.code, code, caught.exception.message)

    def test_empty_reads_do_not_create_storage_and_no_identity_is_required(self):
        self.assertEqual(self.call('read')['items'], [])
        caps = self.call('capabilities')
        self.assertEqual(caps['release_status'], 'alpha')
        self.assertEqual(caps['tested_environments'], [{'platform': 'macOS', 'python': '3.14'}])
        self.assertEqual(caps['platforms'], ['macOS'])
        self.assertEqual(caps['untested_platforms'], ['Linux'])
        self.assertEqual(len(caps['operations']), 10)
        self.assertEqual(list(self.root.iterdir()), [])
        receipt = self.begin()
        self.assertEqual(receipt['state'], 'open')
        summary = self.summary()
        self.assertEqual(summary['metadata'], {})
        self.assertIsNone(summary['subject'])
        self.assertIsNone(summary['confirmed_session_elapsed_ms'])
        self.assertIsNone(summary['confirmed_unclassified_ms'])

    def test_phases_and_overlapping_spans_have_separate_totals(self):
        self.begin(metadata={'owner': 'Alex'})
        self.clock.seconds = 5
        first = self.call('transition', label='changing', metadata={'activity': 'edit'})
        self.clock.seconds = 6
        one = self.call('span_begin', label='build', metadata={'owner': 'Sam'})
        two = self.call('span_begin', label='test')
        self.clock.seconds = 10
        self.call('transition', label='verifying')
        self.clock.seconds = 11
        self.call('span_end', span_id=one['span_id'])
        self.call('span_end', span_id=two['span_id'])
        self.clock.seconds = 15
        self.call('end', outcome='unsuccessful', evidence={'exit_code': 1})
        summary = self.summary()
        self.assertEqual(summary['confirmed_session_elapsed_ms'], 15000)
        self.assertEqual(summary['confirmed_phase_ms'], 10000)
        self.assertEqual(summary['confirmed_unclassified_ms'], 5000)
        self.assertEqual([s['duration_ms'] for s in summary['spans']], [5000, 5000])
        self.assertEqual(summary['spans'][0]['effective_metadata']['owner'], 'Sam')
        self.assertEqual(summary['spans'][1]['effective_metadata']['owner'], 'Alex')
        self.assertEqual(summary['phases'][0]['id'], first['phase_id'])
        self.assertEqual(summary['state'], 'closed')

    def test_parent_and_session_closure_reject_open_children_without_mutation(self):
        self.begin()
        parent = self.call('span_begin', label='parent')
        child = self.call('span_begin', label='child', parent_span_id=parent['span_id'])
        before = self.log.read_bytes()
        self.assert_error('open_children', 'span_end', span_id=parent['span_id'])
        self.assert_error('open_spans', 'end')
        self.assertEqual(self.log.read_bytes(), before)
        self.assertTrue(all(s['state'] == 'open' for s in self.summary()['spans']))
        self.call('span_end', span_id=child['span_id'])
        self.call('span_end', span_id=parent['span_id'])
        child_end = next(event for event in self.call('read')['items']
                         if event['type'] == 'span.ended' and event['payload']['span_id'] == child['span_id'])
        self.assertEqual(child_end['payload']['parent_span_id'], parent['span_id'])
        self.call('end')
        self.assert_error('closed_session', 'transition', label='later')
        self.assert_error('closed_span', 'span_end', span_id=child['span_id'])

    def test_cross_session_parent_is_rejected(self):
        self.begin()
        parent = self.call('span_begin', label='parent')
        self.begin(request_id='second-session')
        self.assert_error('invalid_parent', 'span_begin', label='child', parent_span_id=parent['span_id'])

    def test_retry_returns_original_receipt_even_after_config_and_lifecycle_changes(self):
        args = {'label': 'Work', 'request_id': 'stable', 'metadata': {'a': 1, 'b': 2}}
        receipt = self.service.execute('work_begin', self.root, args)
        self.sid = receipt['session_id']
        self.call('end')
        self.configure({'metadataSchemas': {'session': {'type': 'object', 'required': ['AGENT']}}})
        reordered = {'request_id': 'stable', 'metadata': {'b': 2, 'a': 1}, 'label': 'Work'}
        self.assertEqual(self.service.execute('work_begin', self.root, reordered), receipt)
        (self.root / '.kanitor.json').write_text('{bad')
        self.assertEqual(WorkService().execute('work_begin', self.root, args), receipt)
        self.assertEqual(len(self.log.read_text().splitlines()), 2)
        self.assert_error('request_conflict', 'begin', label='Different', request_id='stable')

    def test_local_metadata_requirements_history_and_outcome_evidence(self):
        self.configure({'metadataSchemas': {
            'session': {'type': 'object', 'required': ['AGENT'], 'properties': {'AGENT': {'type': 'string', 'minLength': 1}}},
            'phase': {'type': 'object', 'required': ['ACTIVITY']}},
            'outcomes': {'verified': {'label': 'Producer reports verification', 'requiresEvidence': True}}})
        self.assert_error('validation_error', 'begin', label='No identity')
        self.assertFalse(self.log.exists())
        self.begin(metadata={'AGENT': '!A', 'literal.dot': {'anything': [0, False, None]}})
        self.assert_error('validation_error', 'transition', label='editing')
        self.call('transition', label='editing', metadata={'ACTIVITY': 'changing'})
        self.assert_error('evidence_required', 'end', outcome='verified')
        self.call('end', outcome='verified', evidence={'screenshot': 'local/path.png'})
        self.assertEqual(self.summary()['outcome_label'], 'Producer reports verification')
        self.configure({'metadataSchemas': {'session': {'type': 'object', 'required': ['NEW']}}})
        summary = self.summary()
        self.assertEqual(summary['metadata']['AGENT'], '!A')
        self.assertIn('configuration_mismatch', [w['code'] for w in summary['warnings']])
        self.assertEqual(self.call('read')['items'][0]['payload']['metadata']['literal.dot'], {'anything': [0, False, None]})

    def test_config_example_reconstructs_repeated_phases_and_scopes(self):
        configuration = loads((Path(__file__).parents[1] / 'examples/work-tracking.json').read_bytes())
        (self.root / '.kanitor.json').write_text(canonical(configuration))
        ids = []
        for index, scope in enumerate(('polish', 'polish', 'integrated-behavior')):
            self.begin(subject={'provider': 'issue', 'ref': 'spacing' if scope == 'polish' else 'feature'},
                       metadata={'AGENT': '!A', 'SCOPE': scope, 'FRAMEWORK': 'godot', 'unknown': {'kept': True}})
            ids.append(self.sid)
            for cycle in range(2 if index == 0 else 1):
                self.clock.seconds += 1
                self.call('transition', label='changing', metadata={'ACTIVITY': 'changing'})
                self.clock.seconds += 1
                self.call('transition', label='verifying', metadata={'ACTIVITY': 'verifying'})
                self.call('note', text='clips' if cycle == 0 and index == 0 else 'looks correct')
            self.clock.seconds += 1
            self.call('end', outcome='verified', evidence={'capture': f'iteration-{index}.png'})
        result = self.call('read', view='sessions')
        self.assertEqual([item['id'] for item in result['items']], ids)
        self.assertEqual([len(item['phases']) for item in result['items']], [4, 2, 2])
        self.assertEqual([item['metadata']['SCOPE'] for item in result['items']], ['polish', 'polish', 'integrated-behavior'])
        self.assertTrue(all(item['metadata']['unknown'] == {'kept': True} for item in result['items']))
        self.assertEqual(len({item['subject']['ref'] for item in result['items']}), 2)

    def test_bad_config_blocks_writes_but_not_raw_export(self):
        self.begin()
        (self.root / '.kanitor.json').write_text('{bad')
        self.assert_error('invalid_config', 'note', text='new')
        result = self.call('read')
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['warnings'][0]['code'], 'invalid_config')

    def test_view_errors_and_unknown_display_keys_do_not_block_work_or_policy(self):
        from kanitor.config import ConfigError
        from kanitor.config_file import load_document
        policy = {'metadataSchemas': {'session': {'type': 'object', 'required': ['owner']}},
                  'outcomes': {'verified': {'requiresEvidence': True}}}
        for view in ({'activityColumns': [{'title': 'Bad', 'field': 'future-field'}]},
                     {'columns': []}, {'keybindings': {'quit': ['down']}},
                     {'futureViewerSetting': True}, {'projects': 42}):
            with self.subTest(view=view):
                (self.root / '.kanitor.json').write_text(json.dumps(dict(view, workTracking=policy)))
                with self.assertRaises(ConfigError):
                    load_document(self.root)
                self.assert_error('validation_error', 'begin', label='Needs owner')
                self.begin(metadata={'owner': 'Alex'})
                self.call('transition', label='changing')
                span = self.call('span_begin', label='test')
                self.call('note', text='recorded despite view error')
                self.call('span_end', span_id=span['span_id'])
                self.assert_error('evidence_required', 'end', outcome='verified')
                self.call('end', outcome='verified', evidence='checks passed')
                self.assertEqual(self.summary()['state'], 'closed')
                self.assertEqual(self.call('capabilities')['metadata_schemas'], policy['metadataSchemas'])

    def test_invalid_legacy_session_layout_does_not_disable_recording_policy(self):
        self.configure({'sessionColumns': [],
                        'metadataSchemas': {'session': {'type': 'object', 'required': ['owner']}}})
        self.assert_error('validation_error', 'begin', label='Needs owner')
        self.begin(metadata={'owner': 'Alex'})
        self.call('end')
        self.assertIsNone(self.call('capabilities')['session_columns'])
        self.assertEqual(self.summary()['state'], 'closed')
        self.assertEqual(self.call('read')['warnings'][0]['code'], 'invalid_config')

    def test_schemas_are_local_only_and_packaged_schema_is_current(self):
        self.configure({'metadataSchemas': {'session': {'$ref': 'https://example.com/schema'}}})
        self.assert_error('invalid_config', 'begin', label='No network')
        artifact = loads((Path(__file__).parents[1] / 'kanitor/work/schema-v1.json').read_bytes())
        self.assertEqual(artifact['operations'], INPUT_SCHEMAS)
        self.assertEqual(artifact['configuration'], CONFIG_SCHEMA)
        self.assertEqual(artifact['event'], EVENT_SCHEMA)

    def test_unresolvable_local_schema_is_a_structured_error_without_commit(self):
        self.configure({'metadataSchemas': {'session': {'$ref': '#/$defs/absent'}}})
        self.assert_error('invalid_schema', 'begin', label='bad schema')
        self.assertFalse(self.log.exists())

    def test_schema_literal_ref_keys_and_boolean_schemas_are_supported_without_fetching(self):
        self.configure({'metadataSchemas': {'session': {'type': 'object',
            'properties': {'$ref': {'type': 'string'}, 'literal': {'const': {'$ref': 'https://example.com/data'}}},
            'required': ['$ref', 'literal']}}})
        self.begin(metadata={'$ref': 'ordinary data', 'literal': {'$ref': 'https://example.com/data'}})
        self.assertEqual(self.summary()['metadata']['$ref'], 'ordinary data')
        self.configure({'metadataSchemas': {'session': False}})
        self.assert_error('validation_error', 'begin', label='disabled by local schema')
        self.assertIn('configuration_mismatch', [warning['code'] for warning in self.summary()['warnings']])

    def test_notes_after_close_and_late_spans_preserve_timing_provenance(self):
        self.begin()
        self.clock.seconds = 10
        self.call('end')
        self.call('note', text='An observation', metadata={'unknown': False})
        span = self.call('span_record', label='retrospective', reported_start='2026-10-22T23:59:59Z',
                         reported_end='2026-10-23T00:00:20Z', measured_duration_ms=20500,
                         clock={'kind': 'monotonic', 'source': 'wrapper'})
        summary = self.summary()
        self.assertEqual(summary['state'], 'closed')
        self.assertEqual(summary['confirmed_session_elapsed_ms'], 10000)
        self.assertEqual(summary['confirmed_phase_ms'], 0)
        self.assertEqual(summary['spans'][0]['duration_ms'], 20500)
        self.assertEqual(summary['spans'][0]['timestamp_duration_ms'], 21000)
        self.assertEqual(summary['spans'][0]['duration_source'], 'producer_reported')
        self.assertEqual(summary['spans'][0]['duration_difference_ms'], -500)
        self.assertEqual(summary['spans'][0]['id'], span['span_id'])
        self.assertTrue({'outside_session', 'duration_difference'} <= {w['code'] for w in summary['warnings']})

    def test_clock_rollback_and_unfinished_intervals_are_not_normalized(self):
        self.clock.seconds = 10
        self.begin()
        self.call('transition', label='open phase')
        self.clock.seconds = 5
        self.call('end')
        summary = self.summary()
        self.assertIsNone(summary['duration_ms'])
        self.assertIsNone(summary['phases'][0]['duration_ms'])
        self.assertEqual(summary['confirmed_phase_ms'], 0)
        self.assertIn('clock_discontinuity', [w['code'] for w in summary['warnings']])

    def test_reported_timestamps_are_validated_without_optional_format_dependencies(self):
        self.begin()
        before = self.log.read_bytes()
        for start in ('not-a-date', '2026-02-30T00:00:00Z', '2026-10-23T00:00:00', '2026-10-23'):
            self.assert_error('validation_error', 'span_record', label='invalid timestamp',
                              reported_start=start, reported_end='2026-10-23T00:00:01Z')
        self.assertEqual(self.log.read_bytes(), before)
        self.call('span_record', label='offset', reported_start='2026-10-23T01:00:00+01:00',
                  reported_end='2026-10-23t00:00:01z')
        self.assertEqual(self.summary()['spans'][0]['duration_ms'], 1000)

    def test_amendments_are_revision_checked_and_rebind_without_rewriting_context(self):
        first = self.begin(subject={'provider': 'issue', 'ref': 'old'}, metadata={'owner': 'Alex'})
        original = self.log.read_bytes()
        self.assert_error('stale_revision', 'amend', target={'kind': 'session', 'id': self.sid},
                          expected_revision=2, correction={'label': 'Corrected'}, reason='mistake')
        self.call('amend', target={'kind': 'session', 'id': self.sid}, expected_revision=first['revision'],
                  correction={'label': 'Corrected', 'subject': {'provider': 'issue', 'ref': 'new'}}, reason='renamed')
        self.assertTrue(self.log.read_bytes().startswith(original))
        summary = self.summary()
        self.assertEqual(summary['original_subject']['ref'], 'old')
        self.assertEqual(summary['subject']['ref'], 'new')
        self.assertEqual(summary['metadata'], {'owner': 'Alex'})
        self.assertEqual(summary['amendments'][0]['reason'], 'renamed')
        self.assertEqual(self.call('read', subject={'provider': 'issue', 'ref': 'old'})['items'], [])
        self.assertEqual(len(self.call('read', subject={'provider': 'issue', 'ref': 'new'})['items']), 2)

    def test_phase_timing_correction_moves_shared_boundary_and_rejects_overlap(self):
        self.begin()
        self.clock.seconds = 5
        one = self.call('transition', label='changing')
        self.clock.seconds = 10
        two = self.call('transition', label='verifying')
        self.clock.seconds = 15
        end = self.call('end')
        self.call('amend', target={'kind': 'phase', 'id': two['phase_id']}, expected_revision=end['revision'],
                  correction={'started_at': '2026-10-23T00:00:12Z'}, reason='late transition call')
        summary = self.summary()
        self.assertEqual([p['duration_ms'] for p in summary['phases']], [7000, 3000])
        self.assertEqual(summary['phases'][0]['ended_at'], summary['phases'][1]['started_at'])
        self.assertEqual(summary['phases'][1]['start_source'], 'producer_correction')
        original = next(e for e in self.call('read')['items'] if e['event_id'] == two['event_id'])
        self.assertEqual(original['recorded_at'], '2026-10-23T00:00:10.000000Z')
        before = self.log.read_bytes()
        self.assert_error('invalid_timing', 'amend', target={'kind': 'phase', 'id': one['phase_id']},
                          expected_revision=summary['revision'], correction={'started_at': '2026-10-23T00:00:13Z'}, reason='invalid')
        self.assertEqual(self.log.read_bytes(), before)
        self.assertEqual(self.summary()['phases'][0]['started_at'], '2026-10-23T00:00:05.000000Z')

    def test_span_timing_measurement_and_note_corrections_are_audited(self):
        self.begin()
        span = self.call('span_record', label='test', reported_start='2026-10-23T00:00:01Z',
                         reported_end='2026-10-23T00:00:03Z', measured_duration_ms=2000, clock={'kind': 'monotonic'})
        amendment = self.call('amend', target={'kind': 'span', 'id': span['span_id']}, expected_revision=span['revision'],
                              correction={'ended_at': '2026-10-23T00:00:04Z', 'measured_duration_ms': 3000}, reason='corrected wrapper data')
        note = self.call('note', text='typo')
        self.call('amend', target={'kind': 'event', 'id': note['note_id']}, expected_revision=note['revision'],
                  correction={'text': 'corrected'}, reason='typo')
        summary = self.summary()
        self.assertEqual(summary['spans'][0]['duration_ms'], 3000)
        self.assertEqual(summary['spans'][0]['duration_source'], 'producer_correction')
        self.assertEqual(summary['spans'][0]['clock'], {'kind': 'monotonic'})
        self.assertEqual(summary['notes'][0]['text'], 'corrected')
        self.assertEqual(len(summary['amendments']), 2)

    def test_interrupt_cascades_with_unknown_ends_and_keeps_confirmed_phases(self):
        self.begin()
        self.call('transition', label='first')
        self.clock.seconds = 5
        self.call('transition', label='unfinished')
        parent = self.call('span_begin', label='parent')
        child = self.call('span_begin', label='child', parent_span_id=parent['span_id'])
        self.clock.seconds = 20
        self.call('amend', target={'kind': 'session', 'id': self.sid}, expected_revision=child['revision'],
                  correction={'state': 'interrupted'}, reason='producer abandoned')
        summary = self.summary()
        self.assertEqual(summary['state'], 'interrupted')
        self.assertIsNone(summary['confirmed_session_elapsed_ms'])
        self.assertEqual(summary['confirmed_phase_ms'], 5000)
        self.assertTrue(all(s['state'] == 'interrupted' and s['duration_ms'] is None for s in summary['spans']))
        self.assertIsNone(summary['phases'][-1]['duration_ms'])

    def test_timing_correction_cannot_close_open_work_or_change_provenance(self):
        first = self.begin()
        self.assert_error('invalid_correction', 'amend', target={'kind': 'session', 'id': self.sid},
                          expected_revision=first['revision'], correction={'ended_at': self.clock()}, reason='must use end')
        self.assert_error('validation_error', 'amend', target={'kind': 'session', 'id': self.sid},
                          expected_revision=first['revision'], correction={'start_source': 'observed'}, reason='not allowed')

    def test_event_and_summary_pagination_freezes_snapshot(self):
        first = self.begin()
        self.call('note', text='one')
        second = self.call('begin', label='second')
        page = self.call('read', limit=1)
        self.assertTrue(page['has_more'])
        self.call('note', text='new')
        rest = self.call('read', after_seq=page['next_after_seq'], as_of_seq=page['as_of_seq'])
        self.assertEqual([event['seq'] for event in rest['items']], [2, 3])
        sessions = self.call('read', view='sessions', limit=1, as_of_seq=3)
        next_page = self.call('read', view='sessions', after_seq=sessions['next_after_seq'], as_of_seq=3)
        self.assertEqual(sessions['items'][0]['id'], first['session_id'])
        self.assertEqual(next_page['items'][0]['id'], second['session_id'])
        self.assert_error('invalid_cursor', 'read', as_of_seq=100)

    def test_truncated_tail_read_prefix_retry_recovery_and_request_conflicts(self):
        original = self.begin(request_id='original')
        committed = self.log.read_bytes()
        with self.log.open('ab') as stream:
            stream.write(b'{"unfinished":')
        self.assertEqual(self.call('read')['warnings'][0]['code'], 'recovery_required')
        self.assertEqual(self.call('begin', label='Work', request_id='original'), original)
        self.assert_error('recovery_required', 'note', text='blocked')
        recovered = self.call('recover', request_id='recovery', reason='interrupted append')
        self.assertEqual(self.log.read_bytes(), committed)
        self.assertEqual(Path(recovered['backup']).read_bytes(), committed + b'{"unfinished":')
        self.assertEqual(self.call('recover', request_id='recovery', reason='interrupted append'), recovered)
        self.assert_error('request_conflict', 'recover', request_id='recovery', reason='changed')
        self.assert_error('request_conflict', 'note', text='wrong request domain', request_id='recovery')
        self.call('note', text='works')

    def test_recovery_restarts_after_log_replacement_and_preserves_new_appends(self):
        self.begin()
        with self.log.open('ab') as stream:
            stream.write(b'{partial')
        original_atomic = storage.atomic_write
        def crash_after_replacement(path, data):
            original_atomic(path, data)
            if path.resolve() == self.log.resolve():
                raise OSError('crash after replacement')
        with patch.object(storage, 'atomic_write', side_effect=crash_after_replacement):
            self.assert_error('storage_error', 'recover', request_id='repair', reason='partial')
        fresh = WorkService(clock=self.clock)
        fresh.execute('work_note', self.root, {'session_id': self.sid, 'text': 'after replacement', 'request_id': 'new'})
        receipt = fresh.execute('work_recover', self.root, {'request_id': 'repair', 'reason': 'partial'})
        self.assertEqual(receipt['state'], 'recovered')
        self.assertEqual(len(self.call('read')['items']), 2)

    def test_full_record_fsync_failure_is_retryable_exactly_once(self):
        self.begin()
        args = {'session_id': self.sid, 'text': 'once', 'request_id': 'failed-sync'}
        with patch.object(storage.os, 'fsync', side_effect=[OSError('sync failed'), None, None]):
            with self.assertRaises(WorkError):
                self.service.execute('work_note', self.root, args)
            receipt = WorkService(clock=self.clock).execute('work_note', self.root, args)
        self.assertEqual(receipt['seq'], 2)
        self.assertEqual(len(self.call('read')['items']), 2)

    def test_partial_write_failure_requires_recovery_before_retry(self):
        self.begin()
        original_write = storage.write_all
        def partial(fd, data):
            os.write(fd, data[:10])
            raise OSError('partial write')
        args = {'session_id': self.sid, 'text': 'once', 'request_id': 'partial'}
        with patch.object(storage, 'write_all', side_effect=partial), self.assertRaises(WorkError):
            self.service.execute('work_note', self.root, args)
        self.assert_error('recovery_required', 'note', **args)
        self.call('recover', reason='partial writer')
        self.assertEqual(self.service.execute('work_note', self.root, args)['seq'], 2)

    def test_corruption_and_unsupported_versions_are_not_skipped_even_with_warm_cache(self):
        self.begin()
        original = self.log.read_bytes()
        self.log.write_bytes(original.replace(b'Work', b'Wark', 1))
        self.assert_error('corrupt_log', 'read')
        self.assert_error('corrupt_log', 'recover', reason='not a tail')
        event = loads(original)
        event['schema_version'] = 999
        self.log.write_text(canonical(event) + '\n')
        self.assert_error('incompatible_version', 'read')

    def test_input_rejects_non_json_numbers_unknown_fields_and_duplicate_keys(self):
        self.assert_error('invalid_json', 'begin', label='bad', metadata={'number': float('nan')})
        self.assert_error('validation_error', 'begin', label='bad', agent='implicit identity')
        self.assert_error('invalid_json', 'begin', label='bad', metadata={1: 'not a JSON key'})
        with self.assertRaises(WorkError):
            loads('{"label":"one","label":"two"}')
        self.assertFalse(self.log.exists())

    def test_multiple_processes_preserve_all_requests_and_shared_retries(self):
        self.begin()
        script = '''import json,sys
from kanitor.work.service import WorkService
s=WorkService()
root,sid,prefix=sys.argv[1:]
receipts=[]
for i in range(12):
 receipts.append(s.execute('work_note',root,{'session_id':sid,'text':'note','request_id':prefix+str(i)})['seq'])
receipts.append(s.execute('work_note',root,{'session_id':sid,'text':'shared','request_id':'shared'})['seq'])
print(json.dumps(receipts))
'''
        processes = [subprocess.Popen([sys.executable, '-c', script, str(self.root), self.sid, f'p{i}-'],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(4)]
        shared = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr)
            shared.append(json.loads(stdout)[-1])
        self.assertEqual(len(set(shared)), 1)
        events = self.call('read')['items']
        self.assertEqual(len(events), 50)
        self.assertEqual([event['seq'] for event in events], list(range(1, 51)))
        self.assertEqual(self.summary()['revision'], 50)
