"""Atomic cache and catalog writes; the JSON catalog is the recovery source."""

import csv
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from mts.identity import ensure_catalog_identity
from mts.exports import flat_chapters


def utcnow():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def atomic_file(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    with atomic_file(path) as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


class HtmlCache:
    def __init__(self, directory):
        self.directory = Path(directory)

    @staticmethod
    def key(url):
        return hashlib.sha256(url.encode()).hexdigest()

    def read(self, url):
        key = self.key(url)
        try:
            meta = json.loads((self.directory / f'{key}.json').read_text())
            html = (self.directory / f'{key}.html').read_text()
            if meta['url'] != url or not isinstance(meta['status_code'], int):
                raise ValueError('Invalid cache metadata')
            digest = hashlib.sha256(html.encode()).hexdigest()
            if meta.get('sha256', digest) != digest:
                raise ValueError('Cache checksum mismatch')
            return dict(meta, sha256=digest, html=html, cache_key=key, request_source='cache')
        except FileNotFoundError:
            return None

    def write(self, url, html, status_code, final_url=None, redirect_target=None):
        key = self.key(url)
        meta = dict(url=url, final_url=final_url or url, status_code=status_code,
                    fetched_at=utcnow(), sha256=hashlib.sha256(html.encode()).hexdigest())
        if redirect_target:
            meta['redirect_target'] = redirect_target
        try:
            previous = self.read(url)
        except (ValueError, KeyError):
            previous = None
        if previous:
            self.pin(previous)
        self.pin(dict(meta, html=html))
        with atomic_file(self.directory / f'{key}.html') as stream:
            stream.write(html)
        write_json(self.directory / f'{key}.json', meta)
        return dict(meta, html=html, cache_key=key, request_source='live')

    def pin(self, page):
        """Keep immutable content by hash, even when the current URL is refreshed."""
        digest = hashlib.sha256(page['html'].encode()).hexdigest()
        if page.get('sha256', digest) != digest:
            raise ValueError('Cannot pin evidence with an incorrect checksum')
        path = self.directory / 'objects' / f'{digest}.html'
        if not path.exists():
            with atomic_file(path) as stream:
                stream.write(page['html'])
        metadata = {k: v for k, v in page.items() if k not in {'html', 'request_source'}}
        metadata['sha256'] = digest
        version = self.directory / 'versions' / self.key(page['url']) / f'{digest}-{page["status_code"]}.json'
        if not version.exists():
            write_json(version, metadata)

    def read_source(self, source):
        digest = source.get('sha256', '')
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            return None
        path = self.directory / 'objects' / f'{digest}.html'
        if not path.exists():
            return None
        html = path.read_text()
        if hashlib.sha256(html.encode()).hexdigest() != digest:
            raise ValueError('Archived source checksum mismatch')
        return html


def load_catalog(directory):
    path = Path(directory) / 'mts_toc.json'
    if not path.exists():
        return []
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise ValueError(f'{path} must contain a list of episodes')
    seen = set()
    for row in rows:
        if not isinstance(row.get('number'), int) or row['number'] in seen:
            raise ValueError(f'{path} contains invalid or duplicate episode numbers')
        seen.add(row['number'])
        if not isinstance(row.get('chapters'), list) or not isinstance(row.get('url'), str):
            raise ValueError(f'{path} contains an invalid episode')
    return rows


def needs_review(row):
    return row.get('requires_review', row['status'] != 'ok')


def save_outputs(directory, rows, discovered=None, interrupted=False):
    directory = Path(directory)
    rows = sorted(rows, key=lambda r: r['number'])
    ensure_catalog_identity(rows)
    write_json(directory / 'mts_toc.json', rows)
    chapter_fields = ['episode', 'episode_title', 'url', 'timestamp', 'chapter_title',
                      'order', 'time_original', 'time_seconds', 'time_format', 'time_valid',
                      'time_frames', 'time_frame_rate', 'time_precision', 'text_original', 'time_separator',
                      'chapter_id', 'original_order', 'title_original', 'title_normalized', 'title_source',
                      'timestamp_confidence', 'source', 'diagnostics']
    with atomic_file(directory / 'mts_chapters.csv') as stream:
        writer = csv.DictWriter(stream, fieldnames=chapter_fields)
        writer.writeheader()
        flattened = iter(flat_chapters(rows))
        for row in rows:
            for index, chapter in enumerate(row['chapters'], 1):
                flat = next(flattened)
                item = {key: chapter.get(key, '') for key in chapter_fields[5:]}
                item.update(episode=row['number'], episode_title=row['title'], url=row['url'],
                            timestamp=chapter.get('time', ''), chapter_title=chapter['title'])
                item['order'] = chapter.get('order', index)
                item['timestamp_confidence'] = flat['timestamp_confidence']
                item['source'] = json.dumps(flat['source'], ensure_ascii=False)
                item['diagnostics'] = json.dumps(flat['diagnostics'], ensure_ascii=False)
                writer.writerow(item)
    with atomic_file(directory / 'mts_chapters.jsonl') as stream:
        for record in flat_chapters(rows):
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    with atomic_file(directory / 'mts_review.csv') as stream:
        fields = ['episode', 'title', 'url', 'status', 'error', 'reasons', 'diagnostics']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            if needs_review(row):
                diagnostics = row.get('diagnostics', [])
                writer.writerow(dict(episode=row['number'], title=row['title'], url=row['url'],
                    status=row['status'], error=row.get('error', ''),
                    reasons=';'.join(sorted({d['code'] for d in diagnostics})),
                    diagnostics=json.dumps(diagnostics, ensure_ascii=False)))
    summary = dict(schema_version=3, scraped_at=utcnow(), episodes=len(rows),
                   episodes_discovered=discovered if discovered is not None else len(rows),
                   chapters=sum(len(r['chapters']) for r in rows),
                   with_toc=sum(r['status'] == 'ok' for r in rows),
                   with_chapters=sum(bool(r['chapters']) for r in rows),
                   without_chapters=sum(not r['chapters'] for r in rows),
                   fully_valid_timestamps=sum(bool(r['chapters']) and all(c.get('time_valid', False) for c in r['chapters']) for r in rows),
                   require_review=sum(needs_review(r) for r in rows),
                   statuses=dict(Counter(r['status'] for r in rows)),
                   diagnostic_counts=dict(Counter(d['code'] for r in rows for d in r.get('diagnostics', []))),
                   interrupted=interrupted)
    # Summary is written last. An interrupted export can be regenerated from JSON.
    write_json(directory / 'mts_summary.json', summary)
    return summary
