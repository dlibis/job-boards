---
type: Testing Guide
title: Ashby Jobs Testing Guide
description: Summarizes the offline self-check suite for ashbyhq-jobs, including parsing, matching, discovery, grep, SQLite lifecycle, output encoding, and environment requirements.
tags: [testing, regression, python]
---

# Testing guide

The test suite is `/test_ashby_jobs.py`, a dependency-free script meant to be run with `uv run test_ashby_jobs.py`. It validates the [job scrape workflow](workflows/job-scrape.md), [board discovery workflow](workflows/board-discovery.md), and [data model](architecture/data-model.md) without relying on live network calls.

## How to run

```bash
uv run test_ashby_jobs.py
```

Both the application and test scripts declare `requires-python = ">=3.11"` in their `uv` script headers and use modern type syntax. During this init run, the host had no `uv` and `python3` was 3.9.6; running `python3 test_ashby_jobs.py` failed during import on `str | None`. Use `uv` or a Python 3.11+ interpreter before judging test health.

## Coverage map

| Test area | Representative tests | Protected behavior |
|---|---|---|
| Slug parsing | `test_slug_parsing`, `test_cdx_jsonl_parsing` | First path segment extraction, percent-decoding spaces, JSONL handling, case-insensitive dedupe. |
| Title matching | `test_fuzzy_matching`, `test_fuzzy_does_not_match_generic_one_word_titles`, `test_exact_matching`, `test_empty_query_matches_nothing` | Fuzzy containment in both directions, one-word false-positive guard, exact matching, empty-query safety. |
| Board scanning | `test_scan_board_filters_and_flattens`, `test_no_filters_returns_every_listed_job`, `test_invalid_payload_raises_rather_than_returning_nothing` | Listed-only filtering, remote filtering, row shape, all-job mode, loud failure on API shape changes. |
| Description grep | `test_plain_text_strips_markup_and_entities`, `test_fragments_give_context_and_dedupe`, `test_grep_filters_on_description_and_records_context` | HTML stripping, context windows, dedupe, word-boundary false-positive behavior. |
| Discovery validation | `test_plausible_rejects_archive_noise_but_keeps_real_slugs`, `test_board_exists_uses_head_and_maps_404_to_false` | Shape filter, real slug preservation, `HEAD` validation, 404-to-false mapping. |
| SQLite history | `test_db_upsert_preserves_history`, `test_db_keeps_grep_context_from_earlier_runs`, `test_unfiltered_run_closes_vanished_postings`, `test_filtered_run_never_closes_anything`, `test_closing_is_scoped_to_boards_actually_scanned`, `test_db_skips_rows_without_an_id` | `first_seen` preservation, `last_seen` refresh, matched-context retention, closed-posting lifecycle, coverage scoping, id requirement. |
| Output and headers | `test_user_agent_is_header_safe`, `test_csv_quoting` | ASCII-safe user agent, CSV escaping, Unicode punctuation round trips. |

## Test style

Tests monkeypatch `ashby_jobs.fetch` directly for scan and validation scenarios rather than introducing a mocking dependency. SQLite behavior uses temporary directories and real `sqlite3` connections. This keeps the repository aligned with its no-dependency architecture.

## Change guidance

- For CLI filter changes, add tests that call `matches()` or `scan_board()` directly and include negative cases.
- For board discovery changes, keep archive fixtures offline and test the parsing/filtering boundaries rather than live services.
- For database changes, test both first insert and subsequent update behavior. Lifecycle changes should include filtered and unfiltered runs.
- For output changes, assert `FIELDS` and representative CSV/JSON behavior so downstream consumers are not surprised.

The [operations runbook](operations/runbook.md) should be updated whenever the required verification command or runtime environment changes.
