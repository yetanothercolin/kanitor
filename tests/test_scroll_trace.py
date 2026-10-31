"""Tests for checkout-only diagnostics; production never imports these hooks."""
import curses
import json
from pathlib import Path
import tempfile
import unittest

from dev.trace_scroll import MousePackets, app_state, summarize, traced_app


class ScrollTraceTests(unittest.TestCase):
    def test_raw_packets_preserve_direction_modifiers_and_fragmented_input(self):
        parser = MousePackets()
        stream = (b'ordinary keys\x1b[A\x1b[<64;11;9M\x1b[<65;11;9M'
                  b'\x1b[<68;12;10M\x1b[<0;4;5m\x1b[M`++\x1b[Ma++')
        events = []
        for byte in stream:
            events.extend(parser.feed(bytes([byte])))
        self.assertEqual([event['direction'] for event in events], ['up', 'down', 'up', None, 'up', 'down'])
        self.assertEqual((events[0]['x'], events[0]['y']), (10, 8))
        self.assertTrue(events[2]['shift'])
        self.assertTrue(events[3]['release'])
        self.assertEqual((events[4]['x'], events[4]['y']), (10, 10))
        self.assertEqual(parser.pending, b'')

    def test_raw_motion_is_not_a_wheel_and_corrupt_input_does_not_block_parser(self):
        events = MousePackets().feed(b'\x1b[<broken\x1b[<35;2;3M\x1b[<65;2;3M')
        self.assertEqual([event['direction'] for event in events], [None, 'down'])
        self.assertEqual(events[0]['code'], 35)
        self.assertTrue(events[0]['motion'])

    def test_summary_reports_boundary_reversals_and_both_input_layers(self):
        before = dict(component='details', board='index', selected_id='card',
                      position=0, at_top=True, at_bottom=False)
        records = [
            dict(time_ns=1, event='raw_mouse', direction='up'),
            dict(time_ns=2, event='curses_mouse', direction='up'),
            dict(time_ns=3, event='wheel', delta=-3, before=before, after=before),
            dict(time_ns=4, event='raw_mouse', direction='down'),
            dict(time_ns=5, event='curses_mouse', direction='down'),
            dict(time_ns=6, event='wheel', delta=3, before=before, after=dict(before, position=3)),
            dict(time_ns=7, event='render')]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'trace.jsonl'
            log.write_text('\n'.join(json.dumps(record) for record in records))
            result = summarize(log)
        self.assertEqual(result['raw_wheel'], {'up': 1, 'down': 1})
        self.assertEqual(result['curses_mouse'], {'up': 1, 'down': 1})
        self.assertEqual(result['wheel_by_component'], {'details': 2})
        self.assertEqual(result['clamped_events'], 1)
        self.assertEqual(result['renders'], 1)
        self.assertEqual(len(result['boundary_reversals']), 1)
        self.assertEqual(result['boundary_reversals'][0]['position_after'], 3)

    def test_tracing_subclass_preserves_real_navigation(self):
        from test_ui import UITests
        from kanitor.ui import App

        class Recorder:
            def __init__(self):
                self.events = []

            def emit(self, event, **values):
                self.events.append(dict(event=event, **values))

        trace = Recorder()
        app = UITests().app(start_in_board=False)
        app.__class__ = traced_app(App, trace)
        app.draw()
        app.scroll_wheel(-3)
        app.scroll_wheel(3)
        app.handle('\n')
        self.assertEqual(app.view, 'tasks')
        app.handle('\n')
        self.assertIsNotNone(app.popup)
        wheels = [event for event in trace.events if event['event'] == 'wheel']
        self.assertEqual(wheels[0]['before']['position'], 0)
        self.assertEqual(wheels[0]['after']['position'], 0)
        self.assertEqual(wheels[1]['after']['position'], 1)

