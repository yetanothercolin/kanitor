from datetime import datetime, timedelta, timezone
import unittest

from kanitor.config import Column, ConfigError, DEFAULT_COLUMNS, layout_columns, parse_config


class DateColumnTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 23, 16, 1).astimezone()

    def column(self, **settings):
        rule = {'title': 'Updated', 'metadata': 'updated', 'width': 'hug'}
        rule.update(settings)
        return parse_config({'columns': [rule]}).columns[0]

    def value(self, column, date):
        return column.value({'metadata': {'updated': date.isoformat()}}, now=self.now)

    def test_updated_default_follows_status_and_formats_native_iso_timestamp(self):
        self.assertEqual(DEFAULT_COLUMNS[0].field, 'status_square')
        self.assertEqual(DEFAULT_COLUMNS[1].field, 'status')
        updated = DEFAULT_COLUMNS[2]
        self.assertEqual(updated.metadata, 'updated')
        self.assertEqual(updated.width, 16)
        self.assertEqual(self.value(updated, self.now), '2026-10-23 16:01')

    def test_custom_formats_apply_to_any_metadata_key_and_date_only_values(self):
        column = parse_config({'columns': [{'title': '', 'metadata': 'review.date',
                                           'format': '%d/%m/%Y'}]}).columns[0]
        self.assertEqual(column.value({'metadata': {'review.date': '2026-10-22'}}), '22/10/2026')
        # Formatting is opt-in; ordinary date-looking text stays unchanged.
        self.assertEqual(Column('Due', metadata='due').value({'metadata': {'due': '2026-10-22'}}), '2026-10-22')
        self.assertEqual(self.value(self.column(format='%%n %H:%M'), self.now), '%n 16:01')

    def test_age_thresholds_use_strict_elapsed_boundaries_and_fallback(self):
        column = self.column(format='%b %Y', thresholds=[
            {'under': '1d', 'format': '%H:%M'},
            {'under': '1y', 'format': '%d %b'}])
        cases = [(self.now - timedelta(minutes=28), '15:33'),
                 (self.now - timedelta(days=1), '22 Oct'),
                 (self.now - timedelta(days=365, seconds=-1), '23 Oct'),
                 (self.now - timedelta(days=365), 'Oct 2025'),
                 (self.now + timedelta(hours=1), 'Oct 2026')]
        for date, expected in cases:
            with self.subTest(date=date):
                self.assertEqual(self.value(column, date), expected)

    def test_thresholds_without_base_format_use_standard_fallback(self):
        column = self.column(thresholds=[{'under': '24h', 'format': '%H:%M'}])
        self.assertEqual(self.value(column, self.now), '16:01')
        self.assertEqual(self.value(column, self.now - timedelta(days=2)), '2026-10-21 16:01')

    def test_z_offsets_and_naive_dates_display_in_local_time(self):
        column = self.column(format='%Y-%m-%d %H:%M')
        utc = self.now.astimezone(timezone.utc)
        for stamp in (utc.isoformat().replace('+00:00', 'Z'), utc.isoformat(),
                      self.now.astimezone(timezone(timedelta(hours=9))).isoformat(),
                      '2026-10-23T16:01:00'):
            with self.subTest(stamp=stamp):
                self.assertEqual(column.value({'metadata': {'updated': stamp}}), '2026-10-23 16:01')

    def test_missing_or_malformed_dates_preserve_readable_data_and_filter_tokens(self):
        column = self.column(format='%H:%M', filterable=True)
        for value, expected in ((None, '—'), ('', '—'), ('not a date', 'not a date'),
                                ('2026-02-30', '2026-02-30'), (123, '123'),
                                (['2026-10-23'], '["2026-10-23"]')):
            with self.subTest(value=value):
                card = {'metadata': {'updated': value}}
                self.assertEqual(column.value(card), expected)
                self.assertEqual(column.filter_token(card), Column('', metadata='updated').filter_token(card))
        card = {'metadata': {'updated': self.now.isoformat()}}
        self.assertEqual(column.value(card), '16:01')
        self.assertIn('2026-10-23', column.filter_token(card))

    def test_hug_measures_formatted_values(self):
        column = self.column(format='%H:%M')
        placed, hidden = layout_columns((column,), 100, 80,
                                        [{'metadata': {'updated': self.now.isoformat()}}])
        self.assertEqual(placed, [(column, 7)])  # Updated heading, not the ISO timestamp.
        self.assertEqual(hidden, 0)

    def test_invalid_date_rules_report_the_setting(self):
        cases = [({'format': 42}, '.format'), ({'format': '%Y\n%m'}, '.format'),
                 ({'format': '%Y%n%m'}, '.format'), ({'thresholds': {}}, '.thresholds'),
                 ({'thresholds': [None]}, '.thresholds[0]'),
                 ({'thresholds': [{'under': '0d', 'format': '%H'}]}, '.under'),
                 ({'thresholds': [{'under': '1month', 'format': '%H'}]}, '.under'),
                 ({'thresholds': [{'under': True, 'format': '%H'}]}, '.under'),
                 ({'thresholds': [{'under': '1d'}]}, '.format'),
                 ({'thresholds': [{'under': '1d', 'format': '%H', 'extra': 1}]}, 'unknown'),
                 ({'thresholds': [{'under': '1y', 'format': '%H'},
                                  {'under': '1d', 'format': '%H'}]}, 'previous'),
                 ({'thresholds': [{'under': '1d', 'format': '%H'},
                                  {'under': '24h', 'format': '%H'}]}, 'previous')]
        for settings, expected in cases:
            with self.subTest(settings=settings):
                with self.assertRaises(ConfigError) as caught:
                    self.column(**settings)
                self.assertIn('.kanitor.json:', str(caught.exception))
                self.assertIn(expected, str(caught.exception))
