import curses
import unittest
from unittest.mock import patch

from kanitor.config import ConfigError, parse_config
from kanitor.keybindings import DEFAULT_BINDINGS, DEFAULT_KEYS, key_token, parse_key
import test_ui
from test_explorer import snapshot
from test_projects import ProjectFixture


class KeyBindingTests(unittest.TestCase):
    def test_default_actions_cover_terminal_aliases_and_modified_movement(self):
        cases = [(curses.KEY_UP, 'up'), ('k', 'up'), (curses.KEY_DOWN, 'down'), ('j', 'down'),
                 ('\n', 'open'), ('\r', 'open'), (curses.KEY_ENTER, 'open'), (' ', 'open'),
                 ('\x1b', 'back'), (curses.KEY_SR, 'jumpUp'), (curses.KEY_SF, 'jumpDown'),
                 (curses.KEY_PPAGE, 'pageUp'), (curses.KEY_NPAGE, 'pageDown')]
        for key, expected in cases:
            with self.subTest(key=key):
                self.assertEqual(DEFAULT_BINDINGS.action(key), expected)
        for name, expected in ((b'kUP', (-10, False)), (b'kDN', (10, False)),
                               (b'kUP6', (-9, True)), (b'kDN6', (9, True))):
            with patch('kanitor.keybindings.curses.keyname', return_value=name):
                self.assertEqual(DEFAULT_BINDINGS.movement(9999, 9), expected)
        for name, expected in ((b'kLFT', 'jumpLeft'), (b'kRIT', 'jumpRight'),
                               (b'kLFT2', 'jumpLeft'), (b'kRIT2', 'jumpRight')):
            with patch('kanitor.keybindings.curses.keyname', return_value=name):
                self.assertEqual(DEFAULT_BINDINGS.action(9999), expected)
        for constant, expected in (('KEY_SLEFT', 'jumpLeft'), ('KEY_SRIGHT', 'jumpRight')):
            if hasattr(curses, constant):
                self.assertEqual(DEFAULT_BINDINGS.action(getattr(curses, constant)), expected)

    def test_overrides_replace_defaults_disable_and_preserve_literal_case(self):
        rules = parse_config({'keybindings': {'down': 'J', 'help': ['F1'], 'refresh': []}})
        bindings = rules.keybindings
        self.assertEqual(bindings.action('J'), 'down')
        self.assertIsNone(bindings.action('j'))
        self.assertIsNone(bindings.action(curses.KEY_DOWN))
        self.assertEqual(bindings.action(curses.KEY_F1), 'help')
        self.assertIsNone(bindings.action('?'))
        self.assertIsNone(bindings.action('R'))
        self.assertEqual(bindings.action('r'), 'toggleResize')
        self.assertEqual(bindings.action('k'), 'up')
        self.assertEqual(bindings.label('refresh'), 'Unbound')
        self.assertEqual(parse_config({}).keybindings, DEFAULT_BINDINGS)
        self.assertEqual(parse_config({'keybindings': {}}).keybindings, DEFAULT_BINDINGS)
        self.assertEqual(parse_config({'keybindings': {action: list(keys) for action, keys in DEFAULT_KEYS.items()}}).keybindings, DEFAULT_BINDINGS)

    def test_bad_keys_actions_and_terminal_alias_conflicts_are_configuration_errors(self):
        invalid = [None, [], {'unknown': ['x']}, {1: ['x']}, {'help': None}, {'help': [1]},
                   {'help': ['']}, {'help': ['alt+x']}, {'help': ['g g']}, {'help': ['F25']},
                   {'help': ['ctrl+shift+x']}, {'help': ['enter', 'Return']},
                   {'help': ['Ctrl+J']}, {'help': ['ctrl+M']}, {'quit': ['Esc']},
                   {'open': ['tab', 'ctrl+i']}, {'help': ['Shift+Tab', 'backtab']},
                   {'left': ['ctrl+h'], 'right': ['backspace']}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ConfigError) as caught:
                parse_config({'keybindings': value}, source='.kanitor.yml')
            self.assertIn('.kanitor.yml: keybindings', str(caught.exception))

    def test_key_names_ctrl_function_keys_and_tab_are_normalized(self):
        for raw, expected in (('Escape', 'escape'), ('Return', 'enter'), ('PgDn', 'pagedown'),
                              ('Ctrl+F', 'ctrl+f'), ('Control+Shift+Up', 'ctrl+shift+up'),
                              ('Shift+Control+Right', 'ctrl+shift+right'), ('Shift+h', 'H'),
                              ('Ctrl+[', 'escape'), ('Ctrl+H', 'backspace'), (' ', 'space')):
            self.assertEqual(parse_key(raw), expected)
        self.assertEqual(key_token('\x06'), 'ctrl+f')
        self.assertEqual(key_token(curses.KEY_F0 + 24), 'f24')
        bindings = parse_config({'keybindings': {'right': ['tab'], 'left': ['shift+tab'], 'focusPane': []}}).keybindings
        self.assertEqual(bindings.action('\t'), 'right')
        self.assertEqual(bindings.action(curses.KEY_BTAB), 'left')


class KeyBindingUITests(ProjectFixture):
    def tasks(self, overrides):
        app = test_ui.UITests().app()
        self.addCleanup(app.close)
        data = snapshot()
        data['customization'] = {'keybindings': overrides}
        app.explorer.apply(data)
        app.draw()
        return app

    def test_custom_navigation_activation_back_and_disabled_defaults(self):
        app = self.tasks({'up': ['i'], 'down': ['m'], 'left': ['h'], 'right': ['l'],
                          'open': ['o'], 'back': ['u'], 'quit': ['Q'], 'help': ['F1']})
        app.handle(curses.KEY_DOWN)
        app.handle('j')
        self.assertEqual(app.explorer.selected_id, 'one')
        app.handle('m')
        self.assertEqual(app.explorer.selected_id, 'two')
        app.handle('l')
        self.assertEqual(app.focus.index, 1)
        app.handle('\n')
        self.assertIsNone(app.popup)
        app.handle('o')
        self.assertEqual(app.popup, ('card', 'two'))
        app.handle(curses.KEY_LEFT)
        self.assertIsNotNone(app.popup)
        app.handle('h')
        self.assertIsNone(app.popup)
        app.handle('i')
        app.handle('i')
        self.assertTrue(app.focus.header)
        app.handle('o')
        self.assertIsNotNone(app.column_menu)
        app.handle('\x1b')
        self.assertIsNotNone(app.column_menu)
        app.handle('u')
        self.assertIsNone(app.column_menu)
        app.handle('u')
        self.assertEqual(app.view, 'boards')
        self.assertTrue(app.handle('q'))
        self.assertIn('o open', app.table_footer())
        self.assertIn('F1 help', app.table_footer())
        app.handle(curses.KEY_F1)
        self.assertEqual(app.popup, 'help')
        self.assertIn('F1', app.help_text())
        app.handle('u')
        self.assertFalse(app.handle('Q'))

    def test_remapped_actions_do_not_steal_search_or_filter_editor_text(self):
        app = self.tasks({'open': ['o'], 'back': ['u'], 'quit': ['Q'], 'search': ['ctrl+f'], 'columnMenu': ['c']})
        app.handle('/')
        self.assertFalse(app.searching)
        app.handle('\x06')
        for key in 'oQcu?':
            app.handle(key)
        self.assertEqual(app.explorer.query, 'oQcu?')
        app.handle('\x1b')
        self.assertEqual(app.explorer.query, '')
        app.draw()
        app.focus.header = True
        app.focus_column(4)
        app.handle('c')
        app.handle('o')  # Filter editor.
        self.assertEqual(app.column_menu['mode'], 'string')
        for key in 'oQcu?':
            app.handle(key)
        self.assertEqual(app.column_menu['draft'], 'oQcu?')
        app.handle('\n')
        self.assertEqual(app.explorer.task_state.filters[('field', 'task')].value, 'oQcu?')
        self.assertIsNone(app.column_menu)

    def test_tab_bindings_move_cells_and_custom_preview_status_and_board_actions(self):
        app = self.tasks({'right': ['tab'], 'left': ['shift+tab'], 'focusPane': [], 'togglePreview': ['v'], 'toggleSelection': [],
                          'statusFilter': ['t'], 'nextBoard': ['n'], 'previousBoard': ['N']})
        app.handle('\t')
        self.assertEqual(app.focus.index, 1)
        app.handle(curses.KEY_BTAB)
        self.assertEqual(app.focus.index, 0)
        app.handle('p')
        self.assertTrue(app.show_preview)
        app.handle('v')
        self.assertFalse(app.show_preview)
        app.handle('t')
        self.assertEqual(app.column_menu['mode'], 'enum')
        app.handle('\x1b')
        app.handle('n')
        self.assertEqual(app.explorer.board_slug, 'review')
        app.handle('N')
        self.assertEqual(app.explorer.board_slug, 'index')

    def test_workspace_and_child_bindings_are_independent_and_reload_in_help(self):
        app = self.app()
        self.fill(app)
        app.catalog.rules = parse_config({'keybindings': {'open': ['x'], 'quit': ['X']}})
        child = app.children[str(self.root / 'one')]
        child.explorer.apply({'boards': child.explorer.boards, 'customization': {'keybindings': {'open': ['o'], 'back': ['u']}}})
        app.handle('\n')
        self.assertIsNone(app.active)
        app.handle('x')
        self.assertIs(app.active, child)
        app.handle('x')
        self.assertEqual(child.view, 'boards')
        app.handle('o')
        self.assertEqual(child.view, 'tasks')
        app.handle('u')
        app.handle('u')
        self.assertIsNone(app.active)
        app.catalog.rules = parse_config({'keybindings': {'open': ['z'], 'quit': ['Z']}})
        self.assertIn('z open', app.table_footer())
        app.handle('x')
        self.assertIsNone(app.active)
        app.handle('z')
        self.assertIs(app.active, child)

    def test_squares_use_remapped_navigation_preview_and_activation(self):
        import test_squares
        app = self.tasks({})
        app.explorer.apply({'boards': [test_squares.board([
            test_squares.card('alpha', 'Building'), test_squares.card('beta', 'Building')])],
            'customization': {'keybindings': {'left': ['h'], 'right': ['l'], 'open': ['o'], 'togglePreview': ['v'], 'toggleSelection': []},
                              'boardColumns': [{'title': 'Board', 'field': 'name', 'width': 12},
                                               {'title': 'Tasks', 'field': 'task_squares', 'width': 5}]}})
        app.view = 'boards'
        app.draw()
        app.handle('l')
        self.assertEqual(app.selected_square, ('index', 'alpha'))
        app.handle('l')
        self.assertEqual(app.selected_square, ('index', 'beta'))
        app.handle('v')
        self.assertFalse(app.square_preview_shown)
        app.handle('\n')
        self.assertIsNone(app.popup)
        app.handle('o')
        self.assertEqual(app.popup, ('card', 'beta'))

    def test_horizontal_jumps_move_one_cell_in_rows_and_headers_in_each_table(self):
        bindings = {'jumpLeft': ['H'], 'jumpRight': ['L']}
        for view in ('tasks', 'boards', 'projects'):
            with self.subTest(view=view):
                if view == 'projects':
                    app = self.app()
                    app.catalog.rules = parse_config({'keybindings': bindings, 'projectColumns': [
                        {'title': 'Project', 'field': 'name'}, {'title': 'Count', 'field': 'cards'},
                        {'title': 'State', 'field': 'state'}]})
                else:
                    app = self.tasks(bindings)
                    if view == 'boards':
                        app.explorer.apply({'boards': app.explorer.boards, 'customization': {
                            'keybindings': bindings, 'boardColumns': [
                                {'title': 'Board', 'field': 'name'}, {'title': 'Slug', 'field': 'slug'},
                                {'title': 'Count', 'field': 'cards'}]}})
                    app.view = view
                app.draw()
                app.handle('L')
                self.assertEqual(app.focus.index, 1)
                self.assertIsNone(app.popup)
                app.handle(curses.KEY_UP)
                self.assertTrue(app.focus.header)
                app.handle('L')
                self.assertEqual(app.focus.index, 2)
                app.handle('H')
                self.assertEqual(app.focus.index, 1)
                self.assertIsNone(app.column_menu)

    def test_horizontal_square_jumps_count_five_across_wrapping_and_clamp_before_exiting(self):
        import test_squares
        bindings = {'jumpLeft': ['H'], 'jumpRight': ['L']}
        for view in ('boards', 'projects'):
            with self.subTest(view=view):
                native = test_squares.board([test_squares.card(str(i), 'Building') for i in range(12)])
                native['tasks'][5]['description'] = 'Description after jumping five squares.'
                columns = [{'title': 'Name', 'field': 'name', 'width': 12},
                           {'title': 'Tasks', 'field': 'task_squares', 'width': 5},
                           {'title': 'Count', 'field': 'cards', 'width': 6}]
                if view == 'projects':
                    app = self.app(paths=('one',))
                    app.catalog.rules = parse_config({'keybindings': bindings, 'projectColumns': columns})
                    child = next(iter(app.children.values()))
                    child.explorer.apply({'boards': [native]})
                    child.reader.snapshot = {'boards': [native]}
                else:
                    app = self.tasks(bindings)
                    app.view = 'boards'
                    app.explorer.apply({'boards': [native], 'customization': {
                        'keybindings': bindings, 'boardColumns': columns}})
                app.draw()
                owner = app.current_summary_id()
                app.handle('L')  # Enter the column at its first square.
                self.assertEqual(app.selected_square, (owner, '0'))
                app.handle('L')
                app.draw()
                self.assertEqual(app.selected_square, (owner, '5'))
                self.assertIn('Description after jumping five squares.', app.screen.text())
                for expected in ('10', '11'):
                    app.handle('L')
                    self.assertEqual(app.selected_square, (owner, expected))
                app.handle('L')
                self.assertEqual(app.focus.index, 2)
                self.assertIsNone(app.selected_square)
                for expected in ('11', '6', '1', '0'):
                    app.handle('H')
                    self.assertEqual(app.selected_square, (owner, expected))
                app.handle('H')
                self.assertEqual(app.focus.index, 0)
                self.assertIsNone(app.selected_square)
                self.assertIsNone(app.popup)
