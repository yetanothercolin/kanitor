from .common import WorkError
from .schemas import CONFIG_SCHEMA, check_metadata_schema, validate


def parse_work_config(value):
    validate(value, CONFIG_SCHEMA, '.kanitor.json.workTracking')
    for schema in value.get('metadataSchemas', {}).values():
        check_metadata_schema(schema)
    if 'sessionColumns' in value:
        from ..config import ConfigError, parse_columns
        try:
            parse_columns(value['sessionColumns'], 'workTracking.sessionColumns', scope='session')
        except ConfigError as error:
            raise WorkError('invalid_config', str(error)) from error
    return value


def load_config(root, *, recording=False):
    path = None
    try:
        from ..config_file import _check_values, load_document
        data, path = load_document(root, validate_view=False)
        config = data.get('workTracking', {})
        if recording and isinstance(config, dict) and 'sessionColumns' in config:
            # Legacy session columns are display rules, never recording policy.
            # Keep valid columns in capabilities for compatibility, but ignore
            # broken layouts while still enforcing metadata/outcome requirements.
            policy = {key: value for key, value in config.items() if key != 'sessionColumns'}
            _check_values(policy)
            parse_work_config(policy)
            try:
                _check_values(config)
                parse_work_config(config)
            except (ValueError, RecursionError, WorkError):
                return policy
        else:
            _check_values(config)
            parse_work_config(config)
        return config
    except (ValueError, OSError, RecursionError, WorkError) as error:
        message = str(error)
        if path is not None:
            message = message.replace('.kanitor.json', path.name)
            if not message.startswith(str(path)):
                message = f'{path}: {message}'
        raise WorkError('invalid_config', message) from error


def metadata(config, kind, value):
    schema = config.get('metadataSchemas', {}).get(kind)
    if schema is not None:
        validate(value, schema, f'{kind}.metadata')


def outcome(config, value, evidence):
    required = config.get('outcomes', {}).get(value, {}).get('requiresEvidence', False) if value else False
    if required and (evidence is None or evidence == '' or evidence == [] or evidence == {}):
        raise WorkError('evidence_required', f'Outcome {value!r} requires nonempty evidence')
