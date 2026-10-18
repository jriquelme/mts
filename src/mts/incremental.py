"""Incremental selection, recoverable run journals, and immutable catalog history."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import uuid

from mts.http import ARCHIVE, FetchFailure, OfflineMiss
from mts.storage import atomic_file, load_catalog, utcnow, write_json
from mts.validation import compare, render_html


FAILED_STATUSES = {'fetch_error', 'parse_error', 'unsupported_layout', 'access_restricted'}


@contextmanager
def catalog_lock(directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    with (path / '.mts.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise FetchFailure(f'Another scraper is using {directory}') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def snapshot_catalog(directory):
    directory = Path(directory)
    path = directory / 'mts_toc.json'
    text = path.read_text() if path.exists() else '[]\n'
    digest = hashlib.sha256(text.encode()).hexdigest()
    target = directory / 'history' / digest / 'mts_toc.json'
    if not target.exists():
        with atomic_file(target) as stream:
            stream.write(text)
    return digest


def archive_stale(client, hours):
    try:
        page = client.cache.read(ARCHIVE)
        if not page or page['status_code'] != 200:
            return True
        fetched = datetime.fromisoformat(page['fetched_at'])
        return (datetime.now(timezone.utc) - fetched).total_seconds() >= hours * 3600
    except (KeyError, ValueError, TypeError):
        return True


def discover(args, client, existing, parse_archive):
    known = [{k: row[k] for k in ('number', 'title', 'url')} for row in existing]
    if existing and not args.discover and (args.retry_failed or args.revalidate or args.revalidate_legacy or args.selected):
        # Explicit existing selections do not need a fresh archive request.
        if not args.selected or args.selected <= {r['number'] for r in known}:
            return known
    refresh = not args.reparse and (args.discover or args.refresh or archive_stale(client, args.discovery_ttl))
    try:
        archive = client.get(ARCHIVE, refresh=refresh)
    except OfflineMiss:
        if not existing:
            raise
        return known
    if archive['status_code'] != 200:
        raise FetchFailure(f'Archive HTTP {archive["status_code"]}')
    discovered = parse_archive(archive['html'])
    if not discovered:
        raise FetchFailure('No episode links found; inspect cached archive HTML.')
    union = {r['number']: r for r in known}
    union.update({r['number']: r for r in discovered})
    return [union[n] for n in sorted(union)]


def plan_run(args, client, existing, parse_archive):
    path = Path(args.output) / 'mts_run.json'
    previous_run = json.loads(path.read_text()) if path.exists() else None
    if args.resume and previous_run:
        required = {'state', 'baseline_hash', 'run_id', 'offline', 'refresh', 'pending', 'episodes', 'discovered'}
        if not isinstance(previous_run, dict) or not required <= previous_run.keys():
            raise FetchFailure('Invalid saved run journal; the catalog is preserved.')
    if args.resume and previous_run and previous_run['state'] in {'running', 'interrupted', 'finalizing'}:
        if args.selected or args.limit:
            raise FetchFailure('Resume the saved selection with --resume alone, or start an explicit new run.')
        if not re.fullmatch(r'[0-9a-f]{64}', previous_run['baseline_hash']) or not re.fullmatch(r'[0-9a-f]{32}', previous_run['run_id']):
            raise FetchFailure('Invalid saved run journal')
        args.reparse = previous_run['offline']
        args.refresh = previous_run['refresh']
        pending = set(previous_run['pending'])
        return previous_run, [e for e in previous_run['episodes'] if e['number'] in pending]
    if args.retry_failed and not existing:
        raise FetchFailure('--retry-failed requires an existing catalog in --output')
    episodes = discover(args, client, existing, parse_archive)
    by_number = {r['number']: r for r in existing}
    discovered_count = len(episodes)
    if args.selected:
        missing = args.selected - {e['number'] for e in episodes}
        if missing:
            raise FetchFailure(f'Episodes not found in archive/catalog: {", ".join(map(str, sorted(missing)))}')
        episodes = [e for e in episodes if e['number'] in args.selected]
    episodes.sort(key=lambda e: e['number'])
    if args.limit:
        episodes = episodes[-args.limit:]
    if args.retry_failed:
        mode = 'retry_failed'
        episodes = [e for e in episodes if e['number'] in by_number and by_number[e['number']]['status'] in FAILED_STATUSES]
    elif args.revalidate_legacy:
        mode = 'revalidate_legacy'
        episodes = [e for e in episodes if e['number'] in by_number and (
            by_number[e['number']].get('source', {}).get('kind') == 'legacy_metadata' or any(
                c.get('source', by_number[e['number']].get('source', {})).get('kind') == 'legacy_metadata'
                for c in by_number[e['number']]['chapters']))]
    elif args.reparse or args.revalidate or args.selected or args.refresh:
        mode = 'revalidate'
    else:
        mode = 'new_only'
        episodes = [e for e in episodes if e['number'] not in by_number]
    journal = dict(schema_version=1, run_id=uuid.uuid4().hex, state='running', started_at=utcnow(),
        baseline_hash=snapshot_catalog(args.output), mode=mode, episodes=episodes,
        pending=[e['number'] for e in episodes], completed=[], discovered=discovered_count,
        offline=args.reparse, refresh=args.refresh)
    persist_run(args.output, journal)
    return journal, episodes


def persist_run(directory, journal):
    journal['updated_at'] = utcnow()
    write_json(Path(directory) / 'mts_run.json', journal)
    write_json(Path(directory) / 'history' / 'runs' / f'{journal["run_id"]}.json', journal)


def write_changes(directory, journal, rows):
    directory = Path(directory)
    baseline = load_catalog(directory / 'history' / journal['baseline_hash'])
    report = compare(baseline, rows)
    report['run_id'] = journal['run_id']
    report['baseline_hash'] = journal['baseline_hash']
    report['run_state'] = journal['state']
    history = directory / 'changes' / journal['run_id']
    write_json(history / 'comparison.json', report)
    with atomic_file(history / 'comparison.html') as stream:
        stream.write(render_html(report, investigation_url=None))
    write_json(directory / 'mts_changes.json', report)
    with atomic_file(directory / 'mts_changes.html') as stream:
        stream.write(render_html(report, json_name='mts_changes.json', investigation_url=None))
    return report
