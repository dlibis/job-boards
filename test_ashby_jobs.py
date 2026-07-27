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
    test_user_agent_is_header_safe()
    test_csv_quoting()
    print("ok")
