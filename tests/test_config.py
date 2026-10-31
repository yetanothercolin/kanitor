from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import patch

from kanitor.__main__ import main
from kanitor.config import Column, ConfigError, DEFAULT_COLUMNS, layout_columns, parse_config


class ColumnConfigTests(unittest.TestCase):
    def test_explicit_name_fields_and_legacy_aliases_share_values_and_identity(self):
        for scope, setting, field in (('project', 'projectColumns', 'project'),
                                      ('board', 'boardColumns', 'board'),
                                      ('task', 'columns', 'task'),
                                      ('activity', 'activityColumns', 'task')):
            with self.subTest(scope=scope):
                rules = parse_config({setting: [{'title': '', 'field': field}]})
                columns = getattr(rules, {'project': 'project_columns', 'board': 'board_columns',
                                         'task': 'columns', 'activity': 'activity_columns'}[scope])
                column = columns[0]
                alias = Column('', field='name', scope=scope)
                row = {'name': 'The display name'}
                self.assertEqual(column.value(row), 'The display name')
                self.assertEqual(column.key, ('field', field))
                self.assertEqual(column.value(row), alias.value(row))
                self.assertEqual(column.key, alias.key)
                self.assertEqual(column.label, alias.label)
                self.assertEqual(column.filter_kind, alias.filter_kind)
        defaults = parse_config({})
        self.assertEqual(defaults.project_columns[0].field, 'project')
        self.assertEqual(defaults.board_columns[1].field, 'board')
        self.assertEqual(defaults.columns[-1].field, 'task')
        self.assertEqual(defaults.activity_columns[-1].field, 'task')

    def test_defaults_and_exact_metadata_keys_preserve_values(self):
        self.assertEqual(parse_config({}).for_board('index'), DEFAULT_COLUMNS)
        card = {'name': 'A task', 'column': 'Ready', 'metadata': {
            'assignee': 'Morgan', 'review.owner': ['Alex', 'Sam'], 'priority': 0,
            'enabled': False, 'details': {'state': 'ready'}, 'empty': ''}}
        self.assertEqual(Column('Owner', metadata='assignee').value(card), 'Morgan')
        self.assertEqual(Column('Owner', metadata='assigned').value(card), '—')
        self.assertEqual(Column('Review', metadata='review.owner').value(card), '["Alex", "Sam"]')
        self.assertEqual(Column('Priority', metadata='priority').value(card), '0')
        self.assertEqual(Column('Enabled', metadata='enabled').value(card), 'false')
        self.assertEqual(Column('Details', metadata='details').value(card), '{"state": "ready"}')
        self.assertEqual(Column('Empty', metadata='empty').value(card), '—')
        self.assertEqual(Column('State', field='status').value(card), 'Ready')

    def test_global_rules_and_per_board_replacements(self):
        rules = parse_config({'columns': [
            {'title': 'Owner', 'metadata': 'assignee', 'width': 18},
            {'title': 'Work', 'field': 'name'}],
            'boards': {'releases': {'columns': [{'title': 'ID', 'field': 'id'}]}}})
        self.assertEqual([c.title for c in rules.for_board('index')], ['Owner', 'Work'])
        self.assertEqual([c.title for c in rules.for_board('releases')], ['ID'])
        self.assertEqual(rules.columns[0].width, 18)

    def test_invalid_rules_have_actionable_file_and_setting_errors(self):
        cases = [([], 'configuration'), ({'column': []}, 'column'),
                 ({'columns': []}, 'columns'),
                 ({'columns': [{'title': 'Owner', 'metadata': 'assignee', 'field': 'name'}]}, 'exactly one'),
                 ({'columns': [{'title': 'Owner', 'field': 'assignee'}]}, '.field'),
                 ({'columns': [{'title': 'Owner', 'metadata': ''}]}, '.metadata'),
                 ({'columns': [{'title': 'Bad\nTitle', 'field': 'name'}]}, '.title'),
                 ({'columns': [{'title': 'Task', 'field': 'name', 'width': True}]}, '.width'),
                 ({'columns': [{'title': 'Task', 'field': 'name', 'width': 0}]}, '.width'),
                 ({'columns': [{'title': 'Task', 'field': 'name', 'width': 'wide'}]}, '.width'),
                 ({'columns': [{'title': 'Task', 'field': 'name', 'width': []}]}, '.width'),
                 ({'columns': [{'field': 'name', 'width': 'fill'}]}, '.title'),
                 ({'columns': [{'title': 'Owner', 'metadata': 'assignee', 'filterable': 1}]}, '.filterable'),
                 ({'boards': {'index': {}}}, 'boards')]
        for value, fragment in cases:
            with self.subTest(value=value):
                with self.assertRaises(ConfigError) as caught:
                    parse_config(value)
                self.assertIn('.kanitor.json:', str(caught.exception))
                self.assertIn(fragment, str(caught.exception))

    def test_layout_shrinks_and_reports_hidden_columns(self):
        rules = parse_config({'columns': [
            {'title': 'Status', 'field': 'status', 'width': 20},
            {'title': 'Assignee', 'metadata': 'assignee', 'width': 20},
            {'title': 'Task', 'field': 'name'}]}).columns
        columns, hidden = layout_columns(rules, 60, 49)
        self.assertEqual(len(columns), 3)
        self.assertEqual(sum(width for _, width in columns) + 2, 49)
        self.assertEqual(hidden, 0)
        columns, hidden = layout_columns(rules * 20, 60, 49)
        self.assertGreater(hidden, 0)
        self.assertLessEqual(sum(width for _, width in columns) + len(columns) - 1, 49)

    def test_empty_headings_hug_unicode_values_and_fill_remaining_space(self):
        rules = parse_config({'columns': [
            {'title': '', 'metadata': 'owner', 'width': 'hug'},
            {'title': 'Priority', 'metadata': 'priority', 'width': 8},
            {'title': 'Task', 'field': 'name', 'width': 'fill'}]}).columns
        rows = [{'name': 'A task', 'metadata': {'owner': '日本語'}},
                {'name': 'Another task', 'metadata': {'owner': 'Alice'}}]
        columns, hidden = layout_columns(rules, 90, 60, rows)
        self.assertEqual([width for _, width in columns], [6, 8, 44])
        self.assertEqual(hidden, 0)
        self.assertEqual(rules[0].heading(), '')
        columns, _ = layout_columns(rules, 90, 60, rows[1:])
        self.assertEqual([width for _, width in columns], [5, 8, 45])

    def test_fill_columns_share_space_and_omitted_width_is_fill(self):
        rules = parse_config({'columns': [
            {'title': '', 'metadata': 'marker', 'width': 'hug'},
            {'title': 'First', 'field': 'name', 'width': 'fill'},
            {'title': 'Second', 'field': 'description'}]}).columns
        columns, _ = layout_columns(rules, 90, 50, [{'metadata': {'marker': 'x'}}])
        self.assertEqual([width for _, width in columns], [1, 24, 23])

    def test_hug_fits_headings_missing_values_and_status_filter_icon(self):
        rules = parse_config({'columns': [
            {'title': 'Owner', 'metadata': 'assignee', 'width': 'hug'},
            {'title': '', 'field': 'status', 'width': 'hug'}]}).columns
        columns, _ = layout_columns(rules, 90, 60, [{'column': 'Todo', 'metadata': {}}])
        self.assertEqual([width for _, width in columns], [5, 4])
        self.assertEqual(rules[1].heading(), '')
        self.assertEqual(rules[1].heading(filtered=True), '▾')
        columns, _ = layout_columns(rules, 90, 60)
        self.assertEqual([width for _, width in columns], [5, 1])

    def test_hug_clips_to_budget_under_terminal_pressure(self):
        rules = (Column('', metadata='owner', width='hug'), Column('Task', field='name', width='fill'))
        columns, hidden = layout_columns(rules, 60, 49, [{'metadata': {'owner': 'x' * 1000}}])
        self.assertEqual(sum(width for _, width in columns) + 1, 49)
        self.assertEqual(hidden, 0)

    def test_filterable_rule_controls_header_and_hug_indicator_width(self):
        rules = parse_config({'columns': [
            {'title': '', 'metadata': 'owner', 'width': 'hug', 'filterable': True},
            {'title': 'Stage', 'field': 'status', 'filterable': False}]}).columns
        self.assertTrue(rules[0].can_filter)
        self.assertEqual(rules[0].heading(filtered=True), '▾')
        self.assertFalse(rules[1].can_filter)
        self.assertEqual(rules[1].heading(filtered=True), 'Stage')
        placed, _ = layout_columns(rules, 90, 60, [{'metadata': {'owner': 'x'}}])
        self.assertEqual(placed[0][1], 1)
        placed, _ = layout_columns(rules, 90, 60, [{'metadata': {'owner': 'x'}}], filtered={rules[0].key})
        self.assertEqual(placed[0][1], 1)

    def test_agent_guide_needs_no_workspace_or_kanbn(self):
        output = io.StringIO()
        with patch('kanitor.__main__.read_once', side_effect=AssertionError('must not read kanbn')), redirect_stdout(output):
            self.assertEqual(main(['--agent-guide', '--root', '/nonexistent/workspace']), 0)
        self.assertIn('"metadata": "assignee"', output.getvalue())
        self.assertIn('.kanitor.json', output.getvalue())
        self.assertIn('AGENTS.md', output.getvalue())
