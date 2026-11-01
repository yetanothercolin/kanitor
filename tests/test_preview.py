import curses
from unittest.mock import patch

from kanitor.model import Explorer
from kanitor.ui import App, cells, wrap_lines
from test_explorer import snapshot
from test_projects import ProjectFixture
from test_ui import StyledScreen
from kanitor.mouse import WHEEL_DOWN, WHEEL_UP


class PreviewTests(ProjectFixture):
    def viewer(self, view):
        text = '\n'.join(f'Paragraph {i:02d} of the complete description.' for i in range(20))
        if view == 'projects':
            app = self.app(paths=('one',), height=40)
            self.fill(app)
            source = next(iter(app.children.values()))
        else:
            explorer = Explorer()
            explorer.apply(snapshot())
            app = App(StyledScreen(40, 110), self.root, explorer, view == 'tasks')
            self.addCleanup(app.close)
            source = app
        task = source.explorer.board['tasks'][1]
        task['description'] = text
        if view == 'activity':
            app.activity.shown = app.activity.focused = True
        elif view == 'tasks':
            app.explorer.selected_id = task['id']
        else:
            app.draw()
            _, _, identity, square = next(hit for hit in app.square_hits if hit[3].id == task['id'])
            app.focus_column(next(i for i, (column, _) in enumerate(app.cell_columns) if column.field == 'task_squares'))
            app.select_square(identity, square)
        app.draw()
        return app, task

    def mouse(self, app, buttons, *, x=None, y=None):
        top, left, height, _ = app.preview_rect
        self.mouse_at = getattr(self, 'mouse_at', 0) + 1
        with patch.object(app, 'get_mouse', return_value=(0, x or left + 5, y or top + min(3, height - 2), 0, buttons)), \
                patch('kanitor.preview.time.monotonic', return_value=self.mouse_at):
            app.handle(curses.KEY_MOUSE)

    def selection(self, app):
        return app.view, app.focused_row_id(), app.selected_square, app.activity.selected, app.activity.focused

    def test_context_separator_wheel_scrollbar_and_full_description_in_each_view(self):
        for view in ('tasks', 'boards', 'projects', 'activity'):
            with self.subTest(view=view):
                app, task = self.viewer(view)
                top = app.preview_rect[0]
                before = self.selection(app)
                context = ''.join(app.screen.grid[top + 1])
                self.assertIn('index · two · Building', context)
                self.assertIn('────', ''.join(app.screen.grid[top + 2]))
                self.assertIn('Paragraph 00', ''.join(app.screen.grid[top + 3]))
                self.assertEqual(app.preview_capacity, 4)
                self.mouse(app, WHEEL_DOWN)
                app.draw()
                self.assertEqual(app.preview_top, 3)
                self.assertIn('Paragraph 03', ''.join(app.screen.grid[top + 3]))
                self.assertEqual(''.join(app.screen.grid[top + 1]), context)
                bar = next(bar for bar in app.scrollbars if bar['kind'] == 'preview')
                self.mouse(app, curses.BUTTON1_PRESSED, x=bar['x'], y=bar['y'] + bar['height'] - 1)
                app.draw()
                self.assertEqual(app.preview_top, 7)
                for _ in range(30):
                    self.mouse(app, WHEEL_DOWN)
                app.draw()
                self.assertEqual(app.preview_top, 16)
                self.assertIn('Paragraph 19', app.screen.text())
                app.needs_redraw = False
                self.mouse(app, WHEEL_DOWN)
                self.assertFalse(app.needs_redraw)
                self.mouse(app, WHEEL_UP)
                self.assertEqual(app.preview_top, 13)
                self.assertEqual(self.selection(app), before)

    def test_preview_resets_for_new_task_and_clamps_live_edits_and_resizing(self):
        app, task = self.viewer('tasks')
        self.mouse(app, WHEEL_DOWN)
        app.draw()
        self.assertEqual(app.preview_top, 3)
        app.handle('p')
        app.draw()
        self.assertIsNone(app.preview_rect)
        app.handle('p')
        app.draw()
        self.assertEqual(app.preview_top, 3)
        task['description'] = 'Shorter updated description'
        app.draw()
        self.assertEqual(app.preview_top, 0)
        self.assertFalse(any(bar['kind'] == 'preview' for bar in app.scrollbars))
        task['description'] = '\n'.join(f'Line {i}' for i in range(30))
        app.draw()
        self.mouse(app, WHEEL_DOWN)
        app.draw()
        app.explorer.selected_id = 'one'
        app.draw()
        self.assertEqual(app.preview_top, 0)
        app.explorer.selected_id = 'two'
        app.draw()
        app.handle('r')
        for _ in range(30):
            app.handle(curses.KEY_DOWN)
        app.draw()
        self.assertEqual(app.preview_rect[2], 3)
        self.assertEqual(app.preview_capacity, 1)
        app.handle('r')
        self.mouse(app, WHEEL_DOWN)
        app.draw()
        self.assertIn('Line 3', app.screen.text())
        self.assertEqual(app.preview_top, 3)

    def test_resize_mode_captures_mouse_before_preview_and_context_clicks_do_not_focus(self):
        app, _ = self.viewer('boards')
        selection = self.selection(app)
        self.mouse(app, curses.BUTTON1_PRESSED, y=app.preview_rect[0] + 1)
        self.assertEqual(self.selection(app), selection)
        app.handle('r')
        geometry = app.pane_geometry
        self.mouse(app, WHEEL_DOWN)
        self.assertEqual(app.preview_top, 0)
        self.assertEqual(app.pane_geometry, geometry)

    def test_hanging_indentation_for_bullets_numbered_lists_and_checklists(self):
        for prefix in ('- ', '* ', '+ ', '• ', '12. ', '3) ', '- [ ] ', '  - [x] '):
            with self.subTest(prefix=prefix):
                lines = wrap_lines(prefix + 'Support scrolling without changing selection or keyboard focus.', 28)
                self.assertGreater(len(lines), 1)
                self.assertTrue(lines[0].startswith(prefix))
                self.assertTrue(all(line.startswith(' ' * cells(prefix)) for line in lines[1:]))
                self.assertTrue(all(cells(line) <= 28 for line in lines))
        self.assertEqual(wrap_lines('- alpha beta gamma delta', 14), ['- alpha beta', '  gamma delta'])
        self.assertEqual(wrap_lines('alpha beta gamma delta', 14), ['alpha beta', 'gamma delta'])

    def test_hanging_unicode_long_words_blank_lines_and_narrow_widths(self):
        for width in (1, 2, 5, 12, 30):
            lines = wrap_lines('  - [ ] 日本語 ' * 8 + '\n\nnormal\x1b text\n- ' + 'X' * 80, width)
            self.assertTrue(all(cells(line) <= width for line in lines))
            self.assertIn('', lines)
            self.assertNotIn('\x1b', ''.join(lines))
