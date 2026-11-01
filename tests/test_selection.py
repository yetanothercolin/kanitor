import base64
import curses
import io
import subprocess
import unittest
from unittest.mock import patch

from kanitor.mouse import LEFT_DRAG, WHEEL_DOWN
from kanitor.selection import ClipboardError, TextFrame, copy_text
from test_projects import ProjectFixture
import test_ui


class TextSelectionTests(unittest.TestCase):
    def test_unicode_cells_reverse_drag_and_multiline_whitespace(self):
        frame = TextFrame(8, 20)
        frame.write(0, 1, '界 café\u0301', 1)
        frame.write(1, 1, 'second', 2)
        self.assertEqual(frame.selected_text((2, 0), (2, 0)), '界')
        self.assertEqual(frame.selected_text((6, 1), (1, 0)), '界 café\u0301\n second')
        frame.write(0, 2, 'X', 0)
        self.assertEqual(frame.selected_text((1, 0), (3, 0)), ' X')

    def test_macos_clipboard_uses_plain_utf8_without_shell(self):
        with patch('kanitor.selection.sys.platform', 'darwin'), \
                patch('kanitor.selection.shutil.which', return_value='/usr/bin/pbcopy'), \
                patch('kanitor.selection.subprocess.run') as run:
            self.assertEqual(copy_text('界\nhello'), 'Copied selection to clipboard.')
            self.assertEqual(run.call_args.args, (['/usr/bin/pbcopy'],))
            self.assertEqual(run.call_args.kwargs['input'], '界\nhello'.encode())
            self.assertNotIn('shell', run.call_args.kwargs)
            run.side_effect = subprocess.TimeoutExpired(['pbcopy'], 2)
            with self.assertRaises(ClipboardError):
                copy_text('retry')

    def test_terminal_clipboard_encodes_text_and_wraps_tmux(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        text = '界\n\x1b]do not execute'
        sequence = '\x1b]52;c;' + base64.b64encode(text.encode()).decode() + '\x07'
        with patch('kanitor.selection.sys.platform', 'linux'), patch.dict('os.environ', {}, clear=True):
            output = Terminal()
            self.assertIn('OSC 52', copy_text(text, output))
            self.assertEqual(output.getvalue(), sequence)
            with patch.dict('os.environ', {'TMUX': 'session'}):
                output = Terminal()
                copy_text(text, output)
                self.assertEqual(output.getvalue(), '\x1bPtmux;' + sequence.replace('\x1b', '\x1b\x1b') + '\x1b\\')
            with self.assertRaises(ClipboardError):
                copy_text(text, io.StringIO())

    def test_drag_highlight_freeze_copy_and_cancel_preserve_navigation(self):
        app = test_ui.UITests().app()
        self.addCleanup(app.close)
        app.screen = test_ui.StyledScreen()
        app.draw()
        frame = app.text_frame
        before = app.explorer.selected_id, app.focus.index, app.popup
        app.handle('v')
        app.draw()
        with patch.object(app, 'get_mouse', return_value=(0, 3, 5, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        with patch.object(app, 'get_mouse', return_value=(0, 18, 5, 0, LEFT_DRAG)):
            app.handle(curses.KEY_MOUSE)
        with patch.object(app, 'get_mouse', return_value=(0, 18, 5, 0, curses.BUTTON1_RELEASED)):
            app.handle(curses.KEY_MOUSE)
        app.draw()
        self.assertTrue(app.screen.attributes[5][10] & curses.A_UNDERLINE)
        self.assertIs(app.text_frame, frame)
        expected = frame.selected_text((3, 5), (18, 5))
        app.explorer.board['tasks'][0]['name'] = 'Live replacement'
        app.draw()
        self.assertNotIn('Live replacement', app.screen.text())
        with patch.object(app, 'get_mouse', return_value=(0, 3, 5, 0, WHEEL_DOWN)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual((app.explorer.selected_id, app.focus.index, app.popup), before)
        with patch('kanitor.selection.copy_text', return_value='Copied selection.') as copy:
            app.handle('y')
            copy.assert_called_once_with(expected)
        self.assertFalse(app.selecting_text)
        app.draw()
        self.assertIn('Live replacement', app.screen.text())
        app.handle('v')
        with patch('kanitor.selection.copy_text') as copy:
            app.handle('\x1b')
            copy.assert_not_called()
        self.assertEqual((app.explorer.selected_id, app.focus.index, app.popup), before)

    def test_details_keyboard_selection_copy_failure_and_resize(self):
        app = test_ui.UITests().app()
        self.addCleanup(app.close)
        app.handle('\n')
        app.draw()
        popup = app.popup
        app.handle('v')
        app.handle(curses.KEY_RIGHT)
        app.handle(curses.KEY_DOWN)
        self.assertEqual(app.text_end, (1, 1))
        with patch('kanitor.selection.copy_text', side_effect=ClipboardError('Unavailable')):
            app.handle('y')
        self.assertTrue(app.selecting_text)
        app.draw()
        self.assertIn('Unavailable', app.screen.text())
        app.screen.height, app.screen.width = 19, 60
        app.draw()
        self.assertFalse(app.selecting_text)
        self.assertEqual(app.popup, popup)
        app.handle('v')
        app.handle(curses.KEY_RESIZE)
        self.assertFalse(app.selecting_text)

    def test_search_menu_and_resize_keep_their_input(self):
        app = test_ui.UITests().app()
        self.addCleanup(app.close)
        app.draw()
        app.handle('/')
        app.handle('v')
        self.assertEqual(app.explorer.query, 'v')
        self.assertFalse(app.selecting_text)
        app.handle('\x1b')
        app.handle('r')
        app.handle('v')
        self.assertFalse(app.selecting_text)


class ProjectTextSelectionTests(ProjectFixture):
    def test_projects_and_child_views_capture_selection_before_navigation(self):
        app = self.app()
        self.fill(app)
        app.draw()
        app.handle('v')
        app.draw()
        with patch.object(app, 'get_mouse', return_value=(0, 3, 5, 0, curses.BUTTON1_PRESSED)):
            app.handle(curses.KEY_MOUSE)
        with patch.object(app, 'get_mouse', return_value=(0, 5, 5, 0, curses.BUTTON1_RELEASED)):
            app.handle(curses.KEY_MOUSE)
        self.assertIsNone(app.active)
        with patch('kanitor.selection.copy_text', return_value='Copied project text.') as copy:
            app.handle('y')
            copy.assert_called_once_with('one')
        app.draw()
        self.assertIn('Copied project text.', app.screen.text())
        app.open_project()
        app.draw()
        app.handle('v')
        self.assertTrue(app.active.selecting_text)
        app.handle('q')
        self.assertFalse(app.active.selecting_text)
        self.assertIsNotNone(app.active)
