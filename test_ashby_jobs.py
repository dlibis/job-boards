#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Offline self-check for the parsing logic. Run: uv run test_ashby_jobs.py"""

import csv
import io
import json

from ashby_jobs import FIELDS, matches, scan_board, slug_from_url


def test_slug_parsing():
    assert slug_from_url("https://jobs.ashbyhq.com/0g/4fc6ba8a-1111?ref=x") == "0g"
    assert (
        slug_from_url("https://jobs.ashbyhq.com/A1%20Garage%20Door%20Service/x")
        == "A1 Garage Door Service"
    )
    assert slug_from_url("https://jobs.ashbyhq.com/") is None


def test_fuzzy_matching():
    # short query finds longer titles
    assert matches("Senior Software Engineer, Backend", "software engineer")
    assert matches("SOFTWARE ENGINEER II", "software engineer")
    # and the reverse: a long query still finds the short title inside it
    assert matches("Software Engineer", "senior software engineer, backend")
    assert not matches("Engineering Manager", "software engineer")


def test_fuzzy_does_not_match_generic_one_word_titles():
    """The reverse direction must not drag in every one-word title in the query."""
    for junk in ("Engineer", "Software", "Senior"):
        assert not matches(junk, "senior software engineer"), junk
    assert matches("Software Engineer", "senior software engineer")


def test_empty_query_matches_nothing():
    assert not matches("Chef", "")
    assert not matches("", "software engineer")


def test_exact_matching():
    assert matches("Software Engineer", "software engineer", "exact")
    assert matches("  SOFTWARE ENGINEER  ", "software engineer", "exact")
    assert not matches("Senior Software Engineer, Backend", "software engineer", "exact")
    assert not matches("Software Engineer", "senior software engineer", "exact")


def test_cdx_jsonl_parsing():
    """Common Crawl returns JSONL, not a JSON array, and mixes in junk paths.

    Covered by fixture because the live CDX index is frequently down — see README.
    """
    payload = "\n".join([
        '{"url": "https://jobs.ashbyhq.com/ramp/abc-123?ref=x"}',
        '{"url": "https://jobs.ashbyhq.com/Ramp/def-456"}',       # dupe, other casing
        '{"url": "https://jobs.ashbyhq.com/A1%20Garage%20Door/x"}',  # spaces in slug
        "",                                                        # blank line
        '{"url": "https://jobs.ashbyhq.com/_next/static/z.js"}',   # junk, 404s later
        '{"url": "https://jobs.ashbyhq.com/"}',                    # no slug at all
    ])
    seen = {}
    for line in payload.splitlines():
        if not line.strip():
            continue
        slug = slug_from_url(json.loads(line)["url"])
        if slug:
            seen.setdefault(slug.lower(), slug)
    assert sorted(seen.values()) == ["A1 Garage Door", "_next", "ramp"]
    assert seen["ramp"] == "ramp"  # first-seen casing wins over "Ramp"


def test_scan_board_filters_and_flattens(monkeypatched_fetch=None):
    """isListed/remote filtering, and that descriptions never reach the output."""
    board = {"jobs": [
        {"title": "Software Engineer", "isListed": True, "isRemote": True,
         "location": "Remote", "descriptionHtml": "<p>huge</p>",
         "descriptionPlain": "huge", "jobUrl": "u1"},
        {"title": "Software Engineer", "isListed": False, "isRemote": True},  # unlisted
        {"title": "Chef", "isListed": True, "isRemote": True},                # no match
        {"title": "Software Engineer II", "isListed": True, "isRemote": False},  # onsite
    ]}
    import ashby_jobs
    original = ashby_jobs.fetch
    ashby_jobs.fetch = lambda *a, **k: json.dumps(board).encode()
    try:
        rows = scan_board("acme", "software engineer", False, "fuzzy")
        remote = scan_board("acme", "software engineer", True, "fuzzy")
    finally:
        ashby_jobs.fetch = original

    assert [r["title"] for r in rows] == ["Software Engineer", "Software Engineer II"]
    assert [r["title"] for r in remote] == ["Software Engineer"]
    assert rows[0]["company"] == "acme"
    assert set(rows[0]) == set(FIELDS), "row must be exactly the declared columns"
    assert not any("escription" in k for k in rows[0]), "descriptions must be dropped"


def test_plain_text_strips_markup_and_entities():
    from ashby_jobs import plain_text
    assert plain_text("<p>Rust &amp; Go</p>\n\n  <b>here</b>") == "Rust & Go here"
    assert plain_text("") == ""


def test_fragments_give_context_and_dedupe():
    import re
    from ashby_jobs import fragments
    text = "we use kubernetes daily. " * 3 + "the end"
    hits = fragments(text, re.compile("kubernetes", re.IGNORECASE))
    assert len(hits) <= 2
    assert all("kubernetes" in h for h in hits)
    # identical windows collapse rather than repeating
    assert len(set(hits)) == len(hits)
    assert fragments("nothing here", re.compile("kubernetes")) == []


def test_grep_filters_on_description_and_records_context():
    import re
    import ashby_jobs
    board = {"jobs": [
        {"title": "Backend Engineer", "isListed": True,
         "descriptionPlain": "You will write <b>Rust</b> and Go all day."},
        {"title": "Backend Engineer", "isListed": True,
         "descriptionPlain": "We deeply value trust and integrity."},  # 'rust' in 'trust'
    ]}
    original = ashby_jobs.fetch
    ashby_jobs.fetch = lambda *a, **k: json.dumps(board).encode()
    try:
        loose = scan_board("acme", None, False, "fuzzy", re.compile("rust", re.I))
        strict = scan_board("acme", None, False, "fuzzy", re.compile(r"\brust\b", re.I))
    finally:
        ashby_jobs.fetch = original

    assert len(loose) == 2, "unbounded 'rust' also matches 'trust' — the documented footgun"
    assert len(strict) == 1, "word-bounded regex excludes 'trust'"
    assert "Rust" in strict[0]["matched"]
    assert "<b>" not in strict[0]["matched"], "markup must be stripped from fragments"


def test_invalid_payload_raises_rather_than_returning_nothing():
    import ashby_jobs
    original = ashby_jobs.fetch
    ashby_jobs.fetch = lambda *a, **k: b'{"error": "nope"}'
    try:
        raised = False
        try:
            scan_board("acme", "engineer", False, "fuzzy")
        except ValueError:
            raised = True
    finally:
        ashby_jobs.fetch = original
    assert raised, "a shape change must fail loudly, not read as 'no jobs found'"


def test_no_filters_returns_every_listed_job():
    """--all mode: no title, no grep. Unlisted jobs are still excluded."""
    import ashby_jobs
    board = {"jobs": [
        {"title": "Chef", "isListed": True},
        {"title": "Welder", "isListed": True},
        {"title": "Secret Role", "isListed": False},
    ]}
    original = ashby_jobs.fetch
    ashby_jobs.fetch = lambda *a, **k: json.dumps(board).encode()
    try:
        rows = scan_board("acme", None, False, "fuzzy", None)
    finally:
        ashby_jobs.fetch = original
    assert [r["title"] for r in rows] == ["Chef", "Welder"]


def test_plausible_rejects_archive_noise_but_keeps_real_slugs():
    """The archive yields 191k URLs; the shape filter is what makes validation cheap."""
    from ashby_jobs import plausible

    for good in ("ramp", "keeling-labs", "A1 Garage Door Service", "ScribdInc", "0g"):
        assert plausible(good), good
    for junk in (
        "_next", "api", "favicon.ico",                       # site plumbing
        "root.6511f3ee_758c_4ed4_8fce_254a11715ed7",         # Ashby embed path
        "4fc6ba8a-532f-46a7-b1f3-d5490d78120e",              # a posting id, not a board
        "$10.2K", '"80e0bf43", "environment":"production"',  # comp strings, JS blobs
        "블록웍스", "", "-" * 80,
    ):
        assert not plausible(junk), junk


def test_board_exists_uses_head_and_maps_404_to_false():
    """Validation must not download board payloads — 5,000 GETs would be ~1GB."""
    import ashby_jobs

    calls = []

    def fake_fetch(url, timeout=30, retries=4, method="GET"):
        calls.append(method)
        if "nope" in url:
            raise ashby_jobs.NotFound(url)
        return b""

    original = ashby_jobs.fetch
    ashby_jobs.fetch = fake_fetch
    try:
        assert ashby_jobs.board_exists("ramp") is True
        assert ashby_jobs.board_exists("nope12345") is False
    finally:
        ashby_jobs.fetch = original
    assert calls == ["HEAD", "HEAD"], f"expected HEAD probes, got {calls}"


def test_db_upsert_preserves_history():
    """first_seen must survive re-scrapes; that is the point of the database."""
    import sqlite3
    import tempfile
    from pathlib import Path
    from ashby_jobs import save

    row = {f: "" for f in FIELDS} | {"id": "job-1", "company": "acme", "title": "SWE"}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "t.db"

        new, updated, _ = save([row], db, "2026-01-01T00:00:00+00:00")
        assert (new, updated) == (1, 0)

        # same posting, later scrape, title edited in place upstream
        new, updated, _ = save([row | {"title": "Senior SWE"}], db, "2026-02-02T00:00:00+00:00")
        assert (new, updated) == (0, 1)

        got = sqlite3.connect(db).execute(
            "SELECT title, first_seen, last_seen FROM jobs"
        ).fetchall()
        assert got == [("Senior SWE", "2026-01-01T00:00:00+00:00", "2026-02-02T00:00:00+00:00")]


def test_db_keeps_grep_context_from_earlier_runs():
    """A later title-only run must not blank out fragments a --grep run found."""
    import sqlite3
    import tempfile
    from pathlib import Path
    from ashby_jobs import save

    row = {f: "" for f in FIELDS} | {"id": "job-1", "company": "acme"}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "t.db"
        save([row | {"matched": "uses Rust daily"}], db, "2026-01-01T00:00:00+00:00")
        save([row], db, "2026-02-02T00:00:00+00:00")  # no --grep this time
        (kept,) = sqlite3.connect(db).execute("SELECT matched FROM jobs").fetchone()
        assert kept == "uses Rust daily"


def test_migrates_a_database_created_before_closed_at():
    """Upgrade path. Every other db test starts from a fresh schema, so none of
    them exercise a database that predates the closed_at column."""
    import sqlite3
    import tempfile
    from pathlib import Path
    from ashby_jobs import FIELDS as F, save

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "old.db"
        # exactly the old schema: no closed_at, no closed_at index
        cols = ",".join(f"{c} TEXT" for c in F if c != "id")
        con = sqlite3.connect(db)
        con.executescript(f"""
            CREATE TABLE jobs (id TEXT PRIMARY KEY, {cols},
                               first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
            CREATE INDEX jobs_company ON jobs(company);
            CREATE INDEX jobs_last_seen ON jobs(last_seen);
        """)
        con.execute(
            "INSERT INTO jobs (id, company, first_seen, last_seen) VALUES "
            "('old-1','acme','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')"
        )
        con.commit()
        con.close()

        row = {f: "" for f in F} | {"id": "new-1", "company": "acme"}
        new, updated, closed = save([row], db, "2026-02-02T00:00:00+00:00", covered=["acme"])

        con = sqlite3.connect(db)
        assert "closed_at" in {c[1] for c in con.execute("PRAGMA table_info(jobs)")}
        # the pre-existing row survives the migration and is closed by this sweep
        got = dict(con.execute("SELECT id, closed_at FROM jobs"))
        assert got["old-1"] == "2026-02-02T00:00:00+00:00"
        assert got["new-1"] is None
        assert (new, updated, closed) == (1, 0, 1)
        # and the index that previously broke the migration now exists
        idx = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        assert "jobs_closed_at" in idx


def test_unfiltered_run_closes_vanished_postings():
    import sqlite3
    import tempfile
    from pathlib import Path
    from ashby_jobs import save

    base = {f: "" for f in FIELDS}
    a = base | {"id": "a", "company": "acme"}
    b = base | {"id": "b", "company": "acme"}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "t.db"
        save([a, b], db, "2026-01-01T00:00:00+00:00", covered=["acme"])

        # b is gone from acme's board on the next full sweep
        _, _, closed = save([a], db, "2026-02-02T00:00:00+00:00", covered=["acme"])
        assert closed == 1
        got = dict(sqlite3.connect(db).execute("SELECT id, closed_at FROM jobs"))
        assert got["a"] is None
        assert got["b"] == "2026-02-02T00:00:00+00:00"

        # b is reposted: it must reopen, not stay closed
        _, _, closed = save([a, b], db, "2026-03-03T00:00:00+00:00", covered=["acme"])
        assert closed == 0
        got = dict(sqlite3.connect(db).execute("SELECT id, closed_at FROM jobs"))
        assert got["b"] is None, "a reappearing posting must reopen"


def test_filtered_run_never_closes_anything():
    """A --title run missing a job is ambiguous: gone, or just not matched."""
    import sqlite3
    import tempfile
    from pathlib import Path
    from ashby_jobs import save

    base = {f: "" for f in FIELDS}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "t.db"
        save([base | {"id": "a", "company": "acme"}, base | {"id": "b", "company": "acme"}],
             db, "2026-01-01T00:00:00+00:00", covered=["acme"])
        # filtered run: only 'a' matched. 'b' must NOT be closed.
        _, _, closed = save([base | {"id": "a", "company": "acme"}],
                            db, "2026-02-02T00:00:00+00:00", covered=None)
        assert closed == 0
        (open_rows,) = sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL").fetchone()
        assert open_rows == 2


def test_closing_is_scoped_to_boards_actually_scanned():
    """A --limit run must not close postings on boards it never visited."""
    import sqlite3
    import tempfile
    from pathlib import Path
    from ashby_jobs import save

    base = {f: "" for f in FIELDS}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "t.db"
        save([base | {"id": "a", "company": "acme"}, base | {"id": "z", "company": "other"}],
             db, "2026-01-01T00:00:00+00:00", covered=["acme", "other"])
        # this run only covered acme, and saw nothing there
        _, _, closed = save([], db, "2026-02-02T00:00:00+00:00", covered=["acme"])
        assert closed == 1
        got = dict(sqlite3.connect(db).execute("SELECT id, closed_at FROM jobs"))
        assert got["a"] is not None
        assert got["z"] is None, "a board that was not scanned must be left alone"


def test_db_skips_rows_without_an_id():
    import tempfile
    from pathlib import Path
    from ashby_jobs import save

    with tempfile.TemporaryDirectory() as tmp:
        assert save([{f: "" for f in FIELDS}], Path(tmp) / "t.db", "2026-01-01T00:00:00+00:00") == (0, 0, 0)


def test_user_agent_is_header_safe():
    """http.client encodes headers as latin-1; non-ASCII here breaks every request.

    Regression: an em-dash in the unset-contact fallback made a fresh clone fail
    100% of requests before any network call.
    """
    import ashby_jobs
    ashby_jobs.UA.encode("latin-1")  # raises if the UA is not header-safe
    assert ashby_jobs.UA.isascii()


def test_csv_quoting():
    """stdlib csv handles RFC4180 escaping — this pins that it stays correct."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    w.writerow({f: "" for f in FIELDS} | {
        "company": "acme",
        "title": 'Senior Software Engineer, Backend "Core"',
        "location": "Remote – US • EU",
    })
    row = list(csv.DictReader(io.StringIO(buf.getvalue())))[0]
    assert row["title"] == 'Senior Software Engineer, Backend "Core"'
    assert row["location"] == "Remote – US • EU"


if __name__ == "__main__":
    test_slug_parsing()
    test_fuzzy_matching()
    test_fuzzy_does_not_match_generic_one_word_titles()
    test_empty_query_matches_nothing()
    test_exact_matching()
    test_cdx_jsonl_parsing()
    test_scan_board_filters_and_flattens()
    test_plain_text_strips_markup_and_entities()
    test_fragments_give_context_and_dedupe()
    test_grep_filters_on_description_and_records_context()
    test_invalid_payload_raises_rather_than_returning_nothing()
    test_no_filters_returns_every_listed_job()
    test_plausible_rejects_archive_noise_but_keeps_real_slugs()
    test_board_exists_uses_head_and_maps_404_to_false()
    test_db_upsert_preserves_history()
    test_db_keeps_grep_context_from_earlier_runs()
    test_migrates_a_database_created_before_closed_at()
    test_unfiltered_run_closes_vanished_postings()
    test_filtered_run_never_closes_anything()
    test_closing_is_scoped_to_boards_actually_scanned()
    test_db_skips_rows_without_an_id()
    test_user_agent_is_header_safe()
    test_csv_quoting()
    print("ok")
