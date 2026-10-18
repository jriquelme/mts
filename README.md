# MTS chapter indexer

Collect public episode metadata and ordered chapter lists from the
[10th Planet MTS archive](https://www.10thplanetjj.com/techniques-archive/).
The scraper fetches ordinary public metadata HTML only. It does not request video
resources, follow login-related redirects, log in, or infer missing timestamps.

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run mts
```

The default command **adds only new episodes**. Existing catalog entries, including
previous access failures, are preserved. Discovery uses an archive cache with a
24-hour lifetime; `--discover` requests a fresh archive check immediately.
`uv run python -m mts` runs the same CLI.

## Revalidation and incremental updates

```sh
# Fresh archive discovery, adding only new episodes
uv run mts --discover

# Explicitly revalidate existing entries with cached evidence where available
uv run mts --revalidate
uv run mts --revalidate-legacy
uv run mts --include 100,101,212

# Refresh selected ordinary metadata pages
uv run mts --include 212 --refresh

# Compare cached HTML against the catalog without any HTTP requests
uv run mts --reparse

# Explicitly retry operational failures
uv run mts --retry-failed

# Resume the exact pending selection and request mode after interruption
uv run mts --resume

# Separate output/cache directories or a small selection
uv run mts --limit 3 --output sample_data --cache sample_cache
uv run mts --help
```

`--limit N` selects the newest N episode numbers before applying the requested
mode; the default mode still excludes known episodes. Requests are sequential,
with a five-second default minimum delay. `--delay` may change this (minimum two
seconds). The client applies timeouts, bounded exponential backoff, `Retry-After`,
and robots.txt policy. `--discovery-ttl` configures archive freshness in hours.

Revalidation compares individual chapters, not just counts. Missing, ambiguous,
reordered, or lower-quality entries preserve prior evidence and IDs. Proposed
source rows remain in `candidate_extraction` with actionable diagnostics. Source
corrections that can be matched confidently keep identity and are flagged as
changes. Uncertain new blocks require review instead of inflating chapter counts.

Use `--resume` without selection or request-mode flags; it restores those from
`mts_run.json`. Interrupted revalidation resumes existing episodes in its saved
worklist. CSV/JSONL/summary exports are regenerated after completion or a clean
Ctrl+C interruption. The catalog is checkpointed atomically after each episode;
exports interrupted by a process kill can be rebuilt with `--resume`.

See [incremental update details](docs/incremental-updates.md) for snapshots, run
journals, change reports, source history, and concurrent-writer protection.

## Output and source provenance

Default directories `mts_data/` and `mts_cache/` are ignored by Git. The catalog
remains the authority for identity and source evidence; all exports are derived.

- `mts_toc.json`: schema 3 episode catalog with stable IDs, ordered chapters,
  timestamp fields, source provenance, validation state, and diagnostics.
- `mts_chapters.jsonl`: one chapter per line, suitable for downstream batch
  enrichment. No semantic classifications or curriculum labels are assigned.
- `mts_chapters.csv`: existing columns plus IDs, original/normalized titles,
  original order, timestamp confidence, provenance, and diagnostics.
- `mts_review.csv`: episodes needing review, including reason codes and details.
- `mts_summary.json`: extraction, timestamp, coverage, and interruption counts.
- `mts_changes.json` / `mts_changes.html`: the current run's before/after report.
- `mts_run.json`: recoverable pending selection and run state.

Prior catalogs are preserved under `mts_data/history/<content-hash>/`. Earlier
run reports live under `mts_data/changes/<run-id>/`. Cached HTML and version
metadata are pinned by source hash, so a failed refresh cannot destroy earlier
successful evidence. A login redirect body is an unsuccessful attempt, not
chapter provenance; prior accepted sources remain attached to retained chapters.

Legacy metadata remains explicit when public HTML is unavailable. JSONL
`timestamp_confidence = unverified_legacy` distinguishes syntactically parseable
inherited offsets from timestamps backed by public source text. Revalidating a
URL or caching a redirect does not establish that its chapter list was verified.

## Stable chapter identity

IDs such as `mts-0001-c000003` use persistent episode-local sequence numbers,
independent of mutable titles, timestamps, and current row order. Insertions use
new sequence numbers; corrections and source reorderings never renumber known
chapters. Duplicate/invalid IDs stop a write. Original title and order remain
immutable, while current source title/order are recorded separately.

See [the export schema and collision strategy](docs/exports.md) for matching
rules, reserved sequences, normalization, provenance, and JSONL fields.

## Statuses and timestamp uncertainty

- `ok`: titles and timestamp formats are parseable; source warnings can still
  require review.
- `toc_partial`: some times are missing, malformed, or ambiguous, or a title is
  missing. Available information is preserved.
- `toc_untimed`: every extracted chapter lacks a timestamp.
- `toc_not_present`: a recognized public description contains no chapter list.
- `unsupported_layout`: no recognized public description layout was found.
- `access_restricted`: HTTP 401/403, a login-related redirect, or an access wall.
- `fetch_error` / `parse_error`: request or extraction failure.
- `robots_disallowed`: site policy disallows the request.

An episode can retain known chapters while its latest revalidation is restricted.
Per-chapter provenance and the separate attempt/validation fields explain which
source supports each entry. An `ok` episode can still have duplicate or backwards
times, a changed title/time, or a proposed source difference requiring review.

Each chapter preserves raw `time_original` and source text, with `time_seconds`,
`time_format`, and `time_valid`. `1:58` becomes 118 seconds; colon spacing such as
`00: 32:15` can be normalized directly. Missing and invalid values have null
seconds. No timestamp is inferred from neighboring chapters or video duration.

Four-field values such as `00:39:59:22` retain a potential frame index and unknown
frame rate. Their nominal whole-second position is 2,399; fractional or drop-frame
conversion is not assumed. MTS 213's semicolon-separated four-field codes retain
`time_separator = ;`. MTS 212's mixed three/four-field clocks remain explicitly
ambiguous where their interpretation cannot be established from source text.
Non-monotonic source times remain warnings and are never silently sorted.

## Validation and reports

```sh
# Offline tests; no development dependencies or network are needed
uv run python -m unittest discover -s tests -v
uv build

# Rebuild from cached evidence, then compare against the maintenance baseline
uv run mts --reparse
uv run python -m mts.validation --baseline reports/maintenance-baseline
uv run python -m mts.quality
```

The comparison command writes `reports/comparison.json` and
`reports/comparison.html`, recording ordered changes, timestamp corrections,
retained proposals, and potential regressions. It exits nonzero for episode or
chapter-count losses or uninvestigated originally empty episodes. The quality
command writes `reports/data-quality.json` and `reports/data-quality.html`, with
actual source coverage, identity preservation, legacy request outcomes, and
follow-up for each original review case.

The maintenance baseline preserves the 4,200-chapter catalog. The earlier
2,582-chapter baseline remains in `reports/baseline/`. Current findings are in
[the maintenance report](reports/maintenance-report.md),
[the data-quality report](reports/data-quality.html), and
[the comparison](reports/comparison.html). The original template investigation is
preserved in [investigation.md](reports/investigation.md).
