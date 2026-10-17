from pathlib import Path
import unittest

from mts.scrape_mts_toc import BASE, episodes_from_archive, extract_chapters


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


class ArchiveTests(unittest.TestCase):
    def test_archive_links(self):
        html = '<h3><a href="/techniques/one/?x=1#comments">MTS 1 One</a></h3>'
        html += '<h3><a href="https://example.com/">MTS 2 External</a></h3>'
        episodes = episodes_from_archive(html)
        self.assertEqual([ep['number'] for ep in episodes], [1])
        self.assertEqual(episodes[0]['url'], BASE + '/techniques/one/')


if __name__ == '__main__':
    unittest.main()
