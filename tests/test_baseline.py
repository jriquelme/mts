"""Freeze the original catalog and source evidence independently of the parser."""

import json
from pathlib import Path
import unittest

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]


class BaselineTests(unittest.TestCase):
    def test_original_metrics(self):
        rows = json.loads((ROOT / 'reports/baseline/mts_toc.json').read_text())
        self.assertEqual(len(rows), 260)
        self.assertEqual(sum(len(r['chapters']) for r in rows), 2582)
        self.assertEqual(sum(bool(r['chapters']) for r in rows), 178)
        self.assertEqual(sum(r['status'] != 'ok' for r in rows), 103)

    def test_headingless_source_was_missed(self):
        rows = json.loads((ROOT / 'reports/baseline/mts_toc.json').read_text())
        self.assertEqual(next(r for r in rows if r['number'] == 101)['chapters'], [])
        soup = BeautifulSoup((ROOT / 'tests/fixtures/mts-101.html').read_text(), 'html.parser')
        self.assertEqual(len(soup.select('#main-video .about p')), 11)
        self.assertNotIn('Table of Contents', soup.get_text())

    def test_prefixed_heading_and_untitled_timecode_evidence(self):
        soup = BeautifulSoup((ROOT / 'tests/fixtures/mts-211.html').read_text(), 'html.parser')
        text = soup.get_text(' ', strip=True)
        self.assertIn('MTS 211 Table Of Contents', text)
        self.assertIn('00:33:16:18', text)


if __name__ == '__main__':
    unittest.main()
