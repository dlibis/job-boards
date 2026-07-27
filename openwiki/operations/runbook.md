---
type: Runbook
title: Ashby Jobs Operations Runbook
description: Practical operating notes for running the Ashby jobs scraper safely, managing generated outputs, handling archive/API failures, and maintaining OpenWiki automation.
tags: [operations, runbook, scraping, automation]
---

# Operations runbook

This runbook connects safe operation of the scraper to the [architecture overview](../architecture/overview.md), [board discovery workflow](../workflows/board-discovery.md), [job scrape workflow](../workflows/job-scrape.md), [data model](../architecture/data-model.md), and [testing guide](../testing.md).

## Good-citizen scraping

Before network runs, set `ASHBY_SCRAPER_CONTACT`:

```bash
export ASHBY_SCRAPER_CONTACT="you@example.com"
```

`/ashby_jobs.py` includes the value in the `User-Agent` for both archive discovery and Ashby API calls. The code defaults to a safe ASCII fallback and strips non-ASCII characters so a missing or unusual contact value does not break all requests.

Keep concurrency modest. The script defaults to 8 workers for Ashby API calls and board validation. Common Crawl paging is sequentially throttled to one request per second in the fallback path.

## Routine runs

Use these patterns from the README and source:

```bash
# Fresh full scrape and board refresh.
uv run ashby_jobs.py --refresh-boards --all

# Later full scrape using cached boards.
uv run ashby_jobs.py --all

# Targeted title or stack searches.
uv run ashby_jobs.py --title "software engineer"
uv run ashby_jobs.py --grep '\brust\b|\bgolang\b'

# Offline regression suite.
uv run test_ashby_jobs.py
python3 test_ashby_jobs.py  # fallback when uv is unavailable and Python is 3.9+
```

The README recommends monthly board refreshes because board discovery depends on archive coverage and has measured lag. Jobs themselves are live on every scrape because the scan phase reads Ashby's posting API directly.

## Persistence and scheduling

Schedule unfiltered `--all` runs if you want the SQLite database to become a fill-rate or disappearance signal. The [data model](../architecture/data-model.md) only stamps `closed_at` after an unfiltered run has covered a board and omitted a previously seen posting. Filtered searches update matching postings but cannot prove that non-matching postings disappeared.

Useful database questions from the README include new postings in the last day, currently open roles (`closed_at IS NULL`), recently closed roles, and companies filling roles quickly.

## Generated output hygiene

`.gitignore` intentionally ignores:

- `*.csv`
- `*.json`, except `/boards.seed.json`
- `*.db` and `*.db-journal`
- Python caches

This is more than cleanup. A full generated `boards.json` is effectively a discovered Ashby customer list, so it should stay local. Generated scrape outputs in the working tree are operational artifacts, not source evidence for code changes.

## Failure modes and responses

| Symptom | Likely cause | Response |
|---|---|---|
| `Common Crawl returned 503` | Common Crawl is rate-limiting or protecting itself from client pressure. | Wait before retrying; do not increase request rate. |
| Common Crawl 502 or 504 | Common Crawl index backend overloaded. | Retry later; Wayback is the preferred default. |
| Board discovery fails entirely | Wayback and Common Crawl unreachable. | Use the committed seed or existing cache; discovery is optional for a fresh clone. |
| Many board scan errors | Ashby API shape or network behavior may have changed. | Inspect stderr, run tests, and verify `scan_board()` still sees a `jobs` array. |
| `uv` is missing from `PATH` | Minimal local or agent environment. | Run `python3 test_ashby_jobs.py`; the source keeps the offline suite working on Python 3.9+. |

## OpenWiki automation

The repository includes `.github/workflows/openwiki-update.yml` for recurring wiki maintenance. It is manual-only until the repository has an `OPENROUTER_API_KEY` secret; the generated daily schedule is intentionally commented out so missing credentials do not fail every morning. The workflow checks out the repository, sets up Node.js, installs `uv`, installs `openwiki@0.2.3` plus Mermaid validation packages, runs `openwiki code --update --print`, and opens a pull request containing `openwiki`, `AGENTS.md`, `CLAUDE.md`, and the workflow file.

Actions in the workflow are pinned to commit SHAs, including `astral-sh/setup-uv`, because the job has `contents: write` and `pull-requests: write`. Root `AGENTS.md` and `CLAUDE.md` both direct future agents to start with `openwiki/quickstart.md` and document the same no-uv test fallback as the [testing guide](../testing.md). Treat `/openwiki/INSTRUCTIONS.md` as user-authored scope metadata and do not rewrite it during routine updates.

## Change guidance

If you change external-service behavior, update [board discovery](../workflows/board-discovery.md) or [job scraping](../workflows/job-scrape.md) with rate-limit and error-handling implications. If you change persistence or scheduling semantics, update the [data model](../architecture/data-model.md) and tests together.
