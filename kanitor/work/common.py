from datetime import datetime, timezone
import json
import math


class WorkError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def as_dict(self):
        result = {'code': self.code, 'message': self.message}
        if self.details is not None:
            result['details'] = self.details
        return result


def canonical(value):
    try:
        def check_keys(item):
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise ValueError('JSON object keys must be strings')
                for child in item.values():
                    check_keys(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    check_keys(child)
        check_keys(value)
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise WorkError('invalid_json', str(error)) from error


def loads(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = item
        return result

    try:
        return json.loads(value, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'Invalid JSON number: {value}')))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise WorkError('invalid_json', str(error)) from error


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00').replace('z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('An explicit UTC offset is required')
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError, OverflowError) as error:
        raise WorkError('invalid_timing', f'Invalid timestamp {value!r}: {error}') from error


def elapsed(start, end):
    if start is None or end is None:
        return None
    milliseconds = (timestamp(end) - timestamp(start)).total_seconds() * 1000
    return round(milliseconds, 6) if milliseconds >= 0 and math.isfinite(milliseconds) else None
