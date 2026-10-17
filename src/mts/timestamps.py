"""Conservative timecode normalization; frame rates are deliberately unknown."""

import re


def normalize_timestamp(original):
    raw = '' if original is None else str(original)
    value = re.sub(r'\s*:\s*', ':', raw.strip())
    result = dict(time_original=raw, time_seconds=None, time_format='missing', time_valid=False)
    if not value:
        return result
    result['time_format'] = 'invalid'
    if not re.fullmatch(r'\d+(?::\d{2}){1,3}', value):
        return result
    parts = [int(x) for x in value.split(':')]
    if len(parts) == 2:
        minutes, seconds = parts
        position = minutes * 60 + seconds
        kind = 'mm:ss'
    else:
        hours, minutes, seconds = parts[:3]
        if minutes >= 60:
            return result
        position = hours * 3600 + minutes * 60 + seconds
        kind = 'hh:mm:ss' if len(parts) == 3 else 'hh:mm:ss:frames'
    if seconds >= 60:
        return result
    result.update(time_seconds=position, time_format=kind, time_valid=True)
    if len(parts) == 4:
        result.update(time_frames=parts[3], time_frame_rate=None, time_precision='second')
    return result


def enrich_chapters(chapters):
    """Add timestamp fields and diagnostics without changing chapter order."""
    enriched, diagnostics = [], []
    positions = {}
    previous = None
    for index, chapter in enumerate(chapters, 1):
        row = dict(chapter)
        row.update(normalize_timestamp(row.get('time_original', row.get('time', ''))))
        row['order'] = index
        enriched.append(row)
        def warn(code, **details):
            diagnostics.append(dict(code=code, chapter=index, **details))
        if row['time_format'] == 'missing':
            warn('timestamp_missing')
        elif not row['time_valid']:
            warn('timestamp_malformed', value=row['time_original'])
        else:
            position = row['time_seconds']
            # Frame-bearing codes with different frame fields are distinct positions.
            key = (position, row.get('time_frames'))
            if key in positions:
                warn('timestamp_duplicate', previous_chapter=positions[key])
            positions[key] = index
            if previous is not None:
                previous_position, previous_frames, previous_index = previous
                backwards = position < previous_position or (
                    position == previous_position and key[1] is not None and previous_frames is not None
                    and key[1] < previous_frames)
                if backwards:
                    warn('timestamp_non_monotonic', previous_chapter=previous_index)
            previous = (position, key[1], index)
            if row['time_format'] == 'hh:mm:ss:frames':
                warn('frame_rate_unknown', value=row['time_original'])
        if re.search(r'\d\s*:\s*\d', row.get('title', '')):
            warn('title_contains_timestamp', value=row['title'])
    return enriched, diagnostics
