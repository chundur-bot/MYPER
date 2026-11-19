"""Read a list of filings from the command line. The app's Add data page does the same with an upload.

    python fetch_from_list.py filings.xlsx               (also looks in filing_lists; a document ID becomes a full link; --location changes the address)
    python fetch_from_list.py filings.xlsx --dry-run     (check the list; reads nothing)
    python fetch_from_list.py filings.xlsx --probe 3     (try the first 3 rows and report what comes back; keeps nothing)

Other options: --allow-host HOST --only-study --country AU --delay 2. The filing itself isn't kept; the app shows the
figures with the link, and filing_links.csv lists every accepted link. Exchange sites are always refused. Every result is written to logs/fetch_<time>.csv.
"""
import argparse
import csv
import socket  # noqa: F401
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also works when run with -P

from sbb import countries, db, fetching, parsers
from sbb.fetching import (ALLOWED_HOSTS, EXCHANGE_HOST, STOP_AFTER_FAILURES, clean_link, document_in_viewer, fetch, get_location, link_for,  # noqa: F401
                          load_allowed_hosts, pick, process, read_rows, refusal, request_address, to_iso, use_location)


def probe(rows, count, location, scheme, default_country=""):
    """Try the first rows and report what comes back. Keeps nothing, so the output is safe to read through."""
    for number, row in rows[:count]:
        link, problem = link_for(row, location, scheme)
        print(f"\nRow {number}: {link or problem}")
        if problem:
            continue
        why = refusal(link)
        if why:
            print(f"  Refused: {why}")
            continue
        try:
            data, ext, note = fetch(link)
        except ValueError as e:
            print(f"  Failed: {e}")
            continue
        print(f"  Got: {len(data):,} bytes, {note}, read as {ext}")
        with tempfile.TemporaryDirectory() as folder:
            f = Path(folder) / f"filing{ext}"
            f.write_bytes(data)
            try:
                text = parsers.PAGE_BREAK.join(parsers.read_pages(f))
            except Exception as e:
                print(f"  Could not read it: {e}")
                continue
        print(f"  Readable text: {len(text):,} characters")
        if not parsers.is_buyback_filing(text, str(pick(row, 'title'))):
            print("  Not a buyback filing: would be skipped")
            continue
        market = countries.get(str(pick(row, "country")).strip().upper()) or countries.get(default_country) or {}
        p = parsers.parse(text, market.get("currency", "AUD"), market.get("code"), market.get("date_order"))
        print(f"  Buyback filing: form {p['form']}, type {p['doc_type']}, date {p['doc_date']}, ticker {p['ticker'] or pick(row, 'ticker') or 'not found'}")
        print(f"  Found: {len(p['transactions'])} purchases, {len(p['snapshots'])} running totals; to review: {[k for k, _ in p['issues']] or 'nothing'}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read filings listed in an Excel or CSV file; keep the figures and links, not the files.")
    ap.add_argument("list_file")
    ap.add_argument("--location", help="Web address or folder that rows with a File Name are joined to")
    ap.add_argument("--country", default="", help="For lists with no Country column; otherwise worked out from the study list")
    ap.add_argument("--delay", type=float, default=2.0, help="Seconds between requests (default 2)")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent), help="The folder holding the app's database and logs")
    ap.add_argument("--dry-run", action="store_true", help="Check the list and report; read nothing")
    ap.add_argument("--probe", type=int, metavar="N", help="Try the first N rows and report what comes back; keep nothing")
    ap.add_argument("--allow-host", action="append", default=[], metavar="HOST", help="Your company's system, by exact name, if it has a public-looking address")
    ap.add_argument("--only-study", action="store_true", help="Skip tickers that aren't in your study list")
    ap.add_argument("--scheme", default=fetching.SCHEME, choices=("https", "http"), help=f"For links with no http:// or https:// at the start (default {fetching.SCHEME}, as your system's links use)")
    a = ap.parse_args(argv)
    root = Path(a.root)
    fetching.LINKS_FILE = root / "filing_links.csv"
    load_allowed_hosts()
    ALLOWED_HOSTS.update(h.strip().lower() for h in a.allow_host if not EXCHANGE_HOST.search(h.strip()))
    location = use_location(a.location) if a.location else get_location()
    if location:
        host = None if location[:1] in "\\/" else clean_link(location)
        if host and host.startswith("http"):
            from urllib.parse import urlparse
            if not EXCHANGE_HOST.search(urlparse(host).hostname or ""):
                ALLOWED_HOSTS.add((urlparse(host).hostname or "").lower())
    list_file = Path(a.list_file)
    if not list_file.exists() and (fetching.LISTS_FOLDER / list_file.name).exists():
        list_file = fetching.LISTS_FOLDER / list_file.name  # also looks in the default folder
    rows = read_rows(list_file)
    if a.probe:
        probe(rows, a.probe, location, a.scheme, a.country.upper())
        return 0
    if a.dry_run:
        counts = {"would read": 0, "refused": 0, "failed": 0}
        for number, row in rows:
            link, problem = link_for(row, location, a.scheme)
            why = problem or refusal(link)
            result = "failed" if problem else "refused" if why else "would read"
            counts[result] += 1
            if why:
                print(f"Row {number}: {result}. {why}")
        print("Done: " + ", ".join(f"{v} {k}" for k, v in counts.items() if v))
        return 0
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"fetch_{datetime.now():%Y%m%d_%H%M%S}.csv"
    con = db.connect(root / "buyback.db")
    countries.load_constituents(con)
    with log_path.open("w", encoding="utf-8", newline="") as fh:
        log = csv.writer(fh)
        log.writerow(["row", "ticker", "link", "result", "detail"])

        def show(number, ticker, link, result, detail):
            log.writerow([number, ticker, link, result, detail])
            print(f"Row {number}: {result}. {detail}" if result in ("failed", "refused", "stopped", "note") else f"Row {number}: {result}")

        counts = process(con, rows, location, a.country.upper() or None, a.delay, a.only_study, a.scheme, show)
    con.close()
    print("Done: " + ", ".join(f"{v} {k}" for k, v in counts.items() if v) + f". Details: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
