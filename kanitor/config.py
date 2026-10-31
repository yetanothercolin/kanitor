"""Declarative board and task columns from workspace configuration."""
from dataclasses import dataclass, field
from functools import cached_property
import json
from pathlib import Path
from typing import Optional, Union

from .dates import DEFAULT_DATE_FORMAT, DateThreshold, duration_seconds, format_date
from .text import cells, clean
from .widths import parse_width, share_widths, shrink_widths
from .keybindings import DEFAULT_BINDINGS, KeyBindings, parse_keybindings

CONFIG_NAME = '.kanitor.json'
CONFIG_NAMES = (CONFIG_NAME, '.kanitor.yml', '.kanitor.yaml')
FIELDS = {'status': 'column', 'task': 'name', 'id': 'id', 'description': 'description', 'name': 'name'}
BOARD_FIELDS = ('slug', 'board', 'description', 'path', 'main', 'cards', 'active', 'done', 'remaining', 'updated', 'task_squares', 'name')
BOARD_COUNTS = ('cards', 'active', 'done', 'remaining')
PROJECT_FIELDS = ('project', 'path', 'root', 'boards', 'cards', 'state', 'task_squares', 'name')
ACTIVITY_FIELDS = ('project', 'board', 'slug', 'id', 'task', 'description', 'status', 'assigned',
                   'activity', 'session', 'started_at', 'elapsed', 'name')
NAME_FIELDS = {'project': 'project', 'board': 'board', 'task': 'task', 'activity': 'task'}
SESSION_FIELDS = ('id', 'label', 'state', 'started_at', 'ended_at', 'last_event_at', 'subject', 'outcome',
                  'confirmed_session_elapsed_ms', 'confirmed_phase_ms', 'confirmed_unclassified_ms')
SESSION_DURATIONS = ('confirmed_session_elapsed_ms', 'confirmed_phase_ms', 'confirmed_unclassified_ms')
SESSION_DATES = ('started_at', 'ended_at', 'last_event_at')
MISSING_VALUE = '\0missing'


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Column:
    title: str
    field: Optional[str] = None
    metadata: Optional[str] = None
    width: Optional[Union[int, str]] = None
    min_terminal_width: int = 0
    filterable: Optional[bool] = None
    format: Optional[str] = None
    thresholds: tuple = ()
    scope: str = 'task'
    sortable: Optional[bool] = None
    filter_type: Optional[str] = None

    @cached_property
    def sizing(self):
        return parse_width(self.width)

    @property
    def is_date(self):
        return self.format is not None or bool(self.thresholds)

    @property
    def is_duration(self):
        return ((self.scope == 'session' and self.field in SESSION_DURATIONS)
                or (self.scope == 'activity' and self.field == 'elapsed'))

    @property
    def canonical_field(self):
        """Resolve legacy name rules without changing their persisted spelling."""
        return NAME_FIELDS.get(self.scope, self.field) if self.field == 'name' else self.field

    @property
    def key(self):
        return ('metadata', self.metadata) if self.metadata is not None else ('field', self.canonical_field)

    @property
    def label(self):
        return self.title or self.metadata or self.canonical_field.title()

    @property
    def can_filter(self):
        if self.field == 'task_squares':
            return False
        if self.filterable is not None:
            return self.filterable
        if self.scope == 'activity':
            return self.field != 'elapsed'
        if self.scope == 'session' and self.filterable is None:
            return self.field == 'state'
        if self.scope == 'board':
            return self.field == 'updated'
        return self.scope == 'task' and (self.canonical_field in ('status', 'task', 'description') or self.metadata in ('updated', 'assigned'))

    @property
    def can_sort(self):
        if self.field == 'task_squares':
            return False
        if self.sortable is not None:
            return self.sortable
        if self.scope == 'activity':
            return True
        return (self.scope == 'task' and self.metadata in ('updated', 'assigned')) or (self.scope == 'board' and self.field == 'updated')

    @property
    def filter_kind(self):
        if self.filter_type:
            return self.filter_type
        if self.format is not None or self.thresholds or self.metadata == 'updated' or self.field == 'updated':
            return 'date'
        name = self.scope in ('project', 'board') and self.canonical_field == NAME_FIELDS[self.scope]
        return 'string' if name or self.canonical_field in ('task', 'description') else 'enum'

    def heading(self, filtered=False, sort=None):
        return self.title + ('▾' if filtered and self.can_filter else '') + (('↓' if sort else '↑') if sort is not None else '')

    def raw_value(self, card):
        if self.metadata is not None:
            return card.get('options' if self.scope == 'board' else 'metadata', {}).get(self.metadata)
        field = self.canonical_field
        if self.scope == 'task':
            field = FIELDS[field]
        elif field == NAME_FIELDS.get(self.scope):
            field = 'name'
        return card.get(field)

    def value(self, card, now=None):
        value = self.raw_value(card)
        if self.is_duration:
            from .work.display import duration_cell
            return duration_cell(value)
        if value is None or value == '':
            return '—'
        if self.field == 'task_squares':
            return ' '.join(square.glyph for square in value.flat) or '—'
        if self.scope == 'session' and self.field == 'subject':
            from .work.display import subject_text
            return subject_text(value)
        if self.scope == 'session' and self.field == 'state':
            return value.title()
        if self.scope == 'session' and self.field == 'outcome':
            return card.get('outcome_label', value)
        if self.is_date:
            formatted = format_date(value, self.format if self.format is not None else DEFAULT_DATE_FORMAT,
                                    self.thresholds, now)
            if formatted is not None:
                return formatted
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)

    def filter_token(self, card):
        value = self.raw_value(card)
        if value is None or value == '':
            return MISSING_VALUE
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


DEFAULT_COLUMNS = (
    Column('STATUS', field='status', width=16),
    Column('UPDATED', metadata='updated', width=16, format=DEFAULT_DATE_FORMAT),
    Column('ASSIGNED', metadata='assigned', width=12, min_terminal_width=90),
    Column('DESCRIPTION', field='task'),
)
DEFAULT_BOARD_COLUMNS = (
    Column('BOARD', field='slug', width='hug', scope='board'),
    Column('NAME', field='board', width='fill', scope='board'),
    Column('TASK STATUS', field='task_squares', width='fill', scope='board'),
    Column('CARDS', field='cards', width='hug', scope='board'),
    Column('ACTIVE', field='active', width='hug', scope='board'),
    Column('DONE', field='done', width='hug', scope='board'),
)
DEFAULT_PROJECT_COLUMNS = (
    Column('PROJECT', field='project', width='fill', scope='project'),
    Column('TASK STATUS', field='task_squares', width='fill', scope='project'),
    Column('BOARDS', field='boards', width='hug', scope='project'),
    Column('TASKS', field='cards', width='hug', scope='project'),
    Column('STATE', field='state', width='hug', scope='project'),
    Column('DIRECTORY', field='path', width='fill', min_terminal_width=100, scope='project'),
)

DEFAULT_ACTIVITY_COLUMNS = (
    Column('PROJECT', field='project', width='hug,18', scope='activity'),
    Column('BOARD', field='board', width='hug,18', scope='activity'),
    Column('ELAPSED', field='elapsed', width='hug', scope='activity'),
    Column('ACTIVITY', field='activity', width='hug,24', min_terminal_width=95, scope='activity'),
    Column('ASSIGNED', metadata='assigned', width='hug,14', min_terminal_width=120, scope='activity'),
    Column('TASK', field='task', width='fill', scope='activity'),
)


@dataclass(frozen=True)
class SquareRules:
    recent_completed: int = 86400
    recent_work: int = 900
    recent_created: int = 86400


@dataclass(frozen=True)
class ColumnRules:
    columns: tuple = DEFAULT_COLUMNS
    boards: dict = field(default_factory=dict)
    board_columns: tuple = DEFAULT_BOARD_COLUMNS
    projects: Optional[tuple] = None
    project_columns: tuple = DEFAULT_PROJECT_COLUMNS
    square_rules: SquareRules = SquareRules()
    keybindings: KeyBindings = DEFAULT_BINDINGS
    activity_columns: tuple = DEFAULT_ACTIVITY_COLUMNS

    def for_board(self, slug):
        return self.boards.get(slug, self.columns)


def fail(location, message):
    raise ConfigError(f'{CONFIG_NAME}: {location} {message}')


def object_keys(value, allowed, location):
    if not isinstance(value, dict):
        fail(location, 'must be an object')
    unknown = set(value) - allowed
    if unknown:
        fail(location, 'has unknown setting(s): ' + ', '.join(sorted(unknown)))


def parse_date_format(value, location):
    if (not isinstance(value, str) or (value and not value.isprintable())
            or any(code in value.replace('%%', '') for code in ('%n', '%t'))):
        fail(location, 'must be a single-line strftime format string')
    return value


def parse_thresholds(value, location):
    if not isinstance(value, list):
        fail(location, 'must be an array of age thresholds')
    thresholds = []
    for index, rule in enumerate(value):
        here = f'{location}[{index}]'
        object_keys(rule, {'under', 'format'}, here)
        seconds = duration_seconds(rule.get('under'))
        if seconds is None:
            fail(here + '.under', 'must be a positive duration such as "1d" or "1y" (units: s, m, h, d, w, y)')
        if thresholds and seconds <= thresholds[-1].seconds:
            fail(here + '.under', 'must be greater than the previous threshold')
        pattern = parse_date_format(rule.get('format'), here + '.format')
        thresholds.append(DateThreshold(seconds, pattern))
    return tuple(thresholds)


def parse_columns(value, location, scope='task'):
    if not isinstance(value, list) or not value:
        fail(location, 'must be a nonempty array')
    columns = []
    for index, rule in enumerate(value):
        here = f'{location}[{index}]'
        allowed = {'title', 'field', 'metadata', 'width', 'format', 'thresholds', 'minTerminalWidth', 'filterable', 'sortable', 'filterType'}
        if scope == 'project':
            allowed.remove('metadata')
        if scope in ('task', 'session'):
            allowed.add('filterable')
        object_keys(rule, allowed, here)
        title = rule.get('title')
        if not isinstance(title, str) or (title and not title.isprintable()):
            fail(here + '.title', 'must be a printable single-line string (may be empty)')
        if ('field' in rule) == ('metadata' in rule):
            fail(here, 'must specify exactly one of field or metadata')
        fields = (ACTIVITY_FIELDS if scope == 'activity' else BOARD_FIELDS if scope == 'board'
                  else PROJECT_FIELDS if scope == 'project' else SESSION_FIELDS if scope == 'session' else FIELDS)
        if 'field' in rule and (not isinstance(rule['field'], str) or rule['field'] not in fields):
            fail(here + '.field', 'must be one of: ' + ', '.join(fields))
        metadata = rule.get('metadata')
        if 'metadata' in rule and (not isinstance(metadata, str) or not metadata.strip()):
            fail(here + '.metadata', 'must be a nonempty metadata key')
        width = rule.get('width')
        if 'width' in rule:
            try:
                if width is None:
                    raise ValueError('must not be null; omit width to use fill')
                parse_width(width)
            except ValueError as error:
                fail(here + '.width', str(error))
        if 'filterable' in rule and type(rule['filterable']) is not bool:
            fail(here + '.filterable', 'must be true or false')
        if 'sortable' in rule and type(rule['sortable']) is not bool:
            fail(here + '.sortable', 'must be true or false')
        if 'filterType' in rule and rule['filterType'] not in ('enum', 'string', 'date'):
            fail(here + '.filterType', 'must be enum, string, or date')
        if rule.get('field') == 'task_squares' and (rule.get('filterable') or rule.get('sortable')):
            fail(here, 'task_squares does not support filtering or sorting')
        if scope == 'activity' and rule.get('field') == 'elapsed' and rule.get('filterable'):
            fail(here, 'live elapsed supports sorting, not exact-value filtering')
        minimum = rule.get('minTerminalWidth', 0)
        if type(minimum) is not int or minimum < 0:
            fail(here + '.minTerminalWidth', 'must be a nonnegative integer')
        if rule.get('field') == 'task_squares' and ('format' in rule or 'thresholds' in rule):
            fail(here, 'task_squares uses taskSquares recency settings, not date formatting')
        pattern = parse_date_format(rule['format'], here + '.format') if 'format' in rule else None
        thresholds = parse_thresholds(rule['thresholds'], here + '.thresholds') if 'thresholds' in rule else ()
        if pattern is None and ('thresholds' in rule or (scope == 'session' and rule.get('field') in SESSION_DATES)
                                or (scope == 'board' and rule.get('field') == 'updated')
                                or (scope == 'activity' and rule.get('field') == 'started_at')):
            pattern = DEFAULT_DATE_FORMAT
        columns.append(Column(title, field=rule.get('field'), metadata=metadata, width=width,
                              min_terminal_width=minimum, filterable=rule.get('filterable'),
                              format=pattern, thresholds=thresholds, scope=scope,
                              sortable=rule.get('sortable'), filter_type=rule.get('filterType')))
    return tuple(columns)


def parse_projects(value):
    if not isinstance(value, list):
        fail('projects', 'must be an array of relative subdirectory paths')
    paths = []
    for index, path in enumerate(value):
        if (not isinstance(path, str) or not path.strip() or not path.isprintable()
                or Path(path).is_absolute() or '..' in Path(path).parts or not Path(path).parts):
            fail(f'projects[{index}]', 'must name a subdirectory under this configuration directory')
        normalized = str(Path(path))
        if normalized in paths:
            fail(f'projects[{index}]', 'duplicates a project path')
        paths.append(normalized)
    return tuple(paths)


def parse_config(value, source=CONFIG_NAME):
    try:
        return _parse_config(value)
    except ConfigError as error:
        raise ConfigError(str(error).replace(CONFIG_NAME, source)) from error


def _parse_config(value):
    object_keys(value, {'columns', 'boards', 'boardColumns', 'projectColumns', 'taskSquares', 'workTracking', 'projects', 'keybindings', 'activityColumns'}, 'configuration')
    try:
        keybindings = parse_keybindings(value.get('keybindings', {}))
    except ValueError as error:
        fail('keybindings', str(error))
    projects = parse_projects(value['projects']) if 'projects' in value else None
    if 'workTracking' in value:
        from .work.common import WorkError
        from .work.config import parse_work_config
        try:
            parse_work_config(value['workTracking'])
        except WorkError as error:
            fail('workTracking', error.message)
    columns = parse_columns(value['columns'], 'columns') if 'columns' in value else DEFAULT_COLUMNS
    boards = value.get('boards', {})
    if not isinstance(boards, dict):
        fail('boards', 'must be an object keyed by native board slug')
    overrides = {}
    for slug, options in boards.items():
        if not isinstance(slug, str) or not slug.strip():
            fail('boards', 'must use nonempty board slugs')
        location = f'boards[{slug!r}]'
        object_keys(options, {'columns'}, location)
        if 'columns' not in options:
            fail(location, 'must specify columns')
        overrides[slug] = parse_columns(options['columns'], location + '.columns')
    board_columns = parse_columns(value['boardColumns'], 'boardColumns', scope='board') if 'boardColumns' in value else DEFAULT_BOARD_COLUMNS
    project_columns = parse_columns(value['projectColumns'], 'projectColumns', scope='project') if 'projectColumns' in value else DEFAULT_PROJECT_COLUMNS
    activity_columns = parse_columns(value['activityColumns'], 'activityColumns', scope='activity') if 'activityColumns' in value else DEFAULT_ACTIVITY_COLUMNS
    options = value.get('taskSquares', {})
    names = {'recentCompleted': 'recent_completed', 'recentWork': 'recent_work', 'recentCreated': 'recent_created'}
    object_keys(options, set(names), 'taskSquares')
    durations = {}
    for key, item in options.items():
        seconds = duration_seconds(item)
        if seconds is None:
            fail('taskSquares.' + key, 'must be a positive duration such as "1d" or "15m"')
        durations[names[key]] = seconds
    return ColumnRules(columns, overrides, board_columns, projects, project_columns, SquareRules(**durations), keybindings, activity_columns)


def layout_columns(columns, terminal_width, available, rows=(), filtered=(), sorting=None):
    """Fit content first, share fill space equally, and relax minimums under pressure."""
    eligible = [column for column in columns if terminal_width >= column.min_terminal_width]
    visible = list(eligible)

    def floor(column):
        spec = column.sizing
        base = 1 if spec.mode == 'hug' else 4
        return min(base, spec.minimum if spec.minimum is not None else base,
                   spec.maximum if spec.maximum is not None else base)

    while visible and sum(floor(c) for c in visible) + len(visible) - 1 > available:
        visible.pop()
    hidden = len(eligible) - len(visible)
    if not visible:
        return [], hidden
    budget = available - len(visible) + 1  # One cell between adjacent columns.
    floors = [floor(column) for column in visible]
    minimums = [max(base, column.sizing.minimum or base) for column, base in zip(visible, floors)]
    if sum(minimums) > budget:
        return list(zip(visible, shrink_widths(minimums, floors, budget))), hidden
    targets = []
    for column, minimum in zip(visible, minimums):
        spec = column.sizing
        if spec.mode == 'hug':
            # Measure every matching row so the layout stays stable while scrolling.
            values = (column.value(card) for card in rows)
            if column.is_duration:
                # Right alignment restores shared unit positions without needing
                # to reserve leading day/hour slots that no row currently uses.
                values = (value.lstrip() for value in values)
            content = max((cells(clean(value)) for value in values), default=0)
            order = sorting[1] if sorting and sorting[0] == column.key else None
            desired = max(cells(clean(column.heading(filtered=column.key in filtered, sort=order))), content)
        elif spec.mode == 'fixed':
            desired = spec.maximum
        else:
            desired = 0
        desired = min(desired, spec.maximum) if spec.maximum is not None else desired
        targets.append(max(minimum, desired))
    if sum(targets) > budget:
        widths = shrink_widths(targets, minimums, budget)
    else:
        widths = targets
        flexible = [index for index, c in enumerate(visible) if c.sizing.mode == 'fill']
        if flexible:
            fixed_total = sum(width for index, width in enumerate(widths) if index not in flexible)
            shares = share_widths([minimums[index] for index in flexible],
                                 [visible[index].sizing.maximum for index in flexible], budget - fixed_total)
            for index, share in zip(flexible, shares):
                widths[index] = share
    return list(zip(visible, widths)), hidden
