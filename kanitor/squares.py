"""Read-only task badges, activity recency, and view-local lane ordering."""
from dataclasses import dataclass
from datetime import datetime

from .config import SquareRules
from .model import state


def date_seconds(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone().timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def latest_work(snapshot):
    if not snapshot:
        return {}
    subjects = {session['id']: session.get('subject') for session in snapshot['sessions']}
    result = {}
    for event in snapshot['events']:
        subject = subjects.get(event['session_id'])
        if subject and subject['provider'] == 'kanbn' and event['type'] != 'work.amended':
            at = date_seconds(event['recorded_at'])
            if at is not None:
                ref = subject['ref']
                result[ref] = max(result.get(ref, float('-inf')), at)
    return result


@dataclass(frozen=True)
class Square:
    id: str
    kind: str
    at: float = float('-inf')
    work_at: float = float('-inf')
    board: str = None

    @property
    def glyph(self):
        return '■' if self.kind in ('done', 'done_old') else '□'

    @property
    def pulse(self):
        return self.kind in ('active', 'stale')


def classify(board, task, work, now, rules, *, include_old_completed=False):
    metadata = task.get('metadata', {})
    history = [event for event in task.get('history', []) if event.get('board', board['slug']) == board['slug']]
    def latest(field, columns):
        dates = [date_seconds(metadata.get(field))]
        dates += [date_seconds(event.get('date')) for event in history
                  if event.get('toColumn', event.get('column')) in columns]
        return max((at for at in dates if at is not None and at <= now), default=float('-inf'))
    options = board.get('options', {})
    workflow = state(board, task['column'])
    activity = work.get(task['id'], float('-inf'))
    def badge(kind, at=float('-inf')):
        return Square(task['id'], kind, at, activity, board['slug'])
    if workflow == 'done':
        at = latest('completed', options.get('completedColumns', []))
        if 0 <= now - at < rules.recent_completed:
            return badge('done', at)
        return badge('done_old', at) if include_old_completed else None
    if workflow == 'active':
        return badge('active' if 0 <= now - activity < rules.recent_work else 'stale')
    started = latest('started', options.get('startedColumns', []))
    previously_active = any(event.get('fromColumn') in options.get('startedColumns', []) for event in history)
    if started != float('-inf') or previously_active or date_seconds(metadata.get('completed')) is not None:
        return badge('paused', started)
    created = latest('created', [])
    creation_dates = [date_seconds(event.get('date')) for event in history if event.get('type') == 'created']
    created = max(created, max((at for at in creation_dates if at is not None and at <= now), default=float('-inf')))
    return badge('new' if 0 <= now - created < rules.recent_created else 'old', created)


def board_squares(board, work, now, rules):
    return [square for task in board['tasks'] if (square := classify(board, task, work, now, rules)) is not None]


def project_squares(boards, work, now, rules):
    return merge_project_squares(board_squares(board, work, now, rules) for board in boards)


def merge_project_squares(groups):
    # Shared tasks appear once. Any incomplete board membership takes precedence
    # over completion elsewhere; a running membership takes precedence over pause.
    priority = {'active': 0, 'stale': 0, 'paused': 1, 'new': 2, 'old': 2, 'done': 3}
    tasks = {}
    for group in groups:
        for square in group:
            old = tasks.get(square.id)
            if old is None or (priority[square.kind], -square.at) < (priority[old.kind], -old.at):
                tasks[square.id] = square
    return list(tasks.values())


@dataclass(frozen=True)
class SquareBundle:
    groups: tuple

    @property
    def flat(self):
        return [square for group in self.groups for square in group]

    def lines(self, width):
        flat = self.flat
        if not flat:
            return [[]]
        count = max(1, (width + 1) // 2)
        if len(flat) <= count:
            return [flat]
        return [group[start:start + count] for group in self.groups for start in range(0, len(group), count)]


class SquareView:
    def __init__(self):
        self.scope = None
        self.active = {}

    def enter(self, scope):
        if scope != self.scope:
            self.active = {}
            self.scope = scope

    def bundle(self, key, squares, freeze=True):
        ranks = self.active.setdefault(key, {}) if freeze else dict(self.active.get(key, {}))
        arrivals = sorted((square for square in squares if square.pulse and square.id not in ranks),
                          key=lambda square: (square.kind == 'stale', -square.work_at))
        for square in arrivals:
            ranks[square.id] = len(ranks)
        done, active, remaining = [], [], []
        for square in squares:
            if square.id in ranks:
                active.append(square)
            elif square.kind == 'done':
                done.append(square)
            else:
                remaining.append(square)
        done.sort(key=lambda square: -square.at)
        active.sort(key=lambda square: ranks[square.id])
        remaining.sort(key=lambda square: ({'paused': 0, 'new': 1, 'old': 2}[square.kind], -square.at))
        return SquareBundle((active, done, remaining))
