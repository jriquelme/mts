"""Persistent episode-local chapter identities, independent of mutable labels."""

import re
import unicodedata


ID_RE = re.compile(r'^mts-(\d+)-c(\d+)$')


def normalized_title(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', value)).strip()


def ensure_catalog_identity(rows):
    used = set()
    for episode in rows:
        for chapter in episode['chapters']:
            identifier = chapter.get('chapter_id')
            if identifier:
                match = ID_RE.fullmatch(identifier)
                if not match or int(match[1]) != episode['number'] or identifier in used:
                    raise ValueError(f'Invalid or duplicate chapter ID: {identifier}')
                if int(match[2]) < 1 or identifier != f'mts-{episode["number"]:04d}-c{int(match[2]):06d}':
                    raise ValueError(f'Noncanonical chapter ID: {identifier}')
                used.add(identifier)
    for episode in rows:
        assigned = [int(ID_RE.fullmatch(c['chapter_id'])[2]) for c in episode['chapters'] if c.get('chapter_id')]
        retired = episode.get('retired_chapter_ids', [])
        for identifier in retired:
            match = ID_RE.fullmatch(identifier)
            if not match or int(match[1]) != episode['number']:
                raise ValueError(f'Invalid retired chapter ID: {identifier}')
            if identifier in used:
                raise ValueError(f'Retired chapter ID collides with an assigned ID: {identifier}')
            assigned.append(int(match[2]))
            used.add(identifier)
        sequence = max([episode.get('next_chapter_sequence', 1), *[n + 1 for n in assigned]])
        for index, chapter in enumerate(episode['chapters'], 1):
            if not chapter.get('chapter_id'):
                identifier = f'mts-{episode["number"]:04d}-c{sequence:06d}'
                while identifier in used:
                    sequence += 1
                    identifier = f'mts-{episode["number"]:04d}-c{sequence:06d}'
                chapter['chapter_id'] = identifier
                used.add(identifier)
                sequence += 1
            chapter.setdefault('original_order', chapter.get('order', index))
            chapter.setdefault('title_original', chapter.get('title_source', chapter['title']))
            chapter['title_normalized'] = normalized_title(chapter['title'])
            chapter.setdefault('source', dict(episode.get('source', {})))
        episode.update(next_chapter_sequence=sequence, chapter_id_strategy='episode_sequence_v1', schema_version=3)
    return rows
