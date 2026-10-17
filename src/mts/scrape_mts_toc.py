#!/usr/bin/env python3
"""Index public MTS episode descriptions, never video resources."""

import argparse
import json
import math
import re
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from mts.extraction import clean, extract_chapters, extract_episode, finish
from mts.http import ARCHIVE, BASE, USER_AGENT, FetchFailure, OfflineMiss, TextClient
from mts.storage import HtmlCache, load_catalog, save_outputs


EPISODE_RE = re.compile(r'\bMTS\s*(\d{1,4})\b', re.I)
FAILED_STATUSES = {'fetch_error', 'parse_error', 'unsupported_layout', 'access_restricted'}


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
    if row.get('schema_version') == 2:
        return dict(row)
    result = dict(row)
    result.update(finish(row['chapters'], [], 'legacy_metadata'))
    if not row['chapters']:
        result.update(status='unsupported_layout', requires_review=True)
    result['diagnostics'].append(dict(code='raw_html_unavailable', severity='info',
        message='Timestamp metadata normalized from the previous catalog; raw extraction not revalidated.'))
    result.update(schema_version=2, source=dict(kind='legacy_metadata'))
    return result


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='mts_data', help='Catalog and CSV directory')
    parser.add_argument('--cache', default='mts_cache', help='Raw HTML evidence directory')
    parser.add_argument('--delay', type=float, default=5.0, help='Minimum delay per network request (default: 5s, minimum: 2s)')
    parser.add_argument('--limit', type=int, default=0, help='Select the newest N episodes (0: all)')
    parser.add_argument('--include', default='', help='Comma-separated episode numbers')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--resume', action='store_true', help='Skip completed results; retry fetch/parse/layout failures')
    modes.add_argument('--retry-failed', action='store_true', help='Process only fetch/parse/layout/access failures in the existing catalog')
    parser.add_argument('--reparse', action='store_true', help='Reparse cached HTML only; never use the network')
    parser.add_argument('--refresh', action='store_true', help='Refresh selected cached pages over HTTP')
    args = parser.parse_args(argv)
    if not math.isfinite(args.delay) or args.delay < 2:
        parser.error('Use --delay >= 2 seconds')
    if args.limit < 0:
        parser.error('Use --limit >= 0')
    if args.refresh and args.reparse:
        parser.error('--refresh and --reparse cannot be combined')
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
    row['diagnostics'] = [dict(code=status, message=message)]
    if row['chapters']:
        row['diagnostics'].append(dict(code='previous_chapters_retained',
            message='Current attempt failed; existing chapter evidence was kept.'))
    return row


def run(args, client):
    existing = load_catalog(args.output)
    if args.retry_failed and not existing:
        raise FetchFailure('--retry-failed requires an existing catalog in --output')
    rows = {r['number']: upgrade_legacy(r) for r in existing}
    if existing and args.retry_failed:
        episodes = [{k: r[k] for k in ('number', 'title', 'url')} for r in existing]
    else:
        try:
            archive = client.get(ARCHIVE)
        except OfflineMiss:
            if not existing:
                raise
            episodes = [{k: r[k] for k in ('number', 'title', 'url')} for r in existing]
        else:
            if archive['status_code'] != 200:
                raise FetchFailure(f'Archive HTTP {archive["status_code"]}')
            episodes = episodes_from_archive(archive['html'])
    if not episodes:
        raise FetchFailure('No episode links found; inspect the cached archive HTML.')
    discovered = len(episodes)
    if args.selected:
        missing = args.selected - {e['number'] for e in episodes}
        if missing:
            raise FetchFailure(f'Episodes not found in archive/catalog: {", ".join(map(str, sorted(missing)))}')
        episodes = [e for e in episodes if e['number'] in args.selected]
    episodes.sort(key=lambda e: e['number'])
    if args.limit:
        episodes = episodes[-args.limit:]
    if args.retry_failed:
        episodes = [e for e in episodes if e['number'] in rows and rows[e['number']]['status'] in FAILED_STATUSES]
    elif args.resume:
        episodes = [e for e in episodes if e['number'] not in rows or rows[e['number']]['status'] in FAILED_STATUSES]
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
                else:
                    try:
                        extraction = extract_episode(page['html'])
                    except Exception as exc:
                        row = failure_row(episode, previous, 'parse_error', f'{type(exc).__name__}: {exc}')
                    else:
                        row = dict(episode, **extraction, schema_version=2)
                        if previous and len(row['chapters']) < len(previous['chapters']):
                            row['requires_review'] = True
                            row['diagnostics'].append(dict(code='chapter_count_decreased',
                                before=len(previous['chapters']), after=len(row['chapters']),
                                message='Compare cached source with prior catalog before accepting this loss.'))
                row['source'] = {k: page[k] for k in ('url', 'final_url', 'status_code', 'fetched_at', 'cache_key', 'request_source')}
                row['source']['kind'] = 'raw_html'
            except OfflineMiss as exc:
                if previous:
                    row = dict(previous)
                    row['diagnostics'] = [d for d in row.get('diagnostics', []) if d['code'] != 'cache_missing']
                    row['diagnostics'].append(dict(code='cache_missing', severity='info', message=str(exc)))
                else:
                    row = failure_row(episode, None, 'fetch_error', str(exc))
            except FetchFailure as exc:
                row = failure_row(episode, previous, exc.status, str(exc))
            rows[number] = row
            save_outputs(args.output, list(rows.values()), discovered)
            codes = sorted({d['code'] for d in row.get('diagnostics', []) if d['code'] != 'frame_rate_unknown'})
            print(f'[{index}/{len(episodes)}] MTS {number}: {len(row["chapters"])} chapters '
                  f'({row["status"]}; {row.get("source", {}).get("request_source", "catalog")})'
                  + (f' [{", ".join(codes)}]' if codes else ''), flush=True)
    except KeyboardInterrupt:
        save_outputs(args.output, list(rows.values()), discovered, interrupted=True)
        print('\nInterrupted. Completed results and exports saved; use --resume to continue.', flush=True)
        return 130
    summary = save_outputs(args.output, list(rows.values()), discovered)
    print(json.dumps(dict(summary, network_requests=client.network_requests), indent=2), flush=True)
    return 0


def main(argv=None):
    args = parse_args(argv)
    client = TextClient(HtmlCache(args.cache), delay=args.delay, offline=args.reparse, refresh=args.refresh)
    try:
        return run(args, client)
    except KeyboardInterrupt:
        print('\nInterrupted before episode processing; existing catalog preserved.', flush=True)
        return 130
    except (FetchFailure, ValueError, OSError) as exc:
        print(f'Stopped: {exc}', flush=True)
        return 1
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
