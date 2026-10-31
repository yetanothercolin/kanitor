from collections import deque
import curses
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from kanitor.mouse import SgrMouseInput, WHEEL_DOWN, WHEEL_UP, WheelGesture, decode_sgr


class InputScreen:
    def __init__(self, keys=(), delay=100):
        self.keys = deque(keys)
        self.delay = delay

    def get_wch(self):
        if not self.keys:
            raise curses.error('no input')
        key = self.keys.popleft()
        if isinstance(key, Exception):
            raise key
        return key

    def timeout(self, delay):
        self.delay = delay


class MouseInputTests(unittest.TestCase):
    def test_interrupted_direction_is_ignored_until_quiet_but_opposite_direction_is_immediate(self):
        gesture = WheelGesture()
        self.assertTrue(gesture.accept(-3, 1.0))
        gesture.interrupt(1.01)
        for now in (1.02, 1.05, 1.1, 1.2):
            self.assertFalse(gesture.accept(-3, now))
        self.assertTrue(gesture.accept(3, 1.21))
        self.assertTrue(gesture.accept(-3, 1.22))
        gesture.interrupt(1.23)
        self.assertFalse(gesture.accept(-3, 1.24))
        self.assertTrue(gesture.accept(-3, 1.5))

    def test_old_gesture_is_not_cancelled_and_pure_wheel_reversals_are_unrestricted(self):
        gesture = WheelGesture()
        self.assertTrue(gesture.accept(-3, 1.0))
        gesture.interrupt(2.0)
        self.assertTrue(gesture.accept(-3, 2.01))
        self.assertTrue(gesture.accept(3, 2.02))
        self.assertTrue(gesture.accept(-3, 2.03))

    def test_recorded_keyboard_navigation_is_not_undone_by_wheel_momentum(self):
        from dev.trace_scroll import app_state
        from test_ui import UITests
        fixture = json.loads((Path(__file__).parent / 'fixtures/trackpad-keyboard-interruption.json').read_text())
        clock = [0]
        for component in ('boards', 'tasks', 'details', 'filter'):
            with self.subTest(component=component), patch('kanitor.ui.time.monotonic', side_effect=lambda: clock[0]):
                app = UITests().app(start_in_board=component != 'boards')
                if component == 'details':
                    app.explorer.selected['description'] = '\n'.join(f'Line {i}' for i in range(100))
                    app.enter_item()
                elif component == 'filter':
                    app.open_status_menu()
                app.draw()
                screen = InputScreen()
                app.mouse_input = SgrMouseInput(screen)
                position = 0
                presses = 0
                for record in fixture['events']:
                    milliseconds, code = record.split()
                    clock[0] = float(milliseconds) / 1000
                    if code == 'Down':
                        presses += 1
                        app.handle(curses.KEY_DOWN)
                        position = min(presses, app_state(app)['maximum'])
                    else:
                        screen.keys.extend(f'\x1b[<{code};21;8M')
                        app.handle(app.read_key())
                    self.assertEqual(app_state(app)['position'], position)
                self.assertEqual(presses, 6)
                # The same direction works again after the gesture's quiet gap.
                clock[0] += 1
                screen.keys.extend('\x1b[<64;21;8M')
                app.handle(app.read_key())
                self.assertLess(app_state(app)['position'], position)

    def test_click_selection_also_interrupts_wheel_tail(self):
        from test_ui import UITests
        app = UITests().app()
        app.draw()
        clock = [1.0]
        with patch('kanitor.ui.time.monotonic', side_effect=lambda: clock[0]):
            screen = InputScreen('\x1b[<64;21;8M')
            app.mouse_input = SgrMouseInput(screen)
            app.handle(app.read_key())
            row, _, selected_id = next(hit for hit in app.hits if hit[1] == 'task' and hit[2] != app.explorer.selected_id)
            clock[0] += .01
            screen.keys.extend(f'\x1b[<0;21;{row + 1}M')
            app.handle(app.read_key())
            self.assertEqual(app.explorer.selected_id, selected_id)
            clock[0] += .01
            screen.keys.extend('\x1b[<64;21;8M')
            app.handle(app.read_key())
            self.assertEqual(app.explorer.selected_id, selected_id)

    def test_vertical_axes_modifiers_clicks_and_ignored_motion(self):
        self.assertEqual(decode_sgr('\x1b[<64;11;9M'), (0, 10, 8, 0, WHEEL_UP))
        self.assertEqual(decode_sgr('\x1b[<65;11;9M')[4], WHEEL_DOWN)
        self.assertEqual(decode_sgr('\x1b[<68;11;9M')[4], WHEEL_UP | curses.BUTTON_SHIFT)
        self.assertEqual(decode_sgr('\x1b[<0;11;9M')[4], curses.BUTTON1_PRESSED)
        for code, terminator in ((66, 'M'), (67, 'M'), (35, 'M'), (32, 'M'), (0, 'm'), (65, 'm')):
            with self.subTest(code=code, terminator=terminator):
                self.assertEqual(decode_sgr(f'\x1b[<{code};11;9{terminator}')[4], 0)
        self.assertIsNone(decode_sgr('\x1b[<64;0;9M'))
        self.assertIsNone(decode_sgr('\x1b[<invalidM'))

    def test_packets_preserve_keyboard_keys_and_escape(self):
        screen = InputScreen(list('\x1b[<64;11;9M') + [curses.KEY_RIGHT, 'p', '\x1b'])
        reader = SgrMouseInput(screen)
        self.assertEqual(reader.get_wch(), curses.KEY_MOUSE)
        self.assertEqual(reader.getmouse()[4], WHEEL_UP)
        self.assertEqual(reader.get_wch(), curses.KEY_RIGHT)
        self.assertEqual(reader.get_wch(), 'p')
        self.assertEqual(reader.get_wch(), '\x1b')
        self.assertEqual(screen.delay, 100)
        with self.assertRaises(curses.error):
            reader.getmouse()

    def test_fragmented_packet_during_nonblocking_drain_is_resumed(self):
        screen = InputScreen('\x1b[<6', delay=0)
        reader = SgrMouseInput(screen, delay=0)
        with self.assertRaises(curses.error):
            reader.get_wch()
        self.assertEqual(screen.delay, 0)
        screen.keys.extend('5;11;9M')
        self.assertEqual(reader.get_wch(), curses.KEY_MOUSE)
        self.assertEqual(reader.getmouse()[4], WHEEL_DOWN)
        self.assertEqual(screen.delay, 0)

    def test_escape_during_nonblocking_drain_remains_responsive(self):
        screen = InputScreen('\x1b', delay=0)
        reader = SgrMouseInput(screen, delay=0)
        with self.assertRaises(curses.error):
            reader.get_wch()
        reader.timeout(100)
        self.assertEqual(reader.get_wch(), '\x1b')
        self.assertEqual(screen.delay, 100)

    def test_unrelated_alt_sequence_is_preserved_and_malformed_mouse_is_consumed(self):
        screen = InputScreen('\x1bx\x1b[<bad;11;9Mp')
        reader = SgrMouseInput(screen)
        self.assertEqual(reader.get_wch(), '\x1b')
        self.assertEqual(reader.get_wch(), 'x')
        with self.assertRaises(curses.error):
            reader.get_wch()
        self.assertEqual(reader.get_wch(), 'p')

    def test_start_and_close_restore_terminal_mouse_modes(self):
        output = io.StringIO()
        reader = SgrMouseInput(InputScreen(), output)
        with patch('kanitor.mouse.curses.mousemask') as mask:
            reader.start()
            mask.assert_called_once_with(0)
        reader.close()
        self.assertEqual(output.getvalue(), '\x1b[?1000h\x1b[?1006h\x1b[?1006l\x1b[?1000l')

    def test_recorded_upward_gesture_never_moves_any_component_down(self):
        from test_ui import UITests
        fixture = json.loads((Path(__file__).parent / 'fixtures/trackpad-up.json').read_text())
        codes = [code for code, count in fixture['runs'] for _ in range(count)]
        self.assertEqual(codes.count(64), 689)
        self.assertEqual(codes.count(66), 8)
        self.assertNotIn(65, codes)
        for component in ('boards', 'tasks', 'details', 'filter'):
            with self.subTest(component=component):
                app = UITests().app(start_in_board=component != 'boards')
                if component == 'details':
                    app.explorer.selected['description'] = '\n'.join(f'Line {i}' for i in range(100))
                    app.enter_item()
                elif component == 'filter':
                    app.open_status_menu()
                app.draw()
                keys = ''.join(f'\x1b[<{code};21;8M' for code in codes)
                app.mouse_input = SgrMouseInput(InputScreen(keys))
                initial_board, initial_card = app.explorer.board_slug, app.explorer.selected_id
                app.needs_redraw = False
                for _ in codes:
                    self.assertTrue(app.handle(app.read_key()))
                    self.assertEqual(app.explorer.board_slug, initial_board)
                    self.assertEqual(app.explorer.selected_id, initial_card)
                    self.assertEqual(app.popup_scroll, 0)
                    self.assertEqual((app.column_menu['index'] if app.column_menu else 0), 0)
                    self.assertFalse(app.needs_redraw)
                # A deliberate opposite gesture still responds immediately.
                app.mouse_input.screen.keys.extend('\x1b[<65;21;8M')
                app.handle(app.read_key())
                if component == 'boards':
                    self.assertNotEqual(app.explorer.board_slug, initial_board)
                elif component == 'tasks':
                    self.assertNotEqual(app.explorer.selected_id, initial_card)
                elif component == 'details':
                    self.assertEqual(app.popup_scroll, 3)
                else:
                    self.assertEqual((app.column_menu['index'] if app.column_menu else 0), 3)
