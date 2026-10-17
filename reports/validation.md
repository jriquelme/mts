# MTS scraper validation

Validation completed on 2026-10-17. The full original catalog is preserved in
`baseline/`. The comparison is available as `comparison.html` and
`comparison.json`; source coverage and hashes are in `evidence.json`.

## Results

- Episodes discovered: 260 before and after.
- Episodes with chapters: 178 → 253; episodes without chapters: 82 → 7.
- Chapters: 2,582 → 4,200, including 1,618 chapters recovered from 75 previously
  empty episodes.
- Episodes with valid timestamp formats: 157 → 230. This measures parseability,
  including nominal whole-second positions for potential frame codes, not source
  accuracy or known frame rates.
- Episodes requiring review: 103 → 52.
- No episode disappeared or lost chapters. Three existing entries changed
  representation without changing episode chapter counts: MTS 90, 96, and 221.
  The one valid timestamp correction recovers MTS 96's captured `00: 32:15` prefix.

## Verification

- All 66 unit and integration tests passed with socket connections explicitly
  disabled. Coverage includes verified historical templates, genuine missing
  lists, noisy markup, invalid and mixed timecodes, duplicate source entries,
  backwards times, cache corruption, retry policy, access restrictions, resume,
  selective retries, interruption recovery, and comparison regression detection.
- A full `uv run mts --reparse` equivalent completed with socket connections
  disabled and reported zero network requests.
- `uv sync --locked` passed and `uv build` produced both source and wheel
  distributions.
- The comparison command exited successfully: no episode losses, chapter-count
  regressions, or original empty episodes left without raw source evidence.

## Coverage limits and remaining work

All 82 original empty episodes were checked. In total, 92 episode descriptions
were reparsed from cached HTML; 168 other episodes retain normalized legacy
metadata and have not had their extraction independently revalidated. The source
coverage lists distinguish these populations explicitly.

MTS 15, 23, 25–28, and 200 have no TOC in their fetched public HTML. Additional
checks of 90, 96, and 226 declined login-related redirects and preserved prior
chapter evidence. No access workaround was attempted.

Review diagnostics retain missing timestamps, two malformed source values,
seventeen ambiguous mixed-format codes in MTS 212, a titleless row in MTS 211,
source duplicates/backwards times, and the three access limitations. Resolve
these from authoritative textual evidence rather than inferring missing values.
