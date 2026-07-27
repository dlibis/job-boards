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
uv run ashby_jobs.py --title "software engineer"
uv run ashby_jobs.py --title "software engineer" --match exact
uv run ashby_jobs.py --title "product designer" --remote --limit 200
uv run ashby_jobs.py --refresh-boards      # re-crawl the slug list
uv run test_ashby_jobs.py                  # offline self-check
```

Outputs `ashby-jobs.csv` (UTF-8 BOM, so Excel renders `–`/`•`) and `ashby-jobs.json`.

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

Against the shipped 26 boards, `software engineer` returns **268** jobs fuzzy and **2**
exact — pick accordingly.

## How it works

Ashby's public API is **per-company**, keyed by a board slug, with no global search
endpoint. So this is two phases.

**Phase 1 — discover slugs.** Query Common Crawl's CDX index for `jobs.ashbyhq.com/*`,
take the first path segment of each URL as a slug, dedupe case-insensitively, cache to
`boards.json`. Skipped entirely on later runs unless `--refresh-boards`.

**Phase 2 — fetch + filter.** Thread pool of 8 over the slugs. Keep jobs where
`isListed` is true and the title matches. 404 means the slug isn't an Ashby customer —
it gets dropped and pruned from `boards.json`, so the list self-corrects and no
denylist is needed.

## Facts verified against live endpoints (2026-07-27)

| Fact | Note |
|---|---|
| `GET api.ashbyhq.com/posting-api/job-board/{slug}` | 200, no auth |
| Invalid slug | 404 — this is the validator |
| Slugs are case-insensitive and may contain spaces | `A1%20Garage%20Door%20Service` → 200 |
| `Accept-Encoding: gzip` | 1.73MB → 220KB, **8x**. Full run ≈130MB, not ≈1GB |
| `includeCompensation=true` omitted | removes the `compensation` field; saves ~no bytes |
| Descriptions are ~95% of the payload | dropped at parse time, never accumulated |
| Common Crawl CDX 502/504s intermittently | see below |

## Known issue: Common Crawl reliability (read before `--refresh-boards`)

CDX is the only free bulk source of Ashby slugs, and it is unreliable. As of 2026-07-27
it returns 504 on every request. **This is server-side load, not your IP and not the
query** — three things establish that:

- `url=example.com`, a trivially cheap exact lookup, 504s identically to the expensive
  wildcard. So it isn't query cost.
- Indexes that don't exist (`CC-MAIN-2026-18`) 504 the same way. So it isn't a bad query.
- `collinfo.json`, served from the same host, returns 200 in 45ms. The static file server
  is fine; the index backend is what's timing out.

Common Crawl's own docs explain the mechanism: the index server handles several million
requests/day, and requests fail on **queue overflow** — nginx then returns 502/504.
Anyone running this will hit the same thing at the same odds; it succeeded once and
failed a dozen times over one afternoon. It is not a permanent outage.

Note the difference between status codes. **504/502 = server overloaded**, retry later,
nothing you did. **503 = you are going too fast**; per CC's docs a repeatedly-abusive IP
can be blocked for 24 hours. The script raises a distinct error with that guidance rather
than burning retries.

Mitigations in place:
- `boards.json` is included, so **Phase 1 is optional** — a new user can run the scraper
  immediately and never touch Common Crawl. Keep this file when copying the project.
- `showNumPages` is not used — it is the most expensive CDX query and times out far more
  often than the pages themselves. Pages are walked until one comes back empty.
- CDX requests are throttled to 1/second per CC's stated limit, with 6 retries and
  exponential backoff on 5xx.

The shipped `boards.json` was seeded by probing 37 candidate company names and keeping
the 26 that returned 200 (openai 752 jobs, zip 131, cursor 122, ramp 119, vanta 103, ...).
Run `--refresh-boards` once CDX recovers to expand to the full ~3,400 boards.

## Skipped, and when to add

- **Multiple CC indexes merged** — one index is plenty. Add if coverage looks thin.
- **Token/regex title matching** — fuzzy still misses "Software Development Engineer",
  where the words are present but not contiguous. Add `--match tokens` if that gap bites.
- **Per-board caching** — postings change daily; caching mostly serves staleness.
- **Rate-limit backoff for Ashby** — no 429s observed. Add on first sighting.

## Being a good citizen

This reads only Ashby's public, unauthenticated posting API — the same data any visitor
sees on a company's job board page. Requests are capped at 8 concurrent, Common Crawl is
throttled to their stated 1/second, and every request identifies itself via
`ASHBY_SCRAPER_CONTACT`. Please keep it that way if you fork.

## License

MIT — see [LICENSE](LICENSE).
