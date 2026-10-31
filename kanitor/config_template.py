"""Annotated YAML configuration generated from the application's defaults."""
from pathlib import Path

from .config import (CONFIG_NAMES, ConfigError, DEFAULT_BOARD_COLUMNS, DEFAULT_COLUMNS,
                     DEFAULT_PROJECT_COLUMNS, DEFAULT_ACTIVITY_COLUMNS, SquareRules)
from .config_file import yaml_module
from .keybindings import DEFAULT_KEYS


def _column_rule(column):
    rule = {'title': column.title}
    rule['metadata' if column.metadata is not None else 'field'] = (
        column.metadata if column.metadata is not None else column.field)
    if column.width is not None:
        rule['width'] = column.width
    if column.min_terminal_width:
        rule['minTerminalWidth'] = column.min_terminal_width
    if column.filterable is not None:
        rule['filterable'] = column.filterable
    if column.sortable is not None:
        rule['sortable'] = column.sortable
    if column.filter_type is not None:
        rule['filterType'] = column.filter_type
    if column.format is not None:
        rule['format'] = column.format
    if column.thresholds:
        rule['thresholds'] = [{'under': f'{rule.seconds}s', 'format': rule.format}
                              for rule in column.thresholds]
    return rule


def default_document():
    squares = SquareRules()
    return {
        'keybindings': {action: list(keys) for action, keys in DEFAULT_KEYS.items()},
        'columns': [_column_rule(column) for column in DEFAULT_COLUMNS],
        'boards': {},
        'boardColumns': [_column_rule(column) for column in DEFAULT_BOARD_COLUMNS],
        'projectColumns': [_column_rule(column) for column in DEFAULT_PROJECT_COLUMNS],
        'activityColumns': [_column_rule(column) for column in DEFAULT_ACTIVITY_COLUMNS],
        'taskSquares': {'recentCompleted': f'{squares.recent_completed}s',
                        'recentWork': f'{squares.recent_work}s',
                        'recentCreated': f'{squares.recent_created}s'},
        'workTracking': {
            'metadataSchemas': {},
            'outcomes': {},
        },
    }


HEADER = """# Kanitor configuration. Active settings reproduce the built-in defaults.
# Delete any setting to use its default. Arrays replace the entire default list.
# Supported filenames: .kanitor.json, .kanitor.yml, .kanitor.yaml, in that order.
# Only one file is used; settings are never merged between files.
# A declared project with no local config inherits its workspace's settings.
# A local config replaces inheritance entirely; {} uses built-in defaults.
# The parent's projects roster is not inherited. Edits are picked up live.
#
# Column rules:
#   title: any single-line string, including "" for an empty heading.
#   field: a built-in field OR metadata: an exact, case-sensitive metadata key.
#          project = project name, board = board name, task = task title.
#          Legacy name aliases project/board/task in Projects/Boards/Tasks or Activity.
#   width: integer >= 4, hug (fit content), or fill (share remaining space).
#          Omitting width means fill.
#          Quoted constraints: "fill,8" (max), "8,fill" (min), "hug,8" (max),
#          "8,hug" (min), "2,hug,8" or "2,fill,8" (both). Bounds are positive
#          integer terminal cells; minimum <= maximum. Spaces around tokens OK.
#          Fill columns target equal final widths; capped surplus is redistributed.
#          Minimums soften on narrow terminals before columns hide; caps stay strict.
#          Quote comma-separated widths, especially inside YAML flow mappings.
#   minTerminalWidth: hide the column below this terminal width (default 0).
#   filterable/sortable: true/false, on task/board/project scalar columns.
#     Tasks: Status enum filter; Updated date filter + sort; Assigned enum + sort;
#     Description text search across name/body. Others default false, except
#     computed board updated. Task Squares cannot be filtered or sorted.
#   filterType: enum, string, or date; overrides inference from the column.
#     Formatted/updated dates infer date; task/description and primary names string.
#     Only active filters show ▾; use arrows then Enter/Space for column menus.
#     Boards start newest updated first; Reset sort restores this default.
#     Filters/sorts are runtime only and never change native kanbn ordering.
#   format: quoted Python strftime string for ISO dates, default "%Y-%m-%d %H:%M".
#   thresholds: increasing age rules; first match wins, format handles older dates.
#   Durations: s, m, h, d, w, y. A day is 24 hours; a year is 365 days.
# Quote date formats, date-like strings, and numeric/boolean metadata keys.

"""

COMMENTS = {
    'keybindings': '# Keyboard actions. Each entry replaces its default keys; [] disables it.\n'
                   '# A single key string is also accepted. Conflicting assignments are errors.\n'
                   '# Named keys are case-insensitive; literal characters preserve case.\n'
                   '# Use Ctrl+letter, Shift/Ctrl/Ctrl+Shift+arrows, or F1-F24.\n'
                   '# jumpLeft/jumpRight: one cell, or five squares in Task Squares.\n'
                   '# toggleActivity: a; focusPane: Tab/Shift+Tab when Activity is shown.\n'
                   '# Text editors retain Enter/Escape/Backspace/Ctrl+U and literal typing.\n',
    'columns': '# Task table. Fields: status, task, id, description; metadata: any ticket key.\n',
    'boards': '# Per-board task column replacements, keyed by native board slug.\n',
    'boardColumns': '# Boards table. Fields: slug, board, description, path, main, cards, active,\n'
                    '# done, remaining, updated, task_squares; metadata reads native board frontmatter.\n',
    'projectColumns': '# Projects table. Fields: project, path, root, boards, cards, state, task_squares.\n'
                      '# Project columns do not accept metadata; scalar filter/sort rules are supported.\n',
    'activityColumns': '# Activity pane (a toggles, Tab switches focus). Selectable cells and headers.\n'
                       '# Fields: project, board, slug, id, task, description, status, assigned, activity,\n'
                       '# session, started_at, elapsed. Metadata reads the ticket.\n'
                       '# project is shown only in Projects; board (name) and slug in Projects/Boards.\n'
                       '# Filter/sort default on; elapsed supports sorting only. Use false to disable.\n'
                       '# elapsed is the latest open work session age, never time in status.\n',
    'taskSquares': '# Recency windows in seconds (86400s = 1d, 900s = 15m).\n',
    'workTracking': '# Optional work recording rules. No identity is required by default;\n'
                    '# metadata schemas and outcome evidence requirements are empty.\n',
}

EXAMPLES = """# --- Optional examples (commented out) ---
# Replace the matching section above; do not add duplicate YAML keys.

# Watch multiple projects. Omitted by default: enabling this setting, even with
# an empty list, opens the Projects view. Paths must stay below this directory.
# projects:
#   - api
#   - packages/web

# Add Vim-style horizontal movement, and use F1 for Help:
# keybindings:
#   left: [left, h]
#   right: [right, l]
#   help: [F1]
#   nextBoard: ["]"]
#   refresh: []  # Disable the refresh shortcut; automatic watching continues.
#   toggleActivity: [a]
#   focusPane: [tab, shift+tab]
# To use Tab for a different action, set focusPane: [] or rebind it (e.g. F6).

# Custom task columns with a filterable assignee and age-dependent dates:
# columns:
#   - {title: Status, field: status, width: "2,hug,8"}
#   - {title: Assignee, metadata: assignee, width: "8,hug,20", filterable: true, sortable: true}
#   - title: Updated
#     metadata: updated
#     width: hug
#     format: "%b %Y"
#     thresholds:
#       - {under: 1d, format: "%H:%M"}
#       - {under: 1y, format: "%d %b"}
#   - {title: Due, metadata: due, width: hug, filterable: true, sortable: true, filterType: date}
#   - {title: Notes, metadata: notes, filterable: true, filterType: string}
#   - {title: "", metadata: priority, width: 6}
#   - {title: Task, field: task, width: "8,fill"}

# Override the task layout for one board only:
# boards:
#   releases:
#     columns:
#       - {title: Status, field: status, width: hug}
#       - {title: Task, field: task, width: fill}

# Compact board/project layouts:
# boardColumns:
#   - {title: Board, field: slug, width: hug}
#   - {title: Name, field: board, width: hug}
#   - {title: Tasks, field: task_squares, width: fill}
# projectColumns:
#   - {title: Project, field: project, width: hug}
#   - {title: Tasks, field: task_squares, width: fill}

# Adjust task square recency windows:
# taskSquares:
#   recentCompleted: 1d
#   recentWork: 15m
#   recentCreated: 1d

# Compact Activity pane (all views use this section):
# activityColumns:
#   - {title: Project, field: project, width: "hug,18"}
#   - {title: Board, field: board, width: "hug,18"}
#   - {title: Elapsed, field: elapsed, width: hug}
#   - {title: Owner, metadata: assignee, width: hug}
#   - {title: Task, field: task, width: fill}

# Optional work metadata validation and evidence requirements:
# workTracking:
#   metadataSchemas:
#     session:
#       type: object
#       properties:
#         AGENT: {type: string, minLength: 1}
#       required: [AGENT]
#       additionalProperties: true
#     phase:
#       type: object
#       properties:
#         ACTIVITY: {enum: [investigating, changing, verifying]}
#     span: {type: object}
#     note: {type: object}
#   outcomes:
#     verified:
#       label: Verified with evidence
#       requiresEvidence: true
"""


def render_yml():
    yaml = yaml_module()
    sections = [HEADER]
    for key, value in default_document().items():
        sections.append(COMMENTS[key])
        sections.append(yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True, width=96))
        sections.append('\n')
    sections.append(EXAMPLES)
    return ''.join(sections)


def init_yml(root):
    root = Path(root).expanduser().resolve()
    for name in CONFIG_NAMES:
        if (root / name).exists():
            raise ConfigError(f'{root / name} already exists; initialization leaves existing configurations untouched.')
    path = root / '.kanitor.yml'
    text = render_yml()
    with path.open('x', encoding='utf-8') as file:
        file.write(text)
    return path
