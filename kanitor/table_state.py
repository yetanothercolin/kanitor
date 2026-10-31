"""Read-only typed column predicates and stable table sorting."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
import math
import re


def date_number(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip().replace('Z', '+00:00')).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def date_bounds(operator, first='', second='', today=None):
    today = today or datetime.now().astimezone().date()
    if operator == 'Today':
        start = end = today
    elif operator == 'Yesterday':
        start = end = today - timedelta(days=1)
    elif operator in ('Last 7 days', 'Last 30 days'):
        end = today
        start = today - timedelta(days=6 if operator == 'Last 7 days' else 29)
    else:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', first) or (operator == 'Between' and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', second)):
            raise ValueError('Use YYYY-MM-DD.')
        start = date.fromisoformat(first)
        end = date.fromisoformat(second) if operator == 'Between' else start
        if end < start:
            raise ValueError('End date must be on or after start date.')
    # Convert each local midnight independently so DST days need not be 24 hours.
    begin = datetime.combine(start, time.min).timestamp()
    finish = datetime.combine(end + timedelta(days=1), time.min).timestamp()
    if operator == 'Before':
        return None, begin
    if operator == 'After':
        return finish, None
    return begin, finish


@dataclass
class Criterion:
    kind: str
    value: object
    second: str = ''

    def matches(self, column, row, today=None):
        token = column.filter_token(row) if self.kind in ('only', 'exclude', 'enum') else None
        if self.kind == 'only':
            return token == self.value
        if self.kind == 'exclude':
            return token != self.value
        if self.kind == 'enum':
            return token in self.value
        if self.kind == 'string':
            value = column.raw_value(row)
            text = '' if value is None else value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
            if column.scope in ('task', 'activity') and column.canonical_field == 'task':
                text += ' ' + (row.get('description') or '')
            return self.value.casefold() in text.casefold()
        number = date_number(column.raw_value(row))
        if number is None:
            return False
        operator, first = self.value
        low, high = date_bounds(operator, first, self.second, today)
        return (low is None or number >= low) and (high is None or number < high)

    def label(self):
        if self.kind == 'enum':
            return f"{len(self.value)} value{'s' if len(self.value) != 1 else ''}"
        if self.kind == 'date':
            return ' '.join(str(v) for v in (*self.value, self.second) if v)
        return f'{self.kind}: {self.value}'


def sort_value(column, row):
    value = column.raw_value(row)
    if value is None or value == '':
        return None
    if column.is_date or column.filter_kind == 'date':
        number = date_number(value)
        return None if number is None else (0, number)
    if type(value) in (int, float):
        return (0, value) if type(value) is int or math.isfinite(value) else None
    if type(value) is bool:
        return (1, value)
    if isinstance(value, str):
        return (2, value.casefold())
    return (3, json.dumps(value, ensure_ascii=False, sort_keys=True))


class TableState:
    def __init__(self, default_sort=None):
        self.filters = {}
        self.default_sort = default_sort
        self.sort = default_sort

    def reconcile(self, columns):
        columns = list(columns)
        enabled = {}
        sortable = {}
        for column in columns:
            if column.can_filter:
                enabled.setdefault(column.key, column)
            if column.can_sort:
                sortable.setdefault(column.key, column)
        self.filters = {key: criterion for key, criterion in self.filters.items()
                        if key in enabled and enabled[key].can_filter
                        and (criterion.kind in ('only', 'exclude') or criterion.kind == enabled[key].filter_kind)}
        if self.sort and self.sort != self.default_sort:
            column = sortable.get(self.sort[0])
            if not column or not column.can_sort:
                self.sort = self.default_sort

    def apply(self, rows, columns, today=None):
        columns = list(columns)
        if today is None and any(criterion.kind == 'date' for criterion in self.filters.values()):
            today = datetime.now().astimezone().date()
        by_key = {}
        for column in columns:
            if column.can_filter:
                by_key.setdefault(column.key, column)
        result = [row for row in rows if all(
            criterion.matches(by_key[key], row, today)
            for key, criterion in self.filters.items() if key in by_key)]
        if self.sort:
            key, descending = self.sort
            column = next((c for c in columns if c.key == key and c.can_sort), None)
            if column is None and self.sort == self.default_sort:
                column = next((c for c in columns if c.key == key), None)
            if column:
                valid, missing = [], []
                for row in result:
                    value = sort_value(column, row)
                    (missing if value is None else valid).append(row if value is None else (value, row))
                result = [row for _, row in sorted(valid, key=lambda pair: pair[0], reverse=descending)] + missing
        return result
