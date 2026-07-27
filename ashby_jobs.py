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
    uv run ashby_jobs.py --grep "rust|golang"                  # search descriptions
    uv run ashby_jobs.py --title engineer --grep "kubernetes"  # both must match
    uv run ashby_jobs.py --refresh-boards

Results go to CSV and JSON, and are also accumulated into a SQLite database keyed on
the Ashby posting id, so first_seen/last_seen survive across scrapes. See the README.

boards.json ships with the repo, so --refresh-boards is optional. Read the README
before running it — Common Crawl's index is frequently overloaded.

A full run scans ~3,400 boards and takes roughly 2-4 minutes / ~130MB downloaded.
"""

# Keeps `X | None` annotations from being evaluated at import, so the file also
# imports under Python 3.9 — which is what a bare `python3` is on macOS, and what
# tooling gets when uv is not on its PATH. uv still provisions 3.11 per the
# metadata above; this only makes the no-uv fallback in AGENTS.md work.
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import unescape
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
WAYBACK_CDX = (
    "http://web.archive.org/cdx/search/cdx?url=jobs.ashbyhq.com"
    "&matchType=domain&fl=original&collapse=urlkey&output=json"
)
_SLUG_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,60}$")
_SLUG_JUNK = {"_next", "api", "static", "assets", "meeting", "b", "favicon.ico"}
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

# Pulled straight off the Ashby job object. `id` is the posting UUID and is what
# makes cross-run history possible.
API_FIELDS = [
    "id", "title", "department", "team", "employmentType",
    "location", "isRemote", "workplaceType", "publishedAt", "jobUrl",
]
# Output columns: the board slug, the API fields, then --grep context (empty without it).
FIELDS = ["company", *API_FIELDS, "matched"]

_HTML_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


class NotFound(Exception):
    """Board slug returned 404 — not an Ashby customer (or never was)."""


class RateLimited(Exception):
    """Common Crawl returned 503. Per their docs this means the request rate was
    too high; a repeatedly-abusive IP can be blocked for 24 hours."""


def fetch(url: str, timeout: int = 30, retries: int = 4, method: str = "GET") -> bytes:
    """GET a URL, transparently gunzipping. Raises NotFound on 404.

    Common Crawl's CDX index 502/504s under load often enough that a single
    attempt fails maybe half the time, so 5xx gets exponential backoff.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"}, method=method
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


def _add(seen: dict[str, str], url: str) -> None:
    """Record the first path segment of a board URL, deduping case-insensitively."""
    slug = slug_from_url(url)
    if slug:
        seen.setdefault(slug.lower(), slug)


def candidates_from_wayback() -> dict[str, str]:
    """The Internet Archive's CDX index. Broader than Common Crawl and far more
    reliable — it is the default for that reason."""
    print("querying the Wayback Machine...", file=sys.stderr)
    rows = json.loads(fetch(WAYBACK_CDX, timeout=300, retries=3))
    seen: dict[str, str] = {}
    for row in rows[1:]:  # first row is the header
        _add(seen, row[0])
    print(f"  {len(rows) - 1} archived URLs -> {len(seen)} candidates", file=sys.stderr)
    return seen


def candidates_from_commoncrawl(max_pages: int = 20) -> dict[str, str]:
    """Common Crawl's CDX index. Kept as a fallback: narrower coverage, and it
    sheds requests under load often enough to fail for hours at a time."""
    collections = json.loads(fetch(COLLINFO))
    cdx = collections[0]["cdx-api"]
    print(f"querying Common Crawl index {collections[0]['id']}...", file=sys.stderr)
    query = f"{cdx}?url=jobs.ashbyhq.com%2F*&output=json&fl=url"

    seen: dict[str, str] = {}
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
        for line in body.splitlines():  # JSONL, not a JSON array
            if line.strip():
                _add(seen, json.loads(line)["url"])
        print(f"  page {page}: {len(seen)} candidates so far", file=sys.stderr)
    return seen


def plausible(slug: str) -> bool:
    """Cheap shape filter, so validation probes thousands of URLs and not 191,000.

    Archived URLs include tracking blobs, compensation strings and JS fragments as
    "path segments". Every live slug observed is alphanumeric plus space, dot,
    underscore or hyphen; `root.<uuid>` is Ashby's internal embed path, never a board.
    """
    return (
        bool(_SLUG_SHAPE.match(slug))
        and slug.lower() not in _SLUG_JUNK
        and not slug.lower().startswith("root.")
        and not re.fullmatch(r"[0-9a-f-]{30,}", slug.lower())
    )


def board_exists(slug: str) -> bool:
    """HEAD the posting API: 200 for a real board, 404 otherwise.

    HEAD returns the status with a zero-length body, so validating ~5,000 candidates
    costs nothing. A GET would download ~220KB per live board — most of a gigabyte
    just to learn which slugs are real.
    """
    try:
        fetch(POSTING_API.format(slug=urllib.parse.quote(slug)),
              timeout=25, retries=2, method="HEAD")
        return True
    except NotFound:
        return False
    except Exception:
        return False  # transient failure: drop it, the next refresh can find it


def discover_boards(concurrency: int = 8) -> list[str]:
    """Find every Ashby board slug: harvest candidates, then validate each one."""
    try:
        seen = candidates_from_wayback()
    except Exception as e:
        print(f"  Wayback failed ({e}); falling back to Common Crawl", file=sys.stderr)
        seen = candidates_from_commoncrawl()

    candidates = sorted(
        (s for s in seen.values() if plausible(s)), key=str.lower
    )
    print(
        f"validating {len(candidates)} plausible slugs against the posting API...",
        file=sys.stderr,
    )
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        live = [s for s, ok in zip(candidates, pool.map(board_exists, candidates)) if ok]
    print(f"  {len(live)} live boards ({len(candidates) - len(live)} dead)", file=sys.stderr)

    # Discovery only sees what the archive captured, so a real board that was never
    # crawled is invisible to it. Union in every slug already known-good rather than
    # letting a refresh lose boards an earlier run had.
    known = {s.lower(): s for s in live}
    for path in (BOARDS_SEED, BOARDS_CACHE):
        if path.exists():
            for slug in json.loads(path.read_text()):
                known.setdefault(slug.lower(), slug)
    if len(known) > len(live):
        print(f"  +{len(known) - len(live)} from seed/previous runs", file=sys.stderr)
    return sorted(known.values(), key=str.lower)


def load_boards(refresh: bool, concurrency: int = 8) -> list[str]:
    if not refresh:
        for path in (BOARDS_CACHE, BOARDS_SEED):
            if path.exists():
                boards = json.loads(path.read_text())
                print(f"{len(boards)} boards from {path.name}", file=sys.stderr)
                return boards
    try:
        boards = discover_boards(concurrency)
    except RateLimited:
        sys.exit(
            "Common Crawl returned 503: request rate too high. Their docs say to slow "
            "down, and that a repeatedly-abusive IP can be blocked for 24 hours. Wait "
            "before retrying."
        )
    except (urllib.error.URLError, TimeoutError) as e:
        sys.exit(
            f"board discovery failed: {e}\n"
            "Both the Wayback Machine and Common Crawl were unreachable. Retry "
            "later; the bundled boards.seed.json means this phase is optional."
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


def plain_text(value: str) -> str:
    """Strip HTML tags, decode entities, collapse whitespace."""
    return _SPACE.sub(" ", unescape(_HTML_TAG.sub(" ", value))).strip()


def fragments(text: str, pattern: re.Pattern[str], limit: int = 2) -> list[str]:
    """Windows of surrounding text for each match, so a hit can be judged in context."""
    found: list[str] = []
    for match in pattern.finditer(text):
        window = text[max(0, match.start() - 90) : match.end() + 150].strip()
        if window not in found:
            found.append(window)
        if len(found) == limit:
            break
    return found


def scan_board(
    slug: str,
    wanted: str | None,
    remote_only: bool,
    mode: str,
    pattern: re.Pattern[str] | None = None,
) -> list[dict]:
    """Fetch one board, return flat rows for matching listed jobs.

    Descriptions are read only when --grep needs them, and even then only the
    matched fragments survive — the full text is ~95% of the payload, and holding
    3,400 boards' worth would be gigabytes.
    """
    data = json.loads(fetch(POSTING_API.format(slug=urllib.parse.quote(slug))))
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        # Fail loudly on a shape change rather than silently reporting no results.
        raise ValueError(f"{slug}: response has no jobs array")

    rows = []
    for job in jobs:
        if not job.get("isListed"):
            continue
        if wanted and not matches(job.get("title", ""), wanted, mode):
            continue
        if remote_only and not job.get("isRemote"):
            continue

        hits: list[str] = []
        if pattern is not None:
            text = plain_text(
                job.get("descriptionPlain") or job.get("descriptionHtml") or ""
            )
            hits = fragments(text, pattern)
            if not hits:
                continue

        rows.append({
            "company": slug,
            **{f: job.get(f, "") for f in API_FIELDS},
            "matched": " … ".join(hits),
        })
    return rows


_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    {"".join(f"{f} TEXT," for f in FIELDS if f != "id")}
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    closed_at   TEXT
);
CREATE INDEX IF NOT EXISTS jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS jobs_last_seen ON jobs(last_seen);
CREATE INDEX IF NOT EXISTS jobs_closed_at ON jobs(closed_at);
"""


def save(
    rows: list[dict],
    db_path: Path,
    seen_at: str,
    covered: list[str] | None = None,
) -> tuple[int, int, int]:
    """Upsert rows keyed on the Ashby posting id. Returns (new, updated, closed).

    first_seen is preserved across runs and last_seen is refreshed, which is the
    whole reason to keep a database rather than just the CSV: it answers "when did
    this posting appear" and "is it still up" across scrapes.

    `covered` is the list of boards this run scanned exhaustively, and is only passed
    for an unfiltered run. On a filtered run a missing job is ambiguous — it may be
    gone, or it may simply not have matched --title — so only an unfiltered run has
    the standing to close a posting. Anything on a covered board that this run did not
    see is stamped closed_at; anything that reappears has it cleared.
    """
    keyed = {r["id"]: r for r in rows if r.get("id")}
    cols = ["id", *[f for f in FIELDS if f != "id"]]
    with sqlite3.connect(db_path) as con:
        con.executescript(_SCHEMA)
        # Databases created before closed_at existed.
        if "closed_at" not in {c[1] for c in con.execute("PRAGMA table_info(jobs)")}:
            con.execute("ALTER TABLE jobs ADD COLUMN closed_at TEXT")
        known = {row[0] for row in con.execute("SELECT id FROM jobs")}
        con.executemany(
            f"INSERT INTO jobs ({','.join(cols)}, first_seen, last_seen) "
            f"VALUES ({','.join('?' * len(cols))}, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            # Everything except first_seen is refreshed; titles and locations do
            # get edited in place on live postings. `matched` is the exception: it
            # belongs to whichever --grep produced it, so a later title-only run
            # must not blank out context an earlier search found.
            + ",".join(
                f"{c}=excluded.{c}"
                for c in cols
                if c not in ("id", "matched")
            )
            + ", matched=CASE WHEN excluded.matched != '' "
            "THEN excluded.matched ELSE jobs.matched END"
            ", last_seen=excluded.last_seen",
            [
                [str(r.get(c, "")) for c in cols] + [seen_at, seen_at]
                for r in keyed.values()
            ],
        )
        closed = 0
        if covered is not None:
            con.execute("CREATE TEMP TABLE scanned (company TEXT PRIMARY KEY)")
            con.executemany(
                "INSERT OR IGNORE INTO scanned VALUES (?)", [(c,) for c in covered]
            )
            cur = con.execute(
                "UPDATE jobs SET closed_at = ? "
                "WHERE closed_at IS NULL AND last_seen < ? "
                "AND company IN (SELECT company FROM scanned)",
                (seen_at, seen_at),
            )
            closed = cur.rowcount
            # A posting that came back is open again.
            con.execute(
                "UPDATE jobs SET closed_at = NULL "
                "WHERE closed_at IS NOT NULL AND last_seen = ?",
                (seen_at,),
            )

    new = len(keyed.keys() - known)
    return new, len(keyed) - new, closed


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--title",
        help="title to match (default: 'software engineer', unless --grep is given)",
    )
    p.add_argument(
        "--match",
        choices=("fuzzy", "exact"),
        default="fuzzy",
        help="fuzzy: either string contains the other (default). exact: titles must be equal",
    )
    p.add_argument(
        "--grep",
        metavar="REGEX",
        help="case-insensitive regex searched against the job description; "
        "matching context lands in the 'matched' column",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="every listed job on every board, no title or description filter "
        "(~54,000 jobs)",
    )
    p.add_argument("--limit", type=int, help="max boards to scan (default: all)")
    p.add_argument("--remote", action="store_true", help="only remote postings")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--refresh-boards", action="store_true", help="re-crawl slug list")
    p.add_argument("--out", default="ashby-jobs", help="output filename prefix")
    p.add_argument(
        "--db",
        default="ashby-jobs.db",
        help="SQLite file accumulating every scrape (default: ashby-jobs.db)",
    )
    p.add_argument("--no-db", action="store_true", help="skip the database write")
    args = p.parse_args()

    if args.all and (args.title or args.grep):
        sys.exit("--all takes no filters; drop --title/--grep or drop --all")
    # The title default only applies when nothing else narrows the search. Applying
    # it to a --grep run would silently AND an unrequested title filter onto it.
    title = None if args.all else (args.title or (None if args.grep else "software engineer"))
    try:
        pattern = re.compile(args.grep, re.IGNORECASE) if args.grep else None
    except re.error as e:
        sys.exit(f"--grep is not a valid regex: {e}")
    if args.grep and r"\b" not in args.grep:
        # Silent and severe: `rust` matches "trust", which appears in almost every
        # description's boilerplate. Measured 1350 hits vs 72 word-bounded.
        print(
            rf"note: --grep {args.grep!r} has no \b word boundary, so it matches "
            rf"inside longer words. Consider '\b{args.grep}\b'.",
            file=sys.stderr,
        )

    boards = load_boards(args.refresh_boards, args.concurrency)
    scanned = boards[: args.limit] if args.limit else boards
    criteria = [f"title {title!r} ({args.match})" if title else "",
                f"description /{args.grep}/" if args.grep else ""]
    what = " + ".join(c for c in criteria if c) or "every listed job"
    print(f"scanning {len(scanned)} boards for {what}...", file=sys.stderr)

    rows: list[dict] = []
    dead: set[str] = set()
    errors = 0

    def work(slug: str) -> list[dict]:
        nonlocal errors
        for attempt in range(2):
            try:
                return scan_board(slug, title, args.remote, args.match, pattern)
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

    written = f"{csv_path.name}, {json_path.name}"
    if not args.no_db:
        seen_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db_path = HERE / args.db if not Path(args.db).is_absolute() else Path(args.db)
        # Only an unfiltered run saw everything, so only it may close postings.
        covered = scanned if (title is None and pattern is None) else None
        new, updated, closed = save(rows, db_path, seen_at, covered)
        written += f", {db_path.name} ({new} new, {updated} already seen"
        written += f", {closed} closed)" if covered is not None else ")"

    print(f"\n{len(rows)} jobs -> {written}", file=sys.stderr)


if __name__ == "__main__":
    main()
