import copy
from datetime import date, datetime
import os
import time
import unittest
from unittest.mock import patch

from kanitor.config import Column, ConfigError, layout_columns, parse_config
from kanitor.model import Explorer
from kanitor.table_state import Criterion, TableState, date_bounds
from test_explorer import snapshot


class TableStateTests(unittest.TestCase):
    def test_migrating_name_alias_to_explicit_field_preserves_filters_and_sort(self):
        rows = [{'id': 'a', 'name': 'Alpha', 'description': 'Unique body'},
                {'id': 'b', 'name': 'Beta'}]
        for scope, field in (('project', 'project'), ('board', 'board'),
                             ('task', 'task'), ('activity', 'task')):
            with self.subTest(scope=scope):
                alias = Column('Name', field='name', scope=scope, filterable=True, sortable=True)
                explicit = Column('Name', field=field, scope=scope, filterable=True, sortable=True)
                state = TableState()
                state.filters[alias.key] = Criterion('string', 'alpha')
                state.sort = (alias.key, True)
                state.reconcile([explicit])
                self.assertEqual(state.sort, (explicit.key, True))
                self.assertEqual(state.filters[explicit.key].value, 'alpha')
                self.assertEqual(state.apply(rows, [explicit]), rows[:1])
                if scope in ('task', 'activity'):
                    state.filters[explicit.key] = Criterion('string', 'unique body')
                    self.assertEqual(state.apply(rows, [explicit]), rows[:1])

    def test_defaults_and_capability_validation_across_scopes(self):
        rules = parse_config({})
        self.assertEqual([(c.can_filter, c.can_sort, c.filter_kind) for c in rules.columns],
                         [(False, False, 'enum'), (True, False, 'enum'), (True, True, 'date'), (True, True, 'enum'), (True, False, 'string')])
        for scope in ('columns', 'boardColumns', 'projectColumns'):
            column = parse_config({scope: [{'title': '', 'field': 'name', 'filterable': True, 'sortable': True, 'filterType': 'enum'}]})
            columns = column.columns if scope == 'columns' else column.board_columns if scope == 'boardColumns' else column.project_columns
            self.assertEqual((columns[0].can_filter, columns[0].can_sort, columns[0].filter_kind), (True, True, 'enum'))
            for bad in ({'sortable': 1}, {'filterType': 'numeric'}):
                with self.assertRaises(ConfigError):
                    parse_config({scope: [{'title': 'Bad', 'field': 'name', **bad}]})
        for scope in ('boardColumns', 'projectColumns'):
            for flag in ('filterable', 'sortable'):
                with self.assertRaisesRegex(ConfigError, 'task_squares'):
                    parse_config({scope: [{'title': 'Tasks', 'field': 'task_squares', flag: True}]})

    def test_raw_typed_quick_filters_and_future_excluded_values(self):
        column = Column('Value', metadata='value', filterable=True)
        rows = [{'metadata': {'value': value}} for value in (0, False, '0', None, '', {'b': 1, 'a': 2})]
        state = TableState()
        state.filters[column.key] = Criterion('only', column.filter_token(rows[0]))
        self.assertEqual(state.apply(rows, [column]), rows[:1])
        state.filters[column.key] = Criterion('exclude', column.filter_token(rows[0]))
        future = {'metadata': {'value': 'future'}}
        self.assertEqual(state.apply(rows + [future], [column]), rows[1:] + [future])
        state.filters[column.key] = Criterion('only', column.filter_token(rows[3]))
        self.assertEqual(state.apply(rows, [column]), rows[3:5])

    def test_search_body_and_enum_and_global_query_compose(self):
        explorer = Explorer()
        data = snapshot()
        data['boards'][0]['tasks'][1]['description'] = 'Full body UNIQUE WORD'
        explorer.apply(data)
        name = explorer.column_rules.columns[-1]
        status = explorer.column_rules.columns[1]
        explorer.task_state.filters[name.key] = Criterion('string', 'unique word')
        explorer.task_state.filters[status.key] = Criterion('enum', {status.filter_token(explorer.board['tasks'][1])})
        self.assertEqual([r['id'] for r in explorer.rows], ['two'])
        explorer.search('café')
        self.assertEqual([r['id'] for r in explorer.rows], ['two'])
        explorer.search('absent')
        self.assertFalse(explorer.rows)

    def test_stable_typed_sort_missing_last_both_directions_and_reset(self):
        column = Column('Value', metadata='value', sortable=True)
        rows = [{'id': i, 'metadata': {'value': value}} for i, value in enumerate((None, 'b', 12, 2, 'A', 'a', '', {'b': 1, 'a': 2}))]
        state = TableState()
        state.sort = (column.key, False)
        self.assertEqual([r['id'] for r in state.apply(rows, [column])], [3, 2, 4, 5, 1, 7, 0, 6])
        state.sort = (column.key, True)
        self.assertEqual([r['id'] for r in state.apply(rows, [column])], [7, 1, 4, 5, 2, 3, 0, 6])
        state.sort = state.default_sort
        self.assertEqual(state.apply(rows, [column]), rows)

    def test_dates_sort_chronologically_across_offsets_invalid_last(self):
        column = Column('Date', metadata='updated')
        rows = [{'metadata': {'updated': value}} for value in ('invalid', '2026-10-28T12:00:00+02:00', '2026-10-28T09:30:00Z', None)]
        state = TableState((column.key, False))
        self.assertEqual(state.apply(rows, [column]), [rows[2], rows[1], rows[0], rows[3]])

    def test_calendar_presets_boundaries_and_strict_dates(self):
        today = date(2026, 10, 28)
        column = Column('Date', metadata='updated')
        rows = [{'metadata': {'updated': value}} for value in ('2026-10-28T00:00:00', '2026-10-28T23:59:59', '2026-10-29T00:00:00', 'bad', '2026-10-22T00:00:00', '2026-10-21T23:59:59')]
        criterion = Criterion('date', ('Today', ''))
        self.assertEqual([r for r in rows if criterion.matches(column, r, today)], rows[:2])
        criterion = Criterion('date', ('Last 7 days', ''))
        self.assertEqual([r for r in rows if criterion.matches(column, r, today)], rows[:2] + [rows[4]])
        self.assertEqual(date_bounds('Before', '2026-10-28')[1], date_bounds('On', '2026-10-28')[0])
        self.assertEqual(date_bounds('After', '2026-10-28')[0], date_bounds('On', '2026-10-29')[0])
        self.assertEqual(date_bounds('Between', '2026-10-27', '2026-10-28'), (date_bounds('On', '2026-10-27')[0], date_bounds('On', '2026-10-28')[1]))
        for first, second in (('20261028', ''), ('2026-02-30', ''), ('2026-10-28', '2026-10-27')):
            with self.assertRaises(ValueError):
                date_bounds('Between' if second else 'On', first, second)

    def test_local_midnights_follow_dst(self):
        if not hasattr(time, 'tzset'):
            self.skipTest('tzset unavailable')
        original = os.environ.get('TZ')
        try:
            os.environ['TZ'] = 'America/Los_Angeles'
            time.tzset()
            for day, hours in (('2026-03-08', 23), ('2026-11-01', 25)):
                low, high = date_bounds('On', day)
                self.assertEqual(high - low, hours * 3600)
        finally:
            if original is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = original
            time.tzset()

    def test_boards_default_recent_tasks_stay_native_and_snapshots_unmodified(self):
        data = snapshot()
        data['boards'][0]['updated'] = '2026-10-27T10:00:00Z'
        data['boards'][1]['updated'] = '2026-10-28T10:00:00Z'
        original = copy.deepcopy(data)
        explorer = Explorer()
        explorer.apply(data)
        self.assertEqual([r['slug'] for r in explorer.board_rows], ['review', 'index'])
        self.assertEqual(explorer.board_slug, 'review')
        explorer.select_board('index')
        self.assertEqual([r['id'] for r in explorer.rows], ['one', 'two', 'three'])
        self.assertEqual(data, original)

    def test_markers_size_only_when_active(self):
        column = Column('Name', field='name', width='hug', sortable=True)
        self.assertEqual(column.heading(), 'Name')
        self.assertEqual(column.heading(True, False), 'Name▾↑')
        placed, _ = layout_columns([column], 80, 40, [], filtered={column.key}, sorting=(column.key, True))
        self.assertEqual(placed[0][1], 6)
