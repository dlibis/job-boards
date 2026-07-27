#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Pull job postings matching a title from Ashby's free public posting API.

No API key. Ashby's public API is per-company (keyed by a board slug) with no global
search, so this runs in two phases: discover slugs from Common Crawl, then fetch and
filter every board.

    uv run ashby_jobs.py --title "software engineer"
    uv run ashby_jobs.py --title "software engineer" --match exact
    uv run ashby_jobs.py --title "product designer" --remote --limit 200
    uv run ashby_jobs.py --refresh-boards

boards.json ships with the repo, so --refresh-boards is optional. Read the README
before running it — Common Crawl's index is frequently overloaded.

A full run scans ~3,400 boards and takes roughly 2-4 minutes / ~130MB downloaded.
"""

import argparse
import csv
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
# Two files on purpose. The seed is small, curated and committed, so a fresh clone
# works without touching Common Crawl. The cache is whatever the last crawl produced
# — potentially every Ashby customer — and is gitignored, so a full crawl never turns
# this repo into a published customer list.
BOARDS_SEED = HERE / "boards.seed.json"
BOARDS_CACHE = HERE / "boards.json"
POSTING_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
COLLINFO = "https://index.commoncrawl.org/collinfo.json"
# Common Crawl asks that clients identify themselves. Set ASHBY_SCRAPER_CONTACT to
# your own email so a server operator can reach *you* about *your* traffic.
#
# Must be ASCII: http.client encodes headers as latin-1, so a stray em-dash or an
# accented character here makes every single request raise before it leaves the
# process. Non-ASCII is stripped rather than allowed to break the run.
_CONTACT = os.environ.get("ASHBY_SCRAPER_CONTACT", "set ASHBY_SCRAPER_CONTACT")
UA = f"ashby-jobs-scraper/1.0 (public posting API; contact: {_CONTACT})".encode(
    "ascii", "ignore"
).decode()

FIELDS = [
    "company", "title", "department", "team", "employmentType",
    "location", "isRemote", "workplaceType", "publishedAt", "jobUrl",
]


class NotFound(Exception):
    """Board slug returned 404 — not an Ashby customer (or never was)."""


class RateLimited(Exception):
    """Common Crawl returned 503. Per their docs this means the request rate was
    too high; a repeatedly-abusive IP can be blocked for 24 hours."""


def fetch(url: str, timeout: int = 30, retries: int = 4) -> bytes:
    """GET a URL, transparently gunzipping. Raises NotFound on 404.

    Common Crawl's CDX index 502/504s under load often enough that a single
    attempt fails maybe half the time, so 5xx gets exponential backoff.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"}
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(url) from e
            if e.code == 503:
                raise RateLimited(url) from e
            if e.code < 500 or attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def slug_from_url(url: str) -> str | None:
    """First path segment of a jobs.ashbyhq.com URL, percent-decoded.

    Slugs may contain spaces, e.g. .../A1%20Garage%20Door%20Service/... -> that name.
    """
    path = urllib.parse.urlparse(url).path
    first = path.strip("/").split("/")[0]
    return urllib.parse.unquote(first) or None


def discover_boards(max_pages: int = 20) -> list[str]:
    """Crawl Common Crawl's CDX index for jobs.ashbyhq.com board slugs."""
    collections = json.loads(fetch(COLLINFO))
    cdx = collections[0]["cdx-api"]
    print(f"using index {collections[0]['id']}", file=sys.stderr)

    query = f"{cdx}?url=jobs.ashbyhq.com%2F*&output=json&fl=url"

    seen: dict[str, str] = {}  # lowercased slug -> first-seen casing
    # ponytail: walk pages until one comes back empty rather than asking
    # showNumPages first — that query is the most expensive one CDX offers and
    # times out far more often than the pages themselves.
    for page in range(max_pages):
        if page:
            time.sleep(1)  # Common Crawl asks for max 1 CDX request/second.
        try:
            body = fetch(f"{query}&page={page}", timeout=120, retries=6).decode()
        except NotFound:
            break
        if not body.strip():
            break
        # CDX responses are JSONL, not a JSON array.
        for line in body.splitlines():
            if not line.strip():
                continue
            slug = slug_from_url(json.loads(line)["url"])
            if slug:
                seen.setdefault(slug.lower(), slug)
        print(f"  page {page}: {len(seen)} slugs so far", file=sys.stderr)

    # ponytail: no denylist for junk paths (_next, api, ...) — Phase 2's 404 prunes
    # them, and that self-corrects as Ashby's customer list changes.
    return sorted(seen.values(), key=str.lower)


def load_boards(refresh: bool) -> list[str]:
    if not refresh:
        for path in (BOARDS_CACHE, BOARDS_SEED):
            if path.exists():
                boards = json.loads(path.read_text())
                print(f"{len(boards)} boards from {path.name}", file=sys.stderr)
                return boards
    try:
        boards = discover_boards()
    except RateLimited:
        sys.exit(
            "Common Crawl returned 503: request rate too high. Their docs say to slow "
            "down, and that a repeatedly-abusive IP can be blocked for 24 hours. Wait "
            "before retrying."
        )
    except (urllib.error.URLError, TimeoutError) as e:
        sys.exit(
            f"board discovery failed: {e}\n"
            "Common Crawl's CDX server is heavily loaded and sheds requests under "
            "queue overflow (nginx then returns 502/504). This is server-side and "
            "affects everyone — not your IP or your query. Retry later; the shipped "
            "boards.json means this phase is optional."
        )
    BOARDS_CACHE.write_text(json.dumps(boards, indent=2))
    print(f"cached {len(boards)} slugs -> {BOARDS_CACHE.name}", file=sys.stderr)
    return boards


def matches(job_title: str, wanted: str, mode: str = "fuzzy") -> bool:
    """Does a posting's title match what the user asked for? Case-insensitive.

    exact  — the whole title equals the query.
             "software engineer" matches "Software Engineer" only.
    fuzzy  — either string contains the other, so it works in both directions:
             a short query finds longer titles ("software engineer" ->
             "Senior Software Engineer, Backend") and a long query still finds
             the short title it contains ("senior software engineer, backend"
             -> "Software Engineer").

             The reverse direction requires the title to be at least two words.
             Without that, querying "senior software engineer" also matches jobs
             titled just "Engineer", "Software", or "Senior" — every one-word
             title that happens to appear in the query.
    """
    title, want = job_title.lower().strip(), wanted.lower().strip()
    if not title or not want:
        return False  # an empty query would otherwise match every job
    if mode == "exact":
        return title == want
    return want in title or (len(title.split()) >= 2 and title in want)


def scan_board(slug: str, wanted: str, remote_only: bool, mode: str) -> list[dict]:
    """Fetch one board, return flat rows for matching listed jobs.

    Descriptions are dropped at parse time and never retained — they are ~95% of
    the payload, and holding 3,400 boards' worth would be gigabytes.
    """
    data = json.loads(fetch(POSTING_API.format(slug=urllib.parse.quote(slug))))
    rows = []
    for job in data.get("jobs", []):
        if not job.get("isListed"):
            continue
        if not matches(job.get("title", ""), wanted, mode):
            continue
        if remote_only and not job.get("isRemote"):
            continue
        rows.append({
            "company": slug,
            **{f: job.get(f, "") for f in FIELDS[1:]},
        })
    return rows


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--title", default="software engineer", help="title to match")
    p.add_argument(
        "--match",
        choices=("fuzzy", "exact"),
        default="fuzzy",
        help="fuzzy: either string contains the other (default). exact: titles must be equal",
    )
    p.add_argument("--limit", type=int, help="max boards to scan (default: all)")
    p.add_argument("--remote", action="store_true", help="only remote postings")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--refresh-boards", action="store_true", help="re-crawl slug list")
    p.add_argument("--out", default="ashby-jobs", help="output filename prefix")
    args = p.parse_args()

    boards = load_boards(args.refresh_boards)
    scanned = boards[: args.limit] if args.limit else boards
    print(
        f"scanning {len(scanned)} boards for {args.title!r} ({args.match} match)...",
        file=sys.stderr,
    )

    rows: list[dict] = []
    dead: set[str] = set()
    errors = 0

    def work(slug: str) -> list[dict]:
        nonlocal errors
        for attempt in range(2):
            try:
                return scan_board(slug, args.title, args.remote, args.match)
            except NotFound:
                dead.add(slug)
                return []
            except Exception as e:
                if attempt:
                    errors += 1
                    print(f"  ! {slug}: {e}", file=sys.stderr)
        return []

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for i, found in enumerate(pool.map(work, scanned), 1):
            rows.extend(found)
            if i % 100 == 0 or i == len(scanned):
                print(
                    f"  {i}/{len(scanned)} boards | {len(dead)} 404 | "
                    f"{errors} err | {len(rows)} matches",
                    file=sys.stderr,
                )

    rows.sort(key=lambda r: (str(r["company"]).lower(), str(r["title"]).lower()))

    # BOM so Excel renders the en-dashes and bullets in location strings.
    csv_path = HERE / f"{args.out}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    json_path = HERE / f"{args.out}.json"
    json_path.write_text(json.dumps(rows, indent=2))

    # Self-prune: drop slugs that 404'd so later runs skip them.
    if dead and not args.limit:
        BOARDS_CACHE.write_text(json.dumps([b for b in boards if b not in dead], indent=2))

    print(f"\n{len(rows)} jobs -> {csv_path.name}, {json_path.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
