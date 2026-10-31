"""One set of discoverable schemas for the library, CLI, and MCP tools."""
from functools import lru_cache
import re

from ..config import SESSION_FIELDS
from ..widths import WIDTH_PATTERN
from .common import WorkError, canonical

SCHEMA_VERSION = 1
DRAFT = 'https://json-schema.org/draft/2020-12/schema'
TEXT = {'type': 'string', 'minLength': 1}
ID = {'type': 'string', 'format': 'uuid'}
TIME = {'type': 'string', 'format': 'date-time'}
METADATA = {'type': 'object'}


def obj(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


SUBJECT = obj({'provider': TEXT, 'ref': TEXT}, ('provider', 'ref'))
RESULT = {'outcome': TEXT, 'evidence': {}}
CONTEXT = {'metadata': METADATA}
TIMING = {'reported_start': TIME, 'reported_end': TIME,
          'measured_duration_ms': {'type': 'number', 'minimum': 0}, 'clock': METADATA}
TARGET = obj({'kind': {'enum': ['session', 'span', 'phase', 'note', 'event']}, 'id': ID}, ('kind', 'id'))
CORRECTION = obj({'label': TEXT, 'metadata': METADATA, 'subject': {'anyOf': [SUBJECT, {'type': 'null'}]},
                  'text': TEXT, **RESULT, 'started_at': TIME, 'ended_at': TIME,
                  'measured_duration_ms': {'type': 'number', 'minimum': 0},
                  'state': {'const': 'interrupted'}})
CORRECTION['minProperties'] = 1

_SPECS = {
    'work_capabilities': ({}, ()),
    'work_begin': ({'subject': SUBJECT, 'label': TEXT, **CONTEXT}, ('label',)),
    'work_transition': ({'session_id': ID, 'label': TEXT, 'note': TEXT, **CONTEXT}, ('session_id', 'label')),
    'work_span_begin': ({'session_id': ID, 'parent_span_id': ID, 'label': TEXT, **CONTEXT}, ('session_id', 'label')),
    'work_span_end': ({'span_id': ID, **RESULT}, ('span_id',)),
    'work_span_record': ({'session_id': ID, 'parent_span_id': ID, 'label': TEXT, **TIMING, **CONTEXT, **RESULT},
                         ('session_id', 'label', 'reported_start', 'reported_end')),
    'work_note': ({'session_id': ID, 'span_id': ID, 'text': TEXT, **CONTEXT}, ('session_id', 'text')),
    'work_end': ({'session_id': ID, **RESULT}, ('session_id',)),
    'work_amend': ({'target': TARGET, 'expected_revision': {'type': 'integer', 'minimum': 1},
                    'correction': CORRECTION, 'reason': TEXT}, ('target', 'expected_revision', 'correction', 'reason')),
    'work_read': ({'session_id': ID, 'subject': SUBJECT, 'view': {'enum': ['events', 'sessions']},
                   'after_seq': {'type': 'integer', 'minimum': 0}, 'as_of_seq': {'type': 'integer', 'minimum': 0},
                   'limit': {'type': 'integer', 'minimum': 1, 'maximum': 1000}}, ()),
    'work_recover': ({'reason': TEXT}, ('reason',)),
}
READ_ONLY = {'work_capabilities', 'work_read'}
OPERATIONS = tuple(name for name in _SPECS if name != 'work_recover')
INPUT_SCHEMAS = {}
for name, (properties, required) in _SPECS.items():
    if name not in READ_ONLY:
        properties = {**properties, 'request_id': {**TEXT, 'maxLength': 256}}
        required = (*required, 'request_id')
    INPUT_SCHEMAS[name] = {'$schema': DRAFT, **obj(properties, required)}

SESSION_COLUMN_SCHEMA = obj({
    'title': {'type': 'string'}, 'field': {'enum': list(SESSION_FIELDS)}, 'metadata': TEXT,
    'width': {'anyOf': [{'type': 'integer', 'minimum': 4}, {'type': 'string', 'pattern': WIDTH_PATTERN}]},
    'minTerminalWidth': {'type': 'integer', 'minimum': 0},
    'filterable': {'type': 'boolean'}, 'format': {'type': 'string'},
    'sortable': {'type': 'boolean'}, 'filterType': {'enum': ['enum', 'string', 'date']},
    'thresholds': {'type': 'array', 'items': obj({'under': TEXT, 'format': {'type': 'string'}}, ('under', 'format'))},
}, ('title',))
SESSION_COLUMN_SCHEMA['oneOf'] = [{'required': ['field'], 'not': {'required': ['metadata']}},
                                {'required': ['metadata'], 'not': {'required': ['field']}}]
CONFIG_SCHEMA = {'$schema': DRAFT, **obj({
    'metadataSchemas': obj({kind: {'type': ['object', 'boolean']} for kind in ('session', 'phase', 'span', 'note')}),
    'outcomes': {'type': 'object', 'additionalProperties': obj({
        'label': TEXT, 'requiresEvidence': {'type': 'boolean'}})},
    'sessionColumns': {'type': 'array', 'minItems': 1, 'items': SESSION_COLUMN_SCHEMA},
})}
EVENT_TYPES = ['session.begun', 'phase.transitioned', 'span.begun', 'span.ended',
               'span.recorded', 'note.added', 'session.ended', 'work.amended']
EVENT_SCHEMA = {'$schema': DRAFT, **obj({
    'schema_version': {'const': SCHEMA_VERSION}, 'event_id': ID,
    'seq': {'type': 'integer', 'minimum': 1}, 'session_id': ID,
    'type': {'enum': EVENT_TYPES}, 'recorded_at': TIME, 'request_id': TEXT,
    'request': obj({'operation': {'enum': list(_SPECS)}, 'arguments': METADATA}, ('operation', 'arguments')),
    'payload': METADATA, 'revision': {'type': 'integer', 'minimum': 1}, 'receipt': METADATA,
    'previous_hash': {'type': 'string'}, 'hash': {'type': 'string'},
}, ('schema_version', 'event_id', 'seq', 'session_id', 'type', 'recorded_at', 'request_id',
    'request', 'payload', 'revision', 'receipt', 'previous_hash', 'hash'))}


@lru_cache(maxsize=128)
def _validator(schema_json):
    from jsonschema import Draft202012Validator, FormatChecker
    from .common import loads, timestamp
    checker = FormatChecker()

    @checker.checks('date-time')
    def date_time(value):
        if not isinstance(value, str):
            return True  # Type validation is the schema's responsibility.
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})', value):
            return False
        try:
            timestamp(value)
            return True
        except WorkError:
            return False
    return Draft202012Validator(loads(schema_json), format_checker=checker)


def validate(value, schema, location='request'):
    from referencing.exceptions import Unresolvable
    canonical(value)  # Reject NaN/Infinity even when a schema leaves a JSON field unrestricted.
    try:
        errors = sorted(_validator(canonical(schema)).iter_errors(value), key=lambda error: str(list(error.path)))
    except (Unresolvable, RecursionError) as error:
        raise WorkError('invalid_schema', f'{location}: metadata schema reference cannot be evaluated: {error}') from error
    if errors:
        error = errors[0]
        path = '.'.join(str(part) for part in error.path)
        raise WorkError('validation_error', f'{location}{"." + path if path else ""}: {error.message}')


def check_metadata_schema(schema):
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    if (isinstance(schema, dict) and '$schema' in schema and
            (not isinstance(schema['$schema'], str) or schema['$schema'].rstrip('#') != DRAFT)):
        raise WorkError('invalid_config', 'Metadata schemas must use JSON Schema Draft 2020-12')
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise WorkError('invalid_config', f'Invalid metadata schema: {error.message}') from error

    def check_refs(value):
        if not isinstance(value, dict):
            return
        for key in ('$ref', '$dynamicRef'):
            if key in value and not value[key].startswith('#'):
                raise WorkError('invalid_config', 'Metadata schemas may reference local fragments only')
        # Traverse schema positions, not enum/const/example data or property names.
        for key in ('$defs', 'definitions', 'properties', 'patternProperties', 'dependentSchemas'):
            children = value.get(key, {})
            if isinstance(children, dict):
                for child in children.values():
                    check_refs(child)
        for key in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
            for child in value.get(key, []):
                check_refs(child)
        for key in ('not', 'if', 'then', 'else', 'items', 'contains', 'propertyNames',
                    'additionalProperties', 'unevaluatedProperties', 'unevaluatedItems', 'contentSchema'):
            check_refs(value.get(key))
    check_refs(schema)
