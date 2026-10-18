from contextlib import redirect_stderr, redirect_stdout
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from mts.http import ARCHIVE, BASE, FetchFailure, TextClient, validate_url
from mts.scrape_mts_toc import main
from mts.storage import HtmlCache, atomic_file, load_catalog, save_outputs, write_json


def response(status=200, text='', headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = text.encode()
    result.encoding = 'utf-8'
    result.headers.update(headers or {'Content-Type': 'text/html'})
    return result


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = Mock()
        self.session.headers = {}
        self.client = TextClient(self.temp.name, session=self.session)
        self.pause = patch('mts.http.time.sleep')
        self.sleep = self.pause.start()
        self.addCleanup(self.pause.stop)

    def test_cache_hit_and_offline_miss_make_no_requests(self):
        self.client.cache.write(ARCHIVE, 'cached', 200)
        self.assertEqual(self.client.get(ARCHIVE)['html'], 'cached')
        self.client.offline = True
        with self.assertRaises(FetchFailure):
            self.client.get(BASE + '/techniques/missing/')
        self.session.get.assert_not_called()
        self.sleep.assert_not_called()

    def test_robots_checked_before_live_request(self):
        self.session.get.side_effect = [response(text='User-agent: *\nDisallow: /'), response(text='unused')]
        with self.assertRaisesRegex(FetchFailure, 'disallows'):
            self.client.get(ARCHIVE)
        self.assertEqual(self.session.get.call_count, 1)

    def test_unavailable_robots_fails_closed(self):
        self.session.get.return_value = response(404)
        with self.assertRaisesRegex(FetchFailure, 'robots.txt unavailable'):
            self.client.get(ARCHIVE)
        self.assertEqual(self.session.get.call_count, 1)

    def test_transient_failure_respects_retry_after(self):
        self.session.get.side_effect = [response(text='User-agent: *\nAllow: /'),
            response(429, headers={'Retry-After': '12'}), response(text='success')]
        page = self.client.get(ARCHIVE)
        self.assertEqual(page['html'], 'success')
        self.assertIn(((12.0,), {}), [(c.args, c.kwargs) for c in self.sleep.call_args_list])
        self.assertEqual(self.session.get.call_count, 3)
        self.assertTrue(all(c.kwargs['timeout'] == (10, 30) for c in self.session.get.call_args_list))

    def test_long_retry_after_records_failure_without_early_retry(self):
        self.session.get.side_effect = [response(text='User-agent: *\nAllow: /'),
            response(429, headers={'Retry-After': '300'})]
        self.assertEqual(self.client.get(ARCHIVE)['status_code'], 429)
        self.assertEqual(self.session.get.call_count, 2)

    def test_exhausted_transient_response_is_cached(self):
        self.client.retries = 2
        self.session.get.side_effect = [response(text='User-agent: *\nAllow: /'), response(503), response(503)]
        self.assertEqual(self.client.get(ARCHIVE)['status_code'], 503)
        self.assertEqual(self.client.cache.read(ARCHIVE)['status_code'], 503)
        self.assertEqual(self.session.get.call_count, 3)

    def test_auth_http_not_retried_and_redirect_not_followed(self):
        self.session.get.side_effect = [response(text='User-agent: *\nAllow: /'), response(403)]
        self.assertEqual(self.client.get(ARCHIVE)['status_code'], 403)
        self.assertEqual(self.session.get.call_count, 2)
        self.session.get.side_effect = [response(302, headers={'Location': '/login/'})]
        with self.assertRaises(FetchFailure) as error:
            self.client.get(BASE + '/techniques/one/')
        self.assertEqual(error.exception.status, 'access_restricted')
        self.assertEqual(self.session.get.call_count, 3)
        self.assertEqual(error.exception.page['redirect_target'], BASE + '/login/')
        self.client.offline = True
        with self.assertRaises(FetchFailure) as cached:
            self.client.get(BASE + '/techniques/one/')
        self.assertEqual(cached.exception.status, 'access_restricted')
        self.assertEqual(self.session.get.call_count, 3)

    def test_network_timeouts_are_bounded(self):
        self.client.retries = 2
        self.session.get.side_effect = [requests.Timeout('timeout'), requests.Timeout('timeout')]
        with self.assertRaises(FetchFailure):
            self.client.get(ARCHIVE)
        self.assertEqual(self.session.get.call_count, 2)

    def test_video_external_and_login_urls_refused(self):
        for url in ('https://example.com/', BASE + '/video.mp4', BASE + '/login/',
                    'http://www.10thplanetjj.com/techniques/one/'):
            with self.subTest(url=url), self.assertRaises(FetchFailure):
                validate_url(url)

    def test_corrupt_cache_never_silently_reparsed(self):
        self.client.cache.write(ARCHIVE, 'good', 200)
        path = Path(self.temp.name) / (HtmlCache.key(ARCHIVE) + '.html')
        path.write_text('torn write')
        self.client.offline = True
        with self.assertRaisesRegex(FetchFailure, 'Corrupt cache'):
            self.client.get(ARCHIVE)

    def test_refresh_preserves_previous_hashed_evidence(self):
        old = self.client.cache.write(ARCHIVE, 'valid source', 200)
        self.client.cache.write(ARCHIVE, 'redirect body', 302, redirect_target=BASE + '/login/')
        self.assertEqual(self.client.cache.read_source(old), 'valid source')
        self.assertEqual(self.client.cache.read(ARCHIVE)['status_code'], 302)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = HtmlCache(self.root / 'cache')
        self.out = self.root / 'out'
        self.archive = ''.join(f'<h3><a href="/techniques/{n}/">MTS {n} Episode</a></h3>' for n in (1, 2, 3))
        self.cache.write(ARCHIVE, self.archive, 200)
        for n in (1, 2, 3):
            self.cache.write(BASE + f'/techniques/{n}/',
                f'<div id="main-video"><div class="about"><h2>MTS {n}</h2><p>00:01 First</p></div></div>', 200)
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def run_cli(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(['--output', str(self.out), '--cache', str(self.cache.directory), *args])

    def test_offline_outputs_and_subset_preserve_existing_catalog(self):
        self.assertEqual(self.run_cli('--reparse'), 0)
        self.assertEqual(len(load_catalog(self.out)), 3)
        self.assertEqual(self.run_cli('--reparse', '--include', '2'), 0)
        self.assertEqual(len(load_catalog(self.out)), 3)
        with (self.out / 'mts_chapters.csv').open() as f:
            self.assertEqual(len(list(csv.DictReader(f))), 3)

    def test_resume_uses_archive_to_discover_unprocessed_episodes(self):
        self.assertEqual(self.run_cli('--reparse', '--include', '1'), 0)
        self.assertEqual(len(load_catalog(self.out)), 1)
        self.assertEqual(self.run_cli('--resume'), 0)
        self.assertEqual(len(load_catalog(self.out)), 3)

    def test_retry_failed_excludes_source_limitations(self):
        self.run_cli('--reparse')
        rows = load_catalog(self.out)
        rows[0]['status'] = 'parse_error'
        rows[1]['status'] = 'toc_not_present'
        rows[2]['status'] = 'toc_untimed'
        write_json(self.out / 'mts_toc.json', rows)
        self.assertEqual(self.run_cli('--retry-failed', '--reparse'), 0)
        self.assertEqual([r['status'] for r in load_catalog(self.out)], ['ok', 'toc_not_present', 'toc_untimed'])

    def test_retry_failed_refreshes_http_failure_only(self):
        self.cache.write(BASE + '/techniques/1/', 'Unavailable', 503)
        self.run_cli('--reparse')
        session = Mock()
        session.headers = {}
        session.get.side_effect = [response(text='User-agent: *\nAllow: /'),
                                  response(text='<article><p>00:01 Recovered</p></article>')]
        with patch('mts.http.requests.Session', return_value=session), patch('mts.http.time.sleep'):
            self.assertEqual(self.run_cli('--retry-failed'), 0)
        self.assertEqual(session.get.call_count, 2)  # robots and the single failed page
        self.assertEqual(load_catalog(self.out)[0]['status'], 'ok')

    def test_retry_failed_without_catalog_stops_without_network(self):
        self.assertEqual(self.run_cli('--retry-failed'), 1)

    def test_legacy_operational_failure_remains_retryable(self):
        self.run_cli('--reparse', '--include', '1')
        rows = load_catalog(self.out)
        rows[0].pop('schema_version')
        rows[0]['status'] = 'parse_error'
        write_json(self.out / 'mts_toc.json', rows)
        self.assertEqual(self.run_cli('--retry-failed', '--reparse'), 0)
        self.assertEqual(load_catalog(self.out)[0]['status'], 'ok')

    def test_legacy_time_fragment_is_normalized_with_provenance(self):
        from mts.scrape_mts_toc import upgrade_legacy
        row = dict(number=96, title='MTS 96', url=BASE + '/techniques/96/',
                   status='toc_untimed', chapters=[dict(time='', title='00: 32:15 Br azilian MMA Fighter captures robber')])
        upgraded = upgrade_legacy(row)
        chapter = upgraded['chapters'][0]
        self.assertEqual(chapter['time_original'], '00: 32:15')
        self.assertEqual(chapter['time_seconds'], 1935)
        self.assertEqual(chapter['title'], 'Br azilian MMA Fighter captures robber')
        self.assertEqual(upgraded['source']['kind'], 'legacy_metadata')
        self.assertIn('timestamp_recovered_from_legacy_title', {d['code'] for d in upgraded['diagnostics']})

    def test_legacy_access_diagnostic_and_live_check_survive_reparse(self):
        from mts.scrape_mts_toc import upgrade_legacy
        row = dict(number=90, title='MTS 90', url=BASE + '/techniques/90/', schema_version=2,
                   status='access_restricted', error='Login-related redirect declined',
                   source=dict(kind='legacy_metadata', last_live_check=dict(status='access_restricted')),
                   chapters=[dict(time='00:01:00', title='Known chapter')])
        upgraded = upgrade_legacy(row)
        self.assertEqual(upgraded['source']['last_live_check']['status'], 'access_restricted')
        self.assertIn('access_restricted', {d['code'] for d in upgraded['diagnostics']})

    def test_missing_cache_preserves_legacy_chapters_with_explicit_provenance(self):
        self.run_cli('--reparse', '--include', '1')
        rows = load_catalog(self.out)
        rows[0].pop('schema_version')
        write_json(self.out / 'mts_toc.json', rows)
        (self.cache.directory / (HtmlCache.key(rows[0]['url']) + '.html')).unlink()
        self.assertEqual(self.run_cli('--reparse', '--include', '1'), 0)
        result = load_catalog(self.out)[0]
        self.assertEqual(len(result['chapters']), 1)
        self.assertEqual(result['source']['kind'], 'legacy_metadata')
        self.assertIn('cache_missing', {d['code'] for d in result['diagnostics']})

    def test_http_access_and_failure_have_distinct_statuses(self):
        self.cache.write(BASE + '/techniques/1/', 'Forbidden', 403)
        self.cache.write(BASE + '/techniques/2/', 'Unavailable', 503)
        self.run_cli('--reparse')
        self.assertEqual([r['status'] for r in load_catalog(self.out)], ['access_restricted', 'fetch_error', 'ok'])

    def test_parser_exception_is_separate_from_fetch_failure(self):
        with patch('mts.scrape_mts_toc.extract_episode', side_effect=ValueError('broken markup')):
            self.run_cli('--reparse', '--include', '1')
        self.assertEqual(load_catalog(self.out)[0]['status'], 'parse_error')

    def test_interruption_saves_all_exports_and_returns_130(self):
        from mts.extraction import extract_episode
        first = extract_episode('<article><p>00:01 First</p></article>')
        with patch('mts.scrape_mts_toc.extract_episode', side_effect=[first, KeyboardInterrupt()]):
            self.assertEqual(self.run_cli('--reparse'), 130)
        self.assertEqual(len(load_catalog(self.out)), 1)
        self.assertTrue(json.loads((self.out / 'mts_summary.json').read_text())['interrupted'])
        self.assertTrue((self.out / 'mts_review.csv').exists())

    def test_chapter_loss_is_flagged(self):
        self.run_cli('--reparse', '--include', '1')
        self.cache.write(BASE + '/techniques/1/', '<article><h2>MTS 1</h2></article>', 200)
        self.run_cli('--reparse', '--include', '1')
        result = load_catalog(self.out)[0]
        self.assertIn('chapter_count_decreased', {d['code'] for d in result['diagnostics']})

    def test_network_failure_preserves_previous_chapters(self):
        self.run_cli('--reparse', '--include', '1')
        with patch('mts.scrape_mts_toc.TextClient.get', side_effect=[
                self.cache.read(ARCHIVE), FetchFailure('timeout')]):
            self.assertEqual(self.run_cli('--include', '1'), 0)
        row = load_catalog(self.out)[0]
        self.assertEqual(row['status'], 'fetch_error')
        self.assertEqual(len(row['chapters']), 1)
        self.assertIn('previous_chapters_retained', {d['code'] for d in row['diagnostics']})

    def test_review_csv_includes_warning_for_ok_status(self):
        self.cache.write(BASE + '/techniques/1/', '<article><p>00:02 First</p><p>00:01 Second</p></article>', 200)
        self.run_cli('--reparse', '--include', '1')
        with (self.out / 'mts_review.csv').open() as f:
            row = list(csv.DictReader(f))[0]
        self.assertEqual(row['episode'], '1')
        self.assertEqual(row['status'], 'ok')
        self.assertIn('timestamp_non_monotonic', row['reasons'])

    def test_invalid_selection_and_arguments(self):
        self.assertEqual(self.run_cli('--reparse', '--include', '99'), 1)
        for args in (['--delay', 'nan'], ['--delay', '1'], ['--limit', '-1'],
                     ['--include', 'no'], ['--include', '1,'], ['--include', '0'],
                     ['--refresh', '--reparse']):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                self.run_cli(*args)
            self.assertEqual(error.exception.code, 2)

    def test_atomic_failure_keeps_previous_file(self):
        path = self.root / 'atomic.json'
        path.write_text('original')
        with self.assertRaises(RuntimeError):
            with atomic_file(path) as stream:
                stream.write('incomplete')
                raise RuntimeError('interrupted')
        self.assertEqual(path.read_text(), 'original')
        self.assertFalse(list(self.root.glob('*.tmp')))


if __name__ == '__main__':
    unittest.main()
