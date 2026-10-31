import curses
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from kanitor.config import Column, ConfigError, layout_columns, parse_config
from kanitor.config_file import load_document
from kanitor.config_template import _column_rule
from kanitor.model import Explorer
from kanitor.projects import ProjectCatalog
from kanitor.projects_ui import ProjectsApp
from kanitor.reader import LiveReader
from kanitor.ui import App
from kanitor.widths import WidthSpec, parse_width
from kanitor.work.reader import WorkReader
from kanitor.work.service import WorkService
from test_explorer import snapshot
from test_reader import wait_for
from test_squares import NOW, at, board, card
import test_ui


def allocated(widths, budget, rows=(), filtered=()):
    columns = [Column('', field='name', width=width) for width in widths]
    placed, hidden = layout_columns(columns, 200, budget + len(columns) - 1, rows, filtered)
    return [width for _, width in placed], hidden


class WidthAllocationTests(unittest.TestCase):
    def test_parser_normalizes_bounds_and_keeps_original_values(self):
        cases = [('fill,8', WidthSpec('fill', None, 8)),
                 ('8,fill', WidthSpec('fill', 8, None)),
                 ('hug,8', WidthSpec('hug', None, 8)),
                 ('8,hug', WidthSpec('hug', 8, None)),
                 ('2,hug,8', WidthSpec('hug', 2, 8)),
                 (' 2 , fill , 8 ', WidthSpec('fill', 2, 8)),
                 ('\t2,\tfill,8\t', WidthSpec('fill', 2, 8)),
                 ('8,fill,8', WidthSpec('fill', 8, 8)),
                 (None, WidthSpec('fill')), ('hug', WidthSpec('hug')),
                 (12, WidthSpec('fixed', None, 12))]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse_width(raw), expected)
                if raw is not None:
                    rules = parse_config({'columns': [{'title': '', 'field': 'name', 'width': raw}]})
                    self.assertEqual(rules.columns[0].width, raw)
                    self.assertEqual(_column_rule(rules.columns[0])['width'], raw)

    def test_invalid_constraints_report_column_path_in_every_table_scope(self):
        invalid = [True, None, 2, 0, -4, 8.5, [], {}, '', '8', '0,hug', 'hug,0',
                   '-2,fill', 'fill,2.5', 'hug,,8', ',hug,8', '2,hug,',
                   '8,hug,2', 'fill,hug', '2,8', '2,fill,hug,8', 'hug,8,12',
                   'hug\n', 'fill,８', 'Fill,8', 'hug,8,', '01,hug']
        for scope, field in (('columns', 'name'), ('boardColumns', 'name'),
                             ('projectColumns', 'name'), ('sessionColumns', 'label')):
            for width in invalid:
                value = {scope: [{'title': '', 'field': field, 'width': width}]}
                if scope == 'sessionColumns':
                    value = {'workTracking': value}
                with self.subTest(scope=scope, width=width), self.assertRaises(ConfigError) as caught:
                    parse_config(value)
                self.assertIn(scope, str(caught.exception))
                self.assertIn('width', str(caught.exception))

    def test_hug_clamps_heading_and_content_and_keeps_small_bounds(self):
        for target, expected in ((1, 2), (2, 2), (4, 4), (6, 6), (8, 8), (12, 8)):
            with self.subTest(target=target):
                self.assertEqual(allocated(['2,hug,8'], 40, [{'name': 'x' * target}]), ([expected], 0))
        self.assertEqual(allocated(['hug,8'], 40, [{'name': 'x' * 12}]), ([8], 0))
        self.assertEqual(allocated(['8,hug'], 40, [{'name': 'x' * 2}]), ([8], 0))
        self.assertEqual(allocated(['8,hug'], 40, [{'name': 'x' * 12}]), ([12], 0))
        columns = [Column('Long heading', field='name', width='hug,2')]
        self.assertEqual(layout_columns(columns, 100, 90)[0][0][1], 2)
        self.assertEqual(allocated(['fill,1'], 40), ([1], 0))
        self.assertEqual(allocated(['2,fill,8'], 2), ([2], 0))

    def test_equal_final_fill_shares_and_cap_redistribution_match_diagrams(self):
        for widths, budget, expected in (
            (['fill,8', 'fill'], 20, [8, 12]),
            (['8,fill', 'fill'], 20, [10, 10]),
            (['8,fill', 'fill'], 12, [8, 4]),
            (['8,fill', '8,fill'], 10, [5, 5]),
            (['8,fill', 'fill'], 10, [6, 4]),
            (['fill,5', 'fill,8', 'fill'], 30, [5, 8, 17]),
            (['fill,8', 'fill,8'], 30, [8, 8]),
            (['fill', '12,fill', 'fill'], 28, [8, 12, 8]),
            (['fill', 'fill', 'fill'], 20, [7, 7, 6]),
            (['12,fill', 'fill', 'fill'], 25, [12, 7, 6]),
            (['fill,4', 'fill'], 9, [4, 5]),
        ):
            with self.subTest(widths=widths, budget=budget):
                self.assertEqual(allocated(widths, budget), (expected, 0))

    def test_content_first_reserves_fill_minimums_and_preserves_caps_during_shrink(self):
        rows = [{'name': 'x' * 12}]
        self.assertEqual(allocated(['hug', 'fill'], 20, rows), ([12, 8], 0))
        self.assertEqual(allocated(['hug', '8,fill'], 16, rows), ([8, 8], 0))
        self.assertEqual(allocated([12, '8,fill'], 16, rows), ([8, 8], 0))
        # Rounding must not allocate a cell to a column already at its cap.
        self.assertEqual(allocated(['hug,1', 'hug', 'hug'], 4, rows), ([1, 2, 1], 0))
        self.assertEqual(allocated(['2,hug,8'], 1, rows), ([1], 0))

    def test_readability_floors_shrink_before_hiding_and_recalculate_gaps(self):
        cols = [Column('', field='name', width='8,fill') for _ in range(3)]
        placed, hidden = layout_columns(cols, 100, 14)
        self.assertEqual(([width for _, width in placed], hidden), ([4, 4, 4], 0))
        placed, hidden = layout_columns(cols, 100, 13)
        self.assertEqual(([width for _, width in placed], hidden), ([6, 6], 1))
        self.assertEqual(layout_columns(cols, 100, 3), ([], 3))
        self.assertEqual(layout_columns(cols, 100, 0), ([], 3))
        self.assertEqual(layout_columns([], 100, 0), ([], 0))

    def test_unicode_filter_markers_and_terminal_visibility_obey_constraints(self):
        owner = Column('', metadata='owner', width='2,hug,8', filterable=True)
        rows = [{'metadata': {'owner': '日本語'}}]
        self.assertEqual(layout_columns([owner], 100, 40, rows)[0][0][1], 6)
        self.assertEqual(layout_columns([owner], 100, 40, [], filtered={owner.key})[0][0][1], 2)
        capped = Column('Long filter heading', metadata='owner', width='hug,2', filterable=True)
        self.assertEqual(layout_columns([capped], 100, 40, rows, {capped.key})[0][0][1], 2)
        hidden = Column('Optional', field='name', width='fill,8', min_terminal_width=90)
        self.assertEqual(layout_columns([hidden], 80, 40), ([], 0))

    def test_budget_and_bounds_invariants_across_mixed_columns_and_resizes(self):
        rules = ['fill', 'fill,1', 'fill,8', '8,fill', 'hug', '2,hug,8', 12]
        for first in rules:
            for second in rules:
                cols = [Column('', field='name', width=first), Column('', field='name', width=second)]
                for budget in range(0, 48):
                    placed, hidden = layout_columns(cols, 100, budget, [{'name': '日本語 long content'}])
                    self.assertEqual(len(placed) + hidden, 2)
                    self.assertLessEqual(sum(size for _, size in placed) + max(0, len(placed) - 1), budget)
                    for column, size in placed:
                        self.assertGreaterEqual(size, 1)
                        if column.sizing.maximum is not None:
                            self.assertLessEqual(size, column.sizing.maximum)


class WidthIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_yaml_json_constraints_stay_strict_in_views_without_blocking_recording(self):
        for name, text in (
            ('.kanitor.yml', 'columns:\n  - {title: Task, field: name, width: "2,hug,8"}\n'),
            ('.kanitor.json', '{"columns":[{"title":"Task","field":"name","width":"2,hug,8"}]}'),
        ):
            path = self.root / name
            path.write_text(text)
            self.assertEqual(parse_config(load_document(self.root)[0]).columns[0].sizing, WidthSpec('hug', 2, 8))
            path.unlink()
        path = self.root / '.kanitor.yml'
        path.write_text('workTracking:\n  sessionColumns:\n    - {title: Work, field: label, width: "8,fill,20"}\n')
        service = WorkService()
        self.assertEqual(service.execute('work_capabilities', self.root)['session_columns'][0]['width'], '8,fill,20')
        reader = WorkReader(self.root, interval=.01)
        self.addCleanup(reader.close)
        wait_for(reader, lambda: reader.snapshot is not None)
        self.assertEqual(reader.snapshot['config']['sessionColumns'][0]['width'], '8,fill,20')
        path.write_text(path.read_text().replace('8,fill,20', '20,fill,8'))
        self.assertIsNone(service.execute('work_capabilities', self.root)['session_columns'])
        session = service.execute('work_begin', self.root, {'label': 'Layout-independent work', 'request_id': 'begin'})
        service.execute('work_end', self.root, {'session_id': session['session_id'], 'request_id': 'end'})
        wait_for(reader, lambda: bool(reader.snapshot['warnings']))

    def test_task_capped_filter_headers_keep_their_hit_targets(self):
        explorer = Explorer()
        data = snapshot()
        data['customization'] = {'columns': [
            {'title': 'Status', 'field': 'status', 'width': 'hug,2'},
            {'title': 'Task', 'field': 'name', 'width': '8,fill,20'}]}
        explorer.apply(data)
        app = App(test_ui.Screen(), self.root, explorer, start_in_board=True)
        self.addCleanup(app.close)
        for width in (100, 60, 80):
            app.screen.width = width
            app.draw()
            self.assertEqual(app.filter_headers[0][2], 2)
            self.assertEqual([size for _, size in app.table_layout()[0]], [2, 20])
        app.handle(curses.KEY_UP)
        app.handle('\n')
        self.assertIsNotNone(app.column_menu)
        app.column_menu = None

    def test_boards_and_projects_reflow_squares_keep_selection_and_open_exact_task(self):
        self.enterContext(patch('kanitor.ui.time.time', return_value=NOW))
        native = board([card(str(i), created=at(-10)) for i in range(30)])
        rules = {'boardColumns': [
            {'title': 'Board', 'field': 'name', 'width': 48},
            {'title': 'Tasks', 'field': 'task_squares', 'width': '2,fill,8'}]}
        explorer = Explorer()
        explorer.apply({'boards': [native], 'customization': rules})
        app = App(test_ui.Screen(28, 100), self.root, explorer)
        self.addCleanup(app.close)
        app.draw()
        self.assertEqual(app.summary_table.heights, [8])
        app.handle(curses.KEY_RIGHT)
        app.handle(curses.KEY_RIGHT)
        app.handle(curses.KEY_DOWN)
        self.assertEqual(app.selected_square, ('index', '5'))
        app.screen.width = 60
        app.draw()
        self.assertEqual(app.summary_table.heights, [15])
        self.assertEqual(app.selected_square, ('index', '5'))
        self.assertTrue(app.scrollbars)
        y, x, _, _ = next(hit for hit in app.square_hits if hit[3].id == '5')
        with patch('kanitor.ui.curses.getmouse', return_value=(0, x, y, 0, curses.BUTTON1_DOUBLE_CLICKED)):
            app.handle(curses.KEY_MOUSE)
        self.assertEqual(app.popup, ('card', '5'))

        (self.root / 'child').mkdir()
        (self.root / '.kanitor.json').write_text(json.dumps({'projects': ['child'], 'projectColumns': [
            {'title': 'Project', 'field': 'name', 'width': 48},
            {'title': 'Tasks', 'field': 'task_squares', 'width': '2,fill,8'}]}))
        catalog = ProjectCatalog(self.root)
        catalog.poll(force=True)
        projects = ProjectsApp(test_ui.Screen(28, 100), self.root, catalog)
        self.addCleanup(projects.close)
        child = next(iter(projects.children.values()))
        child.explorer.apply({'boards': [native]})
        child.reader.snapshot = {'boards': [native]}
        projects.draw()
        self.assertEqual(projects.summary_table.heights, [8])
        projects.handle(curses.KEY_RIGHT)
        projects.handle(curses.KEY_RIGHT)
        projects.handle(curses.KEY_DOWN)
        self.assertEqual(projects.selected_square[1], '5')
        projects.screen.width = 60
        projects.draw()
        self.assertEqual(projects.summary_table.heights, [15])
        self.assertEqual(projects.selected_square[1], '5')
        self.assertTrue(projects.scrollbars)
        projects.handle('\n')
        self.assertEqual(child.popup, ('card', '5'))

    @unittest.skipUnless(shutil.which('node') and shutil.which('kanbn'), 'native Node/kanbn required')
    def test_native_reader_loads_constraints_live_rejects_invalid_bounds_and_recovers(self):
        shutil.copytree(Path(__file__).resolve().parents[1] / 'examples/demo/.kanbn', self.root / '.kanbn')
        reader = LiveReader(self.root, interval=.01)
        self.addCleanup(reader.close)
        wait_for(reader, lambda: reader.snapshot is not None)
        path = self.root / '.kanitor.yml'
        path.write_text('columns:\n  - {title: Task, field: name, width: "2,hug,8"}\n')
        wait_for(reader, lambda: reader.snapshot['customization'].get('columns', [{}])[0].get('width') == '2,hug,8')
        path.write_text(path.read_text().replace('2,hug,8', '8,hug,2'))
        wait_for(reader, lambda: bool(reader.error))
        self.assertIn('.kanitor.yml:', reader.error)
        self.assertIn('minimum width', reader.error)
        self.assertEqual(reader.snapshot['customization']['columns'][0]['width'], '2,hug,8')
        path.write_text(path.read_text().replace('8,hug,2', 'fill,8'))
        wait_for(reader, lambda: not reader.error and reader.snapshot['customization']['columns'][0]['width'] == 'fill,8')
