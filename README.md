# MTS chapter indexer

Collect public episode titles, URLs, and ordered chapter lists from the
[10th Planet MTS archive](https://www.10thplanetjj.com/techniques-archive/).
The scraper fetches public HTML text only. It does not request video resources,
log in, or infer missing chapters or times.

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run mts --limit 3
```

`uv run python -m mts` runs the same CLI. Use `uv run mts --help` for all options.

## Incremental execution

```sh
# Crawl all episodes, reusing cached HTML when available
uv run mts

# Continue an interrupted run, skipping completed episodes
uv run mts --resume

# Retry HTTP, access, parsing, and unsupported-layout failures
uv run mts --retry-failed

# Re-extract cached pages without any network requests
uv run mts --reparse

# Investigate selected episodes; keep all other catalog entries
uv run mts --include 100,101,157,158,210,211,220,221,242,243,244

# Explicitly refresh selected source pages and archive discovery
uv run mts --include 243 --refresh

# Use separate output and cache directories
uv run mts --limit 3 --output sample_data --cache sample_cache
```

`--limit N` selects the newest N episodes, processed in episode-number order.
Requests are sequential, with a five-second minimum delay by default. `--delay`
can change this (minimum two seconds). Requests have connection/read timeouts,
bounded exponential backoff, and respect `Retry-After`. Before a live crawl the
scraper checks robots.txt; it stops if policy cannot be retrieved. Cache-only
runs make no requests. Redirects outside public episode pages are not followed.

`--resume` treats extracted lists, untimed/partial lists, and descriptions without
a TOC as completed results. `--retry-failed` retries operational failures; it does
not repeatedly request pages merely because source timestamps are missing.
Failed HTTP/access responses are refreshed when retried. Parsing/layout failures
reuse cached evidence unless `--refresh` is specified. `--retry-failed` requires
an existing catalog. It can be combined with `--reparse` for an offline retry.

`--reparse` uses cached source HTML when available. For an existing episode whose
raw HTML is unavailable, it retains the previous chapters, normalizes their time
metadata, and records `raw_html_unavailable` / `cache_missing` diagnostics.
These entries explicitly have `source.kind = legacy_metadata`; their extraction
has not been independently revalidated. Use a targeted live run to cache them.
Time-like prefixes accidentally retained in old chapter titles are separated
into timestamp fields while preserving the original label in `text_original`.
Ambiguous or malformed values remain invalid rather than being corrected by guess.

Press Ctrl+C to stop cleanly. Completed episodes and all exports are saved, and
the command exits with code 130. Continue with `--resume`. Selective runs merge
results into the existing catalog instead of replacing unselected episodes.

## Output and source evidence

The default output directory is `mts_data/` and the default raw HTML cache is
`mts_cache/`. Both are ignored by Git.

- `mts_toc.json`: episode-based catalog, retaining the original `number`, `title`,
  `url`, `chapters`, and `status` fields, with schema version 2, diagnostics,
  `requires_review`, extraction layout, and source provenance.
- `mts_chapters.csv`: one row per chapter. Existing columns are preserved and
  timestamp metadata, source text, and chapter order are appended.
- `mts_review.csv`: episodes needing review, including a reason list and full
  diagnostics. An `ok` episode can still have warnings.
- `mts_summary.json`: counts by extraction status and diagnostic code, timestamp
  completeness, and interruption state.

All four files are updated after each episode using atomic file replacement.
The JSON catalog is the recovery source if interruption occurs between separate
file replacements; the next run regenerates the exports. Catalog entries are
sorted by episode number; chapter order remains the source order.

The cache stores HTML and metadata under a hash of each URL. Metadata includes
HTTP status, final URL, retrieval time, and a content checksum. Existing cached
text remains available for repeated offline extraction and source inspection.
Network or parser failures retain previously extracted chapters. A decrease in
chapter count is explicitly flagged for investigation.

## Extraction statuses and diagnostics

- `ok`: chapters have parseable timestamps and titles. Duplicate or backwards
  times still generate review warnings.
- `toc_partial`: some timestamps are missing or malformed, or a source timecode
  has no chapter title. All captured rows and available times are preserved.
- `toc_untimed`: every extracted chapter lacks a timestamp.
- `toc_not_present`: a recognized public episode description contains no chapter
  list. A nearby video login form does not establish that a TOC is restricted.
- `unsupported_layout`: no recognized public description layout was found.
- `access_restricted`: HTTP 401/403, a login redirect, or a login-only page.
- `fetch_error`: HTTP/network failure or an offline cache miss without previous
  catalog evidence.
- `parse_error`: unexpected extraction failure; inspect the cached response.
- `robots_disallowed`: the site's crawling policy disallows the page.

This refines the previous `toc_untimed` label, which covered both completely
untimed and partially timed lists. For example, MTS 1 has a timestamp for only
1 of 3 chapters, and MTS 2 and 3 each have times for 4 of 5 chapters. These are now
`toc_partial`. MTS 4 has no timestamps for its 7 chapters and is `toc_untimed`.
Missing values reflect the published list; the scraper does not invent them.

Diagnostics identify missing/malformed/duplicate timestamps, backwards times,
time-like fragments remaining in titles, empty chapter titles, and extraction
losses. Entries are never reordered to hide source inconsistencies. Identical
chapter titles at different source positions remain distinct. The parser walks
each source block once, avoiding duplicates introduced by nested markup.

## Timestamp metadata

Each chapter retains `time` for compatibility, plus `time_original`,
`time_seconds`, `time_format`, `time_valid`, `order`, and `text_original`.
Colon spacing is normalized in `time`; `time_original` retains the captured
spacing, and `text_original` preserves the chapter's extracted text.

`time_format` is `mm:ss`, `hh:mm:ss`, `hh:mm:ss:frames`, `missing`, `invalid`, or
`ambiguous`.
For example, `1:58` becomes 118 seconds and `00: 32:15` becomes 1,935 seconds.
Missing or invalid times have null seconds and `time_valid = false`; their raw
strings are preserved. Unsupported punctuation is flagged rather than guessed.

For `00:39:59:22`, seconds are the frame-independent position 2,399,
`time_frames = 22`, `time_frame_rate = null`, and `time_precision = second`.
The last component is retained as a potential frame index; no frame rate or
fractional seconds are assumed. `time_valid` means the timecode
structure is parseable, not that source accuracy or an exact frame position has
been verified. `frame_rate_unknown` is informational and alone does not require
manual review. Duplicate and non-monotonic times remain warnings.

MTS 213 also uses four-field values such as `00;08;35;23`. Their whole-second
clock position is parsed, while `time_separator = ;` and the original code are
retained. No drop-frame interpretation or frame rate is assumed. Other
unsupported punctuation remains invalid.

Some source lists mix four-component frame codes with three-component values
such as `58:44:04` before `01:00:39:17` (MTS 212). The shorter value could mean
hours/minutes/seconds or minutes/seconds/frames. In a mixed frame list, apparent
clock times of two hours or more are conservatively marked `ambiguous`, with
null seconds and a diagnostic; the scraper does not choose between those readings.

## Tests and validation

Tests use sanitized local description fixtures and mocked HTTP; no network is
needed and no development dependencies are required.

```sh
uv run python -m unittest discover -s tests -v
uv build

# Reparse existing evidence, then regenerate the comparison reports
uv run mts --reparse
uv run python -m mts.validation --baseline reports/baseline --catalog mts_data --report reports
```

The comparison command writes `reports/comparison.json` and an HTML report with
before/after metrics. It records recovered episodes, chapter additions/removals,
ordered chapter-level diffs, timestamp corrections, remaining failures, and raw
HTML coverage. It exits nonzero if episodes lose chapters, disappear, or an
originally empty episode still lacks raw source evidence for investigation.

The original 260-episode catalog is preserved in `reports/baseline/`.
See [the investigation](reports/investigation.md) for verified templates and
source limitations, and [the comparison](reports/comparison.html) for measured
results. Counts retained from legacy metadata are clearly distinguished from
newly validated HTML extraction.
