"""Stable flat records for downstream enrichment, without semantic labels."""

from copy import deepcopy

from mts.provenance import public_source


def flat_chapters(rows):
    for episode in rows:
        for index, chapter in enumerate(episode['chapters'], 1):
            source = deepcopy(chapter.get('source', episode.get('source', {})))
            valid = chapter.get('time_valid', False)
            kind = chapter.get('time_format', 'missing')
            if not valid:
                confidence = kind if kind in {'missing', 'ambiguous'} else 'invalid'
            elif not public_source(source):
                confidence = 'unverified_legacy'
            elif kind == 'hh:mm:ss:frames':
                confidence = 'nominal_second_unknown_frame_rate'
            else:
                confidence = 'whole_second'
            diagnostics = [deepcopy(d) for d in episode.get('diagnostics', []) if (
                d['chapter_id'] == chapter['chapter_id'] if d.get('chapter_id') else d.get('chapter', index) == index)]
            yield dict(schema_version=1, chapter_id=chapter['chapter_id'],
                episode_number=episode['number'], episode_title=episode['title'],
                source_url=episode['url'], order=chapter.get('order', index),
                original_order=chapter['original_order'], source_order=chapter.get('source_order', chapter.get('order', index)),
                title_original=chapter['title_original'], title_normalized=chapter['title_normalized'],
                title_source=chapter.get('title_source', chapter['title']),
                timestamp_raw=chapter.get('time_original', chapter.get('time', '')),
                time_seconds=chapter.get('time_seconds') if valid else None,
                time_format=kind, time_valid=valid, timestamp_confidence=confidence,
                time_frames=chapter.get('time_frames'), time_frame_rate=chapter.get('time_frame_rate'),
                source=source, episode_status=episode['status'],
                validation=deepcopy(episode.get('validation', {})), diagnostics=diagnostics)
