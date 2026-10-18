# Chapter identity and enrichment exports

The catalog is schema version 3. Each active chapter has a persistent ID such as
`mts-0001-c000003`. The episode number scopes a monotonically allocated sequence;
the sequence is independent of chapter title, timestamp, and current row order.
The JSONL record schema is independently versioned as version 1.

On first migration, existing chapters receive IDs in their existing catalog
order. The catalog persists `next_chapter_sequence` for each episode. A source
insertion receives the next unused sequence, and existing chapters keep their
IDs. Persisted `retired_chapter_ids` reserve previously issued sequences if a
future explicit editorial process retires entries. The scraper itself preserves
previous entries rather than deleting them. Duplicate or invalid IDs stop a write;
the scraper never silently assigns a replacement identity to an existing chapter.

Revalidation first matches exact title/time occurrences, retaining distinct
occurrences of repeated chapters. Unique titles can establish identity when only
times change; unique valid timestamps can establish identity when only titles
change. If neither establishes identity, the previous chapter and its ID remain
active and the unmatched source entry is saved as a review candidate. No fuzzy
match or row-number guess changes a chapter's identity.

`original_order` and `title_original` record the first captured order and title
and do not change during subsequent corrections. `order` is the current catalog
order, `source_order` is the matched source position, and `title_source` retains
the latest source label. `title_normalized` applies Unicode NFC and whitespace
normalization without correcting spelling or assigning semantic labels. New
source insertions can share an original ordinal with an older chapter; ordinals
are provenance, not identifiers.

`mts_chapters.jsonl` contains one active chapter per line, with:

- Chapter ID, episode number/title, and source URL.
- Original, current, and source order; original, normalized, and source title.
- Raw timestamp, format, validity, whole-second position when unambiguous, and
  timestamp confidence.
- Per-chapter source provenance, episode validation state, and diagnostics.

Confidence values distinguish missing, invalid, ambiguous, unverified legacy,
whole-second, and nominal whole-second positions with unknown frame rate. An
unknown offset remains null. IDs and provenance are shared with the catalog and
CSV export; the existing CSV columns are retained with additional fields appended.

No classification fields, speculative technique descriptions, or curriculum
labels are generated. Batch enrichment can use `chapter_id` as its join key and
must retain the catalog as the authority for source evidence and identity.
