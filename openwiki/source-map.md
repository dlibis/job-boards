---
type: Source Map
title: Ashby Jobs Source Map
description: Maps the ashbyhq-jobs repository files, generated artifacts, tests, docs, automation, and OpenWiki pages to their engineering concepts.
tags: [source-map, navigation, repository]
---

# Source map

Use this page to jump from a repository file to the wiki concept that explains it. For behavior, prefer the concept pages over reading generated output artifacts. The [quickstart](quickstart.md) links all major pages, while this map is optimized for file navigation.

## Primary source files

| Path | Role | Wiki concept |
|---|---|---|
| `/ashby_jobs.py` | Single-file CLI and runtime: HTTP fetch, board discovery, matching, board scan, CSV/JSON writing, SQLite persistence. | [Architecture overview](architecture/overview.md), [job scrape workflow](workflows/job-scrape.md), [board discovery workflow](workflows/board-discovery.md), [data model](architecture/data-model.md) |
| `/test_ashby_jobs.py` | Dependency-free offline regression suite. | [Testing guide](testing.md) |
| `/README.md` | User-facing product documentation, measured completeness/freshness claims, operating guidance, and design rationale. | [Quickstart](quickstart.md), [operations runbook](operations/runbook.md) |
| `/boards.seed.json` | Small committed set of known-good board slugs for fresh clones and discovery preservation. | [Board discovery workflow](workflows/board-discovery.md) |
| `/.gitignore` | Prevents generated scrape outputs and caches from being committed while allowing `boards.seed.json`. | [Operations runbook](operations/runbook.md), [data model](architecture/data-model.md) |
| `/LICENSE` | MIT license. | [Quickstart](quickstart.md) |

## Generated and local artifacts

| Path pattern | Meaning | Handling |
|---|---|---|
| `/boards.json` | Generated board cache after refreshes. | Treat as local operational output and avoid committing. |
| `/*.csv` | Generated query snapshots. | Ignored by git; useful to users, not source evidence for code behavior. |
| `/*.json` except `/boards.seed.json` | Generated query snapshots or caches. | Ignored by git. |
| `/*.db` | SQLite scrape history. | Ignored by git; lifecycle semantics are documented in [data model](architecture/data-model.md). |
| `/__pycache__/` | Python bytecode cache. | Ignored. |

The working tree observed during this init run included generated output files such as `ashby-jobs.csv`, `ashby-jobs.json`, `ashby-jobs.db`, and shorter-named snapshots. They demonstrate expected artifact names but should not be treated as canonical source.

## Automation and agent files

| Path | Role | Notes |
|---|---|---|
| `/.github/workflows/openwiki-update.yml` | Scheduled/manual OpenWiki update workflow. | Currently untracked in the provided git status; see [operations](operations/runbook.md). |
| `/AGENTS.md` | Agent-facing pointer to OpenWiki docs. | Do not rewrite during normal wiki updates. |
| `/CLAUDE.md` | Claude-facing pointer to OpenWiki docs. | Do not rewrite during normal wiki updates. |
| `/openwiki/INSTRUCTIONS.md` | User-authored OpenWiki brief for this repository. | Control metadata, not generated documentation. |
| `/openwiki/quickstart.md` and linked pages | Generated code wiki. | Update through OpenWiki runs and keep links/source references accurate. |

## Function-level landmarks in `/ashby_jobs.py`

| Function or symbol | Why it matters |
|---|---|
| `POSTING_API`, `COLLINFO`, `WAYBACK_CDX` | External integration points. |
| `fetch()` | Shared HTTP behavior, retries, gzip, status-to-exception mapping, and user agent. |
| `slug_from_url()`, `_add()`, `plausible()` | Archive URL to slug candidate pipeline. |
| `candidates_from_wayback()`, `candidates_from_commoncrawl()` | Discovery integrations. |
| `board_exists()`, `discover_boards()`, `load_boards()` | Board validation, union-with-known behavior, and cache loading. |
| `matches()`, `plain_text()`, `fragments()`, `scan_board()` | Filtering and row construction. |
| `_SCHEMA`, `save()` | SQLite persistence, migration, and lifecycle rules. |
| `main()` | CLI contract and orchestration. |

## Git-history landmarks

Recent history is especially useful when reviewing changes:

- Discovery moved from a Common Crawl-centered approach to Wayback-first plus `HEAD` validation.
- Board cache handling changed so generated discovery output is local while `boards.seed.json` remains committed.
- Description search was added through `--grep` with fragment retention rather than whole-description storage.
- SQLite persistence grew from upsert history into disappearance tracking with `closed_at`.

These history landmarks explain cross-page relationships: [board discovery](workflows/board-discovery.md) supplies coverage, [job scraping](workflows/job-scrape.md) emits filtered rows, and the [data model](architecture/data-model.md) decides when missing rows can become closed postings.
