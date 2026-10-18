# MTS scraper maintenance and data quality

The catalog retains 4,200 chapters across 253 of 260
episodes. Every original chapter identity, original title, and original order
survives this phase. The new-only update path, safe chapter reconciliation,
stable identifiers, JSONL export, catalog snapshots, source history, and resumable
run journals are implemented and tested.

## Actual source coverage

All 168 legacy episodes lacked accepted public HTML at the start. Each ordinary
episode URL was requested sequentially through the existing robots, five-second
delay, timeout, retry, and access-control policies. Outcomes were
{'access_restricted': 168}. Login-related destinations
were not followed; no authentication or alternative-client workaround was used.

This is an unsuccessful source revalidation under the current client's strict
redirect policy, not evidence that the text is necessarily subscriber-only.
The attempt hash, response status, target, and retrieval time are recorded in
`maintenance-fetch.json` and the catalog's separate attempt/validation fields.
Redirect bodies are excluded from chapter provenance and coverage counts.

Accepted public HTML supports metadata for 92 episodes: 85 with chapter lists
and seven descriptions verified to lack a TOC. These sources support
1,794 active chapters. The other 168 episodes and
2,406 chapters retain legacy or unverified evidence.
All 92 previously cached public pages were reparsed and compared individually
against the preserved catalog without network access. These records remain
supported by their existing source hashes; they were not freshly fetched during
this phase. All recorded public chapter hashes remain readable from immutable
local source objects.

The refreshed public archive still discovers 260 episodes, so the default
incremental path adds none. No existing episode pages are requested by default.

## Original review cases and unresolved uncertainties

Of the original 52 review cases, 20 retain unresolved public-source quality
issues and 32 are blocked by access limitations. None was marked resolved by
guessing. The aggregate review count is now
188, including 136 newly documented review cases.
The increase reflects previously unaudited legacy access limitations; no known
chapters were discarded or replaced by lower-quality results.

The seven public descriptions without TOCs remain unresolved: [15, 23, 25, 26, 27, 28, 200].
No new authoritative source text established missing chapters or timestamps.

MTS 212 retains seventeen ambiguous three-field values mixed with four-field
codes. Its cached HTML contains no JSON-LD, alternative description metadata, or
chapter time attributes that establish whether those values are HH:MM:SS or
MM:SS:frames. Their numeric offsets remain null. The interpretation is not inferred
from surrounding entries or duration.

MTS 121 still has the malformed source value `00:18:124`; MTS 90's inherited
`0 0:15:25` also remains invalid because fresh authoritative text is unavailable.
The empty title in MTS 211, source duplicates, non-monotonic times, and missing
times remain explicit diagnostics. Repeated source chapters are preserved, and
chapter order is not automatically sorted.

The machine-readable quality report includes follow-up and evidence status for
every original review case. Resolve these only from corrected authoritative
textual metadata; the scraper does not inspect videos or assign semantic labels.

## Stable exports and preservation

All 4,200 active chapters have unique persistent episode-local IDs. IDs do not
depend on mutable titles, timestamps, or current row positions. New insertions
allocate new sequences; uncertain matches retain existing entries and save the
proposal for review. Original titles and orders are immutable. CSV, JSONL, and
catalog IDs agree exactly. See `../docs/exports.md` for schema and collision rules.

The previous catalog is preserved in `maintenance-baseline/`; the first ID mapping
is in `chapter-identity-baseline.json`. Runtime snapshots and historical change
reports are under `mts_data/history/` and `mts_data/changes/`. Source bodies are
pinned by hash before replacement. Operational failures record their latest
attempt separately while preserving the source that supports each retained chapter.

## Verification

All 104 tests pass with socket connections disabled. Coverage includes migration,
source-entry preservation, stable IDs, JSONL/CSV agreement, incremental discovery,
access redirects and HTTP-200 access walls, wrong-episode responses, partial
failures, identity reservations, persistent review flags, and resumable exports.
A full cached revalidation completed with zero network requests. The default
incremental path also performed no network requests against fresh discovery.

`uv sync --locked` and `uv build` pass. The updated comparison reports no episode
losses or chapter-count regressions. All 4,200 initial IDs and original title/order
fields remain present. Source coverage is reported separately from timestamp
format validity and HTTP cache coverage.

See `comparison.html`, `comparison.json`, `data-quality.html`, and
`data-quality.json` for measured results and per-episode details. No curriculum
classifications or speculative technique descriptions were added.
