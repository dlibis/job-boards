#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Offline self-check for the parsing logic. Run: uv run test_ashby_jobs.py"""

import csv
import io

from ashby_jobs import FIELDS, matches, slug_from_url


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
    test_csv_quoting()
    print("ok")
