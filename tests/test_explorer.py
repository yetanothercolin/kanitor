import copy
from pathlib import Path
import tempfile
import unittest

from kanitor.model import Explorer, card_details, counts, find_root, state


def snapshot():
    return {'boards': [
        {'slug': 'index', 'name': 'Example', 'options': {'startedColumns': ['Building'], 'completedColumns': ['Shipped']},
         'columns': ['Queue', 'Building', 'Shipped'], 'tasks': [
             {'id': 'one', 'name': 'Reopened card', 'board': 'index', 'column': 'Queue',
              'metadata': {'completed': '2026-10-21', 'assigned': 'Alex', 'tags': ['backend']},
              'subTasks': [{'text': 'All checked', 'completed': True}]},
             {'id': 'two', 'name': 'Search café 日本語', 'board': 'index', 'column': 'Building',
              'metadata': {'assigned': 'Morgan'}, 'description': 'Inspect native metadata'},
             {'id': 'three', 'name': 'Shipped card', 'board': 'index', 'column': 'Shipped', 'metadata': {}}]},
        {'slug': 'review', 'name': 'Review', 'options': {}, 'columns': ['Done'],
         'tasks': [{'id': 'one', 'name': 'Reopened card', 'board': 'review', 'column': 'Done', 'metadata': {}}]}
    ]}


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.data = snapshot()
        self.explorer = Explorer()
        self.explorer.apply(self.data)

    def test_native_column_authority_and_no_inferred_completion(self):
        self.assertEqual(counts(self.explorer.board), {'done': 1, 'active': 1, 'remaining': 1})
        self.assertEqual(state(self.data['boards'][1], 'Done'), 'remaining')
        self.assertEqual(state(self.explorer.board, 'Queue'), 'remaining')

    def test_search_metadata_unicode_and_multiple_words(self):
        self.explorer.search('ALEX BACKEND')
        self.assertEqual([c['id'] for c in self.explorer.rows], ['one'])
        self.explorer.search('日本語 café')
        self.assertEqual(self.explorer.selected_id, 'two')
        self.explorer.search('native Morgan')
        self.assertEqual(self.explorer.selected_id, 'two')
        self.explorer.toggle_all_statuses()
        self.assertEqual(self.explorer.rows, [])
        self.explorer.toggle_status('Building')
        self.assertEqual(self.explorer.selected_id, 'two')

    def test_selection_survives_reorder_and_falls_back_on_removal(self):
        self.explorer.move_task(1)
        updated = copy.deepcopy(self.data)
        updated['boards'][0]['tasks'].reverse()
        self.explorer.apply(updated)
        self.assertEqual(self.explorer.selected_id, 'two')
        updated['boards'][0]['tasks'] = [updated['boards'][0]['tasks'][0]]
        self.explorer.apply(updated)
        self.assertEqual(self.explorer.selected_id, 'three')
        updated['boards'] = updated['boards'][1:]
        self.explorer.apply(updated)
        self.assertEqual(self.explorer.board_slug, 'review')
        self.assertIsNone(self.explorer.statuses)

    def test_multiple_statuses_empty_selection_and_live_column_changes(self):
        self.explorer.toggle_status('Building')
        self.assertEqual([card['id'] for card in self.explorer.rows], ['one', 'three'])
        self.explorer.toggle_status('Queue')
        self.assertEqual([card['id'] for card in self.explorer.rows], ['three'])
        self.explorer.toggle_status('Shipped')
        self.assertEqual(self.explorer.status_summary, 'No statuses')
        self.assertEqual(self.explorer.rows, [])
        self.explorer.toggle_status('Queue')
        updated = copy.deepcopy(self.data)
        updated['boards'][0]['columns'].remove('Queue')
        updated['boards'][0]['tasks'] = updated['boards'][0]['tasks'][1:]
        self.explorer.apply(updated)
        self.assertEqual(self.explorer.enabled_statuses, set())
        self.explorer.toggle_all_statuses()
        self.assertIsNone(self.explorer.statuses)
        self.assertEqual(len(self.explorer.rows), 2)

    def test_board_membership_and_empty_filters(self):
        self.explorer.select_board('review')
        self.assertEqual(self.explorer.selected['column'], 'Done')
        self.explorer.search('nothing matches')
        self.assertIsNone(self.explorer.selected)
        self.explorer.move_task(100)
        self.explorer.search('')
        self.explorer.move_board(-1)
        self.assertEqual(self.explorer.selected['column'], 'Queue')

    def test_details_retain_custom_structures_and_native_sections(self):
        card = dict(self.explorer.selected, description='The description',
                    relations=[{'type': 'child-of', 'task': 'parent'}],
                    comments=[{'author': 'Morgan', 'date': 'today', 'text': 'Evidence'}],
                    history=[{'type': 'moved', 'fromColumn': 'Building', 'toColumn': 'Queue'}])
        text = card_details(card)
        for fragment in ('The description', '[x] All checked', 'child-of: parent', 'Evidence', 'fromColumn: Building', 'backend'):
            self.assertIn(fragment, text)

    def test_root_discovery_from_nested_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.kanbn').mkdir()
            child = root / 'src' / 'nested'
            child.mkdir(parents=True)
            self.assertEqual(find_root(child), root.resolve())
            self.assertEqual(find_root(root / '.kanbn'), root.resolve())

    def enable_owner_filter(self):
        self.data['customization'] = {'columns': [
            {'title': 'Status', 'field': 'status'},
            {'title': 'Owner', 'metadata': 'assigned', 'filterable': True},
            {'title': 'Task', 'field': 'name'}]}
        self.explorer.apply(self.data)
        return self.explorer.filter_columns[0]

    def test_custom_filter_combines_with_status_and_search_and_keeps_all_options(self):
        owner = self.enable_owner_filter()
        self.explorer.toggle_all_filter_values(owner)
        self.assertEqual(self.explorer.rows, [])
        for card in self.data['boards'][0]['tasks'][:2]:
            self.explorer.toggle_filter_value(owner, owner.filter_token(card))
        self.assertEqual([c['id'] for c in self.explorer.rows], ['one', 'two'])
        self.explorer.toggle_all_statuses()
        self.explorer.toggle_status('Queue')
        self.assertEqual([c['id'] for c in self.explorer.rows], ['one'])
        self.assertEqual([label for _, label in self.explorer.filter_options(owner)], ['Alex', 'Morgan', '(Missing)'])
        self.explorer.search('no match')
        self.assertEqual(self.explorer.rows, [])
        self.explorer.search('')
        self.assertEqual(self.explorer.selected_id, 'one')
        self.assertIn('Owner: Alex, Morgan', self.explorer.filter_summary)

    def test_filter_values_preserve_types_and_match_whole_arrays_and_objects(self):
        owner = self.enable_owner_filter()
        values = [0, '0', False, 'false', ['Alex', 'Morgan'], {'b': 2, 'a': 1}, None, '']
        template = self.data['boards'][0]['tasks'][0]
        self.data['boards'][0]['tasks'] = [dict(template, id=f'value-{i}', metadata={'assigned': value})
                                           for i, value in enumerate(values)]
        self.explorer.apply(self.data)
        options = self.explorer.filter_options(owner)
        self.assertEqual(len(options), 7)  # Missing/null/empty share a bucket.
        self.assertIn('0 (number)', [label for _, label in options])
        self.assertIn('0 (text)', [label for _, label in options])
        self.explorer.toggle_all_filter_values(owner)
        card = self.data['boards'][0]['tasks'][4]
        self.explorer.toggle_filter_value(owner, owner.filter_token(card))
        self.assertEqual([c['id'] for c in self.explorer.rows], ['value-4'])
        missing = self.data['boards'][0]['tasks'][6]
        self.explorer.toggle_filter_value(owner, owner.filter_token(missing))
        self.assertEqual([c['id'] for c in self.explorer.rows], ['value-4', 'value-6', 'value-7'])

    def test_filters_follow_live_rules_and_board_changes(self):
        owner = self.enable_owner_filter()
        self.explorer.toggle_all_filter_values(owner)
        self.explorer.toggle_filter_value(owner, owner.filter_token(self.data['boards'][0]['tasks'][0]))
        updated = copy.deepcopy(self.data)
        updated['customization']['columns'][1]['title'] = 'Assignee'
        updated['customization']['columns'][1]['width'] = 'hug'
        self.explorer.apply(updated)
        self.assertEqual([c['id'] for c in self.explorer.rows], ['one'])
        self.assertIn('Assignee: Alex', self.explorer.filter_summary)
        updated['customization']['columns'][1]['filterable'] = False
        self.explorer.apply(updated)
        self.assertFalse(self.explorer.column_filters)
        self.assertEqual(len(self.explorer.rows), 3)
        self.explorer.apply(self.data)
        self.explorer.toggle_all_filter_values(owner)
        self.explorer.select_board('review')
        self.assertFalse(self.explorer.column_filters)
        self.assertEqual(len(self.explorer.rows), 1)
