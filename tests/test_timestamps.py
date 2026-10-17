import unittest

from mts.timestamps import enrich_chapters, normalize_timestamp


class TimestampTests(unittest.TestCase):
    def test_formats(self):
        for raw, seconds, kind in [('1:58', 118, 'mm:ss'), ('00:54:14', 3254, 'hh:mm:ss'),
                                   ('0:11:00', 660, 'hh:mm:ss'), ('00: 32:15', 1935, 'hh:mm:ss')]:
            with self.subTest(raw=raw):
                time = normalize_timestamp(raw)
                self.assertEqual(time['time_original'], raw)
                self.assertEqual(time['time_seconds'], seconds)
                self.assertEqual(time['time_format'], kind)
                self.assertTrue(time['time_valid'])

    def test_frames_do_not_assume_rate(self):
        time = normalize_timestamp('00:39:59:22')
        self.assertEqual(time['time_seconds'], 2399)
        self.assertEqual(time['time_frames'], 22)
        self.assertIsNone(time['time_frame_rate'])
        self.assertEqual(time['time_precision'], 'second')
        self.assertTrue(time['time_valid'])

    def test_invalid_and_missing(self):
        for raw in ('00:99:10', '1:99', 'n/a', '00:3:04', '00:02:03:xx'):
            with self.subTest(raw=raw):
                time = normalize_timestamp(raw)
                self.assertFalse(time['time_valid'])
                self.assertIsNone(time['time_seconds'])
                self.assertEqual(time['time_original'], raw)
                self.assertEqual(time['time_format'], 'invalid')
        self.assertEqual(normalize_timestamp('')['time_format'], 'missing')

    def test_validation_keeps_order_and_repeated_titles(self):
        chapters = [dict(time='1:20', title='Sweep'), dict(time='1:20', title='Sweep'),
                    dict(time='1:10', title='Sweep'), dict(time='', title='00:20 Fragment')]
        rows, diagnostics = enrich_chapters(chapters)
        self.assertEqual([r['time'] for r in rows], ['1:20', '1:20', '1:10', ''])
        self.assertEqual([r['order'] for r in rows], [1, 2, 3, 4])
        self.assertEqual({d['code'] for d in diagnostics},
                         {'timestamp_duplicate', 'timestamp_non_monotonic', 'timestamp_missing', 'title_contains_timestamp'})

    def test_frame_order_without_rate_assumption(self):
        _, diagnostics = enrich_chapters([dict(time='00:00:01:22', title='First'),
                                         dict(time='00:00:01:10', title='Second')])
        self.assertIn('timestamp_non_monotonic', {d['code'] for d in diagnostics})


if __name__ == '__main__':
    unittest.main()
