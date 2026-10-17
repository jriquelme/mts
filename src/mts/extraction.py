"""Extract only the episode description, retaining source order and evidence."""

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from mts.timestamps import enrich_chapters


SCOPES = ('#main-video .about', '.entry-content', '.post-content', 'article')
HEADING = re.compile(r'^(?:MTS\s*\d+\s*[-–—:]?\s*)?table\s+of\s+contents\s*[:.!]?$', re.I)
TOKEN = r'\d{1,3}(?:\s*:\s*(?:\d{1,3}|[a-zA-Z]{1,2})){1,3}'
LEADING = re.compile(rf'^\s*\(?(?P<time>{TOKEN})(?=$|[\s)\]–—-])\)?\s*[-–—:]?\s*(?P<title>.*)$', re.S)
TRAILING = re.compile(rf'^(?P<title>.*?)\s*\((?P<time>{TOKEN})\)\s*$', re.S)
BLOCKS = ('p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'tr')
NOISE = ('.comments-link, .commentlist, .comment, #comments, #respond, .related, '
         '.related-posts, .video, .login-video, nav, form, script, style, iframe, video, '
         '[hidden], [aria-hidden="true"]')


def clean(text):
    return re.sub(r'\s+', ' ', text).strip()


def block_lines(block):
    """BR separates chapters except when it splits a timestamp."""
    parts = []
    for child in block.descendants:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag) and child.name == 'br':
            parts.append('\u2028')
    text = ''.join(parts)
    text = re.sub(r'(?<=:)\s*\u2028\s*(?=\d{2}:)', ' ', text)
    lines = []
    for line in (part.strip() for part in text.split('\u2028') if part.strip()):
        # MTS 221 wraps "Blue Belt<br>Championship" inside one timed P.
        if lines and LEADING.match(lines[-1]) and not LEADING.match(line):
            lines[-1] += '\n' + line
        else:
            lines.append(line)
    return lines


def source_lines(scope):
    # Walking leaf blocks once avoids extracting a LI again through its child P.
    blocks = [b for b in scope.find_all(BLOCKS) if not b.find(BLOCKS)]
    if not blocks:
        blocks = [scope]
    for block in blocks:
        for raw in block_lines(block):
            yield raw, block.name == 'li' or block.find_parent('li') is not None


def parse_chapter(raw):
    match = LEADING.match(raw) or TRAILING.match(raw)
    if match:
        original = match['time'].strip()
        return dict(time=re.sub(r'\s*:\s*', ':', original), time_original=original,
                    title=clean(match['title']), text_original=raw)
    return dict(time='', time_original='', title=clean(raw), text_original=raw)


def finish(chapters, diagnostics, layout):
    chapters, warnings = enrich_chapters(chapters)
    diagnostics.extend(warnings)
    for chapter in chapters:
        if not chapter['title']:
            diagnostics.append(dict(code='chapter_title_missing', chapter=chapter['order']))
    missing = sum(c['time_format'] == 'missing' for c in chapters)
    invalid = any(not c['time_valid'] for c in chapters)
    empty_title = any(not c['title'] for c in chapters)
    if not chapters:
        status = 'toc_not_present'
    elif missing == len(chapters):
        status = 'toc_untimed'
    elif invalid or empty_title:
        status = 'toc_partial'
    else:
        status = 'ok'
    needs_review = any(d['code'] != 'frame_rate_unknown' for d in diagnostics)
    return dict(chapters=chapters, status=status, layout=layout, diagnostics=diagnostics,
                requires_review=status != 'ok' or needs_review)


def extract_episode(html):
    soup = BeautifulSoup(html, 'html.parser')
    selector = next((s for s in SCOPES if soup.select_one(s) is not None), None)
    if selector is None:
        restricted = soup.select_one('input[type="password"]') is not None
        status = 'access_restricted' if restricted else 'unsupported_layout'
        return dict(chapters=[], status=status, layout=None, requires_review=True,
                    diagnostics=[dict(code=status, message='No recognized public episode description. Inspect cached HTML.')])
    scope = soup.select_one(selector)
    for unwanted in list(scope.select(NOISE)):
        if unwanted.parent is not None:
            unwanted.decompose()
    lines = list(source_lines(scope))
    heading = next((i for i, (text, _) in enumerate(lines) if HEADING.fullmatch(clean(text))), None)
    chapters = []
    started = heading is not None
    for index, (raw, is_list) in enumerate(lines):
        text = clean(raw)
        if heading is not None and index <= heading:
            continue
        if HEADING.fullmatch(text):
            continue
        if re.match(r'^(?:MTS\s*\d+\b|(?:Mastering the System:\s*)?Episode\s+\d+\b)', text, re.I):
            continue
        if re.match(r'^(?:comments?\s+(?:off|closed)|leave a (?:reply|comment)|related posts?|play video|log\s*in|sign up)\b', text, re.I):
            break
        chapter = parse_chapter(raw)
        if chapter['time_original'] or is_list or started:
            chapters.append(chapter)
            started = True
    diagnostics = []
    if not chapters:
        diagnostics.append(dict(code='toc_not_present', message='Recognized episode description has no chapter list. Inspect cached description; do not infer video access.'))
    layout = 'headed_blocks' if heading is not None else 'headingless_blocks'
    result = finish(chapters, diagnostics, layout)
    result['source_selector'] = selector
    return result


def extract_chapters(html):
    """Compatibility wrapper for callers of the original two-value API."""
    result = extract_episode(html)
    return result['chapters'], result['status']
