"""Compare source entries individually; never replace stronger evidence with less."""

from collections import defaultdict
from copy import deepcopy

from mts.extraction import clean, finish


def title_key(chapter):
    return clean(chapter.get('title', '')).casefold()


def time_key(chapter):
    if not chapter.get('time_valid'):
        return None
    return chapter.get('time_seconds'), chapter.get('time_frames')


def align_chapters(previous, current):
    """Match exact occurrences, then unique titles/times, without positional guesses."""
    mapping = {}
    used = set()
    for pass_index, key in enumerate((lambda c: (title_key(c), c.get('time', '')), title_key, time_key)):
        old_groups, new_groups = defaultdict(list), defaultdict(list)
        for i, chapter in enumerate(previous):
            if i not in used:
                value = key(chapter)
                if value is not None and value != '':
                    old_groups[value].append(i)
        for j, chapter in enumerate(current):
            if j not in mapping:
                value = key(chapter)
                if value is not None and value != '':
                    new_groups[value].append(j)
        for value in old_groups.keys() & new_groups.keys():
            old_indices, new_indices = old_groups[value], new_groups[value]
            if len(old_indices) == len(new_indices) == 1 or (
                    pass_index == 0 and len(old_indices) == len(new_indices)):
                for i, j in zip(old_indices, new_indices):
                    mapping[j] = i
                    used.add(i)
    return mapping


def reconcile_episode(previous, candidate):
    if not previous or not previous['chapters']:
        result = deepcopy(candidate)
        for chapter in result['chapters']:
            chapter['source'] = deepcopy(candidate.get('source', {}))
        result['validation'] = dict(state='revalidated', source=deepcopy(candidate.get('source', {})))
        return result
    old, new = previous['chapters'], candidate['chapters']
    mapping = align_chapters(old, new)
    reverse = {i: j for j, i in mapping.items()}
    missing = sorted(set(range(len(old))) - set(reverse))
    additions = sorted(set(range(len(new))) - set(mapping))
    reordered = [mapping[j] for j in sorted(mapping)] != sorted(mapping.values())
    issues, changes = [], []
    for i in missing:
        issues.append(dict(code='chapter_missing_in_source', chapter=i + 1,
                           message='Previous entry retained; no unambiguous source match.'))
    if len(new) < len(old):
        issues.append(dict(code='chapter_count_decreased', before=len(old), after=len(new),
                           message='Prior entries retained; inspect proposed source extraction.'))
    if reordered:
        issues.append(dict(code='chapter_order_changed', message='Prior chapter order retained; source order differs.'))
    if missing and additions:
        issues.append(dict(code='chapter_match_ambiguous', message='Unmatched source rows kept as candidates, not duplicate active entries.'))
    canonical = []
    degraded = False
    for i, old_chapter in enumerate(old):
        kept = deepcopy(old_chapter)
        kept.setdefault('source', deepcopy(previous.get('source', {})))
        j = reverse.get(i)
        if j is not None:
            fresh = new[j]
            lower_quality = (old_chapter.get('time_valid', False) and not fresh.get('time_valid', False)) or (
                bool(old_chapter.get('title')) and not fresh.get('title'))
            if lower_quality:
                degraded = True
                issues.append(dict(code='chapter_quality_regressed', chapter=i + 1,
                                   message='Previous title/time retained; current source is incomplete or ambiguous.'))
            else:
                kept.update(deepcopy(fresh))
                kept['source'] = deepcopy(candidate.get('source', {}))
                kept['source_order'] = j + 1
                for field in ('title', 'time'):
                    if old_chapter.get(field, '') != fresh.get(field, ''):
                        code = 'chapter_title_changed' if field == 'title' else 'chapter_timestamp_changed'
                        issues.append(dict(code=code, chapter=i + 1, before=old_chapter.get(field, ''), after=fresh.get(field, '')))
                        changes.append(dict(chapter=i + 1, field=field, before=old_chapter.get(field, ''),
                                            after=fresh.get(field, ''), source=deepcopy(candidate.get('source', {}))))
        canonical.append(kept)
    # Safe insertions require all old entries to be matched and source order to
    # agree. Otherwise the full proposal remains available for manual resolution.
    if additions and not missing and not reordered and not degraded:
        merged = []
        for j, fresh in enumerate(new):
            if j in mapping:
                merged.append(canonical[mapping[j]])
            else:
                added = deepcopy(fresh)
                added.update(source=deepcopy(candidate.get('source', {})), source_order=j + 1)
                merged.append(added)
        canonical = merged
    result = deepcopy(candidate)
    result.update(finish(canonical, issues, candidate.get('layout')))
    retained = bool(missing or reordered or degraded)
    result['validation'] = dict(state='preserved' if retained else 'revalidated',
        source=deepcopy(candidate.get('source', {})), matched_chapters=len(mapping),
        unmatched_previous=[i + 1 for i in missing], unmatched_source=[j + 1 for j in additions],
        source_order_changed=reordered)
    if retained:
        result['source'] = deepcopy(previous.get('source', {}))
        result['candidate_extraction'] = {k: deepcopy(candidate[k]) for k in ('chapters', 'status', 'diagnostics', 'source') if k in candidate}
    if changes:
        result['chapter_changes'] = changes
    return result
