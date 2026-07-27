# ashbyhq-jobs

Pull every public job posting from every Ashby job board. No API key, no account, no
dependencies.

Ashby's posting API is public but per-company, keyed by a board slug, with no global
search endpoint. This finds the boards — 3,617 of them — then fans out across all of
them. **~54,000 live postings, start to finish in about two minutes.**

> **Engineers and coding agents:** the [`openwiki/`](openwiki/quickstart.md) wiki is the
> map of the code — architecture, workflows, data model, runbook. Agents should start
> with [For coding agents](#for-coding-agents-llms) below.

## Quick start

No dataset is bundled; you generate your own. The only prerequisite is
[uv](https://docs.astral.sh/uv/) — no `pip install`, no venv, no dependencies, and it
fetches its own Python.

```bash
git clone https://github.com/mherzog4/ashbyhq-jobs.git
cd ashbyhq-jobs

# Identify your traffic. Archive operators ask clients to do this, and it puts
# your address on your requests rather than someone else's.
export ASHBY_SCRAPER_CONTACT="you@example.com"

# Find every board, then pull every posting from all of them.
uv run ashby_jobs.py --refresh-boards --all
```

That is the whole thing. Expect roughly:

```
querying the Wayback Machine...
  191135 archived URLs -> 7463 candidates
validating 5000 plausible slugs against the posting API...
  3611 live boards (1389 dead)
  +6 from seed/previous runs
cached 3617 slugs -> boards.json
scanning 3617 boards for every listed job...
  3617/3617 boards | 0 404 | 0 err | 54572 matches

54572 jobs -> ashby-jobs.csv, ashby-jobs.json, ashby-jobs.db (54572 new, 0 already seen)
```

Roughly 80 seconds to discover the boards and 30 to scrape them. You end up with:

| file | what it is |
|---|---|
| `ashby-jobs.csv` | every posting, UTF-8 BOM so Excel renders `–`/`•` correctly |
| `ashby-jobs.json` | the same rows |
| `ashby-jobs.db` | SQLite, accumulating across runs with `first_seen`/`last_seen` |
| `boards.json` | the 3,617 discovered slugs, cached so later runs skip discovery |

Later runs reuse `boards.json`, so a re-scrape is just `uv run ashby_jobs.py --all` and
takes ~30 seconds. Re-run `--refresh-boards` about monthly — see
[How recent is the data?](#how-recent-is-the-data) for why more often buys nothing.

### Narrower searches

```bash
uv run ashby_jobs.py --title "software engineer"
uv run ashby_jobs.py --title "software engineer" --match exact
uv run ashby_jobs.py --title "product designer" --remote --limit 200
uv run ashby_jobs.py --grep '\brust\b|\bgolang\b'    # search descriptions
uv run test_ashby_jobs.py                            # offline self-check
```

## How complete is this?

Measured, not estimated:

| | count |
|---|---|
| Boards discovered and validated live | **3,617** |
| Jobs returned by `--all` | **54,560** |
| Jobs on those boards, counted independently | 54,569 |
| Difference | 9 unlisted postings, excluded on purpose |

So it gets **every listed job on every board it knows about**. The honest limit is the
board list, not the scraping — and there is no authoritative list of Ashby customers to
check against, so completeness cannot be proven, only bounded.

Where boards can still be missed:

- **Discovery only sees what the Internet Archive captured.** A board that exists but was
  never crawled is invisible. This is real, not theoretical: `newtonx` was live but absent
  from 191k archived URLs. To stop that from costing you anything, `--refresh-boards`
  unions its results with `boards.seed.json` and the previous `boards.json`, so a refresh
  never loses a board an earlier run knew about.
- **New Ashby customers** appear before the archive notices them — a median of 48 days
  before, measured above. Re-run `--refresh-boards` monthly, or add the slug by hand.
- **The shape filter** drops candidates that cannot be slugs. Sampling 150 of the 2,463 it
  rejected turned up zero real boards, so this looks safe, but it is a sample.

If you find a board this misses, add it to `boards.seed.json` and it is permanent.

## How recent is the data?

Two independent clocks. Job data is live; the board list lags.

**Jobs are real-time.** Every run hits Ashby's API directly — nothing is cached — so you
get postings published hours ago. Measured across a full 54,572-job pull:

| posted within | jobs | share |
|---|---|---|
| today | 946 | 1.7% |
| 7 days | 6,754 | 12.4% |
| 30 days | 19,780 | 36.2% |
| 90 days | 37,614 | 68.9% |

Median posting age is 48 days. That is the shape of the job market, not scrape lag.

**Board discovery lags by ~48 days.** A company that adopts Ashby is invisible until the
Internet Archive crawls its board. Comparing each board's first archive capture against
its oldest surviving posting:

| percentile | lag before the archive first saw the board |
|---|---|
| p25 | 20 days |
| **p50** | **48 days** |
| p75 | 110 days |
| p90 | 257 days |

The archive is actively crawling — 348 of the 3,617 boards were captured within the last
week, some the same day — but a brand-new customer typically waits about seven weeks to
become discoverable.

**Why the lag matters less than it looks.** A board only has to be discovered once; after
that every scrape reads live data from it. The lag is a one-time cost per company, not a
staleness tax on jobs, and it only applies to companies that adopted Ashby in the last
couple of months. For the other ~3,600 it is already paid.

Practically: re-run `--refresh-boards` monthly (about 80 seconds). Running it daily buys
nothing, because the archive will not have moved. If you need one specific new company
immediately, skip the archive entirely — add its slug to `boards.seed.json` and it is
permanent from the next run.

## Match modes

`--match fuzzy` (default) — either string contains the other, so it works in both
directions. A short query finds longer titles, and a long query still finds the short
title inside it:

| `--title` | matches |
|---|---|
| `software engineer` | Software Engineer, Senior Software Engineer, Backend, SOFTWARE ENGINEER II |
| `senior software engineer, backend` | Senior Software Engineer, Backend, **and** Software Engineer |

The reverse direction requires the title to be **at least two words**. Without that guard,
querying `senior software engineer` also matches every job titled just `Engineer`,
`Software`, or `Senior`. An empty `--title` matches nothing rather than everything.

`--match exact` — the whole title must equal the query (case- and whitespace-insensitive).
`software engineer` matches only `Software Engineer`.

## Searching descriptions with `--grep`

Titles are a weak filter — they miss "Software Development Engineer" and tell you nothing
about the stack. `--grep` runs a case-insensitive regex against the job description and
puts the surrounding context in a `matched` column, so a hit can be judged without
opening the posting.

```bash
uv run ashby_jobs.py --grep '\brust\b|\bgolang\b'          # description only
uv run ashby_jobs.py --title engineer --grep '\bkubernetes\b'  # both must match
```

`--title` and `--grep` are ANDed. Giving `--grep` alone drops the title filter entirely
rather than silently ANDing the default `software engineer` onto it.

**Use `\b`.** Without word boundaries a pattern matches inside longer words, and job
descriptions are full of boilerplate that will catch you:

| pattern | jobs matched (26 boards) |
|---|---|
| `rust\|golang` | **1350** — `rust` matches "t**rust**", which is in nearly every description |
| `\brust\b\|\bgolang\b` | **72** |

That is an 18x false-positive rate with no visible symptom, so the script warns on stderr
when a `--grep` pattern contains no `\b`.

Only matched fragments are kept, never whole descriptions — the gzip and memory
characteristics below are unchanged by `--grep`.

Against the shipped 26 boards, `software engineer` returns **268** jobs fuzzy and **2**
exact — pick accordingly.

## The database

Every run also upserts into `ashby-jobs.db` (SQLite, stdlib, no setup). The CSV is a
snapshot of one query; the database accumulates across runs and is what lets you ask
questions a snapshot can't answer.

Rows are keyed on the Ashby posting UUID, with `first_seen` preserved and `last_seen`
refreshed. Everything else is overwritten each run, since titles and locations do get
edited in place on live postings. The exception is `matched`: a later title-only run
won't blank out `--grep` context an earlier search found.

```bash
uv run ashby_jobs.py --title "software engineer"     # writes ashby-jobs.db
uv run ashby_jobs.py --db ~/jobs.db                  # somewhere else
uv run ashby_jobs.py --no-db                         # CSV/JSON only
```

The run summary reports `N new, M already seen`, so a scheduled scrape tells you what
changed without diffing anything.

```sql
-- postings that showed up in the last day
SELECT company, title, jobUrl FROM jobs
WHERE first_seen > datetime('now', '-1 day');

-- postings that have since disappeared (see the section below)
SELECT company, title, first_seen, closed_at FROM jobs
WHERE closed_at IS NOT NULL ORDER BY closed_at DESC;

-- who is hiring hardest
SELECT company, COUNT(*) n FROM jobs GROUP BY company ORDER BY n DESC LIMIT 10;

-- roles whose description mentioned your --grep term, with the context
SELECT company, title, matched FROM jobs WHERE matched != '';
```

### Detecting when a posting disappears

`last_seen` alone can't tell you a job is gone, because it only advances when a run's
filters happen to match. On a `--title` run, "filled last week" and "didn't match this
time" look identical.

So closing a posting is reserved for **unfiltered `--all` runs**, which are the only ones
that saw everything. After such a run, any posting on a scanned board that wasn't seen
gets a `closed_at` stamp; anything reposted has it cleared. Filtered runs never touch it,
and the closing is scoped to boards actually scanned, so `--limit` can't close jobs at
companies it skipped.

```
54581 jobs -> ... (54581 new, 0 already seen, 0 closed)
54578 jobs -> ... (0 new, 54578 already seen, 3 closed)
```

Schedule `--all` (daily or weekly) and the database becomes a real fill-rate signal:

```sql
-- how long postings stay open
SELECT AVG(julianday(closed_at) - julianday(first_seen)) AS avg_days_open
FROM jobs WHERE closed_at IS NOT NULL;

-- currently open roles only
SELECT company, title, jobUrl FROM jobs WHERE closed_at IS NULL;

-- companies filling roles fastest
SELECT company, COUNT(*) filled,
       ROUND(AVG(julianday(closed_at) - julianday(first_seen))) avg_days
FROM jobs WHERE closed_at IS NOT NULL
GROUP BY company HAVING filled >= 5 ORDER BY avg_days LIMIT 20;
```

Until you've run `--all` at least twice, `closed_at` is null everywhere — one sweep
establishes the baseline, the next detects what left.

## How it works

Ashby's public API is **per-company**, keyed by a board slug, with no global search
endpoint. So this is two phases.

**Phase 1 — discover slugs.** Query the **Wayback Machine's** CDX index for everything
archived under `jobs.ashbyhq.com`, take the first path segment of each URL as a candidate
slug, drop the ones that can't be slugs, then validate the rest against the posting API.
Cached to `boards.json` and skipped on later runs unless `--refresh-boards`.

A real run, end to end in about a minute:

```
191,117 archived URLs  ->  7,463 candidates  ->  5,000 plausible  ->  3,611 live boards
```

Three details make that work:

- **The Wayback Machine, not Common Crawl.** Common Crawl was the obvious index and it is
  the wrong default: narrower coverage (~3,400 estimated) and it sheds requests under load
  for hours at a time. The Internet Archive returned 191k URLs in 34 seconds. Common Crawl
  is still there as an automatic fallback.
- **A shape filter before validating.** Archived "path segments" include tracking blobs,
  compensation strings like `$10.2K`, and JS fragments. Filtering to plausible slugs cuts
  7,463 candidates to 5,000 probes.
- **HEAD, not GET.** A live board returns 200 with a zero-length body under HEAD, so
  validating 5,000 candidates costs nothing. GET would have downloaded ~220KB per live
  board — most of a gigabyte purely to learn which slugs are real.

**Phase 2 — fetch + filter.** Thread pool of 8 over the slugs. Keep jobs where `isListed`
is true and the title matches. Because Phase 1 already validated, a healthy run sees zero
404s; any that do appear get pruned from `boards.json` so the list self-corrects.

Full scrape of all 3,611 boards for `software engineer`: **4,375 jobs in 25 seconds.**

## Facts verified against live endpoints (2026-07-27)

| Fact | Note |
|---|---|
| `GET api.ashbyhq.com/posting-api/job-board/{slug}` | 200, no auth |
| Invalid slug | 404 — this is the validator |
| Slugs are case-insensitive and may contain spaces | `A1%20Garage%20Door%20Service` → 200 |
| `Accept-Encoding: gzip` | 1.73MB → 220KB, **8x**. Full run ≈130MB, not ≈1GB |
| `includeCompensation=true` omitted | removes the `compensation` field; saves ~no bytes |
| Descriptions are ~95% of the payload | read only for `--grep`, never accumulated |
| `HEAD` on the posting API | 200 with a 0-byte body, or 404 — free validation |
| Wayback CDX for `jobs.ashbyhq.com` | 191,117 URLs in 34s → **3,611 live boards** |
| Posting data | live, uncached — 946 jobs published the same day |
| Archive lag for a new board | median 48 days (p90 257) |
| Common Crawl CDX | 502/504 on essentially every request; see below |

## Why Common Crawl is only the fallback

Common Crawl is the usual answer to "give me every URL under a domain", and it was this
project's first implementation. It loses on both axes that matter.

**Reliability.** Over an afternoon it returned 502/504 on essentially every request, and
the failure is server-side, not anything you can fix:

- `url=example.com`, a trivially cheap exact lookup, 504s identically to an expensive
  wildcard — so it isn't query cost.
- Indexes that don't exist (`CC-MAIN-2026-18`) 504 the same way — so it isn't a bad query.
- `collinfo.json`, on the same host, returns 200 in 45ms — the static file server is fine;
  the index backend is what times out.

Their docs explain it: the index server handles several million requests/day and sheds
requests on **queue overflow**. Everyone hits this at the same odds.

**Coverage.** Its estimate was ~3,400 candidate slugs. The Wayback Machine yielded 3,611
*validated live* boards from a far larger URL set.

If you do fall through to it, the status codes differ in meaning. **502/504 = server
overloaded**, retry later, nothing you did. **503 = you are going too fast**; per their
docs a repeatedly-abusive IP can be blocked for 24 hours, so the script raises a distinct
error with that guidance rather than burning retries. CDX requests are throttled to
1/second, and `showNumPages` is avoided because it is the most expensive query they offer.

`boards.seed.json` (26 verified boards) is bundled regardless, so **Phase 1 is always
optional** and a fresh clone works without either index.

## For coding agents (LLMs)

If you have been pointed at this repository by a human, read this section first, then
[`openwiki/quickstart.md`](openwiki/quickstart.md).

**Orientation.** `README.md` is the user-facing narrative. `openwiki/` is the
engineer-facing map — [architecture](openwiki/architecture/overview.md),
[board discovery](openwiki/workflows/board-discovery.md),
[job scrape](openwiki/workflows/job-scrape.md),
[data model](openwiki/architecture/data-model.md),
[runbook](openwiki/operations/runbook.md), [testing](openwiki/testing.md).
The whole tool is one file, `ashby_jobs.py`, ~330 lines, zero dependencies.

**Before you run anything network-facing:**

```bash
export ASHBY_SCRAPER_CONTACT="the-user@example.com"   # ask; do not invent an address
uv run test_ashby_jobs.py                             # offline, no network, ~1s
```

The test suite is the fast feedback loop — it covers every filter, the SQLite lifecycle
and the archive-parsing paths without touching the network. Run it before and after any
change. A full `--refresh-boards --all` takes ~2 minutes and downloads ~130MB; do not
run it casually, and never in a loop.

**Things that look like bugs but are load-bearing.** Each is pinned by a test; if you
"fix" one, a test will fail and it is telling you the truth:

| Looks wrong | Why it is correct |
|---|---|
| Fuzzy match requires a ≥2-word title in the reverse direction | Without it, `--title "senior software engineer"` matches every job titled `Engineer` |
| Only `--all` runs set `closed_at` | A filtered run cannot distinguish "gone" from "did not match my filter" |
| Closing is scoped to boards actually scanned | Otherwise `--limit 10` would "close" postings at 3,600 unvisited companies |
| Validation uses `HEAD`, not `GET` | `GET` would download ~220KB per board — near a gigabyte per refresh |
| The User-Agent is stripped to ASCII | HTTP headers are latin-1; one em-dash made *every* request fail |
| `boards.json` is gitignored, `boards.seed.json` is committed | A full crawl is effectively Ashby's customer list and must not be published |

**Do not commit:** `boards.json`, `*.csv`, `*.json` outputs, `*.db`. `.gitignore` denies
these by default and allows only `boards.seed.json`. If you add an output format, add it
to `.gitignore` in the same change.

**Do not hand-edit `openwiki/`.** Those pages are generated. Change the source or the
README and let OpenWiki regenerate them (`openwiki --update`).

**Network etiquette is a requirement, not a style preference.** Concurrency is capped at
8, Common Crawl is throttled to its stated 1 request/second, and every request identifies
itself. Do not raise these to make something finish faster.

**If you are adding a search mode,** note that `--grep` patterns without `\b` are a
documented footgun (`rust` matches "t**rust**": 1350 hits vs 72). The script warns about
it. Keep that warning.

## Skipped, and when to add

- **Merging Wayback with Common Crawl** — the union would add slugs one index missed.
  Wayback alone already validates 3,611 boards, so this buys little for double the crawl.
- **Token title matching** — fuzzy still misses "Software Development Engineer", where
  the words are present but not contiguous. `--grep` covers most of this need already.
- **Per-board caching** — postings change daily; caching mostly serves staleness.
- **Rate-limit backoff for Ashby** — no 429s observed. Add on first sighting.

## Being a good citizen

This reads only Ashby's public, unauthenticated posting API — the same data any visitor
sees on a company's job board page. Requests are capped at 8 concurrent, Common Crawl is
throttled to their stated 1/second, and every request identifies itself via
`ASHBY_SCRAPER_CONTACT`. Please keep it that way if you fork.

## License

MIT — see [LICENSE](LICENSE).
