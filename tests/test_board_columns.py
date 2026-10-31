import copy
import curses
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from kanitor.config import ConfigError, DEFAULT_BOARD_COLUMNS, DEFAULT_COLUMNS, parse_config
from kanitor.model import Explorer
from test_explorer import snapshot
import test_ui


class BoardColumnTests(unittest.TestCase):
    def test_board_rules_are_independent_of_global_and_per_board_task_rules(self):
        rules = parse_config({'boardColumns': [{'title': '', 'field': 'name', 'width': 'fill'}],
                              'boards': {'review': {'columns': [{'title': 'Work', 'field': 'id'}]}}})
        self.assertEqual(rules.for_board('index'), DEFAULT_COLUMNS)
        self.assertEqual(rules.for_board('review')[0].field, 'id')
        self.assertEqual(rules.board_columns[0].title, '')
        self.assertFalse(rules.board_columns[0].can_filter)
        self.assertEqual(parse_config({}).board_columns, DEFAULT_BOARD_COLUMNS)

    def test_invalid_board_rules_have_setting_paths(self):
        cases = [([], 'boardColumns'), ({}, 'boardColumns'),
                 ([{'title': 'Stage', 'field': 'status'}], '.field'),
                 ([{'title': 'Board', 'field': 'name', 'filterable': 1}], 'filterable'),
                 ([{'title': 'Owner', 'metadata': 'owner', 'field': 'slug'}], 'exactly one'),
                 ([{'title': 'Owner', 'metadata': ''}], '.metadata'),
                 ([{'title': 'Board', 'field': 'slug', 'width': 2}], '.width'),
                 ([{'title': 'Date', 'metadata': 'updated', 'format': 1}], '.format')]
        for value, fragment in cases:
            with self.subTest(value=value), self.assertRaises(ConfigError) as caught:
                parse_config({'boardColumns': value})
            self.assertIn('.kanitor.json: boardColumns', str(caught.exception))
            self.assertIn(fragment, str(caught.exception))

    def test_board_summaries_use_native_workflow_and_leave_snapshots_unchanged(self):
        data = snapshot()
        original = copy.deepcopy(data)
        explorer = Explorer()
        explorer.apply(data)
        explorer.search('no matches')
        row = explorer.board_rows[0]
        self.assertEqual({key: row[key] for key in ('cards', 'active', 'done', 'remaining')},
                         {'cards': 3, 'active': 1, 'done': 1, 'remaining': 1})
        self.assertEqual(explorer.board_rows[1]['remaining'], 1)
        self.assertEqual(data, original)

    def test_metadata_uses_exact_board_frontmatter_keys_and_date_rules(self):
        columns = parse_config({'boardColumns': [
            {'title': 'Owner', 'metadata': 'review.owner', 'width': 'hug'},
            {'title': 'Updated', 'metadata': 'updated', 'format': '%Y-%m-%d %H:%M'}]}).board_columns
        board = {'options': {'review.owner': ['Alex', 'Sam'], 'updated': '2026-10-23T16:01:00'},
                 'metadata': {'review.owner': 'wrong source'}}
        self.assertEqual(columns[0].value(board), '["Alex", "Sam"]')
        self.assertEqual(columns[1].value(board), '2026-10-23 16:01')
        self.assertEqual(columns[0].value({'options': {}}), '—')

    def test_custom_board_layout_renders_and_navigation_still_uses_slugs(self):
        app = test_ui.UITests().app(start_in_board=False)
        data = snapshot()
        data['boards'][0]['options']['owner'] = 'Alex'
        data['customization'] = {'boardColumns': [
            {'title': 'Owner', 'metadata': 'owner', 'width': 'hug'},
            {'title': '', 'field': 'slug', 'width': 'hug'},
            {'title': 'Left', 'field': 'remaining', 'width': 'hug'},
            {'title': 'Project', 'field': 'name', 'width': 'fill'}]}
        app.explorer.apply(data)
        app.draw()
        text = app.screen.text()
        header = text.splitlines()[4]
        self.assertLess(header.index('Owner'), header.index('Left'))
        self.assertLess(header.index('Left'), header.index('Project'))
        self.assertNotIn('CARDS', header)
        self.assertIn('Alex', text)
        self.assertIn('index', text)
        self.assertEqual(app.filter_headers, [])
        app.handle(curses.KEY_DOWN)
        self.assertEqual(app.explorer.board_slug, 'review')
        app.handle('\n')
        app.draw()
        self.assertEqual(app.view, 'tasks')
        self.assertIn('STATUS', app.screen.text())
        app.back_to_boards()
        data['customization'] = {}
        app.explorer.apply(data)
        app.draw()
        self.assertEqual(app.explorer.board_slug, 'review')
        self.assertIn('CARDS', app.screen.text().splitlines()[4])

    def test_board_layout_handles_unicode_hiding_and_small_terminal(self):
        app = test_ui.UITests().app(16, 60, start_in_board=False)
        data = snapshot()
        data['boards'][0]['options']['owner'] = '日本語'
        data['customization'] = {'boardColumns': [
            {'title': '', 'metadata': 'owner', 'width': 'hug'},
            {'title': 'Board', 'field': 'name', 'width': 'fill'}]}
        app.explorer.apply(data)
        app.draw()
        self.assertIn('日本語', app.screen.text())
        self.assertEqual(app.hidden_columns, 0)
        data['customization']['boardColumns'] = [{'title': 'Name', 'field': 'name', 'width': 20}] * 30
        app.explorer.apply(data)
        app.draw()
        self.assertGreater(app.hidden_columns, 0)
        self.assertIn('columns hidden', app.screen.text())

    def test_board_date_display_tracks_thresholds(self):
        app = test_ui.UITests().app(start_in_board=False)
        data = snapshot()
        now = datetime(2026, 10, 23, 16, 1).astimezone()
        data['boards'][0]['options']['updated'] = now.isoformat()
        data['customization'] = {'boardColumns': [{'title': 'Updated', 'metadata': 'updated',
            'format': '%d %b', 'thresholds': [{'under': '1d', 'format': '%H:%M'}]}]}
        app.explorer.apply(data)
        with patch('kanitor.ui.datetime') as clock:
            clock.now.return_value = now
            self.assertIn('16:01', app.date_display_signature()[0])
            clock.now.return_value = now + timedelta(days=1)
            self.assertIn('23 Oct', app.date_display_signature()[0])

    def test_hug_status_header_reserves_only_visible_text_and_square_gap_is_one(self):
        app = test_ui.UITests().app()
        data = snapshot()
        for card in data['boards'][0]['tasks']:
            card['column'] = 'Done'
        data['boards'][0]['columns'] = ['Done']
        data['customization'] = {'columns': [
            {'title': 'Status', 'field': 'status', 'width': 'hug'},
            {'title': 'Updated', 'metadata': 'updated', 'width': 'hug'},
            {'title': 'Task', 'field': 'name', 'width': 'fill'}]}
        app.explorer.apply(data)
        app.draw()
        placed, _ = app.table_layout()
        self.assertEqual([width for _, width in placed[:2]], [6, 7])
        lines = app.screen.text().splitlines()
        self.assertEqual(lines[5][3:9], '□ Done')
        self.assertEqual(lines[4].index('Status'), 5)
        self.assertEqual(lines[4].index('Updated'), 12)
        app.explorer.toggle_status('Done')
        app.draw()
        self.assertEqual(app.table_layout()[0][0][1], 7)
        self.assertIn('Status▾', app.screen.text().splitlines()[4])
