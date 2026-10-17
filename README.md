# MTS chapter indexer

Collect public episode titles, URLs, and chapter lists from the
[10th Planet MTS archive](https://www.10thplanetjj.com/techniques-archive/).
Only HTML text metadata is fetched; videos and login credentials are not needed.

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run mts --limit 3
```

`mts` runs the scraper. `uv run python -m mts` also works.

```sh
# Crawl all episodes (several minutes)
uv run mts

# Select episodes and an output directory
uv run mts --include 1,34,180,260 --output mts_data

# Show all options
uv run mts --help
```

`--limit N` selects the newest N episodes, processed in episode-number order.
Requests use a three-second minimum delay by default; `--delay` must be at least
two seconds. The scraper checks robots.txt and retries temporary HTTP failures.

The output directory defaults to `mts_data/` (ignored by Git):

- `mts_toc.json`: episode metadata and chapter lists, saved after each episode.
- `mts_chapters.csv`: one row per chapter.
- `mts_review.csv`: episodes needing review, including errors and missing timestamps.
- `mts_summary.json`: run timestamp and counts.

`toc_untimed` means an episode's bullet list contains **at least one chapter
without a timestamp**. It can still contain timed chapters: all available times
are preserved, and only missing times get an empty `time` / `timestamp`.
This status alone does not indicate a fetch or parser failure. For example:

- MTS 1: 1 of 3 chapters has a timestamp.
- MTS 2 and MTS 3: each has timestamps for 4 of 5 chapters.
- MTS 4: none of its 7 chapters has a timestamp.

These counts match the published chapter lists; the scraper does not infer
missing times. Episodes marked `toc_untimed` are included in the review CSV.
Episodes with no recognizable list or a fetch error are also flagged for review.
Only episodes with status `ok` count toward `with_toc`.

Pressing Ctrl+C stops the run and currently prints a `KeyboardInterrupt`
traceback. Completed episodes remain in `mts_toc.json`, which is saved after each
episode. The CSV files and summary are written only after the crawl finishes;
after an interrupted run they may be absent or left over from an earlier run.

Running `uv run mts` again starts from episode 1; there is no automatic resume.
Each run replaces the files in its output directory as they are written. Use a
different `--output` directory to preserve a previous run.

Run the offline regression tests with:

```sh
uv run python -m unittest discover -s tests -v
```
