<!-- OPENWIKI:START -->

## OpenWiki

This repository uses OpenWiki for recurring code documentation. Start with `openwiki/quickstart.md`, then follow its links to architecture, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

The scheduled OpenWiki GitHub Actions workflow refreshes the repository wiki. Do not hand-edit generated OpenWiki pages unless explicitly asked; prefer updating source code/docs and letting OpenWiki regenerate.

<!-- OPENWIKI:END -->

<!-- Hand-written; outside the OPENWIKI markers so regeneration preserves it. -->

## Running the tests

The suite is offline, needs no network and no dependencies, and finishes in about a
second. Run it before and after any change — do not document behaviour as unverified
without trying both commands below.

```bash
uv run test_job_boards.py     # preferred: uv provisions Python 3.11
python3 test_job_boards.py    # fallback: works on any Python >= 3.9, including
                              # macOS's system python3, with uv absent from PATH
```

The fallback exists specifically for tooling that runs with a minimal `PATH`. If `uv`
is not found, use the second command rather than reporting that the tests could not be
run. Both print `ok` on success.

## Do not run casually

`--refresh-boards` and `--all` are live network operations across 13,146 boards on three
platforms, taking tens of minutes. Never in a loop. Everything you need to verify a code
change is covered by the offline suite. `--limit 10` plus `--ats <one>` is the cheap way
to exercise a real request path.

`--refresh-recent` is the cheap discovery pass (~4 minutes) and `--since 7d` narrows to
recent postings — still live network calls, so the same rules apply.

For a freshest-first feed, `--since 1d --sort recent` is the pairing that matters:
`--sort` defaults to `board`, which groups by platform and company and buries the newest
postings in the middle of the file. Note that no platform supports server-side date
filtering, so `--since` never makes a run cheaper — every board is fetched in full and
the window is applied locally. Latency to a new posting depends on how often the scraper
runs, not how narrow the filter is.

`--grep` on Greenhouse requests full job descriptions, which is roughly **26x** the
bytes of a normal run. Do not add it casually to an unlimited run.

## Performance: what to change and what not to

This tool is network-bound. Parsing and normalisation are **0.2%** of a run, so
optimising them is wasted effort. Only round trips and connections matter.

Connections are pooled per thread against the three posting-API hosts, which took a full
run from 6m35s to 3m51s. Two consequences:

- **Add a new ATS host to `_POOLED_HOSTS`**, or it silently opts out of that. A test
  enforces this.
- **Read headers in lowercase.** The pooled path returns a plain dict, unlike urlopen's
  case-insensitive `Message`. These APIs already disagree — ashby and greenhouse send
  `etag`, lever sends `ETag` — and a case-sensitive lookup for `Content-Encoding` would
  return gzip bytes as if they were JSON.

**Do not raise `--concurrency` to make something faster.** It is the one lever that works
by moving cost onto Ashby, Greenhouse and Lever. 8 is a requirement, not a tunable.

## If you add a filter, update `may_close_postings()`

This is the single most damaging thing to get wrong in this codebase.

`closed_at` asserts a posting is gone. Only a run that saw every posting on a board may
set it, so every narrowing flag — `--title`, `--grep`, `--since`, `--new-only` — has to be
listed in `may_close_postings()` in `job_boards.py`. A filter missing from it means a
perfectly normal-looking run silently marks huge numbers of live postings as closed:
`--all --since 7d` would close everything older than a week.

It is pinned by `test_only_an_unfiltered_run_may_close_postings`. Add your filter to both
in the same change.

Set `JOB_SCRAPER_CONTACT` to a real address before any network run. Ask for one;
do not invent it.

## Read before changing behaviour

`README.md` has a "For coding agents (LLMs)" section listing behaviours that look like
bugs and are deliberate, each pinned by a test. Read it before changing filter logic,
the database lifecycle, board validation, or any per-platform normaliser.

The normalisers in `job_boards.py` are where platform differences live. Two that have
already caused silent, wrong-looking-correct output: Lever's job title is `text`, not
`title`, and its `createdAt` is epoch milliseconds rather than ISO.
