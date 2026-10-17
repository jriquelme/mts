import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from mts.scrape_mts_toc import ARCHIVE, BASE, episodes_from_archive, extract_chapters, get, main


FIXTURES = Path(__file__).parent / 'fixtures'


class ChapterTests(unittest.TestCase):
    def fixture(self, number):
        return (FIXTURES / f'mts-{number}.html').read_text()

    def test_modern_toc_uses_description_instead_of_comments(self):
        chapters, status = extract_chapters(self.fixture(180))
        self.assertEqual(status, 'ok')
        self.assertEqual(len(chapters), 14)
        self.assertEqual(chapters[0]['time'], '00:02:13')
        self.assertEqual(chapters[-1]['time'], '00:52:09')
        self.assertFalse(any(c['title'] == 'Unrelated comment' for c in chapters))

    def test_timestamp_broken_across_br(self):
        chapters, status = extract_chapters(self.fixture(260))
        self.assertEqual(status, 'ok')
        self.assertEqual(len(chapters), 15)
        self.assertEqual(chapters[1]['time'], '00:03:04')
        self.assertEqual(chapters[-1]['time'], '01:30:49')

    def test_old_untimed_bullets_preserve_inline_formatting(self):
        chapters, status = extract_chapters(self.fixture(34))
        self.assertEqual(status, 'toc_untimed')
        self.assertEqual(len(chapters), 11)
        self.assertEqual(chapters[1]['title'], 'Eddie teaches Ronda Rousey the Rubber Guard Part 1')
        self.assertTrue(all(c['time'] == '' for c in chapters))

    def test_old_trailing_timestamp(self):
        chapters, status = extract_chapters(self.fixture(1))
        self.assertEqual(status, 'toc_partial')
        self.assertEqual({k: chapters[1][k] for k in ('time', 'title')}, {'time': '1:58', 'title': 'Japanese Necktie'})

    def test_inline_tags_and_multiple_chapters_in_one_paragraph(self):
        chapters, status = extract_chapters('''<article><h3>Table of Contents:</h3>
            <p>00:01:02 <strong>First</strong> chapter<br>00:02:03 Second chapter</p>
            <p>00:02:03 Second chapter</p></article>''')
        self.assertEqual(status, 'ok')
        self.assertEqual([{k: c[k] for k in ('time', 'title')} for c in chapters], [
            {'time': '00:01:02', 'title': 'First chapter'},
            {'time': '00:02:03', 'title': 'Second chapter'},
            {'time': '00:02:03', 'title': 'Second chapter'},
        ])

    def test_missing_and_empty_toc(self):
        self.assertEqual(extract_chapters('<div id="content">Table of Contents<br>00:01:00 Comment</div>'),
                         ([], 'unsupported_layout'))
        self.assertEqual(extract_chapters('<article><p>Table of Contents</p></article>'),
                         ([], 'toc_not_present'))

    def test_frame_timestamp(self):
        chapters, status = extract_chapters('<article><p>Table of Contents</p><p>00:01:02:03 Frames</p></article>')
        self.assertEqual(status, 'ok')
        self.assertEqual(chapters[0]['time'], '00:01:02:03')


class CrawlTests(unittest.TestCase):
    archive = '''<h3><a href="/techniques/one/?x=1#comments">MTS 1 One</a></h3>
        <h3><a href="/techniques/two/">MTS 2 Two</a></h3>
        <h3><a href="https://example.com/">MTS 3 External</a></h3>'''

    def test_archive_links(self):
        episodes = episodes_from_archive(self.archive)
        self.assertEqual([ep['number'] for ep in episodes], [1, 2])
        self.assertEqual(episodes[0]['url'], BASE + '/techniques/one/')

    @patch('mts.scrape_mts_toc.get')
    def test_end_to_end_exports_and_review_episode_number(self, fetch):
        fetch.side_effect = ['User-agent: *\nAllow: /', self.archive,
                             (FIXTURES / 'mts-1.html').read_text(),
                             (FIXTURES / 'mts-260.html').read_text()]
        with tempfile.TemporaryDirectory() as output:
            main(['--output', output, '--include', '1,2', '--delay', '2'])
            out = Path(output)
            items = json.loads((out / 'mts_toc.json').read_text())
            self.assertEqual([row['status'] for row in items], ['toc_partial', 'ok'])
            summary = json.loads((out / 'mts_summary.json').read_text())
            self.assertEqual((summary['episodes'], summary['chapters'], summary['require_review']), (2, 18, 1))
            with (out / 'mts_review.csv').open() as f:
                self.assertEqual(list(csv.DictReader(f))[0]['episode'], '1')
            with (out / 'mts_chapters.csv').open() as f:
                self.assertEqual(len(list(csv.DictReader(f))), 18)
        self.assertEqual(fetch.call_args_list[0].args[1], BASE + '/robots.txt')

    @patch('mts.scrape_mts_toc.get')
    def test_robots_disallow_stops_before_archive(self, fetch):
        fetch.return_value = 'User-agent: *\nDisallow: /'
        with tempfile.TemporaryDirectory() as output:
            with self.assertRaisesRegex(SystemExit, 'disallows'):
                main(['--output', output])
        self.assertEqual(fetch.call_count, 1)

    @patch('mts.scrape_mts_toc.get')
    def test_missing_selection_does_not_silently_produce_empty_output(self, fetch):
        fetch.side_effect = ['User-agent: *\nAllow: /', self.archive]
        with tempfile.TemporaryDirectory() as output:
            with self.assertRaisesRegex(SystemExit, 'Episodes not found.*99'):
                main(['--output', output, '--include', '99'])

    @patch('mts.scrape_mts_toc.get')
    def test_invalid_arguments_do_not_fetch(self, fetch):
        for args in (['--delay', 'nan'], ['--delay', '1'], ['--limit', '-1'],
                     ['--include', 'no'], ['--include', '1,'], ['--include', '0']):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code, 2)
        fetch.assert_not_called()

    @patch('mts.scrape_mts_toc.time.sleep')
    def test_retry_transient_http_failure(self, sleep):
        unavailable = requests.Response()
        unavailable.status_code = 503
        success = requests.Response()
        success.status_code = 200
        success._content = b'HTML'
        session = Mock()
        session.get.side_effect = [unavailable, success]
        self.assertEqual(get(session, ARCHIVE, 2), 'HTML')
        self.assertEqual(session.get.call_count, 2)

    @patch('mts.scrape_mts_toc.time.sleep')
    def test_retry_exhaustion_raises_http_error_without_last_backoff(self, sleep):
        unavailable = requests.Response()
        unavailable.status_code = 503
        session = Mock()
        session.get.return_value = unavailable
        with self.assertRaises(requests.HTTPError):
            get(session, ARCHIVE, 2, retries=2)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(sleep.call_count, 3)


if __name__ == '__main__':
    unittest.main()
