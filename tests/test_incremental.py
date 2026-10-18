from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, patch

from mts.http import ARCHIVE, BASE, TextClient
from mts.incremental import catalog_lock
from mts.storage import load_catalog, write_json
from test_reliability import ExecutionCase, response


class IncrementalTests(ExecutionCase):
    def test_default_does_not_revalidate_existing_or_repeat_access_failures(self):
        self.run_cli('--reparse')
        rows = load_catalog(self.out)
        rows[0]['status'] = 'access_restricted'
        write_json(self.out / 'mts_toc.json', rows)
        with patch('mts.scrape_mts_toc.TextClient.get', return_value=self.cache.read(ARCHIVE)) as fetch:
            self.assertEqual(self.run_cli(), 0)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[0], ARCHIVE)
        self.assertEqual(load_catalog(self.out)[0]['status'], 'access_restricted')

    def test_fresh_discovery_adds_only_new_episode(self):
        self.run_cli('--reparse')
        old = load_catalog(self.out)
        identifiers = [c['chapter_id'] for r in old for c in r['chapters']]
        archive = self.archive + '<h3><a href="/techniques/4/">MTS 4 New</a></h3>'
        session = Mock()
        session.headers = {}
        session.get.side_effect = [response(text='User-agent: *\nAllow: /'), response(text=archive),
                                  response(text='<article><p>00:01 New chapter</p></article>')]
        with patch('mts.http.requests.Session', return_value=session), patch('mts.http.time.sleep'):
            self.assertEqual(self.run_cli('--discover'), 0)
        urls = [call.args[0] for call in session.get.call_args_list]
        self.assertEqual(urls, [BASE + '/robots.txt', ARCHIVE, BASE + '/techniques/4/'])
        rows = load_catalog(self.out)
        self.assertEqual(len(rows), 4)
        self.assertEqual([c['chapter_id'] for r in rows[:3] for c in r['chapters']], identifiers)

    def test_stale_archive_is_refreshed_but_existing_pages_are_not(self):
        self.run_cli('--reparse')
        session = Mock()
        session.headers = {}
        session.get.side_effect = [response(text='User-agent: *\nAllow: /'), response(text=self.archive)]
        with patch('mts.http.requests.Session', return_value=session), patch('mts.http.time.sleep'):
            self.assertEqual(self.run_cli('--discovery-ttl', '0'), 0)
        self.assertEqual([c.args[0] for c in session.get.call_args_list], [BASE + '/robots.txt', ARCHIVE])

    def test_explicit_legacy_revalidation_targets_legacy_only(self):
        self.run_cli('--reparse')
        rows = load_catalog(self.out)
        rows[0]['source']['kind'] = 'legacy_metadata'
        rows[0]['chapters'][0]['source']['kind'] = 'legacy_metadata'
        identifier = rows[0]['chapters'][0]['chapter_id']
        write_json(self.out / 'mts_toc.json', rows)
        original_get = TextClient.get
        called = []
        def get(client, url, **kwargs):
            called.append(url)
            return original_get(client, url, **kwargs)
        with patch.object(TextClient, 'get', get):
            self.assertEqual(self.run_cli('--revalidate-legacy'), 0)
        self.assertEqual(called, [BASE + '/techniques/1/'])
        result = load_catalog(self.out)[0]
        self.assertEqual(result['chapters'][0]['chapter_id'], identifier)
        self.assertEqual(result['source']['kind'], 'raw_html')

    def test_interrupted_revalidation_resumes_saved_worklist(self):
        self.run_cli('--reparse')
        from mts.extraction import extract_episode
        first = extract_episode('<article><p>00:01 First</p></article>')
        with patch('mts.scrape_mts_toc.extract_episode', side_effect=[first, KeyboardInterrupt()]):
            self.assertEqual(self.run_cli('--reparse'), 130)
        journal = json.loads((self.out / 'mts_run.json').read_text())
        self.assertEqual(journal['pending'], [2, 3])
        run_id = journal['run_id']
        with patch('mts.scrape_mts_toc.extract_episode', wraps=extract_episode) as extract:
            self.assertEqual(self.run_cli('--resume'), 0)
        self.assertEqual(extract.call_count, 2)
        journal = json.loads((self.out / 'mts_run.json').read_text())
        self.assertEqual(journal['run_id'], run_id)
        self.assertEqual(journal['pending'], [])
        self.assertEqual(journal['state'], 'complete')

    def test_prior_catalog_snapshot_and_change_reports_are_preserved(self):
        self.run_cli('--reparse')
        original = (self.out / 'mts_toc.json').read_text()
        old_hash = hashlib.sha256(original.encode()).hexdigest()
        old_id = load_catalog(self.out)[0]['chapters'][0]['chapter_id']
        self.cache.write(BASE + '/techniques/1/', '<article><p>00:01 Corrected title</p></article>', 200)
        self.run_cli('--revalidate', '--include', '1')
        snapshot = self.out / 'history' / old_hash / 'mts_toc.json'
        self.assertEqual(snapshot.read_text(), original)
        self.assertEqual(load_catalog(self.out)[0]['chapters'][0]['chapter_id'], old_id)
        changes = json.loads((self.out / 'mts_changes.json').read_text())
        self.assertEqual(changes['changed_episodes'][0]['episode'], 1)
        self.assertTrue((self.out / 'mts_changes.html').exists())
        self.assertEqual(len(list((self.out / 'changes').iterdir())), 2)

    def test_export_finalization_can_resume_after_interruption(self):
        self.run_cli('--reparse')
        with patch('mts.scrape_mts_toc.save_outputs', side_effect=KeyboardInterrupt()):
            self.assertEqual(self.run_cli('--reparse'), 130)
        self.assertEqual(json.loads((self.out / 'mts_run.json').read_text())['state'], 'finalizing')
        self.assertEqual(self.run_cli('--resume'), 0)
        self.assertEqual(json.loads((self.out / 'mts_run.json').read_text())['state'], 'complete')

    def test_output_lock_prevents_concurrent_writers(self):
        with catalog_lock(self.out):
            self.assertEqual(self.run_cli('--reparse'), 1)

    def test_corrupt_resume_journal_preserves_catalog(self):
        self.run_cli('--reparse')
        before = (self.out / 'mts_toc.json').read_text()
        write_json(self.out / 'mts_run.json', dict(incomplete=True))
        self.assertEqual(self.run_cli('--resume'), 1)
        self.assertEqual((self.out / 'mts_toc.json').read_text(), before)

    def test_http_200_login_wall_preserves_source_and_is_not_revalidation(self):
        self.run_cli('--reparse')
        old = load_catalog(self.out)[0]
        self.cache.write(BASE + '/techniques/1/', '<title>Access Denied</title>',200)
        self.run_cli('--reparse','--include','1')
        row = load_catalog(self.out)[0]
        self.assertEqual(row['status'],'access_restricted')
        self.assertEqual(row['source']['sha256'],old['source']['sha256'])
        self.assertEqual(row['last_attempt']['kind'],'http_response')
        self.assertEqual(row['chapters'][0]['chapter_id'],old['chapters'][0]['chapter_id'])

    def test_new_http_200_error_page_does_not_claim_public_metadata(self):
        self.cache.write(BASE + '/techniques/1/', '<title>Access Denied</title>',200)
        self.run_cli('--reparse','--include','1')
        row=load_catalog(self.out)[0]
        self.assertEqual(row['source']['kind'],'http_response')
        self.assertFalse(row['chapters'])

    def test_redirected_wrong_episode_metadata_is_not_accepted(self):
        self.run_cli('--reparse')
        old=load_catalog(self.out)[0]
        self.cache.write(BASE + '/techniques/1/','<article><h2>MTS 2</h2><p>00:01 Wrong episode</p></article>',200)
        self.run_cli('--reparse','--include','1')
        row=load_catalog(self.out)[0]
        self.assertEqual(row['status'],'parse_error')
        self.assertIn('Episode number mismatch',row['error'])
        self.assertEqual(row['chapters'][0]['chapter_id'],old['chapters'][0]['chapter_id'])
        self.assertEqual(row['chapters'][0]['title'],old['chapters'][0]['title'])
