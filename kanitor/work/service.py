"""Shared public work operations. Adapters do not implement lifecycle semantics."""
from copy import deepcopy
from pathlib import Path
import subprocess
import threading
import uuid

from .common import WorkError, canonical, loads, timestamp, utc_now
from .config import load_config, metadata, outcome
from .schemas import (CONFIG_SCHEMA, EVENT_SCHEMA, INPUT_SCHEMAS, OPERATIONS, READ_ONLY,
                      SCHEMA_VERSION, validate)
from .state import EVENT_OPERATIONS, State, require, summarize
from .store import Store, digest

OPERATION_EVENTS = {operation: event for event, operation in EVENT_OPERATIONS.items()}


def resolve_subject(root, subject):
    if subject is None:
        return {'state': 'none'}
    if subject['provider'] != 'kanbn':
        return {'state': 'unverified', 'provider': subject['provider']}
    try:
        result = subprocess.run(['node', str(Path(__file__).with_name('subject.cjs')), str(root), subject['ref']],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise WorkError('subject_provider_error', result.stderr.strip() or 'Kanbn subject lookup failed')
        return loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WorkError('subject_provider_error', str(error)) from error


class WorkService:
    def __init__(self, clock=utc_now, subject_resolver=resolve_subject):
        self.clock = clock
        self.subject_resolver = subject_resolver
        self._stores = {}
        self._states = {}
        self._mutex = threading.Lock()

    def execute(self, operation, workspace, arguments=None):
        if operation not in INPUT_SCHEMAS:
            raise WorkError('unknown_operation', f'Unknown operation: {operation}')
        arguments = loads(canonical(arguments if arguments is not None else {}))
        validate(arguments, INPUT_SCHEMAS[operation])
        if not isinstance(workspace, (str, Path)) or not str(workspace).strip():
            raise WorkError('invalid_workspace', 'An explicit workspace root is required')
        try:
            root = Path(workspace).expanduser().resolve()
            with self._mutex:
                store = self._stores.setdefault(root, Store(root))
            with store.locked(write=operation not in READ_ONLY):
                events = store.load()
                if operation == 'work_recover':
                    return deepcopy(store.recover(arguments))
                if operation not in READ_ONLY:
                    request = {'operation': operation, 'arguments': arguments}
                    receipt = store.retry(request)
                    if receipt is not None:
                        return deepcopy(receipt)
                    recovery_manifest = store.folder / 'recovery' / f'{digest(arguments["request_id"].encode())}.json'
                    require(not recovery_manifest.exists(), 'request_conflict', 'Request ID belongs to a recovery operation')
                    require(not store.tail, 'recovery_required', 'Incomplete final record; run kanitor work recover')
                state = self._state(store)
                if operation == 'work_read':
                    return self._read(store, state, arguments)
                config = load_config(root, recording=True)
                if operation == 'work_capabilities':
                    return self._capabilities(store, config)
                event, trial = self._prepare(state, operation, arguments, config, root, len(events) + 1)
                store.append(event)
                self._states[root] = (store.generation, len(store.events), trial)
                return deepcopy(event['receipt'])
        except OSError as error:
            raise WorkError('storage_error', str(error)) from error

    def _state(self, store):
        generation, count, state = self._states.get(store.root, (store.generation, 0, State()))
        if generation != store.generation or count > len(store.events):
            state, count = State(), 0
        try:
            for event in store.events[count:]:
                state.apply(event)
        except (WorkError, KeyError, TypeError, StopIteration) as error:
            self._states.pop(store.root, None)
            raise WorkError('corrupt_log', f'Cannot replay event {event["seq"]}: {error}') from error
        self._states[store.root] = (store.generation, len(store.events), state)
        return state

    def _capabilities(self, store, config):
        return deepcopy({'schema_versions': [SCHEMA_VERSION], 'workspace': str(store.root),
            'operations': list(OPERATIONS), 'input_schemas': {name: INPUT_SCHEMAS[name] for name in OPERATIONS},
            'cli_maintenance_schemas': {'work_recover': INPUT_SCHEMAS['work_recover']},
            'configuration_schema': CONFIG_SCHEMA, 'event_schema': EVENT_SCHEMA,
            'metadata_schemas': config.get('metadataSchemas', {}), 'outcomes': config.get('outcomes', {}),
            'session_columns': config.get('sessionColumns'),
            'storage': '.kanitor/work/events.jsonl', 'platforms': ['macOS'],
            'release_status': 'alpha', 'tested_environments': [{'platform': 'macOS', 'python': '3.14'}],
            'untested_platforms': ['Linux'],
            'subject_providers': {'kanbn': 'native active/archive lookup', 'other': 'opaque, unverified'},
            'read_defaults': {'view': 'events', 'after_seq': 0, 'limit': 100, 'maximum_limit': 1000},
            'cursor_fields': {'events': 'seq', 'sessions': 'created_seq'},
            'recovery_required': bool(store.tail)})

    def viewer_snapshot(self, workspace):
        """One read-only committed prefix, without per-row provider lookups."""
        root = Path(workspace).expanduser().resolve()
        with self._mutex:
            store = self._stores.setdefault(root, Store(root))
        try:
            with store.locked():
                store.load()
                state = self._state(store)
                warnings = ([{'code': 'recovery_required', 'message': 'Incomplete final record ignored; CLI recovery is required before new writes'}]
                            if store.tail else [])
                try:
                    config = load_config(root)
                except WorkError as error:
                    config = None
                    warnings.append({'code': 'invalid_config', 'message': error.message})
                return {'readOnly': True, 'as_of_seq': len(store.events), 'config': config, 'warnings': warnings,
                        'sessions': [summarize(session, config) for session in state.sessions.values()],
                        'events': deepcopy(store.events)}
        except OSError as error:
            raise WorkError('storage_error', str(error)) from error

    def _prepare(self, state, operation, args, config, root, seq):
        payload = {key: deepcopy(value) for key, value in args.items() if key != 'request_id'}
        if operation == 'work_begin':
            sid = str(uuid.uuid4())
        elif operation in ('work_span_end',):
            sid = state.span(args['span_id'])['session_id']
        elif operation == 'work_amend':
            sid = state.target(args['target'])[0]['id']
        else:
            sid = args['session_id']
        if operation in ('work_begin', 'work_transition', 'work_span_begin', 'work_span_record', 'work_note'):
            kind = {'work_begin': 'session', 'work_transition': 'phase', 'work_note': 'note'}.get(operation, 'span')
            metadata(config, kind, payload.get('metadata', {}))
        if operation in ('work_end', 'work_span_end', 'work_span_record'):
            outcome(config, payload.get('outcome'), payload.get('evidence'))
        subject = args.get('subject') if operation == 'work_begin' else None
        if operation == 'work_amend' and 'subject' in args['correction']:
            subject = args['correction']['subject']
        if subject is not None:
            resolution = self.subject_resolver(root, subject)
            require(resolution['state'] != 'unresolved', 'unknown_subject', f'Subject does not exist: {subject["ref"]}')
        if operation in ('work_span_begin', 'work_span_record'):
            payload['span_id'] = str(uuid.uuid4())
            payload.setdefault('parent_span_id', None)
        elif operation == 'work_span_end':
            payload['parent_span_id'] = state.span(args['span_id'])['parent_span_id']
        now = timestamp(self.clock()).isoformat(timespec='microseconds').replace('+00:00', 'Z')
        event = {'schema_version': SCHEMA_VERSION, 'event_id': str(uuid.uuid4()), 'seq': seq,
                 'session_id': sid, 'type': OPERATION_EVENTS[operation], 'recorded_at': now,
                 'request_id': args['request_id'], 'request': {'operation': operation, 'arguments': deepcopy(args)},
                 'payload': payload, 'revision': state.sessions[sid]['revision'] + 1 if sid in state.sessions else 1}
        trial = State()
        trial.sessions, trial.spans, trial.events = dict(state.sessions), dict(state.spans), dict(state.events)
        if sid in state.sessions:
            source = state.sessions[sid]
            # Entity edits replace values rather than mutating nested metadata.
            # Copy the mutable entity containers, retaining immutable historical values.
            copied = {**source, 'phases': [dict(phase) for phase in source['phases']],
                      'spans': {key: dict(span) for key, span in source['spans'].items()},
                      'notes': [dict(note) for note in source['notes']],
                      'amendments': list(source['amendments'])}
            trial.sessions[sid] = copied
            trial.spans.update(copied['spans'])
        changed = trial.apply(event)
        if operation == 'work_amend':
            _, target, kind = trial.target(args['target'])
            correction = args['correction']
            if 'metadata' in correction:
                metadata(config, kind, target['metadata'])
            if set(correction) & {'outcome', 'evidence'}:
                outcome(config, target.get('outcome'), target.get('evidence'))
        receipt = {'event_id': event['event_id'], 'request_id': args['request_id'], 'seq': seq,
                   'session_id': sid, 'recorded_at': now, 'revision': event['revision'], 'state': changed['state']}
        if 'span_id' in payload:
            receipt.update(span_id=payload['span_id'], state=trial.span(payload['span_id'])['state'])
        if operation == 'work_transition':
            receipt['phase_id'] = event['event_id']
        if operation == 'work_note':
            receipt['note_id'] = event['event_id']
        if operation == 'work_amend':
            _, target, _ = trial.target(args['target'])
            receipt['state'] = target.get('state', changed['state'])
        event['receipt'] = receipt
        return event, trial

    def _read(self, store, state, args):
        through = args.get('as_of_seq', len(store.events))
        require(through <= len(store.events), 'invalid_cursor', 'Snapshot sequence exceeds the log')
        if through < len(store.events):
            state = State()
            for event in store.events[:through]:
                state.apply(event)
        after, limit = args.get('after_seq', 0), args.get('limit', 100)
        if args.get('session_id'):
            state.session(args['session_id'])
        sessions = [session for session in state.sessions.values()
                    if (not args.get('session_id') or session['id'] == args['session_id'])
                    and (not args.get('subject') or session['subject'] == args['subject'])]
        selected = {session['id'] for session in sessions}
        view = args.get('view', 'events')
        warnings = ([{'code': 'recovery_required', 'message': 'Incomplete final record excluded from committed prefix'}]
                    if store.tail else [])
        try:
            config = load_config(store.root)
        except WorkError as error:
            config = {}
            warnings.append({'code': 'invalid_config', 'message': error.message})
        if view == 'events':
            matches = [event for event in store.events[:through] if event['seq'] > after and event['session_id'] in selected]
            items = deepcopy(matches[:limit])
            cursor = items[-1]['seq'] if items else after
        else:
            matches = sorted((session for session in sessions if session['created_seq'] > after), key=lambda s: s['created_seq'])
            items = [summarize(session, config) for session in matches[:limit]]
            resolution_cache = {}
            for item in items:
                subject = item['subject']
                key = canonical(subject)
                if key not in resolution_cache:
                    try:
                        resolution_cache[key] = self.subject_resolver(store.root, subject)
                    except WorkError as error:
                        resolution_cache[key] = {'state': 'unavailable', 'message': error.message}
                item['subject_resolution'] = deepcopy(resolution_cache[key])
                if item['subject_resolution']['state'] in ('unresolved', 'unavailable'):
                    item['warnings'].append({'code': 'unresolved_subject', 'entity_id': item['id'],
                                             'message': 'Historical subject is missing or its provider is unavailable'})
            cursor = items[-1]['created_seq'] if items else after
        return {'view': view, 'items': items, 'as_of_seq': through,
                'next_after_seq': cursor, 'has_more': len(matches) > limit, 'warnings': warnings}
