from copy import deepcopy
import unittest

from mts.extraction import extract_episode
from mts.reconciliation import reconcile_episode


def episode(entries, kind='raw_html'):
    html = '<article>' + ''.join(f'<p>{time} {title}</p>' for time, title in entries) + '</article>'
    return dict(number=1, title='MTS 1', url='https://www.10thplanetjj.com/techniques/1/',
                source=dict(kind=kind, sha256=kind), **extract_episode(html))


class ReconciliationTests(unittest.TestCase):
    def test_missing_entries_preserved_and_candidate_saved(self):
        old = episode([('00:01', 'First'), ('00:02', 'Second')], 'legacy_metadata')
        before = deepcopy(old)
        result = reconcile_episode(old, episode([('00:01', 'First')]))
        self.assertEqual([c['title'] for c in result['chapters']], ['First', 'Second'])
        self.assertEqual(result['validation']['state'], 'preserved')
        self.assertTrue(result['requires_review'])
        self.assertEqual(len(result['candidate_extraction']['chapters']), 1)
        self.assertEqual(result['chapters'][1]['source']['kind'], 'legacy_metadata')
        self.assertEqual(old, before)

    def test_invalid_new_time_does_not_replace_good_time(self):
        old = episode([('00:01', 'First')])
        current = episode([('00:99', 'First')])
        result = reconcile_episode(old, current)
        self.assertEqual(result['chapters'][0]['time'], '00:01')
        self.assertIn('chapter_quality_regressed', {d['code'] for d in result['diagnostics']})

    def test_reordered_source_does_not_reorder_catalog(self):
        old = episode([('00:01', 'First'), ('00:02', 'Second')])
        result = reconcile_episode(old, episode([('00:02', 'Second'), ('00:01', 'First')]))
        self.assertEqual([c['title'] for c in result['chapters']], ['First', 'Second'])
        self.assertEqual([c['source_order'] for c in result['chapters']], [2, 1])
        self.assertIn('chapter_order_changed', {d['code'] for d in result['diagnostics']})

    def test_ambiguous_replacement_not_added_as_extra_chapter(self):
        result = reconcile_episode(episode([('00:01', 'Old')]), episode([('00:02', 'Different')]))
        self.assertEqual([c['title'] for c in result['chapters']], ['Old'])
        self.assertIn('chapter_match_ambiguous', {d['code'] for d in result['diagnostics']})

    def test_complete_legacy_migration_uses_source_hash(self):
        old = episode([('00:01', 'First')], 'legacy_metadata')
        result = reconcile_episode(old, episode([('00:01', 'First')]))
        self.assertEqual(result['source']['kind'], 'raw_html')
        self.assertEqual(result['chapters'][0]['source']['sha256'], 'raw_html')
        self.assertEqual(result['validation']['state'], 'revalidated')

    def test_source_correction_is_accepted_but_flagged(self):
        old = episode([('00:01', 'First')])
        result = reconcile_episode(old, episode([('00:03', 'First')]))
        self.assertEqual(result['chapters'][0]['time'], '00:03')
        self.assertIn('chapter_timestamp_changed', {d['code'] for d in result['diagnostics']})
        self.assertEqual(result['chapter_changes'][0]['before'], '00:01')

    def test_legitimate_repeated_titles_and_identical_entries_keep_occurrences(self):
        rows = [('00:01', 'Sweep'), ('00:02', 'Sweep'), ('00:02', 'Sweep')]
        result = reconcile_episode(episode(rows), episode(rows))
        self.assertEqual(len(result['chapters']), 3)
        self.assertNotIn('chapter_match_ambiguous', {d['code'] for d in result['diagnostics']})

    def test_insertion_keeps_known_chapters_and_source_order(self):
        old = episode([('00:01', 'First'), ('00:03', 'Last')])
        new = episode([('00:01', 'First'), ('00:02', 'New'), ('00:03', 'Last')])
        result = reconcile_episode(old, new)
        self.assertEqual([c['title'] for c in result['chapters']], ['First', 'New', 'Last'])


if __name__ == '__main__':
    unittest.main()
