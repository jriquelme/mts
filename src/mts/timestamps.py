"""Conservative timecode normalization; frame rates are deliberately unknown."""

import re


def normalize_timestamp(original):
    raw = '' if original is None else str(original)
    value = re.sub(r'\s*:\s*', ':', raw.strip())
    result = dict(time_original=raw, time_seconds=None, time_format='missing', time_valid=False)
    if not value:
        return result
    result['time_format'] = 'invalid'
    # Verified in MTS 213: four-field codes use semicolons consistently.
    # Preserve that separator, including any possible drop-frame significance.
    if re.fullmatch(r'\d+(?:\s*;\s*\d{2}){3}', raw.strip()):
        value = re.sub(r'\s*;\s*', ':', raw.strip())
        result['time_separator'] = ';'
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
    mixed_frames = any(normalize_timestamp(c.get('time_original', c.get('time', '')))['time_format']
                       == 'hh:mm:ss:frames' for c in chapters)
    for index, chapter in enumerate(chapters, 1):
        row = dict(chapter)
        for field in ('time_frames', 'time_frame_rate', 'time_precision', 'time_separator'):
            row.pop(field, None)
        row.update(normalize_timestamp(row.get('time_original', row.get('time', ''))))
        # MTS 212 mixes HH:MM:SS:FF with values such as 58:44:04 before
        # 01:00:39:17. The three fields may be MM:SS:FF, not 58 hours.
        # Keep both readings unresolved rather than choosing an undocumented clock.
        if mixed_frames and row['time_format'] == 'hh:mm:ss' and row['time_seconds'] >= 7200:
            row.update(time_seconds=None, time_format='ambiguous', time_valid=False)
        row['order'] = index
        enriched.append(row)
        def warn(code, **details):
            diagnostics.append(dict(code=code, chapter=index, **details))
        if row['time_format'] == 'missing':
            warn('timestamp_missing')
        elif row['time_format'] == 'ambiguous':
            warn('timestamp_format_ambiguous', value=row['time_original'],
                 message='Mixed frame timecodes: HH:MM:SS versus MM:SS:frames is unresolved.')
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
                if row.get('time_separator') == ';':
                    warn('timestamp_semicolon_timecode', severity='info', value=row['time_original'],
                         message='Four source fields retained; no drop-frame rate or fractional conversion assumed.')
        if re.search(r'\b\d{1,3}\s*:\s*\d{2}(?![\d/])', row.get('title', '')):
            warn('title_contains_timestamp', value=row['title'])
    return enriched, diagnostics
