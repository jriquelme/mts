#!/usr/bin/env python3
"""Collect 10th Planet MTS *textual* episode/chapter metadata (never videos).

Usage:
  uv run mts --limit 3
  uv run mts

Outputs: mts_toc.json, mts_chapters.csv, mts_review.csv, mts_summary.json
Respect the site's robots.txt and terms. Run only with authorization.
"""
import argparse
import csv
import json
import math
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = 'https://www.10thplanetjj.com'
ARCHIVE = BASE + '/techniques-archive/'
USER_AGENT = 'PersonalMTSChapterIndexer/1.0 (personal research; text metadata only)'
EPISODE_RE = re.compile(r'\bMTS\s*(\d{1,3})\b', re.I)
STAMP = r'\d{1,2}(?::\d{2}){1,3}'
TIME_RE = re.compile(rf'^({STAMP})\s*(?:[-–—:]\s*)?(.+?)\s*$')
TRAILING_TIME_RE = re.compile(rf'^(.+?)\s*\(({STAMP})\)\s*$')


def clean(s):
    return re.sub(r'\s+', ' ', s).strip()


def get(session, url, pause, retries=4):
    # Delay before every request, including first; use a little random jitter.
    for attempt in range(retries):
        time.sleep(pause + random.uniform(0, min(1, pause / 3)))
        try:
            response = session.get(url, timeout=(10, 30), allow_redirects=True)
            if response.status_code in (429, 500, 502, 503, 504):
                if attempt == retries - 1:
                    response.raise_for_status()
                wait = min(120, 8 * 2 ** attempt)
                print(f'HTTP {response.status_code}: backing off {wait}s: {url}', flush=True)
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(min(120, 8 * 2 ** attempt))
    raise RuntimeError(f'Retries exhausted for {url}')


def episodes_from_archive(html):
    soup = BeautifulSoup(html, 'html.parser')
    episodes = {}
    for h in soup.find_all(['h2', 'h3', 'h4']):
        title = clean(h.get_text(' ', strip=True))
        match = EPISODE_RE.search(title)
        if not match:
            continue
        a = h.find('a', href=True)
        if not a:
            continue
        url = urldefrag(urljoin(BASE, a['href']))[0].split('?')[0]
        if urlparse(url).netloc not in {'www.10thplanetjj.com', '10thplanetjj.com'}:
            continue
        number = int(match.group(1))
        episodes.setdefault(number, {'number': number, 'title': title, 'url': url})
    return [episodes[n] for n in sorted(episodes)]


def extract_chapters(html):
    soup = BeautifulSoup(html, 'html.parser')
    # The site's #content contains comments and related episodes, not the TOC.
    scope = (soup.select_one('#main-video .about') or soup.select_one('.entry-content')
             or soup.select_one('.post-content') or soup.select_one('article'))
    if scope is None:
        return [], 'toc_heading_missing'
    for unwanted in scope.select('.comments-link, .commentlist, #comments, #respond, '
                                  '.related, .related-posts, script, style'):
        unwanted.decompose()
    # Preserve inline formatting within a chapter, while keeping block/BR boundaries.
    # Some pages even break a timestamp across a BR ("00:<br>03:04").
    for br in list(scope.find_all('br')):
        before = str(br.previous_sibling or '').rstrip()
        after = str(br.next_sibling or '').lstrip()
        br.replace_with(' ' if re.search(r'\d:\s*$', before) and re.match(r'\d{2}:', after) else '\n')
    for block in scope.find_all(['p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'tr']):
        block.insert_before('\n')
        block.insert_after('\n')
    text = re.sub(r'(?<=\d):\s+(?=\d{2}(?:\D|$))', ':', scope.get_text())
    lines = [clean(line) for line in text.splitlines() if clean(line)]
    start = next((i for i, x in enumerate(lines) if re.search(r'^table\s+of\s+contents\s*:?$', x, re.I)), None)
    if start is None:
        # Older episodes publish a bullet list without a TOC heading or timestamps.
        entries = scope.select('li')
        chapters = []
        for entry in entries:
            label = clean(entry.get_text(' ', strip=True))
            if not label:
                continue
            match = TIME_RE.match(label)
            trailing = TRAILING_TIME_RE.match(label)
            if match:
                stamp, label = match.groups()
            elif trailing:
                label, stamp = trailing.groups()
            else:
                stamp = ''
            chapters.append({'time': stamp, 'title': label})
        if chapters:
            return chapters, ('ok' if all(c['time'] for c in chapters) else 'toc_untimed')
        return [], 'toc_heading_missing'
    chapters, seen = [], set()
    for line in lines[start + 1:]:
        if re.match(r'^(comments?\s+off|leave a reply|related posts?|post a comment|play video|sign up|log in)\b', line, re.I):
            break
        if re.match(r'^MTS\s*\d+\b', line, re.I) and chapters:
            break
        m = TIME_RE.match(line)
        if m:
            stamp, label = m.groups()
            # Reject unrelated line formats and keep raw time (some episodes have frame fields).
            if len(stamp.split(':')) not in (2, 3, 4):
                continue
            key = (stamp, label)
            if key not in seen:
                chapters.append({'time': stamp, 'title': label})
                seen.add(key)
        elif chapters and len(line) > 300:
            break
    return chapters, ('ok' if chapters else 'toc_empty')


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--output', default='mts_data')
    p.add_argument('--delay', type=float, default=3.0, help='Minimum seconds between HTTP requests')
    p.add_argument('--limit', type=int, default=0, help='Only crawl N episodes (test mode)')
    p.add_argument('--include', default='', help='Optional comma-separated episode numbers, e.g. 34,180,259')
    p.add_argument('--ignore-robots', action='store_true', help='Only use if site owner explicitly permits crawling')
    args = p.parse_args(argv)
    if not math.isfinite(args.delay) or args.delay < 2:
        p.error('Use --delay >= 2 seconds')
    if args.limit < 0:
        p.error('Use --limit >= 0')
    try:
        selected = {int(x.strip()) for x in args.include.split(',')} if args.include else set()
        if any(n <= 0 for n in selected):
            raise ValueError
    except ValueError:
        p.error('--include must contain comma-separated positive episode numbers')
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml'})
    robots = RobotFileParser()
    robots.set_url(BASE + '/robots.txt')
    try:
        robots.parse(get(session, robots.url, args.delay).splitlines())
        robots_ok = True
    except Exception as exc:
        robots_ok = False
        print(f'Could not read robots.txt: {exc}')
        if not args.ignore_robots:
            raise SystemExit('Stop: robots.txt unavailable. Check manually, then use --ignore-robots only if permitted.')
    def allowed(url):
        return args.ignore_robots or (robots_ok and robots.can_fetch(USER_AGENT, url))
    if not allowed(ARCHIVE):
        raise SystemExit('robots.txt disallows crawling the archive.')
    archive_html = get(session, ARCHIVE, args.delay)
    episodes = episodes_from_archive(archive_html)
    if not episodes:
        raise SystemExit('No episode links found. Site markup may have changed; inspect the archive.')
    if selected:
        missing = selected - {ep['number'] for ep in episodes}
        if missing:
            raise SystemExit(f'Episodes not found in archive: {", ".join(map(str, sorted(missing)))}')
        episodes = [ep for ep in episodes if ep['number'] in selected]
    if args.limit:
        episodes = episodes[-args.limit:]
    print(f'Collecting text metadata from {len(episodes)} episode pages.')
    items = []
    for i, episode in enumerate(episodes, 1):
        row = dict(episode)
        try:
            if not allowed(row['url']):
                row.update(chapters=[], status='robots_disallowed')
            else:
                html = get(session, row['url'], args.delay)
                chapters, status = extract_chapters(html)
                row.update(chapters=chapters, status=status)
        except Exception as exc:
            row.update(chapters=[], status='fetch_error', error=str(exc)[:300])
        items.append(row)
        print(f"[{i}/{len(episodes)}] MTS {row['number']}: {len(row['chapters'])} chapters ({row['status']})", flush=True)
        # Save after each episode to preserve progress from interrupted runs.
        (out / 'mts_toc.json').write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding='utf-8')
    with (out / 'mts_chapters.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['episode', 'episode_title', 'url', 'timestamp', 'chapter_title'])
        writer.writeheader()
        for row in items:
            for chapter in row['chapters']:
                writer.writerow(dict(episode=row['number'], episode_title=row['title'], url=row['url'],
                                     timestamp=chapter['time'], chapter_title=chapter['title']))
    with (out / 'mts_review.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['episode', 'title', 'url', 'status', 'error'])
        writer.writeheader()
        for row in items:
            if row['status'] != 'ok':
                writer.writerow(dict(episode=row['number'], title=row['title'], url=row['url'],
                                     status=row['status'], error=row.get('error', '')))
    summary = dict(scraped_at=datetime.now(timezone.utc).isoformat(), episodes=len(items),
                   chapters=sum(len(x['chapters']) for x in items),
                   with_toc=sum(x['status'] == 'ok' for x in items),
                   require_review=sum(x['status'] != 'ok' for x in items))
    (out / 'mts_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
