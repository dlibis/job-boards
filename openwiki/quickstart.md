---
type: Guide
title: Ashby Jobs OpenWiki Quickstart
description: Entry point for the ashbyhq-jobs code wiki, covering the scraper's purpose, repository layout, primary workflows, operations, testing, and where engineers should start.
tags: [openwiki, quickstart, ashby-jobs]
---

# Ashby Jobs OpenWiki quickstart

This repository is a dependency-free Python CLI for pulling public job postings from Ashby-hosted job boards. Ashby's public posting API is unauthenticated but scoped to one company board slug at a time, so the tool first maintains a board-slug list and then fans out across those boards to produce CSV, JSON, and optional SQLite outputs. The README is the user-facing product narrative; this wiki is the engineer-facing map for changing and operating the code.

Start with the [architecture overview](architecture/overview.md) for the end-to-end runtime, then use the workflow pages when changing board discovery or scrape behavior.

## What the tool does

The main script, `/ashby_jobs.py`, supports these core use cases:

- Discover Ashby board slugs via Internet Archive CDX, with Common Crawl as fallback, then validate candidates by `HEAD`ing Ashby's posting API.
- Reuse `boards.json` when present, or the curated `/boards.seed.json` seed in a fresh clone.
- Scan boards concurrently, keeping only listed jobs that pass `--all`, `--title`, `--grep`, `--remote`, and match-mode filters.
- Write `ashby-jobs.csv`, `ashby-jobs.json`, and, unless `--no-db` is set, an accumulating SQLite database.
- Track posting appearance and disappearance across runs using `first_seen`, `last_seen`, and `closed_at`.

## First commands

The repository is designed to run through `uv` using script metadata in `/ashby_jobs.py` and `/test_ashby_jobs.py`; both declare Python `>=3.11` and no dependencies.

```bash
export ASHBY_SCRAPER_CONTACT="you@example.com"
uv run ashby_jobs.py --refresh-boards --all
uv run ashby_jobs.py --title "software engineer" --match exact
uv run ashby_jobs.py --grep '\brust\b|\bgolang\b'
uv run test_ashby_jobs.py
```

Set `ASHBY_SCRAPER_CONTACT` before real network runs so archive operators and API owners can identify the traffic source. The code strips non-ASCII characters from the fallback contact string because HTTP headers must be latin-1 safe.

## Documentation map

- [Architecture overview](architecture/overview.md) explains how `main()`, board loading, scraping, outputs, and persistence fit together.
- [Board discovery workflow](workflows/board-discovery.md) explains Wayback/Common Crawl candidate harvesting, slug filtering, `HEAD` validation, cache semantics, and why `boards.json` is ignored.
- [Job scrape workflow](workflows/job-scrape.md) explains CLI filters, title matching, description grep, remote filtering, concurrency, output writing, and failure handling.
- [Data model](architecture/data-model.md) documents output row fields, SQLite schema, upsert behavior, and posting lifecycle semantics.
- [Operations runbook](operations/runbook.md) covers scheduled usage, freshness expectations, privacy/git hygiene, rate-limit guidance, and the OpenWiki update workflow.
- [Testing guide](testing.md) summarizes the offline regression suite and verification caveats.
- [Source map](source-map.md) maps repository files to the concepts above.

## Recent evolution from git history

Recent commits show a progression from a simple public-board scraper into a more durable data collection tool:

- Initial implementation added the dependency-free CLI, seed boards, README, and offline tests.
- The committed board list was split into `/boards.seed.json` while generated `boards.json` became ignored output, preventing full crawls from publishing a customer list.
- `--grep` was added to search descriptions without retaining full descriptions in output rows.
- SQLite accumulation was added so repeated scrapes preserve `first_seen` and `last_seen`.
- Discovery moved to Wayback-first with `HEAD` validation because Common Crawl was less reliable and narrower.
- `--all` was added and board refreshes were changed to union archive results with seed and previous cache.
- The latest change tracks disappeared postings by stamping `closed_at` after unfiltered scans only.

## Change checklist for future agents

1. Read the page matching the area you are changing, then inspect the referenced source functions in `/ashby_jobs.py` and tests in `/test_ashby_jobs.py`.
2. Keep generated outputs (`*.csv`, `*.json`, `*.db`, `boards.json`) out of documentation examples except as outputs; `.gitignore` intentionally denies them.
3. Preserve the operational contract that public scraping is bounded, identifiable, and low-impact.
4. Run `uv run test_ashby_jobs.py` in an environment with Python 3.11+. If `uv` is unavailable, do not assume local `python3` is sufficient.
5. When changing data retention or lifecycle semantics, update the [data model](architecture/data-model.md), [operations runbook](operations/runbook.md), and tests together.

## Backlog

- Packaging and distribution: source anchor `/ashby_jobs.py` script metadata. Deferred because the repository currently presents itself as a single `uv run` script, not an installable package.
- Live endpoint measurements: source anchor `/README.md` facts table. Deferred because the wiki captures the current documented measurements but should not refresh external metrics during this init run.
