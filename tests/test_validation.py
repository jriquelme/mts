import unittest

from mts.validation import compare, metrics, render_html


def episode(number, chapters, **kwargs):
    return dict(number=number, title=f'MTS {number}', url='https://example.com/',
                chapters=[dict(time=t, title=label) for t, label in chapters], status='ok', **kwargs)


class ValidationTests(unittest.TestCase):
    def test_recoveries_losses_and_changes_are_reported(self):
        before = [episode(1, []), episode(2, [('1:00', 'First'), ('2:00', 'Second')]),
                  episode(3, [('00: 32:15', 'Same title')])]
        after = [episode(1, [('1:00', 'New')], source=dict(kind='raw_html',status_code=200,sha256='a' * 64)),
                 episode(2, [('1:00', 'First')]), episode(3, [('00:32:15', 'Same title')])]
        report = compare(before, after)
        self.assertEqual(report['chapters_newly_recovered'], 1)
        self.assertEqual(report['potential_regressions'][0]['episode'], 2)
        self.assertEqual(report['timestamp_corrections'][0]['before'], '00: 32:15')
        self.assertEqual(len(report['changed_episodes']), 3)
        self.assertEqual(report['source_coverage']['reparsed_html'], [1])

    def test_duplicate_counts_preserved_and_missing_episodes_flagged(self):
        before = [episode(1, [('1:00', 'Repeated'), ('1:00', 'Repeated')]), episode(2, [])]
        after = [episode(1, [('1:00', 'Repeated')])]
        report = compare(before, after)
        self.assertEqual(report['chapters_removed'], 1)
        self.assertEqual(report['missing_episodes'], [2])
        self.assertEqual(report['source_coverage']['originally_empty_without_raw_html'], [2])

    def test_empty_toc_not_counted_as_valid_timestamp_episode(self):
        self.assertEqual(metrics([episode(1, [])])['fully_valid_timestamps'], 0)

    def test_metrics_respect_contextual_timestamp_ambiguity(self):
        row = episode(1, [('58:44:04', 'Ambiguous')])
        row['chapters'][0]['time_valid'] = False
        self.assertEqual(metrics([row])['fully_valid_timestamps'], 0)

    def test_html_report_includes_metrics_and_coverage_limits(self):
        report = compare([episode(1, [])], [episode(1, [('1:00', 'New')])])
        html = render_html(report)
        self.assertIn('Episodes with chapters', html)
        self.assertIn('not independently revalidated', html)
        self.assertIn('unknown frame rate', html)

    def test_cached_redirect_is_not_public_chapter_evidence(self):
        row = episode(1, [('1:00', 'Legacy')], source=dict(kind='raw_html',status_code=302,sha256='a' * 64))
        report = compare([], [row])
        self.assertEqual(report['source_coverage']['reparsed_html'], [])
        self.assertEqual(report['source_coverage']['retained_metadata'], [1])

    def test_missing_ids_and_changed_original_metadata_are_regressions(self):
        before = episode(1, [('1:00', 'First'),('2:00','Second')])
        after = episode(1, [('1:00', 'Corrected'),('2:00','Second')])
        before['chapters'][0].update(chapter_id='mts-0001-c000001',title_original='First',original_order=1)
        before['chapters'][1].update(chapter_id='mts-0001-c000002',title_original='Second',original_order=2)
        after['chapters'][0].update(chapter_id='mts-0001-c000001',title_original='Wrongly overwritten',original_order=1)
        after['chapters'][1].update(chapter_id='mts-0001-c000003',title_original='Second',original_order=2)
        report = compare([before],[after])
        self.assertEqual(report['missing_chapter_ids'],['mts-0001-c000002'])
        self.assertEqual(report['original_metadata_changes'][0]['field'],'title_original')


if __name__ == '__main__':
    unittest.main()
