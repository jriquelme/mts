#!/usr/bin/env python3
"""Index public MTS episode descriptions, never video resources."""

import argparse
import json
import math
import re
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from mts.extraction import clean, extract_chapters, extract_episode, finish, parse_chapter
from mts.http import ARCHIVE, BASE, USER_AGENT, FetchFailure, OfflineMiss, TextClient
from mts.reconciliation import reconcile_episode
from mts.identity import ensure_catalog_identity
from mts.incremental import FAILED_STATUSES, catalog_lock, plan_run, persist_run, write_changes
from mts.storage import HtmlCache, load_catalog, save_outputs, write_json


EPISODE_RE = re.compile(r'\bMTS\s*(\d{1,4})\b', re.I)


def episodes_from_archive(html):
    soup = BeautifulSoup(html, 'html.parser')
    episodes = {}
    for heading in soup.find_all(['h2', 'h3', 'h4']):
        title = clean(heading.get_text(' ', strip=True))
        match = EPISODE_RE.search(title)
        anchor = heading.find('a', href=True)
        if not match or not anchor:
            continue
        url = urldefrag(urljoin(BASE, anchor['href']))[0].split('?')[0]
        if urlparse(url).netloc not in {'www.10thplanetjj.com', '10thplanetjj.com'}:
            continue
        number = int(match.group(1))
        episodes.setdefault(number, dict(number=number, title=title, url=url))
    return [episodes[n] for n in sorted(episodes)]


def upgrade_legacy(row):
    if row.get('schema_version', 0) >= 3:
        return dict(row)
    if row.get('schema_version', 0) >= 2 and row.get('source', {}).get('kind') != 'legacy_metadata':
        return dict(row)
    result = dict(row)
    chapters, recovered = [], []
    for index, chapter in enumerate(row['chapters'], 1):
        current = dict(chapter)
        if not chapter.get('time'):
            parsed = parse_chapter(chapter['title'])
            if parsed['time_original']:
                current.update(parsed)
                recovered.append(dict(code='timestamp_recovered_from_legacy_title', chapter=index,
                    severity='info', original_title=chapter['title'],
                    message='Time-like prefix separated from an existing catalog label; raw HTML not revalidated.'))
        chapters.append(current)
    result.update(finish(chapters, [], 'legacy_metadata'))
    result['diagnostics'].extend(recovered)
    if not row['chapters']:
        result.update(status='unsupported_layout', requires_review=True)
    if row['status'] in FAILED_STATUSES or row['status'] == 'robots_disallowed':
        result.update(status=row['status'], requires_review=True)
        result['diagnostics'].append(dict(code=row['status'],
            message=row.get('error', 'Previous operational failure; inspect prior evidence.')))
    result['diagnostics'].append(dict(code='raw_html_unavailable', severity='info',
        message='Timestamp metadata normalized from the previous catalog; raw extraction not revalidated.'))
    result.update(schema_version=2, source=dict(row.get('source', {}), kind='legacy_metadata'))
    return result


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='mts_data', help='Catalog and CSV directory')
    parser.add_argument('--cache', default='mts_cache', help='Raw HTML evidence directory')
    parser.add_argument('--delay', type=float, default=5.0, help='Minimum delay per network request (default: 5s, minimum: 2s)')
    parser.add_argument('--limit', type=int, default=0, help='Select the newest N episodes (0: all)')
    parser.add_argument('--include', default='', help='Comma-separated episode numbers')
    modes = parser.add_mutually_exclusive_group()
    parser.add_argument('--resume', action='store_true', help='Continue the pending selection from an interrupted run')
    modes.add_argument('--retry-failed', action='store_true', help='Process only fetch/parse/layout/access failures in the existing catalog')
    modes.add_argument('--revalidate', action='store_true', help='Explicitly revalidate existing episodes')
    modes.add_argument('--revalidate-legacy', action='store_true', help='Revalidate only episodes retaining legacy metadata')
    parser.add_argument('--discover', action='store_true', help='Refresh archive discovery, adding only new episodes unless revalidation is selected')
    parser.add_argument('--discovery-ttl', type=float, default=24, help='Archive cache lifetime in hours (default: 24)')
    parser.add_argument('--reparse', action='store_true', help='Reparse cached HTML only; never use the network')
    parser.add_argument('--refresh', action='store_true', help='Refresh selected cached pages over HTTP')
    args = parser.parse_args(argv)
    if not math.isfinite(args.delay) or args.delay < 2:
        parser.error('Use --delay >= 2 seconds')
    if args.limit < 0:
        parser.error('Use --limit >= 0')
    if not math.isfinite(args.discovery_ttl) or args.discovery_ttl < 0:
        parser.error('Use --discovery-ttl >= 0')
    if args.refresh and args.reparse:
        parser.error('--refresh and --reparse cannot be combined')
    if args.discover and args.reparse:
        parser.error('--discover and --reparse cannot be combined')
    try:
        args.selected = {int(x.strip()) for x in args.include.split(',')} if args.include else set()
        if any(n <= 0 for n in args.selected):
            raise ValueError
    except ValueError:
        parser.error('--include must contain comma-separated positive episode numbers')
    return args


def failure_row(episode, previous, status, message):
    row = dict(previous or episode)
    row.update(status=status, error=message, requires_review=True, schema_version=2)
    row.setdefault('chapters', [])
    row['diagnostics'] = [d for d in row.get('diagnostics', [])
                          if d['code'] not in FAILED_STATUSES | {'robots_disallowed', 'previous_chapters_retained'}]
    row['diagnostics'].append(dict(code=status, message=message))
    if row['chapters']:
        row['diagnostics'].append(dict(code='previous_chapters_retained',
            message='Current attempt failed; existing chapter evidence was kept.'))
    return row


def record_source(row, page):
    source = {k: page[k] for k in ('url', 'final_url', 'status_code', 'fetched_at', 'cache_key', 'request_source')}
    source['kind'] = 'raw_html'
    for field in ('origin', 'final_url_verified', 'sha256', 'redirect_target'):
        if field in page:
            source[field] = page[field]
    if row.get('source') and row['status'] in FAILED_STATUSES | {'robots_disallowed'}:
        row['last_attempt'] = source
        row['validation'] = dict(state=row['status'], source=source)
    else:
        row['source'] = source


def run(args, client):
    existing = load_catalog(args.output)
    journal, episodes = plan_run(args, client, existing, episodes_from_archive)
    client.offline, client.refresh = args.reparse, args.refresh
    rows = {r['number']: upgrade_legacy(r) for r in existing}
    ensure_catalog_identity(list(rows.values()))
    discovered = journal['discovered']
    print(f'Processing {len(episodes)} of {discovered} discovered episodes (sequential public HTML).', flush=True)
    try:
        for index, episode in enumerate(episodes, 1):
            number = episode['number']
            previous = rows.get(number)
            try:
                page = client.get(episode['url'], refresh=bool(
                    previous and previous['status'] in {'fetch_error', 'access_restricted'} and not args.reparse))
                if page['status_code'] != 200:
                    status = 'access_restricted' if page['status_code'] in (401, 403) else 'fetch_error'
                    row = failure_row(episode, previous, status, f'HTTP {page["status_code"]}; inspect cached response.')
                    record_source(row, page)
                else:
                    try:
                        extraction = extract_episode(page['html'])
                    except Exception as exc:
                        row = failure_row(episode, previous, 'parse_error', f'{type(exc).__name__}: {exc}')
                        record_source(row, page)
                    else:
                        candidate = dict(episode, **extraction, schema_version=2)
                        record_source(candidate, page)
                        row = reconcile_episode(previous, candidate)
            except OfflineMiss as exc:
                if previous:
                    row = dict(previous)
                    row['diagnostics'] = [d for d in row.get('diagnostics', []) if d['code'] != 'cache_missing']
                    row['diagnostics'].append(dict(code='cache_missing', severity='info', message=str(exc)))
                else:
                    row = failure_row(episode, None, 'fetch_error', str(exc))
            except FetchFailure as exc:
                row = failure_row(episode, previous, exc.status, str(exc))
                if exc.page:
                    record_source(row, exc.page)
            rows[number] = row
            ensure_catalog_identity(list(rows.values()))
            write_json(Path(args.output) / 'mts_toc.json', sorted(rows.values(), key=lambda r: r['number']))
            journal['completed'].append(number)
            journal['pending'].remove(number)
            persist_run(args.output, journal)
            codes = sorted({d['code'] for d in row.get('diagnostics', []) if d['code'] != 'frame_rate_unknown'})
            print(f'[{index}/{len(episodes)}] MTS {number}: {len(row["chapters"])} chapters '
                  f'({row["status"]}; {row.get("source", {}).get("request_source", "catalog")})'
                  + (f' [{", ".join(codes)}]' if codes else ''), flush=True)
    except KeyboardInterrupt:
        journal['state'] = 'interrupted'
        persist_run(args.output, journal)
        save_outputs(args.output, list(rows.values()), discovered, interrupted=True)
        write_changes(args.output, journal, list(rows.values()))
        print('\nInterrupted. Completed results and exports saved; use --resume to continue.', flush=True)
        return 130
    journal['state'] = 'finalizing'
    persist_run(args.output, journal)
    summary = save_outputs(args.output, list(rows.values()), discovered)
    journal['state'] = 'complete'
    write_changes(args.output, journal, list(rows.values()))
    persist_run(args.output, journal)
    print(json.dumps(dict(summary, network_requests=client.network_requests), indent=2), flush=True)
    return 0


def main(argv=None):
    args = parse_args(argv)
    client = TextClient(HtmlCache(args.cache), delay=args.delay, offline=args.reparse, refresh=args.refresh)
    try:
        with catalog_lock(args.output):
            return run(args, client)
    except KeyboardInterrupt:
        print('\nInterrupted. The catalog and run journal are preserved; use --resume to continue.', flush=True)
        return 130
    except (FetchFailure, ValueError, OSError) as exc:
        print(f'Stopped: {exc}', flush=True)
        return 1
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
