"""Reproducible catalog comparison, with source coverage and chapter-level diffs."""

import argparse
from collections import Counter
from difflib import SequenceMatcher
from html import escape
import json
from pathlib import Path

from mts.storage import atomic_file, load_catalog, needs_review, utcnow, write_json
from mts.timestamps import normalize_timestamp
from mts.provenance import public_source


def metrics(rows):
    return dict(episodes_discovered=len(rows), episodes_with_chapters=sum(bool(r['chapters']) for r in rows),
        episodes_without_chapters=sum(not r['chapters'] for r in rows),
        total_chapters=sum(len(r['chapters']) for r in rows),
        fully_valid_timestamps=sum(bool(r['chapters']) and all(
            c['time_valid'] if 'time_valid' in c else normalize_timestamp(c.get('time', ''))['time_valid']
            for c in r['chapters']) for r in rows),
        episodes_requiring_review=sum(needs_review(r) for r in rows))


def projection(chapter):
    return chapter.get('time', ''), chapter['title']


def compare(before, after):
    original = {r['number']: r for r in before}
    current = {r['number']: r for r in after}
    recovered, changed, regressions, corrections = [], [], [], []
    added, removed = 0, 0
    for number, row in current.items():
        old = original.get(number, dict(chapters=[]))
        old_chapters, chapters = old['chapters'], row['chapters']
        if not old_chapters and chapters:
            recovered.append(dict(episode=number, chapters=len(chapters), status=row['status']))
        if len(chapters) < len(old_chapters):
            regressions.append(dict(episode=number, before=len(old_chapters), after=len(chapters),
                                   action='Inspect cached source and chapter-level changes.'))
        old_pairs = [projection(c) for c in old_chapters]
        new_pairs = [projection(c) for c in chapters]
        operations = []
        for kind, i, j, k, l in SequenceMatcher(a=old_pairs, b=new_pairs, autojunk=False).get_opcodes():
            if kind != 'equal':
                operations.append(dict(kind=kind, before=old_chapters[i:j], after=chapters[k:l]))
                if kind == 'replace' and j - i == l - k == 1:
                    old_chapter, new_chapter = old_chapters[i], chapters[k]
                    old_time, new_time = old_chapter.get('time', ''), new_chapter.get('time', '')
                    valid = new_chapter.get('time_valid', normalize_timestamp(new_time)['time_valid'])
                    if valid and old_time != new_time and old_chapter['title'] != new_chapter['title']:
                        corrections.append(dict(episode=number, before_title=old_chapter['title'],
                            title=new_chapter['title'], before=old_time, after=new_time,
                            original=new_chapter.get('time_original'),
                            confidence='aligned source replacement; inspect chapter diff'))
        # Multisets preserve counts of legitimate repeated source entries.
        added += sum((Counter(new_pairs) - Counter(old_pairs)).values())
        removed += sum((Counter(old_pairs) - Counter(new_pairs)).values())
        if operations:
            changed.append(dict(episode=number, before=len(old_chapters), after=len(chapters), operations=operations))
        times_by_title = {}
        for chapter in old_chapters:
            times_by_title.setdefault(chapter['title'], []).append(chapter.get('time', ''))
        for chapter in chapters:
            values = times_by_title.get(chapter['title'], [])
            if values:
                old_time = values.pop(0)
                valid = chapter.get('time_valid', normalize_timestamp(chapter.get('time', ''))['time_valid'])
                if valid and old_time != chapter.get('time', ''):
                    corrections.append(dict(episode=number, title=chapter['title'], before=old_time,
                                            after=chapter.get('time', ''), original=chapter.get('time_original')))
    missing_episodes = sorted(set(original) - set(current))
    original_ids = {c['chapter_id']: c for r in before for c in r['chapters'] if c.get('chapter_id')}
    current_ids = {c['chapter_id']: c for r in after for c in r['chapters'] if c.get('chapter_id')}
    missing_ids = sorted(set(original_ids) - set(current_ids))
    original_field_changes = [dict(chapter_id=key, field=field,
        before=original_ids[key].get(field), after=current_ids[key].get(field))
        for key in sorted(original_ids.keys() & current_ids.keys())
        for field in ('title_original', 'original_order')
        if original_ids[key].get(field) != current_ids[key].get(field)]
    remaining = [dict(episode=r['number'], url=r['url'], status=r['status'], diagnostics=r.get('diagnostics', []))
                 for r in after if not r['chapters']]
    def fully_sourced(row):
        return all(public_source(c.get('source', row.get('source', {}))) for c in row['chapters']) if row['chapters'] else public_source(row.get('source', {}))
    raw = sorted(r['number'] for r in after if fully_sourced(r))
    retained = sorted(r['number'] for r in after if not fully_sourced(r))
    proposals = []
    for row in after:
        proposal = row.get('candidate_extraction')
        if proposal:
            proposals.append(dict(episode=row['number'], retained_chapters=len(row['chapters']),
                proposed_chapters=len(proposal['chapters']), status=proposal['status'],
                source=proposal.get('source'), chapters=proposal['chapters'],
                review_reasons=[d for d in row.get('diagnostics', []) if d['code'].startswith(('chapter_', 'new_chapter_'))]))
    return dict(generated_at=utcnow(), before=metrics(before), after=metrics(after),
        source_coverage=dict(reparsed_html=raw, retained_metadata=retained,
            originally_empty_without_raw_html=sorted(r['number'] for r in before
                if not r['chapters'] and r['number'] not in raw)),
        newly_recovered=recovered, chapters_newly_recovered=sum(r['chapters'] for r in recovered),
        chapters_added=added, chapters_removed=removed, changed_episodes=changed,
        timestamp_corrections=corrections, remaining_without_chapters=remaining,
        potential_regressions=regressions, missing_episodes=missing_episodes,
        missing_chapter_ids=missing_ids, original_metadata_changes=original_field_changes,
        candidate_changes=proposals,
        review_diagnostics=dict(Counter(d['code'] for r in after if needs_review(r)
            for d in r.get('diagnostics', []) if d.get('severity') != 'info' and d['code'] != 'frame_rate_unknown')))


def render_html(report, json_name='comparison.json', investigation_url='investigation.md'):
    labels = dict(episodes_discovered='Episodes discovered', episodes_with_chapters='Episodes with chapters',
        episodes_without_chapters='Episodes without chapters', total_chapters='Total chapters',
        fully_valid_timestamps='Episodes with valid timestamp formats', episodes_requiring_review='Episodes requiring review')
    rows = ''.join(f'<tr><th>{label}</th><td>{report["before"][key]}</td><td>{report["after"][key]}</td></tr>'
                   for key, label in labels.items())
    coverage = report['source_coverage']
    recovered = ', '.join(str(r['episode']) for r in report['newly_recovered'])
    remaining = ''.join('<li>MTS {episode}: <strong>{status}</strong> — <a href="{url}">source</a></li>'.format(
        episode=r['episode'], status=escape(r['status']), url=escape(r['url'], quote=True))
        for r in report['remaining_without_chapters'])
    changed = ''.join(f'<li>MTS {r["episode"]}: {r["before"]} → {r["after"]} chapters</li>' for r in report['changed_episodes'])
    investigation_link = f'<a href="{escape(investigation_url, quote=True)}">Investigation</a>.' if investigation_url else ''
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>MTS catalog validation</title>
<style>body{{font:16px/1.5 system-ui;max-width:1000px;margin:40px auto;padding:0 24px;color:#202020}}
table{{border-collapse:collapse;width:100%;margin:24px 0}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #ddd}}
th:first-child{{width:60%}}details{{margin:24px 0}}small{{color:#555}}h1{{font-size:28px}}</style>
<h1>MTS catalog validation</h1><p>Source: preserved original catalog compared with the improved local catalog.
Generated {escape(report['generated_at'])}.</p>
<table><caption>Extraction quality before and after</caption><thead><tr><th>Metric</th><th>Before</th><th>After</th></tr></thead><tbody>{rows}</tbody></table>
<p><strong>{len(report['newly_recovered'])} episodes recovered; {report['chapters_newly_recovered']} chapters recovered from previously empty episodes.</strong>
{report['chapters_added']} chapter entries added and {report['chapters_removed']} removed or replaced across the comparison.</p>
<p>Recorded public HTML supports metadata for {len(coverage['reparsed_html'])} episodes, including verified descriptions without TOCs. Prior metadata retained and timestamp-normalized for
{len(coverage['retained_metadata'])} episodes without cached raw HTML; their extraction is not independently revalidated.
Original empty episodes without raw evidence: {escape(str(coverage['originally_empty_without_raw_html']))}.</p>
<p>Timestamp-format validity does not establish source accuracy. Four-component timecodes retain the unknown frame rate;
numeric seconds give only the whole-second position. Duplicate and backwards source times remain in source order.</p>
<details><summary>Recovered episodes</summary><p>{escape(recovered)}</p></details>
<details><summary>Remaining episodes without chapters</summary><ul>{remaining}</ul></details>
<details><summary>Changed episode counts</summary><ul>{changed}</ul></details>
<p>Episodes losing chapters: {escape(str(report['potential_regressions']))}. Missing episodes: {escape(str(report['missing_episodes']))}.</p>
<p>Missing stable chapter IDs: {len(report.get('missing_chapter_ids', []))}. Changed original title/order fields: {len(report.get('original_metadata_changes', []))}.
Proposed source extractions retained for manual review: {len(report.get('candidate_changes', []))}.</p>
<p>Review reasons: {escape(str(report['review_diagnostics']))}.</p>
<p>See <a href="{escape(json_name, quote=True)}">{escape(json_name)}</a> for ordered chapter-level changes, timestamp corrections, and source coverage;
{investigation_link}</p></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='reports/baseline')
    parser.add_argument('--catalog', default='mts_data')
    parser.add_argument('--report', default='reports')
    args = parser.parse_args(argv)
    report = compare(load_catalog(args.baseline), load_catalog(args.catalog))
    path = Path(args.report)
    write_json(path / 'comparison.json', report)
    with atomic_file(path / 'comparison.html') as stream:
        stream.write(render_html(report))
    print(json.dumps({k: report[k] for k in ('before', 'after', 'chapters_newly_recovered',
          'chapters_added', 'chapters_removed', 'potential_regressions')}, indent=2))
    return int(bool(report['potential_regressions'] or report['missing_episodes']
                    or report['source_coverage']['originally_empty_without_raw_html']
                    or report['missing_chapter_ids'] or report['original_metadata_changes']))


if __name__ == '__main__':
    raise SystemExit(main())
