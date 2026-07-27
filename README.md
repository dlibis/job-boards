# ashbyhq-jobs

Pull job postings matching a title from Ashby's free public posting API. No API key,
no account, no dependencies.

Ashby's public API is per-company with no global search endpoint, so this discovers
company board slugs from Common Crawl, then fans out across them.

Only prerequisite is [uv](https://docs.astral.sh/uv/) — no `pip install`, no venv, no
dependencies. `uv` fetches its own Python.

Set your own contact address first. Common Crawl asks clients to identify themselves, and
this puts *your* address on *your* traffic:

```bash
export ASHBY_SCRAPER_CONTACT="you@example.com"
```

```bash
uv run ashby_jobs.py --all                                 # every job, ~54,000
uv run ashby_jobs.py --title "software engineer"
uv run ashby_jobs.py --title "software engineer" --match exact
uv run ashby_jobs.py --title "product designer" --remote --limit 200
uv run ashby_jobs.py --refresh-boards      # re-crawl the slug list
uv run test_ashby_jobs.py                  # offline self-check
```

Outputs `ashby-jobs.csv` (UTF-8 BOM, so Excel renders `–`/`•`) and `ashby-jobs.json`.

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
- **New Ashby customers** appear before the archive notices them. Re-run
  `--refresh-boards` periodically; it takes about a minute.
- **The shape filter** drops candidates that cannot be slugs. Sampling 150 of the 2,463 it
  rejected turned up zero real boards, so this looks safe, but it is a sample.

If you find a board this misses, add it to `boards.seed.json` and it is permanent.

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

-- gone: last seen more than a week ago, so probably filled or pulled
SELECT company, title, last_seen FROM jobs
WHERE last_seen < datetime('now', '-7 days') ORDER BY last_seen;

-- who is hiring hardest
SELECT company, COUNT(*) n FROM jobs GROUP BY company ORDER BY n DESC LIMIT 10;

-- roles whose description mentioned your --grep term, with the context
SELECT company, title, matched FROM jobs WHERE matched != '';
```

One caveat on `last_seen`: it only advances when a run's filters actually match the
posting. A row going stale means "no recent run matched it", which is not quite the same
as "the job is gone" — compare like-for-like queries if you care about the difference.

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
