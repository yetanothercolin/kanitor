"""Date display rules; native metadata and filter identities remain unchanged."""
from dataclasses import dataclass
from datetime import datetime
import re

DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M'
DURATION_UNITS = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800, 'y': 31536000}


@dataclass(frozen=True)
class DateThreshold:
    seconds: int
    format: str


def duration_seconds(value):
    """Return a positive, fixed duration, or None for an invalid rule."""
    match = re.fullmatch(r'([1-9][0-9]*)([smhdwy])', value) if isinstance(value, str) else None
    return int(match[1]) * DURATION_UNITS[match[2]] if match else None


def format_date(value, pattern, thresholds=(), now=None):
    """Format ISO dates in local time. Leave malformed metadata readable as-is."""
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.strip().replace('Z', '+00:00')).astimezone()
        current = now.astimezone() if now is not None else datetime.now().astimezone()
        # Use timestamps so DST boundaries still represent actual elapsed time.
        age = current.timestamp() - date.timestamp()
        for threshold in thresholds:
            if 0 <= age < threshold.seconds:
                pattern = threshold.format
                break
        return date.strftime(pattern)
    except (ValueError, OverflowError, OSError):
        return None
