from pathlib import Path
import unittest

from mts.extraction import extract_episode


FIXTURES = Path(__file__).parent / 'fixtures'


class ExtractionTests(unittest.TestCase):
    def test_verified_layout_pairs(self):
        expected = {100: 22, 101: 11, 157: 14, 158: 19, 210: 27, 211: 15,
                    220: 33, 221: 29, 242: 21, 243: 7, 244: 15}
        for number, count in expected.items():
            with self.subTest(episode=number):
                result = extract_episode((FIXTURES / f'mts-{number}.html').read_text())
                self.assertEqual(len(result['chapters']), count)
                self.assertTrue(result['chapters'][0]['time_valid'])

    def test_genuinely_absent_descriptions_are_not_auth_failures(self):
        for number in (15, 23):
            with self.subTest(episode=number):
                html = (FIXTURES / f'mts-{number}.html').read_text()
                result = extract_episode(html + '<form><input type="password"></form>')
                self.assertEqual(result['status'], 'toc_not_present')
                self.assertFalse(result['chapters'])

    def test_untitled_timecode_preserved(self):
        result = extract_episode((FIXTURES / 'mts-211.html').read_text())
        row = result['chapters'][4]
        self.assertEqual(row['time_original'], '00:33:16:18')
        self.assertEqual(row['title'], '')
        self.assertEqual(result['status'], 'toc_partial')
        self.assertIn('chapter_title_missing', {d['code'] for d in result['diagnostics']})

    def test_legitimate_repeated_headings_are_preserved(self):
        result = extract_episode((FIXTURES / 'mts-101.html').read_text())
        sweeps = [c for c in result['chapters'] if c['title'] == 'COP Sweep']
        self.assertEqual(len(sweeps), 3)
        self.assertEqual([c['time'] for c in sweeps], ['00:27:43', '00:57:07', '01:14:15'])

    def test_leaf_blocks_do_not_duplicate_nested_list_chapters(self):
        result = extract_episode('<article><ul><li><p>00:01 First</p></li><li>00:02 Second</li></ul></article>')
        self.assertEqual(len(result['chapters']), 2)

    def test_br_inside_title_is_continuation(self):
        result = extract_episode((FIXTURES / 'mts-221.html').read_text())
        self.assertEqual(result['chapters'][24]['title'],
                         'Fedor Nikolov vs Garrett Lineberger at High Rollerz Blue Belt Championship')

    def test_attached_title_after_timecode(self):
        result = extract_episode('<article><p>00:39:00Eddie Bravo on Music, MMA, Nick Diaz</p></article>')
        self.assertEqual(result['chapters'][0]['time_original'], '00:39:00')
        self.assertEqual(result['chapters'][0]['title'], 'Eddie Bravo on Music, MMA, Nick Diaz')

    def test_mixed_heading_case_spacing_invalid_and_untimed(self):
        result = extract_episode('''<article><h3>MTS 9 TABLE OF CONTENTS:</h3>
            <p>00: 32:15 – First</p><p>00:99:15 Invalid</p><p>Untimed</p></article>''')
        self.assertEqual(result['status'], 'toc_partial')
        self.assertEqual(result['chapters'][0]['time_original'], '00: 32:15')
        self.assertEqual(result['chapters'][0]['time_seconds'], 1935)
        self.assertFalse(result['chapters'][1]['time_valid'])
        self.assertEqual(result['chapters'][2]['title'], 'Untimed')

    def test_navigation_comments_embeds_and_recommendations_excluded(self):
        result = extract_episode('''<article><h3>Table of Contents</h3>
            <p>00:01 First</p><div class="related-posts"><p>00:02 Related</p></div>
            <nav><p>00:03 Navigation</p></nav><div id="comments"><p>00:04 Comment</p></div>
            <iframe src="video"></iframe><p hidden>00:05 Hidden duplicate</p></article>''')
        self.assertEqual([r['title'] for r in result['chapters']], ['First'])

    def test_unrecognized_page_and_auth_wall(self):
        self.assertEqual(extract_episode('<main>Unknown layout</main>')['status'], 'unsupported_layout')
        self.assertEqual(extract_episode('<input type="password">')['status'], 'access_restricted')


if __name__ == '__main__':
    unittest.main()
