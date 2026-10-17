# MTS TOC extraction investigation

The original catalog contains 260 episodes, 178 with chapters and 82 without,
2,582 chapters, 157 episodes marked `ok`, and 103 requiring review (82 missing
lists and 21 lists with missing timestamps). The exact original catalog and
summary are preserved in `baseline/` for reproducible comparisons.

## Verified description formats

The public episode description is `#main-video .about`. The sibling `#content`
contains comments and recommendations. The login form protects video playback;
its presence does not establish that the public chapter list is restricted.

- [MTS 100](https://www.10thplanetjj.com/techniques/mts-100-10-x-10/)
  uses list items, sometimes wrapping times in nested spans. It was supported.
- MTS 101 and 157 use one timestamped paragraph per chapter with no TOC heading.
  The original parser incorrectly required a heading unless it found list items.
  This explains the representative endpoints of the 101–157 missing cluster.
- MTS 158 and 210 use a plain `Table of Contents` heading followed by paragraphs.
  Capitalization varies. Four-component timecodes occur in MTS 210.
- MTS 211 and 220 prefix the heading with an episode number, such as
  `MTS 211 Table Of Contents`; MTS 221 returns to the plain heading.
  The original exact heading match rejects the prefixed form.
- MTS 242 has a plain heading; MTS 243 has an episode-prefixed heading.
- MTS 260 contains a timestamp split across a BR (`00:<br>03:04`).
- Early episodes use untimed or mixed lists, including trailing parenthesized
  timestamps. Missing times are source limitations; they must remain blank.

MTS 211 has a standalone `00:33:16:18` row without a chapter title. This is a
source-quality problem. Retain the timecode and flag the missing title rather
than assigning it to the next chapter. Repeated headings such as “COP Sweep” in
MTS 101 occur at different source times and must remain separate chapters.

The sanitized fixtures preserve only description markup, not video resources or
full pages. Full local evidence is cached under `mts_cache/` (ignored by Git).
The cache records URL, HTTP status, origin, and retrieval time.

## Investigation coverage

The first pass compares the requested representative pairs. The follow-up checks
every originally empty episode against cached source HTML, including isolated
failures. Final coverage, source limitations, and comparison metrics are recorded
in the validation report. A higher chapter count alone is not evidence of better
extraction: source order, untitled rows, and losses of previously extracted
chapters require explicit checks.
