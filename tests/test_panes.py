import curses
import json
from unittest.mock import patch

from kanitor.config import parse_config
from kanitor.model import Explorer
from kanitor.mouse import LEFT_DRAG, SgrMouseInput, WHEEL_DOWN, WHEEL_UP
from kanitor.panes import PaneLayoutState, pane_geometry
from kanitor.ui import App
from test_explorer import snapshot
from test_mouse import InputScreen
from test_projects import ProjectFixture
from test_ui import StyledScreen


class PaneTests(ProjectFixture):
    def mouse(self, app, x, y, buttons):
        with patch.object(app, 'get_mouse', return_value=(0, x, y, 0, buttons)):
            app.handle(curses.KEY_MOUSE)

    def viewer(self, view='boards', height=40):
        if view == 'projects':
            app = self.app(height=height)
        else:
            explorer = Explorer()
            explorer.apply(snapshot())
            app = App(StyledScreen(height, 110), self.root, explorer, view == 'tasks')
            self.addCleanup(app.close)
        app.activity.shown = True
        app.draw()
        return app

    def test_each_view_draws_dividers_and_moves_only_the_active_boundary(self):
        for view in ('projects', 'boards'):
            with self.subTest(view=view):
                app = self.viewer(view)
                original = app.pane_geometry
                selected = app.focused_row_id()
                app.handle('r')
                app.draw()
                self.assertTrue(app.resize_mode)
                self.assertEqual(app.screen.grid[original.dividers[0]][1], '─')
                self.assertIn('Resize', app.screen.text())
                app.handle(curses.KEY_UP)
                app.handle(curses.KEY_UP)  # No intervening draw.
                app.draw()
                first = app.pane_geometry
                self.assertEqual(first.dividers, (original.dividers[0] - 2, original.dividers[1]))
                self.assertEqual(first.heights, (original.heights[0] - 2, original.heights[1] + 2, original.heights[2]))
                app.handle('\t')
                self.assertEqual(app.resize_active, 'preview')
                self.assertFalse(app.activity.focused)
                app.handle(curses.KEY_UP)
                app.draw()
                second = app.pane_geometry
                self.assertEqual(second.dividers, (first.dividers[0], first.dividers[1] - 1))
                self.assertEqual(second.heights, (first.heights[0], first.heights[1] - 1, first.heights[2] + 1))
                self.assertEqual(app.preview_rect[2], second.heights[2])
                app.handle(curses.KEY_BTAB)
                self.assertEqual(app.resize_active, 'activity')
                app.handle(curses.KEY_BTAB)
                self.assertEqual(app.resize_active, 'preview')
                self.assertEqual(app.focused_row_id(), selected)
                app.handle('r')
                app.draw()
                self.assertFalse(app.resize_mode)
                self.assertEqual(app.pane_geometry, second)
                self.assertEqual(app.screen.grid[second.dividers[0]][1], ' ')
                app.handle('\t')
                self.assertTrue(app.activity.focused)

    def test_bounds_never_push_the_other_divider_and_preview_can_shrink(self):
        app = self.viewer()
        app.handle('r')
        second = app.pane_geometry.dividers[1]
        for _ in range(100):
            app.handle(curses.KEY_UP)
        app.draw()
        self.assertEqual(app.pane_geometry.heights[0], 5)
        self.assertEqual(app.pane_geometry.dividers[1], second)
        for _ in range(100):
            app.handle(curses.KEY_DOWN)
        app.draw()
        self.assertEqual(app.pane_geometry.heights[1], 5)
        self.assertEqual(app.pane_geometry.dividers[1], second)
        first = app.pane_geometry.dividers[0]
        app.handle('\t')
        for _ in range(100):
            app.handle(curses.KEY_DOWN)
        app.draw()
        self.assertEqual(app.pane_geometry.dividers[0], first)
        self.assertEqual(app.preview_rect[2], 3)
        with patch.object(app.view_state, 'set_mapping_entry') as save:
            app.handle(curses.KEY_DOWN)
        save.assert_not_called()
        for _ in range(100):
            app.handle(curses.KEY_UP)
        app.draw()
        self.assertEqual(app.pane_geometry.dividers[0], first)
        self.assertEqual(app.pane_geometry.heights[1], 5)

    def test_sgr_drag_each_divider_in_each_view_saves_only_on_release(self):
        for view in ('projects', 'boards'):
            with self.subTest(view=view):
                app = self.viewer(view)
                app.handle('r')
                app.draw()
                selected = app.focused_row_id()
                screen = InputScreen()
                app.mouse_input = SgrMouseInput(screen)
                for index in (0, 1):
                    original = app.pane_geometry.dividers
                    start = original[index]
                    with patch.object(app.view_state, 'set_mapping_entry', wraps=app.view_state.set_mapping_entry) as save:
                        for code, row, end in ((0, start, 'M'), (32, start - 1, 'M'), (32, start - 2, 'M')):
                            screen.keys.extend(f'\x1b[<{code};11;{row + 1}{end}')
                            app.handle(app.read_key())
                            app.draw()
                        self.assertEqual(app.pane_geometry.dividers[index], start - 2)
                        self.assertEqual(app.pane_geometry.dividers[1 - index], original[1 - index])
                        save.assert_not_called()
                        # Release at a different position also applies its final row.
                        screen.keys.extend(f'\x1b[<0;11;{start}m')
                        app.handle(app.read_key())
                        save.assert_called_once()
                    self.assertIsNone(app.resize_drag)
                    self.assertEqual(app.pane_geometry.dividers[index], start - 1)
                    self.assertEqual(app.focused_row_id(), selected)
                    current = app.pane_geometry
                    screen.keys.extend(f'\x1b[<32;11;{start - 4}M')
                    app.handle(app.read_key())
                    self.assertEqual(app.pane_geometry, current)  # No held capture after release.
                    self.assertEqual(json.loads(app.view_state.path.read_text())['paneLayout']['shared']['dividers'],
                                     list(current.dividers))
                self.assertIsNone(app.popup)

    def test_drag_clamps_at_edges_without_moving_other_divider_or_rebounding(self):
        app = self.viewer()
        app.handle('r')
        first, second = app.pane_geometry.dividers
        self.mouse(app, 10, first, curses.BUTTON1_PRESSED)
        self.mouse(app, 500, 0, LEFT_DRAG)
        self.assertEqual(app.pane_geometry.dividers, (8, second))
        self.mouse(app, 500, 500, LEFT_DRAG)
        self.assertEqual(app.pane_geometry.dividers, (second - 6, second))
        self.mouse(app, 10, second - 7, LEFT_DRAG)
        self.assertEqual(app.pane_geometry.dividers, (second - 7, second))
        # Wheels and unrelated buttons never move a captured divider.
        current = app.pane_geometry
        for button in (WHEEL_UP, WHEEL_DOWN, curses.BUTTON3_RELEASED, 0):
            self.mouse(app, 10, 0, button)
            self.assertEqual(app.pane_geometry, current)
        self.mouse(app, 10, second - 7, curses.BUTTON1_RELEASED)
        self.assertIsNone(app.resize_drag)

    def test_drag_cancels_on_keyboard_exit_resize_and_new_click(self):
        app = self.viewer()
        for ending in ('\t', 'r', '\x1b', curses.KEY_RESIZE):
            if not app.resize_mode:
                app.handle('r')
            app.draw()
            original = app.pane_geometry.dividers[0]
            self.mouse(app, 10, original, curses.BUTTON1_PRESSED)
            self.mouse(app, 10, original - 1, LEFT_DRAG)
            app.handle(ending)
            self.assertIsNone(app.resize_drag)
            current = app.pane_geometry
            self.mouse(app, 10, 3, LEFT_DRAG)
            self.assertEqual(app.pane_geometry, current)
        app.resize_mode = True
        app.draw()
        first, second = app.pane_geometry.dividers
        self.mouse(app, 10, first, curses.BUTTON1_PRESSED)
        self.mouse(app, 10, second, curses.BUTTON1_PRESSED)
        self.assertEqual(app.resize_drag['name'], 'preview')
        app.screen.height = 25
        app.draw()
        self.assertIsNone(app.resize_drag)
        current = app.pane_geometry
        self.mouse(app, 10, 3, LEFT_DRAG)
        self.assertEqual(app.pane_geometry, current)

    def test_drag_requires_press_on_resizer_and_reports_save_failures(self):
        app = self.viewer()
        app.handle('r')
        original = app.pane_geometry
        self.mouse(app, 10, 5, curses.BUTTON1_PRESSED)
        self.mouse(app, 10, original.dividers[0], LEFT_DRAG)
        self.assertEqual(app.pane_geometry, original)
        self.mouse(app, 10, original.dividers[0], curses.BUTTON1_CLICKED)
        self.assertIsNone(app.resize_drag)
        self.mouse(app, 10, original.dividers[0], curses.BUTTON1_PRESSED)
        self.mouse(app, 10, original.dividers[0] - 1, LEFT_DRAG)
        app.needs_redraw = False
        with patch.object(app.view_state, 'set_mapping_entry', return_value='Could not save view preferences'):
            self.mouse(app, 10, original.dividers[0] - 1, curses.BUTTON1_RELEASED)
        self.assertIn('Could not save view preferences', app.notice)
        self.assertTrue(app.needs_redraw)
        self.assertIsNone(app.resize_drag)
    def test_defaults_grow_main_and_absolute_edits_survive_terminal_resizing(self):
        app = self.viewer()
        original = app.pane_geometry
        app.screen.height += 5
        app.draw()
        self.assertEqual(app.pane_geometry.heights, (original.heights[0] + 5, 8, 8))
        app.handle('r')
        app.handle(curses.KEY_UP)
        app.draw()
        edited = app.pane_geometry
        for height, width in ((25, 60), (16, 60), (19, 70), (24, 80), (10, 40), (40, 110), (45, 110)):
            app.screen.height, app.screen.width = height, width
            app.handle(curses.KEY_RESIZE)
            app.draw()  # Screen rejects out-of-bounds drawing.
            if height >= 25:
                self.assertGreaterEqual(app.pane_geometry.heights[0], 5)
                self.assertGreaterEqual(app.pane_geometry.heights[1], 5)
                self.assertGreaterEqual(app.pane_geometry.heights[2], 3)
        self.assertEqual(app.pane_geometry, edited)
        self.assertEqual(app.pane_layout_state.dividers, list(edited.dividers))

    def test_persisted_sizes_are_shared_across_views_and_visible_panes(self):
        app = self.viewer()
        app.handle('r')
        app.handle(curses.KEY_UP)
        app.draw()
        edited = app.pane_geometry
        restored = self.viewer()
        self.assertEqual(restored.pane_geometry, edited)
        self.assertFalse(restored.resize_mode)
        boards = self.viewer('boards')
        self.assertEqual(boards.pane_geometry.heights[1:], edited.heights[1:])
        restored.activity.shown = False
        restored.draw()
        self.assertEqual(restored.preview_rect[2], 8)
        restored.activity.shown = True
        restored.draw()
        self.assertEqual(restored.pane_geometry, edited)
        data = json.loads(app.view_state.path.read_text())
        self.assertEqual(data['paneLayout']['shared']['dividers'], list(edited.dividers))

    def test_no_dividers_single_divider_and_mouse_focus(self):
        app = self.viewer()
        app.activity.shown = app.show_preview = app.square_preview_shown = False
        app.draw()
        app.handle('r')
        for key in ('\t', curses.KEY_UP, curses.KEY_DOWN):
            app.handle(key)
        app.draw()
        self.assertIn('no dividers', app.screen.text())
        app.handle('\x1b')
        self.assertEqual(app.view, 'boards')
        app.show_preview = app.square_preview_shown = True
        app.draw()
        app.handle('r')
        app.handle(curses.KEY_DOWN)
        app.draw()
        self.assertEqual(app.preview_rect[2], 7)
        app.handle('\t')
        self.assertEqual(app.resize_active, 'preview')
        app.handle('r')
        app.activity.shown = True
        app.draw()
        app.handle('r')
        second = app.pane_geometry.dividers[1]
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 10, second, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.resize_active, 'preview')
        selected = app.explorer.selected_id
        with patch('kanitor.ui.curses.getmouse', return_value=(0, 10, 6, 0, curses.BUTTON1_DOUBLE_CLICKED)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.explorer.selected_id, selected)
        self.assertIsNone(app.popup)
        self.assertTrue(app.handle('q'))  # Exits resizing without quitting.
        self.assertFalse(app.resize_mode)

    def test_remapping_and_text_editors_and_details_keep_their_keys(self):
        app = self.viewer()
        app.explorer.column_rules = parse_config({'keybindings': {'toggleResize': 'z', 'refresh': 'r'}})
        app.handle('z')
        self.assertTrue(app.resize_mode)
        app.handle('z')
        app.handle('/')
        app.handle('z')
        self.assertTrue(app.searching)
        self.assertEqual(app.explorer.query, 'z')
        self.assertFalse(app.resize_mode)
        app.handle('\x1b')
        app.handle('\n')
        app.handle('z')
        self.assertIsNotNone(app.popup)
        self.assertFalse(app.resize_mode)

    def test_short_activity_preview_clips_and_keeps_size_when_ticket_disappears(self):
        app = self.viewer()
        task = app.explorer.board['tasks'][1]
        task['description'] = '\n'.join(f'Description line {i}' for i in range(20))
        app.handle('\t')
        app.draw()
        self.assertTrue(app.activity.focused)
        app.handle('r')
        app.handle('\t')
        for _ in range(30):
            app.handle(curses.KEY_DOWN)
        app.draw()
        geometry = app.preview_rect, app.activity.rect
        self.assertEqual(app.preview_rect[2], 3)
        self.assertIn('Description line 0', app.screen.text().splitlines()[app.preview_rect[0] + 1])
        self.assertIn('preview', [bar['kind'] for bar in app.scrollbars])
        for name, row in zip(app.pane_geometry.names[1:], app.pane_geometry.dividers):
            attributes = app.screen.attributes[row]
            self.assertEqual(any(attr & curses.A_REVERSE for attr in attributes), name == 'preview')
        for y, _ in app.activity.hits:
            self.assertFalse(any(attr & curses.A_REVERSE for attr in app.screen.attributes[y]))
        task['column'] = 'Shipped'
        app.draw()
        self.assertIn('No Activity ticket selected.', app.screen.text())
        self.assertEqual((app.preview_rect, app.activity.rect), geometry)

    def test_invalid_saved_positions_and_save_failure_are_nonfatal(self):
        app = self.viewer()
        for value in (None, 'bad', {}, [True, 12], [12], ['12', 18]):
            app.view_state.set_mapping_entry('paneLayout', 'shared', value)
            app.pane_layout_state = PaneLayoutState(app.view_state)
            app.draw()
            self.assertEqual(app.pane_geometry.heights[1:], (8, 8))
        app.handle('r')
        with patch.object(app.view_state, 'set_mapping_entry', return_value='Could not save view preferences'):
            app.handle(curses.KEY_UP)
        app.draw()
        self.assertEqual(app.pane_geometry.heights[1:], (9, 8))
        self.assertIn('Could not save view preferences', app.screen.text())

    def test_geometry_clamps_impossible_coordinates_and_retains_readable_panes(self):
        for height in range(25, 80):
            for positions in ((-100, -100), (1000, -100), (1000, 1000), (8, 14)):
                geometry = pane_geometry(height, True, True, positions)
                self.assertGreaterEqual(geometry.heights[0], 5)
                self.assertGreaterEqual(geometry.heights[1], 5)
                self.assertGreaterEqual(geometry.heights[2], 3)
                self.assertEqual(sum(geometry.heights) + 2, height - 5)

    def test_activity_is_unavailable_in_tasks_without_losing_summary_preference(self):
        app = self.viewer('boards')
        app.handle('a')
        app.handle('a')
        app.draw()
        app.handle('r')
        app.handle(curses.KEY_UP)
        app.handle('r')
        app.draw()
        sizes = app.pane_geometry.heights[1:]
        app.enter_item()
        app.draw()
        self.assertEqual(app.view, 'tasks')
        self.assertFalse(app.activity_visible)
        self.assertIsNone(app.activity.rect)
        self.assertEqual(app.preview_rect[2], sizes[-1])
        self.assertNotIn('activity', app.table_footer())
        with patch.object(app.view_state, 'set_flag') as save:
            app.handle('a')
            app.handle('\t')
            save.assert_not_called()
        self.assertFalse(app.activity.focused)
        self.assertTrue(app.view_state.flag('activityVisible'))
        app.back_to_boards()
        app.draw()
        self.assertTrue(app.activity_visible)
        self.assertEqual(app.pane_geometry.heights[1:], sizes)

    def test_projects_boards_and_tasks_share_layout_and_persist_parent_preferences(self):
        app = self.app(height=40)
        self.fill(app)
        app.activity.shown = True
        app.draw()
        app.handle('r')
        app.handle(curses.KEY_UP)
        app.handle(curses.KEY_UP)
        app.handle('\t')
        app.handle(curses.KEY_UP)
        app.handle('r')
        app.draw()
        sizes = app.pane_geometry.heights[1:]
        self.assertEqual(sizes, (9, 9))
        app.open_project()
        child = app.active
        child.activity.shown = True
        child.draw()
        self.assertEqual(child.pane_geometry.heights[1:], sizes)
        child.enter_item()
        child.draw()
        self.assertEqual(child.preview_rect[2], 9)
        child.handle('r')
        child.handle(curses.KEY_UP)
        child.handle('r')
        child.draw()
        self.assertEqual(child.preview_rect[2], 10)
        child.back_to_boards()
        child.draw()
        self.assertEqual(child.pane_geometry.heights[1:], (9, 10))
        app.show_projects()
        app.draw()
        self.assertEqual(app.pane_geometry.heights[1:], (9, 10))
        restored = self.app(height=40)
        restored.activity.shown = True
        restored.draw()
        self.assertEqual(restored.pane_geometry.heights[1:], (9, 10))

    def test_legacy_divider_preferences_migrate_without_changing_stored_data_until_edit(self):
        app = self.viewer('boards')
        app.view_state.set_mapping_entry('paneDividers', 'boards:activity,preview', [18, 29])
        before = app.view_state.path.read_bytes()
        app.pane_layout_state = PaneLayoutState(app.view_state)
        app.draw()
        self.assertEqual(app.pane_geometry.dividers, (18, 29))
        self.assertEqual(app.view_state.path.read_bytes(), before)
        app.handle('r')
        app.handle(curses.KEY_UP)
        app.draw()
        data = json.loads(app.view_state.path.read_text())
        self.assertEqual(data['paneDividers']['boards:activity,preview'], [18, 29])
        self.assertEqual(data['paneLayout']['shared']['dividers'], [17, 29])
