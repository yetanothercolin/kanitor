"""Board-local workflow state and explorer navigation; no filesystem writes."""
import json
from collections import Counter
from pathlib import Path

from .config import CONFIG_NAMES, Column, ColumnRules, MISSING_VALUE, parse_config
from .table_state import TableState

BOARD_UPDATED = Column('UPDATED', field='updated', scope='board')


def find_root(start):
    """Find the closest conventional workspace, or let the native API explain failure."""
    start = Path(start).expanduser().resolve()
    if start.name == '.kanbn':
        return start.parent
    for folder in (start, *start.parents):
        if any((folder / name).exists() for name in ('.kanbn', 'kanbn.json', 'kanbn.yml', *CONFIG_NAMES, '.kanitor/work/events.jsonl')):
            return folder
    return start


def state(board, column):
    options = board.get('options', {})
    if column in options.get('completedColumns', []):
        return 'done'
    if column in options.get('startedColumns', []):
        return 'active'
    return 'remaining'


def counts(board):
    result = dict(done=0, active=0, remaining=0)
    for task in board['tasks']:
        result[state(board, task['column'])] += 1
    return result


def display(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def card_details(card):
    lines = [card['name'], '', f"ID: {card['id']}",
             f"Board: {card['board']}    Column: {card['column']}", '', 'METADATA']
    lines.extend(f'{key}: {display(value)}' for key, value in card.get('metadata', {}).items())
    if not card.get('metadata'):
        lines.append('No metadata.')
    lines.extend(['', 'DESCRIPTION', card.get('description') or 'No description.'])
    checks = card.get('subTasks', [])
    if checks:
        lines.extend(['', f"CHECKLIST · {sum(bool(c.get('completed')) for c in checks)}/{len(checks)}"])
        lines.extend(f"[{'x' if item.get('completed') else ' '}] {item.get('text', '')}" for item in checks)
    for title, key in [('RELATIONS', 'relations'), ('COMMENTS', 'comments'), ('HISTORY', 'history')]:
        entries = card.get(key, [])
        if entries:
            lines.extend(['', title])
        for entry in entries:
            if key == 'relations':
                lines.append(f"{entry.get('type') or 'related'}: {entry.get('task', '')}")
            elif key == 'comments':
                lines.extend([f"{entry.get('date', '')} · {entry.get('author') or 'anonymous'}", entry.get('text', ''), ''])
            else:
                lines.append(' · '.join(f'{k}: {display(v)}' for k, v in entry.items()))
    return '\n'.join(lines)


class Explorer:
    def __init__(self, board_slug=None):
        self.boards = []
        self.board_slug = board_slug
        self.statuses = None
        self.query = ''
        self.selected_id = None
        self.column_rules = ColumnRules()
        self.column_filters = {}
        self.task_state = TableState()
        self.board_state = TableState((BOARD_UPDATED.key, True))

    @property
    def board(self):
        return next((b for b in self.boards if b['slug'] == self.board_slug), None)

    @property
    def board_rows(self):
        """Display summaries without adding computed fields to native snapshots."""
        return self.board_state.apply(self.board_universe, self.board_state_columns)

    @property
    def board_universe(self):
        return [dict(board, cards=len(board['tasks']), **counts(board)) for board in self.boards]

    @property
    def board_state_columns(self):
        columns = self.column_rules.board_columns
        return columns if any(c.key == BOARD_UPDATED.key for c in columns) else (*columns, BOARD_UPDATED)

    @property
    def display_boards(self):
        return self.board_rows

    @property
    def task_state_columns(self):
        columns = self.column_rules.for_board(self.board_slug)
        status = self.status_filter_column
        return (*columns, status) if status and not any(c.key == status.key for c in columns) else columns

    @property
    def rows(self):
        if not self.board:
            return []
        words = self.query.casefold().split()
        filters = [(column, self.column_filters[column.key]) for column in self.filter_columns
                   if column.key in self.column_filters]
        rows = [card for card in self.board['tasks']
                if (self.statuses is None or card['column'] in self.statuses)
                and all(column.filter_token(card) in selected for column, selected in filters)
                and all(word in self.search_text(card) for word in words)]
        return self.task_state.apply(rows, self.task_state_columns)

    @staticmethod
    def search_text(card):
        return ' '.join(display(card.get(key, '')) for key in
                        ('id', 'name', 'column', 'description', 'metadata')).casefold()

    @property
    def selected(self):
        return next((card for card in self.rows if card['id'] == self.selected_id), None)

    def reconcile(self):
        self.board_state.reconcile(self.board_state_columns)
        if not self.board:
            self.board_slug = self.board_rows[0]['slug'] if self.board_rows else None
            self.statuses = None
            self.column_filters = {}
        self.task_state.reconcile(self.task_state_columns)
        if self.board and self.statuses is not None:
            self.statuses.intersection_update(self.board['columns'])
        if self.status_filter_column is None:
            self.statuses = None
        columns = {column.key: column for column in self.filter_columns}
        for key in list(self.column_filters):
            if key not in columns:
                del self.column_filters[key]
            else:
                self.column_filters[key].intersection_update(token for token, _ in self.filter_options(columns[key]))
        rows = self.rows
        if not any(card['id'] == self.selected_id for card in rows):
            self.selected_id = rows[0]['id'] if rows else None

    def apply(self, snapshot):
        previous = self.rows
        selected = self.selected_id
        index = next((i for i, row in enumerate(previous) if row['id'] == self.selected_id), 0)
        previous_boards = self.board_rows
        board_slug = self.board_slug
        board_index = next((i for i, row in enumerate(previous_boards) if row['slug'] == board_slug), 0)
        rules = parse_config(snapshot.get('customization', {}))
        self.boards = snapshot['boards']
        self.column_rules = rules
        self.reconcile()
        boards = self.board_rows
        if board_slug and not any(row['slug'] == board_slug for row in boards) and boards:
            self.select_board(boards[min(board_index, len(boards) - 1)]['slug'])
        if previous and not any(row['id'] == selected for row in self.rows):
            rows = self.rows
            self.selected_id = rows[min(index, len(rows) - 1)]['id'] if rows else None

    def select_board(self, slug):
        if slug != self.board_slug:
            self.board_slug, self.statuses, self.selected_id = slug, None, None
            self.column_filters = {}
            self.task_state = TableState()
            self.reconcile()

    def move_board(self, delta):
        boards = self.display_boards
        if boards:
            index = next((i for i, b in enumerate(boards) if b['slug'] == self.board_slug), 0)
            self.select_board(boards[(index + delta) % len(boards)]['slug'])

    def move_task(self, delta):
        rows = self.rows
        if rows:
            index = next((i for i, card in enumerate(rows) if card['id'] == self.selected_id), 0)
            self.selected_id = rows[max(0, min(len(rows) - 1, index + delta))]['id']

    @property
    def enabled_statuses(self):
        return set(self.board['columns']) if self.board and self.statuses is None else set(self.statuses or ())

    @property
    def filter_columns(self):
        columns = self.column_rules.for_board(self.board_slug)
        # Repeated source columns share one filter, independent of their headings.
        unique = {}
        for column in columns:
            if column.can_filter and column.field != 'status':
                unique.setdefault(column.key, column)
        return list(unique.values())

    @property
    def status_filter_column(self):
        columns = [c for c in self.column_rules.for_board(self.board_slug) if c.field == 'status']
        return next((c for c in columns if c.can_filter), None) if columns else Column('STATUS', field='status')

    def filter_column(self, key):
        if key == ('field', 'status'):
            return self.status_filter_column
        return next((c for c in self.filter_columns if c.key == key), None)

    def filter_options(self, column):
        if not self.board:
            return []
        if column.field == 'status':
            return [(name, name) for name in self.board['columns']]
        options = {column.filter_token(card): column.value(card) for card in self.board['tasks']}
        if MISSING_VALUE in options:
            options[MISSING_VALUE] = '(Missing)'
        # Distinguish values such as the number 0 and the string "0" when needed.
        labels = Counter(options.values())
        for token, label in list(options.items()):
            if token != MISSING_VALUE and labels[label] > 1:
                value = json.loads(token)
                kind = 'text' if isinstance(value, str) else 'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (int, float)) else 'array' if isinstance(value, list) else 'object'
                options[token] = f'{label} ({kind})'
        return sorted(options.items(), key=lambda item: (item[0] == MISSING_VALUE, item[1].casefold(), item[0]))

    def is_filtered(self, column):
        return column.key in self.task_state.filters or (self.statuses is not None if column.field == 'status' else column.key in self.column_filters)

    def enabled_filter_values(self, column):
        if column.field == 'status':
            return self.enabled_statuses
        return set(self.column_filters[column.key]) if column.key in self.column_filters else {token for token, _ in self.filter_options(column)}

    def toggle_filter_value(self, column, token):
        if not self.filter_column(column.key):
            return
        if column.field == 'status':
            self.toggle_status(token)
            return
        available = {key for key, _ in self.filter_options(column)}
        if token not in available:
            return
        selected = self.enabled_filter_values(column)
        selected.symmetric_difference_update({token})
        if selected == available:
            self.column_filters.pop(column.key, None)
        else:
            self.column_filters[column.key] = selected
        self.reconcile()

    def toggle_all_filter_values(self, column):
        if not self.filter_column(column.key):
            return
        if column.field == 'status':
            self.toggle_all_statuses()
            return
        if column.key in self.column_filters:
            del self.column_filters[column.key]
        else:
            self.column_filters[column.key] = set()
        self.reconcile()

    @property
    def filter_summary(self):
        parts = [self.status_summary]
        for column in self.filter_columns:
            if column.key in self.column_filters:
                selected = self.enabled_filter_values(column)
                labels = [label for token, label in self.filter_options(column) if token in selected]
                parts.append(f"{column.label}: {', '.join(labels) if labels else 'No values'}")
        columns = {c.key: c for c in self.task_state_columns}
        parts.extend(f'{columns[key].label}: {criterion.label()}' for key, criterion in self.task_state.filters.items() if key in columns and key != ('field', 'status'))
        return ' · '.join(parts)

    @property
    def status_summary(self):
        column = self.status_filter_column
        criterion = self.task_state.filters.get(('field', 'status'))
        if column and criterion and self.board:
            names = [name for name in self.board['columns'] if criterion.matches(column, {'column': name})]
            return ', '.join(names) or 'No statuses'
        if self.statuses is None:
            return 'All statuses'
        return ', '.join(column for column in self.board['columns'] if column in self.statuses) if self.statuses else 'No statuses'

    def toggle_status(self, column):
        if not self.board or column not in self.board['columns']:
            return
        selected = self.enabled_statuses
        selected.symmetric_difference_update({column})
        self.statuses = None if selected == set(self.board['columns']) else selected
        self.reconcile()

    def toggle_all_statuses(self):
        self.statuses = set() if self.statuses is None else None
        self.reconcile()

    def search(self, query):
        self.query = query
        self.reconcile()


def plain_snapshot(snapshot, explorer):
    lines = [f"KANITOR · {snapshot['root']} · READ ONLY", '', 'BOARDS']
    for board in explorer.boards:
        totals = counts(board)
        lines.append(f"{board['slug']}: {board['name']} · {len(board['tasks'])} cards · {totals['done']} done · {totals['active']} active")
    if explorer.board:
        lines.extend(['', f"{explorer.board_slug} * {explorer.filter_summary}"])
        lines.extend(f"[{card['column']}] {card['name']} ({card['id']})" for card in explorer.rows)
        if not explorer.rows:
            lines.append('No matching tasks.' if explorer.query or explorer.statuses is not None or explorer.column_filters else 'This board has no tasks yet.')
    return '\n'.join(lines)
