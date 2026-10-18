# Incremental discovery and safe revalidation

`uv run mts` discovers episodes and adds only episode numbers absent from the
current catalog. Existing episodes, including previous access failures, are not
repeatedly requested by default. Archive discovery uses cached HTML for up to
24 hours; stale discovery is refreshed through the normal robots, timeout, and
sequential delay policies. `--discovery-ttl` changes that lifetime.

```sh
# Check fresh discovery and add only new episodes
uv run mts --discover

# Revalidate selected existing episodes using available cache evidence
uv run mts --include 100,101

# Revalidate all existing entries, or only entries retaining legacy evidence
uv run mts --revalidate
uv run mts --revalidate-legacy

# Explicitly request fresh public HTML for a selected episode
uv run mts --include 212 --refresh

# Reparse cached HTML without HTTP, preserving stronger prior data
uv run mts --reparse

# Retry operational failures explicitly
uv run mts --retry-failed

# Continue the saved pending selection after interruption
uv run mts --resume
```

Revalidation matches chapters individually. Missing, ambiguous, lower-quality,
or reordered source entries retain the prior catalog evidence and identifiers.
The proposed source extraction and review reasons remain available in
`candidate_extraction`. Confident corrections retain identity and original title
and order, while title/time changes are explicitly flagged for review. A larger
source chapter count does not by itself authorize replacing unmatched entries.

Every run snapshots its previous catalog in `history/<content-hash>/mts_toc.json`
before migration or updates. The run journal `mts_run.json` records its baseline,
selection, completed entries, pending entries, and cache/refresh mode. The
canonical JSON catalog is checkpointed atomically after each episode, followed
by the journal. A crash between those writes may repeat one cached comparison;
it cannot renumber established IDs. `--resume` retains the original run ID and
baseline and resumes the original selection, including an interrupted revalidation.

CSV, JSONL, review, and summary files are regenerated at completion or a clean
Ctrl+C interruption. If a process is killed during export finalization, the
journal remains resumable and the canonical catalog regenerates the exports.
A kernel-managed output-directory lock prevents simultaneous catalog writers
and is released automatically when a process exits.

Each run writes `mts_changes.json` and `mts_changes.html`, with historical copies
under `changes/<run-id>/`. Earlier run journals remain in `history/runs/`.
Cached source bodies are also pinned by hash under `mts_cache/objects/`, with
version metadata under `mts_cache/versions/`, so a redirect or failed refresh
does not destroy earlier successful evidence.

Login-related redirects are recorded without being followed. Such a response
is an unsuccessful revalidation attempt, not chapter provenance. Previously
accepted source metadata remains attached to the preserved chapters; the latest
attempt is recorded separately. Retry those cases only when there is a legitimate
reason to expect the public response to change.
