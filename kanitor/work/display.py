"""Shared work-duration formatting for Activity and legacy column settings."""

def duration_cell(value):
    """Stable d/h/m/s slots for table columns; unknown is distinct from subsecond."""
    if value is None or value == '' or value < 0:
        return '—'.rjust(14)
    if value < 1000:
        return '<1s'.rjust(14)
    minutes, seconds = divmod(int(value // 1000), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = [f'{days}d' if days else '  ',
             f'{hours:2d}h' if days or hours else '   ',
             f'{minutes:2d}m' if days or hours or minutes else '   ',
             f'{seconds:2d}s']
    return ' '.join(parts)


def subject_text(subject):
    return f"{subject['provider']}:{subject['ref']}" if subject else 'No subject'
