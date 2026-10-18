"""Source coverage and review-case accounting, separate from semantic enrichment."""

import argparse
from collections import Counter
from html import escape
import json
from pathlib import Path

from mts.storage import atomic_file, load_catalog, needs_review, utcnow, write_json
from mts.provenance import public_source


INFO_CODES = {'frame_rate_unknown', 'raw_html_unavailable', 'cache_missing',
              'timestamp_semicolon_timecode', 'timestamp_recovered_from_legacy_title'}
ACCESS_CODES = {'access_restricted', 'fetch_error', 'parse_error', 'unsupported_layout',
                'robots_disallowed', 'previous_chapters_retained'}


def review_codes(row):
    return sorted({d['code'] for d in row.get('diagnostics', [])
                   if d['code'] not in INFO_CODES and d.get('severity') != 'info'})


def quality_report(before, after, fetch_report, identity_baseline):
    previous = {r['number']: r for r in before}
    current = {r['number']: r for r in after}
    by_id = {c['chapter_id']: c for row in after for c in row['chapters']}
    missing_ids, altered_originals = [], []
    for identity in identity_baseline:
        chapter = by_id.get(identity['chapter_id'])
        if chapter is None:
            missing_ids.append(identity['chapter_id'])
        elif any(chapter.get(k) != identity[k] for k in ('title_original', 'original_order')):
            altered_originals.append(identity['chapter_id'])
    source_counts = Counter()
    fully_sourced, retained = [], []
    for row in after:
        sources = [c.get('source', row.get('source', {})) for c in row['chapters']]
        source_counts.update('public_html' if public_source(s) else 'legacy_or_unverified' for s in sources)
        verified = all(public_source(s) for s in sources) if sources else public_source(row.get('source', {}))
        (fully_sourced if verified else retained).append(row['number'])
    followup = []
    for old in before:
        if not needs_review(old):
            continue
        row = current.get(old['number'])
        codes = review_codes(row) if row else ['episode_missing']
        quality_codes = sorted(set(codes) - ACCESS_CODES)
        blocked = bool(set(codes) & ACCESS_CODES)
        if row and not codes:
            outcome = 'resolved'
        elif blocked:
            outcome = 'blocked_by_access_or_operational_failure'
        else:
            outcome = 'unresolved_source_quality'
        followup.append(dict(episode=old['number'], before=review_codes(old), after=codes,
            quality_reasons=quality_codes, outcome=outcome,
            has_public_evidence=row['number'] in fully_sourced if row else False,
            action='Use authoritative corrected textual metadata; retain current values and source order until then.'))
    attempts = fetch_report.get('attempts', [])
    mixed = current.get(212, {})
    ambiguous = [dict(chapter_id=c.get('chapter_id'), order=c['order'], raw=c.get('time_original'),
                      title=c['title']) for c in mixed.get('chapters', []) if c.get('time_format') == 'ambiguous']
    return dict(generated_at=utcnow(),
        legacy_audit=dict(targets=fetch_report.get('legacy_episodes', []), attempted=[a['episode'] for a in attempts],
            outcomes=dict(Counter(a['status'] for a in attempts)), finished_at=fetch_report.get('finished_at')),
        coverage=dict(public_evidence_episodes=fully_sourced, legacy_or_unverified_episodes=retained,
                      chapter_sources=dict(source_counts)),
        identity=dict(baseline_count=len(identity_baseline), active_count=len(by_id),
                      missing_ids=missing_ids, changed_original_fields=altered_originals),
        original_review_cases=followup, review_outcomes=dict(Counter(c['outcome'] for c in followup)),
        newly_flagged_episodes=sorted(r['number'] for r in after if needs_review(r)
            and (r['number'] not in previous or not needs_review(previous[r['number']]))),
        remaining_without_chapters=[r['number'] for r in after if not r['chapters']],
        mixed_timecode_212=dict(ambiguous=ambiguous,
            finding='Cached public description mixes three/four components. No alternative metadata or time attributes supply an authoritative interpretation; no neighboring-time or duration inference applied.'),
        candidates=[dict(episode=r['number'], validation=r.get('validation'),
                         source_status=r['candidate_extraction'].get('status'))
                    for r in after if r.get('candidate_extraction')])


def render_quality(report):
    coverage, audit = report['coverage'], report['legacy_audit']
    cases = ''.join(f'<tr><td>{c["episode"]}</td><td>{escape(c["outcome"])}</td><td>{escape(", ".join(c["after"]))}</td></tr>'
                    for c in report['original_review_cases'])
    mixed = ''.join(f'<li>Chapter {c["order"]}: <code>{escape(c["raw"])}</code> — {escape(c["title"])}</li>'
                    for c in report['mixed_timecode_212']['ambiguous'])
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>MTS data quality and source coverage</title>
<style>body{{font:16px/1.5 system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#202020}}
table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #ddd}}
h1{{font-size:28px}}details{{margin:24px 0}}</style><h1>MTS data quality and source coverage</h1>
<p>Generated {escape(report['generated_at'])}. Source: maintenance baseline, current catalog, and sequential public-request audit.</p>
<p><strong>{len(coverage['public_evidence_episodes'])} episode records have supporting public HTML, including descriptions without TOCs;
{len(coverage['legacy_or_unverified_episodes'])} retain legacy or unverified metadata.</strong>
Public chapter evidence: {coverage['chapter_sources'].get('public_html', 0)} chapters.
Legacy or unverified chapter evidence: {coverage['chapter_sources'].get('legacy_or_unverified', 0)} chapters.</p>
<p>The audit attempted {len(audit['attempted'])} of {len(audit['targets'])} legacy episodes.
Outcomes: {escape(str(audit['outcomes']))}. A cached redirect body does not count as validated episode metadata.</p>
<p>Stable IDs missing: {len(report['identity']['missing_ids'])}; altered original title/order fields:
{len(report['identity']['changed_original_fields'])}. Original review outcomes: {escape(str(report['review_outcomes']))}.</p>
<p>Known public descriptions without chapter lists: {escape(str(report['remaining_without_chapters']))}.</p>
<details><summary>Original review cases and current reasons</summary><table><thead><tr><th>Episode</th><th>Outcome</th><th>Reasons</th></tr></thead><tbody>{cases}</tbody></table></details>
<details><summary>MTS 212 unresolved timecodes</summary><p>{escape(report['mixed_timecode_212']['finding'])}</p><ul>{mixed}</ul></details>
<p>New review flags can indicate newly documented access limitations, not a loss of retained chapter data.
The seven known missing public TOCs remain unresolved unless authoritative source text appears.</p>
<p><a href="data-quality.json">Machine-readable quality report</a> · <a href="comparison.html">Catalog comparison</a> ·
<a href="maintenance-fetch.json">Public-request audit</a></p></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='reports/maintenance-baseline')
    parser.add_argument('--catalog', default='mts_data')
    parser.add_argument('--attempts', default='reports/maintenance-fetch.json')
    parser.add_argument('--identities', default='reports/chapter-identity-baseline.json')
    parser.add_argument('--report', default='reports')
    args = parser.parse_args(argv)
    report = quality_report(load_catalog(args.baseline), load_catalog(args.catalog),
        json.loads(Path(args.attempts).read_text()), json.loads(Path(args.identities).read_text()))
    write_json(Path(args.report) / 'data-quality.json', report)
    with atomic_file(Path(args.report) / 'data-quality.html') as stream:
        stream.write(render_quality(report))
    print(json.dumps({k: report[k] for k in ('legacy_audit', 'identity', 'review_outcomes')}, indent=2))
    return int(bool(report['identity']['missing_ids'] or report['identity']['changed_original_fields']
                    or set(report['legacy_audit']['targets']) - set(report['legacy_audit']['attempted'])))


if __name__ == '__main__':
    raise SystemExit(main())
