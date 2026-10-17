# MTS TOC extraction investigation

The missing-TOC clusters were chiefly parser failures. Checking all 82 originally
empty episodes recovered 75 TOCs and 1,618 chapters. Seven public descriptions
contain no chapter list. The catalog now has 4,200 chapters across 253 of 260
episodes, with no episode losing previously extracted chapters.

The original catalog and summary are preserved in `baseline/`: 178 episodes with
chapters, 82 without, 2,582 chapters, 157 marked `ok`, and 103 requiring review.
The final catalog requires review for 52 episodes. These counts include source
quality warnings, not just fetch or parsing failures.

## Verified public description formats

The episode description is `#main-video .about`. The sibling `#content` contains
comments and recommendations. A nearby login form protects playback and does not
establish that a public chapter list is restricted.

- MTS 100 uses list items with nested spans around timestamps. MTS 101 switches
  to timestamped paragraphs without a TOC heading. Every episode in 101–157 was
  checked and uses headingless chapter blocks; MTS 158 returns to a plain heading.
- MTS 210 uses a plain `Table Of Contents` heading. MTS 211, 212, 219, and 220
  prefix the heading with the episode number. MTS 213–218 omit the heading.
  All ten originally empty episodes in 211–220 are recovered. MTS 221 uses the
  plain heading again.
- MTS 242 has a plain heading; MTS 243 prefixes it with `MTS 243`; MTS 244 returns
  to the plain heading. MTS 243 is recovered.
- MTS 47 puts twelve chapters in one paragraph, separated by BR tags, with some
  entire chapters wrapped in bold. The parser now reads these as twelve source
  entries rather than requiring a heading or list items.
- MTS 162–164, 179, and 185–186 contain headingless timestamped descriptions and
  are recovered. The other isolated failures are genuine missing lists below.
- MTS 260 splits `00:03:04` across a BR. MTS 221 splits a chapter title across a
  BR: “Blue Belt” followed by “Championship.” The first is one timestamp and the
  second is one title, not an extra chapter.
- Early episodes contain untimed or mixed lists, including trailing parenthesized
  timestamps. Missing times remain blank. Repeated titles such as “COP Sweep” in
  MTS 101 remain separate ordered chapters.

The source URLs, cached HTML hashes, selector, detected heading, markup features,
HTTP status, and extraction counts for each inspected page are in `evidence.json`.
Sanitized description-only fixtures are in `../tests/fixtures/`; full local
HTML is retained in the ignored `mts_cache/` directory. The initial investigation
saved requested URLs but did not capture final redirect URLs; its evidence
explicitly records final URLs as unverified rather than claiming they are known.
Four cached control pages came from the earlier live check; their import metadata
does not establish their exact original retrieval time.

## Source limitations and ambiguous timecodes

MTS 15, 25–28, and 200 have only a title in the public description. MTS 23 adds a
short promotional sentence but no chapter list. All seven returned HTTP 200 with
recognizable description markup. None contains embedded JSON-LD or inline chapter
structures supplying a missing TOC. They are `toc_not_present`. This establishes
absence from fetched public HTML, not absence from a video or subscriber session.
Obtaining an author-provided textual TOC is a separate manual step.

The recovered sources also contain issues that must remain visible:

- MTS 121 contains `00:18:124`. The intended correction is uncertain, so the raw
  value is retained with null seconds and a malformed-time diagnostic.
- MTS 211 contains `00:33:16:18` with no title. The row is preserved and flagged.
- MTS 212 mixes four-field codes with values such as `58:44:04` before
  `01:00:39:17`. Seventeen three-field values could mean HH:MM:SS or MM:SS:frames.
  Their numeric positions remain unresolved instead of becoming implausible hour
  offsets. This ambiguity produces `toc_partial`.
- MTS 213 consistently uses 26 semicolon-separated four-field codes alongside
  colon-separated codes. Their nominal HH:MM:SS position is available, but the
  separator, potential frame index, and unknown frame rate remain explicit.
  No drop-frame or fractional conversion is applied. Other punctuation patterns
  without verified meaning are not guessed.
- Duplicate and backwards times occur in the source, including MTS 118, 120,
  123, 133, and 219. They generate warnings and do not trigger sorting or removal.

## Access limitations in additional diagnostic checks

Additional checks of MTS 90, 96, and 226 returned redirects to
`/forum/login_info.php`. The scraper declined those login-related destinations.
Their existing chapter metadata is preserved and marked `access_restricted`, with
`last_live_check` provenance and review diagnostics. This is a limitation of the
current public HTTP session and conservative redirect policy; it does not prove
that the text is subscriber-only. No login, browser impersonation, or access-control
workaround was attempted. Details are in `access_checks.json`.

The saved MTS 96 label already contained `00: 32:15`; separating this captured
prefix recovers 1,935 seconds without a new source request. The original label and
legacy provenance remain available. MTS 90's `0 0:15:25` is separated as an invalid
raw timestamp, with no guessed numeric correction. MTS 226's qualifier/date label
is preserved and excluded from clock-fragment false positives.

## Validation and remaining review

All 82 original empty episodes have raw HTML evidence. In total 92 episodes were
reparsed from HTML, including successful control pages. The remaining 168 retain
previous metadata with normalized timestamp fields; their extraction is not
independently revalidated. This avoids another full-site crawl while making the
coverage limit explicit.

There are no fetch, parser, or unsupported-layout failures among the 82 investigated
empty episodes. Remaining gaps are the seven absent public TOCs, incomplete or
malformed source times/titles, mixed clock formats, source ordering warnings, and
the three additional login-related redirect limitations.

No episode loses chapters. Three existing entries change representation: the
invalid time prefix in MTS 90, the recoverable time prefix in MTS 96, and the title
continuation in MTS 221. Their episode counts remain 17, 23, and 29. The comparison
records these as three replacements, not three lost chapters. No uncertain title
spelling or source time was corrected by inference.

See `comparison.html` for before/after metrics and `comparison.json` for every
ordered chapter-level change, timestamp correction, remaining failure, and source
coverage list. The catalog preserves source text and ordering for later semantic
enrichment; no curriculum labels or speculative technique descriptions are added.
