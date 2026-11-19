"""Local web page. Python standard library only; listens on 127.0.0.1 (this PC only) and makes no web requests."""
import hashlib
import json
import mimetypes
import os
import shutil
import tempfile
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import countries, db, fetching, hand, ingest, manage, queries as q, report, tracker

ROOT = db.ROOT
STATIC = Path(__file__).resolve().parent / "static"
LIBRARY = ["Research_Report.md", "Vendor_Study.md", "README_app.md", "Data_Dictionary.md", "Filing_Types.md"]
BUILT = {"Data_Dictionary.md", "Filing_Types.md"}  # made from the data files each time, so the pages can't drift from them


def filing_types_md():
    """For each market, the types of document it files about a buyback, what each is, and whether this tool reads it."""
    import csv
    cell = lambda v: str(v or "").replace("|", "/").replace("\n", " ").strip()
    with (ROOT / "data" / "filing_types.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    names = {c["code"]: f"{c['name']} ({c['exchange']})" for c in countries.load()}
    out = ["# Filing types", "", "For each market, the documents a company files about a buyback, a short description, and whether this tool reads them. Edit `data\\filing_types.csv` in Excel to change this page.", ""]
    if any(r["status"].strip().lower() != "approved" for r in rows):
        out += ["> Descriptions marked **Draft** were written from the research report and the sample filings, and are waiting for your review. Change a row's status to Approved once it is right.", ""]
    for code in dict.fromkeys(r["country"] for r in rows):
        out += [f"## {names.get(code, code)}", "", "| Document | Type | Description | Read by the tool? | What is taken from it | Status |", "|---|---|---|---|---|---|"]
        out += [f"| {cell(r['form'])} | {cell(r['filing_type'])} | {cell(r['description'])} | **{cell(r['read'])}** | {cell(r['takes'])} | {cell(r['status'])} |" for r in rows if r["country"] == code]
        out.append("")
    return "\n".join(out)


def data_dictionary_md():
    """The data dictionary and the keywords file, as one Library page."""
    import csv
    cell = lambda v: str(v or "").replace("|", "/").replace("\n", " ").strip()
    out = ["# Data dictionary", "", "Every field the app collects or plans to collect. Edit `data\\data_dictionary.csv` in Excel to change this page.", ""]
    with (ROOT / "data" / "data_dictionary.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for entity in dict.fromkeys(r["entity"] for r in rows):
        out += [f"## {entity}", "", "| Field | Status | Description | UK source | ASX source | NZX source | Example | Stored in |", "|---|---|---|---|---|---|---|---|"]
        out += [f"| {cell(r['field'])} | {cell(r['status'])} | {cell(r['description'])} | {cell(r['uk_source'])} | {cell(r['asx_source'])} | {cell(r['nzx_source'])} | {cell(r['example'])} | `{cell(r['stored_in'])}` |" if r["stored_in"] else
                f"| {cell(r['field'])} | {cell(r['status'])} | {cell(r['description'])} | {cell(r['uk_source'])} | {cell(r['asx_source'])} | {cell(r['nzx_source'])} | {cell(r['example'])} | – |" for r in rows if r["entity"] == entity]
        out.append("")
    out += ["## Phrases the parser looks for", "", "From `data\\keywords.csv`. {DATE} and {NAME} mark what is captured, and {...} stands for a few words. Edits apply at the next read, with no restart.", "",
            "| Market | Field | Phrase | Means | Example |", "|---|---|---|---|---|"]
    for f in [ROOT / "data" / "keywords.csv"] + sorted((ROOT / "data" / "keywords").glob("*.csv")):  # the main file, then any phrase files copied into data\\keywords
        with f.open(encoding="utf-8-sig", newline="") as fh:
            out += [f"| {cell(r['market'])} | {cell(r['field'])} | `{cell(r['phrase'])}` | {cell(r['means'])} | {cell(r['example'])} |" for r in csv.DictReader(fh) if (r.get("phrase") or "").strip()]
    return "\n".join(out)
TYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8", ".txt": "text/plain; charset=utf-8"}


def periods(con):
    """All programmes by default, with no date limit; years that have data can be chosen as an option."""
    years = {str(date.today().year)}
    for table, column in (("transactions", "trade_date"), ("snapshots", "as_of")):
        years |= {r[0][:4] for r in con.execute(f"select distinct {column} from {table}") if r[0]}
    return {"default": {"from": q.ALL_FROM, "to": q.ALL_TO}, "years": sorted(years, reverse=True), "read_only": read_only_info(con)}


READ_ONLY = {"on": False, "source": None, "copy": None, "seen": None}  # set when the app shows a published copy of someone else's database
LOCAL = ROOT / "data" / "local_settings.json"  # this PC's own choices: where a copy is published to, where a read-only copy is read from
OPEN_TO_READERS = {"/api/tracker/run", "/api/read_only/refresh"}  # the only requests a read-only copy answers that change anything, and they touch its private copy alone


def local(key, value=None):
    """A setting kept for this PC only. With a value, stores it."""
    try:
        held = json.loads(LOCAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        held = {}
    if value is None:
        return held.get(key)
    held[key] = value
    LOCAL.write_text(json.dumps(held, indent=2), encoding="utf-8")
    return value


def settle(con, force=False):
    """Bring the figures up to date at a start. Typed files in the inbox are read first. If nothing the figures depend on has changed since the last
    full rebuild (the same version, filings and data files), the rebuild is skipped. Returns "rebuilt" or "unchanged"."""
    if not READ_ONLY["on"]:
        ingest.scan(con)
        moved = hand.migrate(con)  # hand entries typed before version 25 sat in manual_entries.csv: moved once into Add by hand
        if moved:
            print(f"{moved} purchase{'s' if moved != 1 else ''} typed on Add by hand before version 25 moved into the new Add by hand list. The old file is kept, renamed to .csv.bak.")
    if not force and db.state(con, "settled") == ingest.state_signature(con):
        return "unchanged"
    if not READ_ONLY["on"]:  # a published copy keeps its owner's company lists
        countries.load_constituents(con)
    ingest.replay_all(con)
    if not READ_ONLY["on"]:
        fetching.write_links(con)
    ingest.mark_settled(con)
    return "rebuilt"


def _stamp(path):
    s = os.stat(path)
    return [s.st_size, s.st_mtime_ns]


def open_read_only(source):
    """Show a published copy without ever writing to it: the file is copied to this PC's temporary folder and the app works on that copy.
    source is the published file, or the folder holding buyback_published.db. Returns the copy's path. Raises ValueError with a plain reason."""
    source = Path(source)
    if source.is_dir():
        source = source / "buyback_published.db"
    if not source.is_file():
        raise ValueError(f"No published database found at {source}. Ask its owner to publish a copy, or check the path.")
    folder = Path(tempfile.gettempdir()) / "sbb_read_only"
    folder.mkdir(exist_ok=True)
    copy = folder / f"copy_{hashlib.sha1(str(source.resolve()).lower().encode()).hexdigest()[:12]}.db"
    part = copy.with_suffix(".part")
    shutil.copyfile(source, part)
    os.replace(part, copy)
    READ_ONLY.update(on=True, source=str(source), copy=str(copy), seen=_stamp(source))
    db.DB_PATH = copy
    return copy


def read_only_info(con=None):
    """What the page shows about a read-only copy: when it was published, and whether a newer one is waiting."""
    if not READ_ONLY["on"]:
        return {"on": False}
    try:
        newer = _stamp(READ_ONLY["source"]) != READ_ONLY["seen"]
    except OSError:
        newer = False  # the shared folder can't be reached just now; the copy in hand still works
    published = version = None
    if con is not None:
        published, version = db.state(con, "published_at"), db.state(con, "published_version")
    return {"on": True, "source": READ_ONLY["source"], "published": published, "version": version, "newer": newer}


def refresh_read_only():
    """Take the newest published copy, if there is one. Returns True if a newer copy was loaded."""
    if _stamp(READ_ONLY["source"]) == READ_ONLY["seen"]:
        return False
    open_read_only(READ_ONLY["source"])
    con = db.connect()
    try:
        settle(con)
        tracker.current(con)
    finally:
        con.close()
    return True


JOB = {"running": False, "name": "", "total": 0, "done": 0, "current": None, "counts": {}, "results": [], "error": "", "stop": False, "started_at": ""}
JOB_LOCK = threading.Lock()


def new_codes(rows, market, agreed):
    """Before a list or pasted links are read: the codes that aren't in the company list, for the user to confirm or correct. None when there's nothing to ask."""
    if agreed:
        return None
    con = db.connect()
    try:
        unknown = fetching.unknown_codes(con, rows, str(market or ""))
    finally:
        con.close()
    return {"unknown": unknown} if unknown else None


def start_rows(rows, name, location="", market=""):
    """Read rows in the background so the page stays responsive. One list at a time."""
    with JOB_LOCK:
        if JOB["running"]:
            raise ValueError("A list is already being read.")
    market = market if countries.get(market or "") else ""  # the market chosen at the top of the page; "All markets" chooses none
    fetching.load_allowed_hosts()
    location = fetching.use_location(location) if location else fetching.get_location()
    if location and not fetching.is_share(location):
        host = urlparse(location).hostname or ""
        if not fetching.EXCHANGE_HOST.search(host):
            fetching.ALLOWED_HOSTS.add(host.lower())
    if not rows:
        raise ValueError("Nothing to read.")
    with JOB_LOCK:
        JOB.update(running=True, name=name, total=len(rows), done=0, current=None, counts={}, results=[], error="", stop=False, started_at=db.now())

    def on_start(number, ticker, link):
        JOB["current"] = {"row": number, "ticker": ticker, "link": link}

    def on_result(number, ticker, link, result, detail):
        JOB["done"] += result not in ("stopped", "note")
        JOB["results"].append({"row": number, "ticker": ticker, "link": link, "result": result, "detail": detail})

    def work():
        con = db.connect()
        try:
            countries.load_constituents(con)
            JOB["counts"] = fetching.process(con, rows, location, None, 1.0, on_result=on_result, should_stop=lambda: JOB["stop"], on_start=on_start, market=market)
            countries.load_constituents(con)
        except Exception as e:  # shown on the page; the list can simply be run again
            JOB["error"] = repr(e)
        finally:
            con.close()
            JOB["current"] = None
            JOB["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "total": len(rows)}


def rows_from_upload(name, data):
    suffix = Path(name).suffix.lower()
    if suffix not in (".xlsx", ".xlsm", ".csv"):
        raise ValueError("Choose an Excel (.xlsx) or CSV file.")
    with tempfile.TemporaryDirectory() as folder:
        f = Path(folder) / f"list{suffix}"
        f.write_bytes(data)
        return fetching.read_rows(f)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        a = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path
        con = db.connect()
        q.only_ticker(a.get("ticker", ""))  # the one company chosen at the top of the page, if any
        try:
            if path in ("/", "/index.html"):
                html = (STATIC / "index.html").read_text(encoding="utf-8")
                for name in ("app.js", "app.css"):
                    html = html.replace(f"/static/{name}\"", f"/static/{name}?v={int((STATIC / name).stat().st_mtime)}\"")
                return self.send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if path in ("/manage", "/manage.html"):  # its own page: exchanges, their tickers, and deleting one ticker
                return self.send(200, (STATIC / "manage.html").read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/static/"):
                f = (STATIC / path.split("/", 2)[2]).resolve()
                if STATIC in f.parents and f.is_file():
                    return self.send(200, f.read_bytes(), TYPES.get(f.suffix.lower()) or mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                return self.send(404, {"error": "not found"})
            cc = a.get("country", "ALL")
            start, end = a.get("from", q.ALL_FROM), a.get("to", q.ALL_TO)
            api = {
                "/api/countries": lambda: countries.load(),
                "/api/periods": lambda: periods(con),
                "/api/summary": lambda: q.summary(con, cc, start, end),
                "/api/companies": lambda: q.companies(con, cc, start, end),
                "/api/company": lambda: q.company(con, cc, a.get("ticker", ""), start, end),
                "/api/programmes": lambda: q.programme_rows(con, cc, start, end),
                "/api/transactions": lambda: q.transactions(con, cc, start, end),
                "/api/venues": lambda: q.venues(con, cc, start, end),
                "/api/activity": lambda: q.activity(con, int(a.get("prog", 0))),
                "/api/filings/status": lambda: {**{k: JOB[k] for k in ("running", "name", "total", "done", "current", "counts", "error", "started_at")}, "results": JOB["results"][-500:], "location": fetching.get_location(), "folder": str(fetching.LISTS_FOLDER), "lists": fetching.lists_in_folder(), "suffix": fetching.DOCUMENT_SUFFIX, "version": db.VERSION, "links_file": str(fetching.LINKS_FILE), "skipped": db.rows(con.execute("select link, ticker, country, skipped_at, heading, reason from skipped_links where reason in ('Not a buyback filing','Removed by you') order by skipped_at desc limit 500"))},
                "/api/cancellations": lambda: q.cancellations(con, cc, start, end),
                "/api/cessations": lambda: q.cessations(con, cc, start, end),
                "/api/documents": lambda: {"rows": q.documents(con, cc), "hits": q.search_documents(con, cc, a["q"]) if a.get("q") else None},
                "/api/document": lambda: q.document(con, int(a.get("id", 0)), a.get("key")),
                "/api/analysis": lambda: q.analysis(con, cc, start, end),
                "/api/quality": lambda: {**q.quality(con, cc, start, end), "waiting": q.waiting(con, cc)},
                "/api/collect": lambda: q.collect_status(con),
                "/api/tickers": lambda: db.rows(con.execute("select c.country, c.ticker, c.company from companies c where (? in ('', 'ALL') or c.country=?) and (exists (select 1 from documents d where d.country=c.country and d.ticker=c.ticker) or exists (select 1 from programmes p where p.country=c.country and p.ticker=c.ticker)) order by c.ticker, c.country", (cc, cc))),
                "/api/tracker/overview": lambda: tracker.overview(con, cc, a.get("ticker", ""), JOB["running"]),
                "/api/tracker/notices": lambda: tracker.notices(con, cc, a.get("ticker", ""), JOB["running"]),
                "/api/tracker/checks": lambda: tracker.checks(con, cc, a.get("ticker", ""), JOB["running"]),
                "/api/tracker/excluded": lambda: tracker.excluded(con, cc, a.get("ticker", ""), JOB["running"]),
                "/api/tracker/plan": lambda: tracker.plan(con, a.get("id")),
                "/api/tracker/notice": lambda: tracker.notice(con, a.get("id")),
                "/api/manage/tickers": lambda: manage.listing(con),
                "/api/hand": lambda: hand.listing(con, cc, a.get("ticker", "")),
                "/api/hand/choices": lambda: hand.choices(con, a.get("market", ""), a.get("company", "").strip().upper()),
                "/api/issues": lambda: q.issues(con, cc, start, end),
                "/api/hand/update_choices": lambda: hand.update_choices(con, a.get("market", ""), a.get("company", "").strip().upper(), a.get("programme", ""), a.get("target", ""), a.get("row", ""), a.get("field", "")),
                "/api/library": lambda: [{"name": n, "exists": n in BUILT or (ROOT / n).exists()} for n in LIBRARY],
            }
            if path in api:
                return self.send(200, api[path]())
            if path == "/api/doc_file":
                d = con.execute("select rel_path, file_name from documents where doc_id=?", (int(a.get("id", 0)),)).fetchone()
                f = (ROOT / d["rel_path"]).resolve() if d else None
                if not f or countries.INBOX not in f.parents or not f.is_file():
                    return self.send(404, {"error": "This file is no longer in the inbox folder."})
                # Saved web pages are sent as downloads, never run as pages inside this app.
                ctype = "application/pdf" if f.suffix.lower() == ".pdf" else "application/octet-stream"
                name = d["file_name"].encode("ascii", "ignore").decode().replace('"', "")
                disp = "inline" if f.suffix.lower() == ".pdf" else "attachment"
                return self.send(200, f.read_bytes(), ctype, {"Content-Disposition": f'{disp}; filename="{name}"'})
            if path == "/api/export":
                f = report.write(con, cc, start, end)
                return self.send(200, f.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", {"Content-Disposition": f'attachment; filename="{f.name}"'})
            if path == "/api/tracker/export":  # the tracker for one exchange, as an Excel file
                f = tracker.workbook(con, cc, JOB["running"])
                return self.send(200, f.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", {"Content-Disposition": f'attachment; filename="{f.name}"'})
            if path == "/api/library_file":
                name = a.get("name", "")
                if name == "Data_Dictionary.md":
                    return self.send(200, data_dictionary_md().encode("utf-8"), "text/plain; charset=utf-8")
                if name == "Filing_Types.md":
                    return self.send(200, filing_types_md().encode("utf-8"), "text/plain; charset=utf-8")
                if name not in LIBRARY or not (ROOT / name).exists():
                    return self.send(404, {"error": "not found"})
                return self.send(200, (ROOT / name).read_bytes(), "text/plain; charset=utf-8")
            if path == "/api/filing_links":
                return self.send(200, ("\ufeff" + fetching.links_csv(con)).encode("utf-8"), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="filing_links.csv"'})
            if path == "/api/template":
                f = ROOT / "templates" / Path(a.get("name", "")).name
                if not f.is_file():
                    return self.send(404, {"error": "not found"})
                return self.send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream", {"Content-Disposition": f'attachment; filename="{f.name}"'})
            return self.send(404, {"error": "not found"})
        except ValueError as e:
            return self.send(400, {"error": str(e)})
        except Exception as e:
            return self.send(500, {"error": repr(e)})
        finally:
            con.close()

    def do_POST(self):
        # Another website open in the browser must not be able to change local data.
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self.send(403, {"error": "Refused: request came from another site."})
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        if READ_ONLY["on"] and urlparse(self.path).path not in OPEN_TO_READERS:
            return self.send(403, {"error": "This is a read-only copy of the database. Changes are made by its owner, who then publishes a new copy."})
        if READ_ONLY["on"] and urlparse(self.path).path == "/api/read_only/refresh":
            try:
                return self.send(200, {"loaded": refresh_read_only(), **read_only_info()})
            except (OSError, ValueError) as e:
                return self.send(400, {"error": f"The published copy couldn't be loaded: {e}"})
        con = db.connect()
        try:
            u = urlparse(self.path)
            if u.path == "/api/filings/start":
                a = {k: v[0] for k, v in parse_qs(u.query).items()}
                rows = rows_from_upload(a.get("name", ""), raw)
                return self.send(200, new_codes(rows, a.get("market", ""), a.get("new_codes") == "1") or start_rows(rows, Path(a.get("name", "")).name, a.get("location", ""), a.get("market", "")))
            if u.path == "/api/filings/stop":
                JOB["stop"] = True
                return self.send(200, {"stopping": True})
            body = json.loads(raw or b"{}")
            if u.path == "/api/reset":
                if body.get("confirm") != "RESET":
                    raise ValueError("Type RESET to confirm.")
                with JOB_LOCK:
                    if JOB["running"]:
                        raise ValueError("A list is being read. Stop it first.")
                    JOB.update(name="", total=0, done=0, current=None, counts={}, results=[], error="")
                done = ingest.reset(con)
                fetching.write_links(con)
                return self.send(200, done)
            if u.path == "/api/filings/paste":
                rows = fetching.parse_pasted(body.get("text", ""), body.get("ticker", ""))
                return self.send(200, new_codes(rows, body.get("market", ""), body.get("new_codes")) or start_rows(rows, "Pasted hyperlinks", "", str(body.get("market", ""))))
            if u.path == "/api/filings/reread":
                country, ticker = str(body.get("country", "")), str(body.get("ticker", ""))
                rows = ingest.reread_rows(con, country, ticker, bool(body.get("only_gaps")))
                if not rows:
                    raise ValueError("No filings to read again for this company." if not body.get("only_gaps") else "No filings with gaps for this company.")
                return self.send(200, start_rows(rows, f"Re-read {ticker}" + (" (filings with gaps)" if body.get("only_gaps") else ""), "", country))
            if u.path == "/api/filings/reread_review":  # every filing under To review, fetched again from its link and read with the current reader
                rows = ingest.review_rows(con, str(body.get("country", "")), str(body.get("ticker", "")).strip().upper())
                if not rows:
                    raise ValueError("No link filings are under To review.")
                return self.send(200, start_rows(rows, "Read filings in review again", "", ""))
            if u.path == "/api/waiting/not_needed":
                with JOB_LOCK:
                    if JOB["running"]:
                        raise ValueError("A list is being read. Try again when it finishes.")
                group = next((g for g in q.waiting(con, None) if g["country"] == body.get("country") and g["ticker"] == body.get("ticker")), None)
                if not group:
                    raise ValueError("Nothing is waiting for that company any more.")
                for doc_id in group["doc_ids"]:
                    ingest.remove_filing(con, doc_id)
                fetching.write_links(con)
                return self.send(200, {"removed": len(group["doc_ids"])})
            if u.path == "/api/filings/remove_many":
                with JOB_LOCK:
                    if JOB["running"]:
                        raise ValueError("A list is being read. Remove the filings when it finishes.")
                removed, problems = 0, []
                for doc_id in body.get("doc_ids", []):
                    try:
                        ingest.remove_filing(con, int(doc_id))
                        removed += 1
                    except ValueError as e:
                        problems.append(str(e))
                fetching.write_links(con)
                return self.send(200, {"removed": removed, "problems": problems})
            if u.path == "/api/filings/remove":
                with JOB_LOCK:
                    if JOB["running"]:
                        raise ValueError("A list is being read. Remove the filing when it finishes.")
                ingest.remove_filing(con, int(body.get("doc_id", 0)))
                fetching.write_links(con)
                return self.send(200, {"removed": True})
            if u.path == "/api/manage/delete":  # one ticker and its filings, out of one exchange; the database is copied to backups first
                with JOB_LOCK:
                    if JOB["running"]:
                        raise ValueError("A list is being read. Delete the ticker when it finishes.")
                ticker = str(body.get("ticker", "")).strip().upper()
                if not ticker or str(body.get("confirm", "")).strip().upper() != ticker:
                    raise ValueError("Type the ticker's code to confirm.")
                gone = manage.delete_ticker(con, str(body.get("country", "")), ticker, bool(body.get("forget_links")))
                fetching.write_links(con)
                return self.send(200, gone)
            if u.path == "/api/filings/move":  # a filing stored under the wrong code goes to the code the user gives
                with JOB_LOCK:
                    if JOB["running"]:
                        raise ValueError("A list is being read. Move the filing when it finishes.")
                moved = ingest.move_filing(con, int(body.get("doc_id", 0)), str(body.get("ticker", "")))
                fetching.write_links(con)
                return self.send(200, moved)
            if u.path == "/api/filings/read_anyway":
                found = con.execute("select link, ticker, country from skipped_links where link=?", (str(body.get("link", "")),)).fetchone()
                if not found:
                    raise ValueError("That link isn't in the skipped list any more.")
                row = {"ticker": found["ticker"] or "", "hyperlink": found["link"], "_force": True}
                if found["country"]:
                    row["country"] = found["country"]
                return self.send(200, start_rows([(1, row)], "Read anyway"))
            if u.path == "/api/filings/read_list":
                f = fetching.LISTS_FOLDER / Path(str(body.get("name", ""))).name
                if not f.is_file():
                    raise ValueError("That list isn't in the folder any more.")
                rows = fetching.read_rows(f)
                return self.send(200, new_codes(rows, body.get("market", ""), body.get("new_codes")) or start_rows(rows, f.name, str(body.get("location", "")), str(body.get("market", ""))))
            if u.path == "/api/scan":
                countries.load_constituents(con)
                return self.send(200, ingest.scan(con))
            if u.path in ("/api/hand/save", "/api/hand/delete"):  # entries made by hand: added, changed or deleted, each kept in the history
                with JOB_LOCK:
                    if JOB["running"]:
                        raise ValueError("A list is being read. Save this when it finishes.")
                if u.path == "/api/hand/save":
                    return self.send(200, hand.save(con, body))
                return self.send(200, hand.delete(con, body.get("entry_id"), body.get("reason")))
            if u.path == "/api/review":
                con.execute("update review set status=? where review_id=?", (body.get("status", "RESOLVED"), body["review_id"]))
                con.commit()
                return self.send(200, {"ok": True})
            if u.path == "/api/assign":
                ingest.assign_company(con, int(body["doc_id"]), str(body["ticker"]).strip().upper())
                fetching.write_links(con)
                return self.send(200, {"ok": True})
            if u.path == "/api/tracker/run":  # rebuild the tracker's own tables from the filings held
                with JOB_LOCK:
                    if JOB["running"]:
                        raise ValueError("A list is being read. The tracker updates when it finishes.")
                return self.send(200, tracker.run(con))
            if u.path == "/api/study":
                entry = countries.add_study(body)
                countries.load_constituents(con)
                return self.send(200, entry)
            if u.path == "/api/country":
                entry = countries.add(body)
                countries.load_constituents(con)
                return self.send(200, entry)
            return self.send(404, {"error": "not found"})
        except ValueError as e:
            return self.send(400, {"error": str(e)})
        except Exception as e:
            return self.send(500, {"error": repr(e)})
        finally:
            con.close()


def serve(port=8770, open_browser=True, read_only=None, rebuild=False):
    if read_only is not None:  # a published copy of someone else's database: copied to this PC and never written back
        source = read_only or local("read_only_source")
        if not source:
            print("Say where the published copy is, once:  python -P run_app.py --read-only \"<folder or file>\"")
            return
        try:
            copy = open_read_only(source)
        except (OSError, ValueError) as e:
            print(e)
            return
        local("read_only_source", str(source))
        print(f"Read-only: showing a copy of {READ_ONLY['source']}\n(kept at {copy}; the published file is never written to)")
        kept = None
    else:
        kept = manage.start_copy()  # the first start of a new version: a copy of the database file as it is, before the app opens or changes it
    con = db.connect()
    if kept:
        print("A copy of your database was saved first:", kept)
    how = settle(con, rebuild)
    print("Figures rebuilt from the filings held." if how == "rebuilt" else "Nothing changed since the last start, so the figures were not rebuilt (python -P run_app.py --rebuild forces it).")
    try:
        tracker.current(con)  # the Tracker section opens up to date
    except Exception as e:  # the app still starts; the Tracker section reports the problem when opened
        print("Tracker not built:", repr(e))
    con.close()
    # Windows lets two servers share a port when address reuse is on; refuse instead, so a second copy cannot answer with old code.
    ThreadingHTTPServer.allow_reuse_address = False
    url = f"http://127.0.0.1:{port}/"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        print(f"Port {port} is already in use: the page is probably already running at {url} (close that window first, or use --port).")
        if open_browser:
            webbrowser.open(url)
        return
    print(f"Share Buyback Insight: {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
