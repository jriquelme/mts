from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from mts.exports import flat_chapters
from mts.identity import ensure_catalog_identity
from mts.reconciliation import reconcile_episode
from mts.storage import load_catalog, save_outputs
from test_reconciliation import episode


class IdentityTests(unittest.TestCase):
    def test_ids_do_not_depend_on_title_or_time(self):
        old = episode([('00:01', 'First'), ('00:02', 'Second')])
        ensure_catalog_identity([old])
        identifiers = [c['chapter_id'] for c in old['chapters']]
        result = reconcile_episode(old, episode([('00:03', 'First'), ('00:02', 'Renamed')]))
        ensure_catalog_identity([result])
        self.assertEqual([c['chapter_id'] for c in result['chapters']], identifiers)
        self.assertEqual(result['chapters'][1]['title_original'], 'Second')
        self.assertEqual(result['chapters'][1]['title_normalized'], 'Renamed')

    def test_insertions_allocate_new_id_without_renumbering(self):
        old = episode([('00:01', 'First'), ('00:03', 'Last')])
        ensure_catalog_identity([old])
        result = reconcile_episode(old, episode([('00:01', 'First'), ('00:02', 'Inserted'), ('00:03', 'Last')]))
        ensure_catalog_identity([result])
        self.assertEqual([c['chapter_id'] for c in result['chapters']],
                         ['mts-0001-c000001', 'mts-0001-c000003', 'mts-0001-c000002'])
        self.assertEqual(result['chapters'][-1]['original_order'], 2)

    def test_duplicate_source_chapters_have_distinct_ids(self):
        row = episode([('00:01', 'Repeated'), ('00:01', 'Repeated')])
        ensure_catalog_identity([row])
        self.assertEqual(len({c['chapter_id'] for c in row['chapters']}), 2)
        again = reconcile_episode(row, episode([('00:01', 'Repeated'), ('00:01', 'Repeated')]))
        ensure_catalog_identity([again])
        self.assertEqual([c['chapter_id'] for c in row['chapters']], [c['chapter_id'] for c in again['chapters']])

    def test_collisions_fail_and_retired_ids_are_never_reused(self):
        row = episode([('00:01', 'First')])
        row['retired_chapter_ids'] = ['mts-0001-c000010']
        ensure_catalog_identity([row])
        self.assertEqual(row['chapters'][0]['chapter_id'], 'mts-0001-c000011')
        row['chapters'].append(deepcopy(row['chapters'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate chapter ID'):
            ensure_catalog_identity([row])

    def test_timestamp_correction_clears_stale_frame_metadata(self):
        old = episode([('00:01:00:22', 'First')])
        ensure_catalog_identity([old])
        result = reconcile_episode(old, episode([('00:01:01', 'First')]))
        self.assertNotIn('time_frames', result['chapters'][0])
        self.assertEqual(result['chapters'][0]['chapter_id'], old['chapters'][0]['chapter_id'])


class ExportTests(unittest.TestCase):
    def test_jsonl_csv_and_catalog_share_stable_id_and_provenance(self):
        rows = [episode([('00:01', 'First'), ('00:02', 'Second')])]
        with tempfile.TemporaryDirectory() as directory:
            save_outputs(directory, rows)
            path = Path(directory)
            records = [json.loads(line) for line in (path / 'mts_chapters.jsonl').read_text().splitlines()]
            with (path / 'mts_chapters.csv').open() as stream:
                csv_rows = list(csv.DictReader(stream))
            catalog = load_catalog(directory)
            self.assertEqual([r['chapter_id'] for r in records], [r['chapter_id'] for r in csv_rows])
            self.assertEqual(records[0]['chapter_id'], catalog[0]['chapters'][0]['chapter_id'])
            self.assertEqual(records[0]['source']['sha256'], 'raw_html')
            self.assertEqual(records[0]['time_seconds'], 1)
            self.assertEqual(records[0]['timestamp_confidence'], 'whole_second')
            for field in ('original_order', 'title_original', 'title_normalized', 'timestamp_raw', 'diagnostics', 'source_url'):
                self.assertIn(field, records[0])

    def test_ambiguous_times_and_legacy_evidence_are_explicit(self):
        legacy = episode([('00:01', 'Known')], 'legacy_metadata')
        ambiguous = episode([('00:02:08:00', 'Intro'), ('58:44:04', 'Ambiguous')])
        ambiguous['number'] = 2
        ensure_catalog_identity([legacy, ambiguous])
        records = list(flat_chapters([legacy, ambiguous]))
        self.assertEqual(records[0]['timestamp_confidence'], 'unverified_legacy')
        self.assertIsNone(records[-1]['time_seconds'])
        self.assertEqual(records[-1]['timestamp_confidence'], 'ambiguous')
        self.assertIn('timestamp_format_ambiguous', {d['code'] for d in records[-1]['diagnostics']})

    def test_original_title_and_unicode_whitespace_normalization(self):
        row = episode([('00:01', 'First')])
        row['chapters'][0]['title_source'] = '  Original\n spacing '
        row['chapters'][0]['title'] = 'Cafe\u0301   title'
        ensure_catalog_identity([row])
        record = next(flat_chapters([row]))
        self.assertEqual(record['title_original'], '  Original\n spacing ')
        self.assertEqual(record['title_normalized'], 'Café title')


if __name__ == '__main__':
    unittest.main()
