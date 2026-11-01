from copy import deepcopy
import curses
from unittest.mock import patch

from kanitor.config import ConfigError, layout_columns, parse_config
import test_activity
from test_projects import ProjectFixture

NOW, date = test_activity.NOW, test_activity.date


class StatusSquareTests(ProjectFixture):
    task_app = test_activity.ActivityTests.task_app
    draw = test_activity.ActivityTests.draw
    def test_status_square_configuration_and_compact_width(self):
        for setting, attribute in (('columns', 'columns'), ('activityColumns', 'activity_columns')):
            rules = parse_config({setting: [{'title': '', 'field': 'status_square', 'width': 'hug'}]})
            column = getattr(rules, attribute)[0]
            self.assertFalse(column.can_filter or column.can_sort)
            self.assertEqual(layout_columns([column], 80, 70)[0][0][1], 1)
            for extra in ({'filterable': True}, {'sortable': True}, {'format': '%Y'}, {'filterType': 'enum'}):
                with self.subTest(setting=setting, extra=extra), self.assertRaisesRegex(ConfigError, 'status_square'):
                    parse_config({setting: [{'title': '', 'field': 'status_square', **extra}]})

    def test_tasks_can_reorder_omit_and_focus_square_without_changing_native_data(self):
        app = self.task_app('tasks')
        app.colors.update(active=0x100, done=0x200, dim=0x400)
        data = {'boards': app.explorer.boards, 'customization': {'columns': [
            {'title': 'Task', 'field': 'task', 'width': 30},
            {'title': '', 'field': 'status_square', 'width': 'hug'}]}}
        app.explorer.apply(data)
        before = deepcopy(app.explorer.boards)
        self.draw(app)
        squares = [(y, x, size, identity) for y, x, size, identity, index in app.cell_hits if index == 1]
        self.assertEqual([app.screen.grid[y][x] for y, x, _, _ in squares], ['□', '□', '■'])
        for (y, x, size, _), color in zip(squares, (0x200, 0x100, 0x200)):
            self.assertEqual(size, 1)
            self.assertTrue(app.screen.attributes[y][x] & color)
        self.assertEqual(squares[0][1], 34)  # No reserved square before Task.
        self.assertEqual(app.screen.grid[5][3], 'R')
        app.handle(curses.KEY_RIGHT)
        self.draw(app)
        self.assertTrue(app.screen.attributes[squares[0][0]][squares[0][1]] & curses.A_REVERSE)
        app.handle('\n')
        self.assertEqual(app.popup, ('card', 'one'))
        app.handle('\x1b')
        data['customization']['columns'].pop()
        app.explorer.apply(data)
        self.draw(app)
        self.assertFalse(any(column.field == 'status_square' for column, _ in app.cell_columns))
        self.assertNotIn('■', app.screen.text())
        self.assertNotIn('□', app.screen.text())
        self.assertEqual(app.explorer.boards, before)

    def test_activity_square_uses_native_workflow_and_historical_style(self):
        app = self.task_app()
        task = app.explorer.board['tasks'][2]
        task['metadata']['completed'] = date(NOW - 20)
        app.explorer.column_rules = parse_config({'activityColumns': [
            {'title': '', 'field': 'status_square', 'width': 'hug'},
            {'title': 'Task', 'field': 'task', 'width': 'fill'}]})
        app.colors.update(active=0x100, done=0x200)
        with patch('kanitor.activity.time.time', return_value=NOW):
            app.handle('a')
            app.handle('\t')
        with patch('kanitor.ui.time.monotonic', return_value=.7):
            self.draw(app)
        self.assertEqual([r['id'] for r in app.activity.rows], ['two', 'three'])
        for y, x, size, identity, index in app.activity.cell_hits:
            if index == 0:
                self.assertEqual((size, app.screen.grid[y][x]), (1, '□' if identity[1] == 'two' else '■'))
                self.assertTrue(app.screen.attributes[y][x] & (0x100 if identity[1] == 'two' else 0x200))
                self.assertFalse(app.screen.attributes[y][x] & curses.A_DIM)
        app.handle(curses.KEY_LEFT)
        self.assertEqual(app.activity.columns[app.activity.focus.index][0].field, 'status_square')
        app.handle(curses.KEY_DOWN)
        self.draw(app)
        self.assertIn('Shipped card', app.screen.text())
        app.handle('\n')
        self.assertEqual(app.popup, ('card', 'three'))
        app.handle('\x1b')
        self.assertEqual(app.activity.selected, (str(app.root), 'three'))
