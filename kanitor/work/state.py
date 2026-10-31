"""Deterministic replay and derived timing. No filesystem or adapter dependencies."""
from copy import deepcopy

from .common import WorkError, elapsed, timestamp

EVENT_OPERATIONS = {
    'session.begun': 'work_begin', 'phase.transitioned': 'work_transition',
    'span.begun': 'work_span_begin', 'span.ended': 'work_span_end',
    'span.recorded': 'work_span_record', 'note.added': 'work_note',
    'session.ended': 'work_end', 'work.amended': 'work_amend',
}


def require(condition, code, message):
    if not condition:
        raise WorkError(code, message)


def interval(identity, label, metadata, start, source, **extra):
    return {'id': identity, 'label': label, 'metadata': deepcopy(metadata), 'state': 'open',
            'started_at': start, 'ended_at': None, 'start_source': source, 'end_source': None, **extra}


class State:
    def __init__(self):
        self.sessions = {}
        self.spans = {}
        self.events = {}

    def session(self, identity):
        require(identity in self.sessions, 'unknown_session', f'Unknown session: {identity}')
        return self.sessions[identity]

    def span(self, identity):
        require(identity in self.spans, 'unknown_span', f'Unknown span: {identity}')
        return self.spans[identity]

    def target(self, target):
        kind, identity = target['kind'], target['id']
        if kind == 'session':
            session = self.session(identity)
            return session, session, kind
        if kind == 'span':
            span = self.span(identity)
            return self.session(span['session_id']), span, kind
        event = self.events.get(identity)
        require(event is not None, 'unknown_target', f'Unknown amendment target: {identity}')
        session = self.session(event['session_id'])
        if event['type'] == 'phase.transitioned' and kind in ('event', 'phase'):
            return session, next(phase for phase in session['phases'] if phase['id'] == identity), 'phase'
        if event['type'] == 'note.added' and kind in ('event', 'note'):
            return session, next(note for note in session['notes'] if note['id'] == identity), 'note'
        raise WorkError('invalid_target', 'Event amendments target phase transitions or notes; use session/span IDs otherwise')

    def apply(self, event):
        p, kind, at = event['payload'], event['type'], event['recorded_at']
        sid = event['session_id']
        require(EVENT_OPERATIONS.get(kind) == event['request']['operation'], 'corrupt_log', 'Operation/event type mismatch')
        if kind == 'session.begun':
            require(sid not in self.sessions and event['revision'] == 1, 'corrupt_log', 'Duplicate session or invalid initial revision')
            session = interval(sid, p['label'], p.get('metadata', {}), at, 'server_recorded',
                               revision=0, created_seq=event['seq'], subject=deepcopy(p.get('subject')),
                               original_subject=deepcopy(p.get('subject')), phases=[], spans={}, notes=[], amendments=[])
            self.sessions[sid] = session
        else:
            session = self.session(sid)
        require(event['revision'] == session['revision'] + 1, 'corrupt_log', 'Nonconsecutive session revision')
        if kind == 'phase.transitioned':
            require(session['state'] == 'open', 'closed_session', 'Cannot transition a finished session')
            if session['phases']:
                previous = session['phases'][-1]
                previous.update(ended_at=at, end_source='server_recorded', state='closed')
            session['phases'].append(interval(event['event_id'], p['label'], p.get('metadata', {}), at,
                                             'server_recorded', note=p.get('note')))
        elif kind in ('span.begun', 'span.recorded'):
            if kind == 'span.begun':
                require(session['state'] == 'open', 'closed_session', 'Cannot start a span in a finished session')
            parent_id = p.get('parent_span_id')
            if parent_id:
                parent = self.span(parent_id)
                require(parent['session_id'] == sid, 'invalid_parent', 'Parent span belongs to another session')
                if kind == 'span.begun':
                    require(parent['state'] == 'open', 'invalid_parent', 'Parent span must be open')
            identity = p['span_id']
            require(identity not in self.spans, 'corrupt_log', 'Duplicate span ID')
            recorded = kind == 'span.recorded'
            span = interval(identity, p['label'], p.get('metadata', {}), p['reported_start'] if recorded else at,
                            'producer_reported' if recorded else 'server_recorded',
                            session_id=sid, parent_span_id=parent_id, clock=deepcopy(p.get('clock')),
                            measured_duration_ms=p.get('measured_duration_ms'))
            if recorded:
                span.update(state='closed', ended_at=p['reported_end'], end_source='producer_reported',
                            outcome=p.get('outcome'), evidence=deepcopy(p.get('evidence')))
            session['spans'][identity] = self.spans[identity] = span
        elif kind == 'span.ended':
            span = self.span(p['span_id'])
            require(span['session_id'] == sid, 'invalid_parent', 'Span belongs to another session')
            require(span['state'] == 'open', 'closed_span', 'Span is already finished')
            require(not any(s['parent_span_id'] == span['id'] and s['state'] == 'open'
                            for s in session['spans'].values()), 'open_children', 'Close or interrupt child spans first')
            span.update(state='closed', ended_at=at, end_source='server_recorded',
                        outcome=p.get('outcome'), evidence=deepcopy(p.get('evidence')))
        elif kind == 'session.ended':
            require(session['state'] == 'open', 'closed_session', 'Session is already finished')
            require(not any(span['state'] == 'open' for span in session['spans'].values()),
                    'open_spans', 'Close or interrupt operation spans before ending the session')
            session.update(state='closed', ended_at=at, end_source='server_recorded',
                           outcome=p.get('outcome'), evidence=deepcopy(p.get('evidence')))
            if session['phases']:
                session['phases'][-1].update(state='closed', ended_at=at, end_source='server_recorded')
        elif kind == 'note.added':
            if p.get('span_id'):
                require(self.span(p['span_id'])['session_id'] == sid, 'invalid_parent', 'Note span belongs to another session')
            session['notes'].append({'id': event['event_id'], 'text': p['text'],
                                     'metadata': deepcopy(p.get('metadata', {})), 'span_id': p.get('span_id'),
                                     'recorded_at': at})
        elif kind == 'work.amended':
            target_session, target, target_kind = self.target(p['target'])
            require(target_session is session, 'invalid_target', 'Amendment target belongs to another session')
            require(p['expected_revision'] == session['revision'], 'stale_revision', 'Expected session revision is stale')
            amend(session, target, target_kind, p['correction'])
            session['amendments'].append({'event_id': event['event_id'], 'target': deepcopy(p['target']),
                                         'correction': deepcopy(p['correction']), 'reason': p['reason'], 'recorded_at': at})
        session['revision'] = event['revision']
        session['last_event_at'] = at
        self.events[event['event_id']] = event
        return session


def amend(session, target, kind, correction):
    allowed = {
        'session': {'label', 'metadata', 'subject', 'outcome', 'evidence', 'started_at', 'ended_at', 'state'},
        'span': {'label', 'metadata', 'outcome', 'evidence', 'started_at', 'ended_at', 'measured_duration_ms', 'state'},
        'phase': {'label', 'metadata', 'started_at', 'ended_at'},
        'note': {'text', 'metadata'},
    }[kind]
    require(not set(correction) - allowed, 'invalid_correction', f'Unsupported correction fields for {kind}')
    if 'state' in correction:
        require(set(correction) == {'state'}, 'invalid_correction', 'Interruption must be a separate amendment')
        require(target['state'] == 'open', 'invalid_correction', 'Only open work can be interrupted')
        affected = [target]
        if kind == 'session':
            affected += list(session['spans'].values()) + session['phases']
        else:
            identities = {target['id']}
            for span in session['spans'].values():  # Parents are always created before children.
                if span['parent_span_id'] in identities:
                    identities.add(span['id'])
                    affected.append(span)
        for entity in affected:
            if entity['state'] == 'open':
                entity.update(state='interrupted', ended_at=None, end_source=None)
        return
    if set(correction) & {'outcome', 'evidence'}:
        require(target['state'] != 'open', 'invalid_correction', 'Outcomes/evidence belong to finished work')
    if 'measured_duration_ms' in correction:
        require(target.get('measured_duration_ms') is not None, 'invalid_correction',
                'Only an existing producer-reported measurement can be corrected')
    if 'ended_at' in correction and kind in ('session', 'span'):
        require(target['state'] != 'open', 'invalid_correction', 'Timing corrections cannot close open work')
    for key, value in correction.items():
        target[key] = deepcopy(value)
        if key == 'started_at':
            target['start_source'] = 'producer_correction'
        elif key == 'ended_at':
            target['end_source'] = 'producer_correction'
        elif key == 'measured_duration_ms':
            target['measurement_corrected'] = True
    if kind == 'session' and 'ended_at' in correction and session['phases']:
        session['phases'][-1].update(ended_at=target['ended_at'], end_source='producer_correction')
    if kind == 'phase':
        index = session['phases'].index(target)
        if 'started_at' in correction and index:
            session['phases'][index - 1].update(ended_at=target['started_at'], end_source='producer_correction')
        if 'ended_at' in correction:
            if index + 1 < len(session['phases']):
                session['phases'][index + 1].update(started_at=target['ended_at'], start_source='producer_correction')
            else:
                require(session['state'] != 'open', 'invalid_correction', 'Timing corrections cannot close the current phase')
                session.update(ended_at=target['ended_at'], end_source='producer_correction')
    if set(correction) & {'started_at', 'ended_at', 'measured_duration_ms'}:
        validate_timing(session, target, kind)


def validate_timing(session, target, kind):
    def valid(entity):
        return entity.get('ended_at') is None or timestamp(entity['ended_at']) >= timestamp(entity['started_at'])
    require(valid(target), 'invalid_timing', 'Corrected end precedes start')
    if kind in ('phase', 'session'):
        require(valid(session), 'invalid_timing', 'Session end precedes start')
        previous = session['started_at']
        for phase in session['phases']:
            require(valid(phase) and timestamp(phase['started_at']) >= timestamp(previous),
                    'invalid_timing', 'Corrected phases would overlap or be out of order')
            if session['ended_at']:
                require(timestamp(phase['ended_at'] or phase['started_at']) <= timestamp(session['ended_at']),
                        'invalid_timing', 'Corrected phase lies outside the session')
            previous = phase['ended_at'] or phase['started_at']
    if kind == 'span':
        spans = session['spans']
        edges = [(spans[target['parent_span_id']], target)] if target['parent_span_id'] else []
        edges += [(target, child) for child in spans.values() if child['parent_span_id'] == target['id']]
        for parent, child in edges:
            if not valid(parent) or not valid(child):
                continue  # Existing discontinuities remain warnings until separately corrected.
            require(timestamp(child['started_at']) >= timestamp(parent['started_at']),
                    'invalid_timing', 'Corrected span starts before its parent')
            if parent['ended_at'] and child['ended_at']:
                require(timestamp(child['ended_at']) <= timestamp(parent['ended_at']),
                        'invalid_timing', 'Corrected span ends after its parent')


def summarize(session, config=None):
    from .config import metadata, outcome
    config = config or {}
    result = deepcopy(session)
    result['corrected'] = bool(session['amendments'])
    result['spans'] = list(result['spans'].values())
    warnings = []

    def warning(code, entity, message):
        warnings.append({'code': code, 'entity_id': entity['id'], 'message': message})

    def timing(entity):
        duration = elapsed(entity['started_at'], entity['ended_at'])
        entity['timestamp_duration_ms'] = duration
        if entity['ended_at'] is None:
            warning('unresolved_interval', entity, f"{entity['state']} interval has no confirmed end")
        elif duration is None:
            warning('clock_discontinuity', entity, 'End precedes start; timestamp duration is unresolved')
        measured = entity.get('measured_duration_ms')
        if measured is not None:
            entity['duration_ms'] = measured
            entity['duration_source'] = 'producer_correction' if entity.get('measurement_corrected') else 'producer_reported'
            entity['duration_difference_ms'] = None if duration is None else round(measured - duration, 6)
            if duration is not None and measured != duration:
                warning('duration_difference', entity, 'Reported measurement differs from timestamp subtraction')
        else:
            entity['duration_ms'] = duration
            entity['duration_source'] = ('producer_correction' if 'producer_correction' in
                (entity['start_source'], entity['end_source']) else entity['start_source'])

    def compatibility(entity, kind):
        try:
            metadata(config, kind, entity['metadata'])
            outcome(config, entity.get('outcome'), entity.get('evidence'))
        except WorkError as error:
            warning('configuration_mismatch', entity, error.message)
        value = entity.get('outcome')
        if value:
            entity['outcome_label'] = config.get('outcomes', {}).get(value, {}).get('label', value)

    timing(result)
    compatibility(result, 'session')
    confirmed_phases = 0
    for phase in result['phases']:
        phase['effective_metadata'] = {**result['metadata'], **phase['metadata']}
        timing(phase)
        compatibility(phase, 'phase')
        if phase['duration_ms'] is not None:
            confirmed_phases += phase['duration_ms']
    effective_spans = {}
    for span in result['spans']:
        parent = effective_spans.get(span['parent_span_id'], result['metadata'])
        span['effective_metadata'] = effective_spans[span['id']] = {**parent, **span['metadata']}
        timing(span)
        compatibility(span, 'span')
        if timestamp(span['started_at']) < timestamp(result['started_at']) or (result['ended_at'] and
                span['ended_at'] and timestamp(span['ended_at']) > timestamp(result['ended_at'])):
            warning('outside_session', span, 'Reported operation lies outside the session window')
        if span['parent_span_id']:
            parent_span = session['spans'][span['parent_span_id']]
            if (timestamp(span['started_at']) < timestamp(parent_span['started_at']) or
                    (parent_span['ended_at'] and span['ended_at'] and timestamp(span['ended_at']) > timestamp(parent_span['ended_at']))):
                warning('outside_parent', span, 'Reported operation lies outside its parent span')
    for note in result['notes']:
        compatibility(note, 'note')
    initial_end = result['phases'][0]['started_at'] if result['phases'] else result['ended_at']
    result['confirmed_phase_ms'] = round(confirmed_phases, 6)
    result['confirmed_unclassified_ms'] = elapsed(result['started_at'], initial_end)
    result['confirmed_session_elapsed_ms'] = result['timestamp_duration_ms']
    result['warnings'] = warnings
    return result
