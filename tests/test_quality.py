from copy import deepcopy
import unittest

from mts.identity import ensure_catalog_identity
from mts.quality import public_source, quality_report, render_quality
from test_reconciliation import episode


class QualityTests(unittest.TestCase):
    def test_redirect_body_never_counts_as_accepted_source(self):
        self.assertFalse(public_source(dict(kind='raw_html', status_code=302, sha256='a' * 64)))
        self.assertFalse(public_source(dict(kind='raw_html', status_code=200, sha256='invalid')))
        self.assertTrue(public_source(dict(kind='raw_html', status_code=200, sha256='a' * 64)))

    def test_review_followup_separates_access_failures_from_resolution(self):
        before = episode([('00:99', 'Malformed')], 'legacy_metadata')
        ensure_catalog_identity([before])
        after = deepcopy(before)
        after.update(status='access_restricted',requires_review=True)
        after['diagnostics'].append(dict(code='access_restricted',message='Login redirect'))
        identities = [dict(chapter_id=c['chapter_id'],title_original=c['title_original'],original_order=c['original_order']) for c in before['chapters']]
        report = quality_report([before],[after],dict(legacy_episodes=[1],attempts=[dict(episode=1,status='access_restricted')]),identities)
        self.assertEqual(report['coverage']['legacy_or_unverified_episodes'],[1])
        self.assertEqual(report['legacy_audit']['outcomes'],dict(access_restricted=1))
        self.assertEqual(report['review_outcomes']['blocked_by_access_or_operational_failure'],1)
        self.assertEqual(report['identity']['missing_ids'],[])
        self.assertIn('timestamp_malformed',report['original_review_cases'][0]['quality_reasons'])

    def test_identity_loss_and_original_changes_are_visible(self):
        row = episode([('00:01', 'First')])
        ensure_catalog_identity([row])
        identity = dict(chapter_id=row['chapters'][0]['chapter_id'],title_original='Original changed',original_order=1)
        report = quality_report([], [row], {}, [identity,dict(chapter_id='missing',title_original='X',original_order=2)])
        self.assertEqual(report['identity']['missing_ids'],['missing'])
        self.assertEqual(report['identity']['changed_original_fields'],[identity['chapter_id']])
        self.assertIn('cached redirect body',render_quality(report))


if __name__ == '__main__':
    unittest.main()
