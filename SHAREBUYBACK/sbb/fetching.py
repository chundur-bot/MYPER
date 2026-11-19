"""Read filings from a list: Excel or CSV rows naming a link, or a file name to join to a filing location.

Used by the app's upload and by fetch_from_list.py. The filing itself isn't kept; the figures and the link are.
Exchange sites are always refused, because their terms restrict automated collection. Other public addresses are refused
unless they are the location the user entered or are listed in data/allowed_hosts.txt.
"""
import csv
import html
import io
import ipaddress
import json
import re
import socket
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse, urlsplit, urlunsplit

from . import countries, db, ingest, parsers

COLUMNS = {
    "url": ("url", "link", "hyperlink", "file_link", "document_link", "download_link", "path", "file_path", "location", "pdf"),
    "file": ("file_name", "filename", "file", "document_name", "doc_name"),
    "ticker": ("ticker", "code", "asx_code", "stock_code", "symbol", "company_code", "nzx_code", "epic", "tidm"),
    "country": ("country", "market"),
    "date": ("date", "filing_date", "announcement_date", "release_date", "published", "publication_date"),
    "title": ("title", "headline", "subject", "announcement", "document_title"),
}
EXCHANGE_HOST = re.compile(r"(^|\.)(asx\.com\.au|asxonline\.com|markitdigital\.com|londonstockexchange\.com|lseg\.com|lse\.co\.uk|nzx\.com|sgx\.com|hkexnews\.hk|hkex\.com\.hk)$", re.I)
TYPES = {"application/pdf": ".pdf", "text/html": ".html", "text/plain": ".txt", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx", "application/vnd.ms-excel": ".xls"}
STOP_AFTER_FAILURES = 5
MAX_BYTES = 50_000_000  # a filing larger than this isn't read
RETRY_WAIT = 2  # seconds before the one retry when the server answers with an error of its own
ALLOWED_HOSTS = set()  # named by the user; an exchange site can never be one
SETTINGS = db.ROOT / "data" / "settings.json"
DEFAULT_LOCATION = "http://ffdocproxy.prod.factset.com/DocProxy/Fetch/"  # your system's own links use http; used until another location is entered
OLD_DEFAULTS = ("https://ffdocproxy.prod.factset.com/DocProxy/Fetch/",)  # earlier versions' default, replaced if it was saved
SCHEME = DEFAULT_LOCATION.split(":", 1)[0]  # for links pasted without their start
DOCUMENT_SUFFIX = "~0~nocache"  # your system's links end with this after a document ID
DOCUMENT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
LINKS_FILE = db.ROOT / "filing_links.csv"  # every accepted filing and its link
LISTS_FOLDER = db.ROOT / "filing_lists"  # the default place for Excel lists


def norm(header):
    return re.sub(r"[^a-z0-9]+", "_", str(header or "").strip().lower()).strip("_")


def cell_link(cell, formula):
    """A document ID shown in the cell is what counts, so the link is built from it. Otherwise a link can sit behind the
    display text, or in a HYPERLINK formula, and either is preferred to the text shown."""
    if DOCUMENT_ID.fullmatch(str(cell.value or "").strip().split("~")[0]):
        return cell.value
    if cell.hyperlink is not None and cell.hyperlink.target:
        return cell.hyperlink.target
    found = re.match(r'\s*=\s*HYPERLINK\(\s*"([^"]+)"', str(formula.value or ""), re.I)
    return found.group(1) if found else cell.value


def read_rows(path):
    """Rows as (row number, dict) with normalised headings. The heading row is the first naming a link or file name column."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        sheet = load_workbook(path, read_only=False, data_only=True).active
        formulas = load_workbook(path, read_only=False, data_only=False).active
        table = [[cell_link(c, f) for c, f in zip(row, raw)] for row, raw in zip(sheet.iter_rows(), formulas.iter_rows())]
    else:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
            table = list(csv.reader(fh))
    for i, row in enumerate(table):
        headings = [norm(c) for c in row]
        if any(h in COLUMNS["url"] or h in COLUMNS["file"] for h in headings):
            return [(i + j + 2, dict(zip(headings, r))) for j, r in enumerate(table[i + 1:]) if any(str(v or "").strip() for v in r)]
    raise ValueError(f"No link or file name column found. Expected a heading such as: File Name, {', '.join(COLUMNS['url'][:3])}")


def pick(row, kind):
    for name in COLUMNS[kind]:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return ""


def to_iso(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()[:10]
    return parsers.to_date(text) or ""


def is_share(link):
    return link.startswith("\\\\") or link.startswith("//") or link.lower().startswith("file:") or bool(re.match(r"[a-z]:[\\/]", link, re.I))  # includes mapped drives such as S:\filings


def share_path(link):
    return Path(unquote(urlparse(link).path).lstrip("/") if link.lower().startswith("file:") and re.match(r"file:/+[a-z]:", link, re.I) else (unquote(link[5:]) if link.lower().startswith("file:") else link))


def load_allowed_hosts(root=db.ROOT):
    f = Path(root) / "data" / "allowed_hosts.txt"
    if f.exists():
        ALLOWED_HOSTS.update(ln.strip().lower() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#"))


def request_address(link):
    """File names can hold spaces or other characters a request can't carry as they are. Anything already encoded stays as it is."""
    u = urlsplit(link)
    return urlunsplit((u.scheme, u.netloc, quote(u.path, safe="/%:@!$&'()*+,;=~-._"), quote(u.query, safe="=&%+:/?@!$'()*,;~-._"), ""))


def clean_link(link, scheme=None):
    """An export may give a link without its start, such as host.company.com/docproxy/abc."""
    link = str(link or "").strip()
    return f"{scheme or SCHEME}://{link}" if re.match(r"[a-z0-9][\w.-]*\.[a-z]{2,}(:\d+)?/", link, re.I) else link


def refusal(link):
    """Why this link must not be fetched, or None."""
    if is_share(link):
        return None
    u = urlparse(link)
    if u.scheme not in ("http", "https") or not u.hostname:
        return "Not a web link or file share"
    if EXCHANGE_HOST.search(u.hostname):
        return "Exchange site: refused, because exchange terms restrict automated collection"
    if u.hostname.lower() in ALLOWED_HOSTS:
        return None
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))}
    except OSError:
        return "Address not found from this PC"
    if not all(ipaddress.ip_address(a.split("%")[0]).is_private for a in addresses):
        return f"Public internet address: if {u.hostname} is your company's system, enter it as the filing location"
    return None


# ---------- filing location ----------
def base_location(location):
    """The address alone, if a full document link was entered as the location."""
    return re.sub(r"/[^/]*" + DOCUMENT_ID.pattern + r"[^/]*(/.*)?$", "/", location, flags=re.I)


def get_location():
    try:
        saved = base_location(json.loads(SETTINGS.read_text(encoding="utf-8")).get("filing_location", ""))
        return DEFAULT_LOCATION if not saved or saved in OLD_DEFAULTS else saved
    except (OSError, ValueError):
        return DEFAULT_LOCATION


def use_location(location):
    """Check the location the user entered, allow its host, and remember it. Raises ValueError with a plain reason."""
    location = base_location(clean_link(location))
    if not location:
        return ""
    if is_share(location):
        if not share_path(location).is_dir():
            raise ValueError(f"Folder not found from this PC: {location}")
    else:
        u = urlparse(location)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("The filing location must be a web address or a folder.")
        if EXCHANGE_HOST.search(u.hostname):
            raise ValueError("Exchange sites can't be used as a filing location, because their terms restrict automated collection.")
        ALLOWED_HOSTS.add(u.hostname.lower())
    SETTINGS.write_text(json.dumps({"filing_location": location}, indent=2), encoding="utf-8")
    return location


def lists_in_folder():
    """Excel and CSV lists waiting in the default folder, newest first."""
    LISTS_FOLDER.mkdir(exist_ok=True)
    found = [f for f in LISTS_FOLDER.iterdir() if f.is_file() and f.suffix.lower() in (".xlsx", ".xlsm", ".csv") and not f.name.startswith("~$")]
    return [{"name": f.name, "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"), "size": f.stat().st_size} for f in sorted(found, key=lambda f: -f.stat().st_mtime)]


def parse_pasted(text, ticker=""):
    """Rows from pasted lines: each line a link or document ID, optionally with its ticker in front. Needs no location unless a line is only an ID."""
    rows, default = [], re.sub(r"[^A-Z0-9.]", "", str(ticker or "").strip().upper())
    for n, line in enumerate(str(text or "").splitlines(), 1):
        parts = line.replace(",", " ").replace("\t", " ").split()
        if not parts:
            continue
        link = parts[-1]
        rows.append((n, {"ticker": parts[0].upper() if len(parts) > 1 else default, "hyperlink": link}))  # with no ticker, the document says which company
    return rows


def link_for(row, location, scheme=None):
    """(link, problem). A full link in the row is used as it is; a file name, in either column, is added to the location."""
    value = str(pick(row, "url")).strip()
    link = clean_link(value, scheme)
    if link and ("://" in link or is_share(link)):
        return link, None
    name = value or str(pick(row, "file")).strip()
    if not name:
        return "", "No link in this row"
    if not location:
        return "", "File name given, but no filing location entered"
    if ".." in re.split(r"[\\/]", name) or name.startswith(("/", "\\")) or re.match(r"[a-z]:", name, re.I):
        return "", f"File name isn't allowed: {name}"
    if is_share(location):
        sep = "/" if location.startswith("//") or location.lower().startswith("file:") else "\\"
        return location.rstrip("\\/") + sep + name, None
    return location.rstrip("/") + "/" + name + (DOCUMENT_SUFFIX if DOCUMENT_ID.fullmatch(name) else ""), None


# ---------- fetching ----------
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Each redirect is checked by hand, so a company link can't lead the script to an exchange or public site."""
    def redirect_request(self, *a, **k):
        return None


def _get(link):
    """(bytes, content type, final link) for a web link, checking every redirect."""
    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))  # never through an internet proxy
    retried = False
    for _ in range(6):
        why = refusal(link)
        if why:
            raise ValueError(why)
        try:
            with opener.open(urllib.request.Request(request_address(link), headers={"User-Agent": "ShareBuybackInsight/1.0 intranet"}), timeout=60) as r:
                data = r.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError(f"The file is larger than {MAX_BYTES // 1_000_000} MB, so it was not read")
                return data, (r.headers.get_content_type() or "").lower(), link
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                link = urljoin(link, e.headers["Location"])
                continue
            if e.code in (500, 502, 503, 504) and not retried:  # often passing: try once more
                retried = True
                time.sleep(RETRY_WAIT)
                continue
            raise ValueError(f"The server answered {e.code}")
        except urllib.error.URLError as e:
            if link.lower().startswith("https:") and "certificat" in str(e.reason).lower():
                raise ValueError(f"Could not connect securely: {e.reason}. If your system's links start with http://, change the Document address on Add data to http://")
            raise ValueError(f"Could not connect: {e.reason}")
        except OSError as e:
            raise ValueError(f"Could not connect: {e}")
    raise ValueError("Too many redirects")


def _extension(data, kind, link):
    if data[:5] == b"%PDF-":
        return ".pdf"
    if data[:4] == b"PK\x03\x04" and b"xl/workbook" in data:  # an Excel workbook, whatever the link ends with or the server calls it
        return ".xlsx"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" and b"W\x00o\x00r\x00k\x00b\x00o\x00o\x00k" in data:  # the older .xls
        return ".xls"
    return TYPES.get(kind) or (Path(urlparse(link).path).suffix.lower() if Path(urlparse(link).path).suffix.lower() in TYPES.values() else "")


def document_in_viewer(page, base):
    """The document address a viewer page points at, or None: an embedded frame first, then a link or script value ending in .pdf."""
    text = page.decode("utf-8", errors="replace")
    for pattern in (r"""<(?:iframe|embed|source)\b[^>]*?\bsrc\s*=\s*["']([^"']+)""", r"""<object\b[^>]*?\bdata\s*=\s*["']([^"']+)""",
                    r"""<meta\b[^>]*?http-equiv\s*=\s*["']refresh["'][^>]*?url\s*=\s*([^"'>\s]+)""",
                    r"""\bhref\s*=\s*["']([^"']+\.pdf(?:\?[^"']*)?)""", r"""["']((?:https?:)?[^"'\s<>]*\.pdf(?:\?[^"'\s<>]*)?)["']"""):
        m = re.search(pattern, text, re.I)
        if m:
            return urljoin(base, html.unescape(m.group(1)).replace("\\/", "/"))
    return None


def fetch(link):
    """(bytes, extension, what happened). A viewer page is followed to its document. Raises ValueError with a plain reason."""
    if is_share(link):
        p = share_path(link)
        if not p.is_file():
            raise ValueError("File not found")
        return p.read_bytes(), p.suffix.lower(), "file"
    data, kind, final = _get(link)
    note = kind
    if kind == "text/html" and data[:5] != b"%PDF-":
        inner = document_in_viewer(data, final)
        has_text = len(re.sub(r"\s+", "", re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", data.decode("utf-8", errors="replace"), flags=re.S | re.I))) >= 200
        if inner:
            try:
                data, kind, final = _get(inner)
                note = f"viewer page, document at {final} ({kind})"
            except ValueError:  # the frame may be a tracker, not the document, so a page with its own text is read as it is
                if not has_text:
                    raise
                note = "web page, read as it is"
        elif not has_text:
            raise ValueError("Viewer page: no document address found. Ask for a direct link to the document")
        else:
            note = "web page, read as it is"
    ext = _extension(data, kind, final)
    if not ext:
        raise ValueError(f"Not a filing type this app can read ({kind})")
    return data, ext, note


def unknown_codes(con, rows, market=""):
    """Codes given with links that aren't in the company list of the market they would be read under, each with the closest
    entries of that list. Asked about before reading, so a second spelling of a company (AVIVA beside AV) isn't added quietly."""
    out, seen = [], set()
    market = market if countries.get(market or "") else ""
    for _, row in rows:
        ticker = re.sub(r"[^A-Z0-9.]", "", str(pick(row, "ticker")).strip().upper())
        ticker = countries.code(re.sub(r"[^A-Z]", "", str(pick(row, "country")).strip().upper())[:3] or market, ticker)
        if not ticker or row.get("_reread") or row.get("_force"):
            continue
        country, problem = resolve_country(con, row, ticker, None, market)
        if problem or (country, ticker) in seen:
            continue
        seen.add((country, ticker))
        listed = [(r["ticker"], r["company"] or "") for r in con.execute("select ticker, company from companies where country=? and (in_index=1 or source is not null) order by ticker", (country,))]
        if any(t == ticker for t, _ in listed):
            continue
        code = ticker.lower()
        near = [(t, c) for t, c in listed if (len(code) >= 3 and code in c.lower()) or (len(t) >= 2 and ticker.startswith(t)) or (len(ticker) >= 2 and t.startswith(ticker))]
        out.append({"code": ticker, "country": country, "suggestions": [{"ticker": t, "company": c} for t, c in near[:4]]})
    return out


def resolve_country(con, row, ticker, default=None, market=""):
    """(country, problem). The row's Country first, then the given default, then the market chosen on the page if the ticker
    is on it or isn't known anywhere, then the study list and the name lists. A ticker known only on another market keeps that market."""
    stated = re.sub(r"[^A-Z]", "", str(pick(row, "country")).strip().upper())[:3]
    if stated:
        return (stated, None) if countries.get(stated) else ("", f"Unknown country {stated}")
    if default:
        return default, None
    if not ticker:
        return "", "No ticker in this row"
    if market and con.execute("select 1 from companies where country=? and ticker=?", (market, ticker)).fetchone():
        return market, None
    for clause in ("and in_index=1", ""):
        found = [r["country"] for r in con.execute(f"select country from companies where ticker=? {clause}", (ticker,))]
        if len(found) == 1:
            return found[0], None
        if len(found) > 1:
            return "", f"{ticker} is on more than one market: add a Country column"
    if market:
        return market, None
    return "", f"Unknown ticker {ticker}: choose its market at the top of the page, or add a Country column"


def links_csv(con):
    """Every accepted filing with its link, as CSV text. Links are written exactly as they were given."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Market", "Ticker", "Filing date", "Heading", "Type", "Status", "Hyperlink", "Read at"])
    us = lambda v: re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", r"\2/\3/\1", v) if isinstance(v, str) else v  # dates as MM/DD/YYYY
    w.writerows(tuple(us(v) for v in r) for r in con.execute("select country, ticker, doc_date, heading, doc_type, status, source_url, imported_at from documents where coalesce(source_url,'')<>'' order by doc_date desc, ticker"))
    return out.getvalue()


def write_links(con):
    """Keep filing_links.csv current. False if another program, such as Excel, has it open."""
    try:
        LINKS_FILE.write_text(links_csv(con), encoding="utf-8-sig", newline="")
        return True
    except OSError:
        return False


def country_from_document(con, data, ext, force=False):
    """The market of a filing given with no ticker, from the ticker or company name it states. Asks rather than guesses."""
    with tempfile.TemporaryDirectory() as folder:
        f = Path(folder) / f"filing{ext}"
        f.write_bytes(data)
        try:
            text = parsers.PAGE_BREAK.join(parsers.read_pages(f))
        except Exception as e:
            raise ValueError(f"The filing could not be read: {e}")
    if len(re.sub(r"\s", "", text)) < 40:
        raise ValueError("No readable text, so the company can't be told from it. Enter its ticker.")
    markets = countries.load()
    if not force and not parsers.is_buyback_filing(text, ""):
        return markets[0]["code"]  # nothing from it is kept, so the market doesn't matter
    stated = parsers.parse(text, markets[0]["currency"])["ticker"]
    found = {r["country"] for r in con.execute("select country from companies where ticker=?", (stated,))} if stated else set()
    if not found:
        found = {m["code"] for m in markets if parsers.match_company("", text, db.rows(con.execute("select ticker, company from companies where country=?", (m["code"],))))}
    if len(found) == 1:
        return found.pop()
    raise ValueError("Couldn't tell the company from this document. Enter its ticker.")


def process(con, rows, location="", default_country=None, delay=2.0, only_study=False, scheme=None, on_result=None, should_stop=None, on_start=None, market=""):
    """Read each row in turn. Links already handled are skipped, so a list can be run again. Returns counts by result."""
    counts = {"read": 0, "to review": 0, "not a buyback": 0, "not in study": 0, "already read": 0, "refused": 0, "failed": 0}
    seen, touched, failures_in_a_row = set(), set(), 0

    def report(number, row, link, result, detail=""):
        counts[result] = counts.get(result, 0) + 1
        if on_result:
            on_result(number, str(pick(row, "ticker")), link, result, detail)

    for number, row in rows:
        if should_stop and should_stop():
            break
        link, problem = link_for(row, location, scheme)
        if on_start:
            on_start(number, str(pick(row, "ticker")), link)
        if problem:
            report(number, row, link, "failed", problem)
            continue
        if link in seen:
            report(number, row, link, "already read", "Same link earlier in the list")
            continue
        seen.add(link)
        why = refusal(link)
        if why:
            report(number, row, link, "refused", why)
            continue
        ticker = re.sub(r"[^A-Z0-9.]", "", str(pick(row, "ticker")).strip().upper())
        ticker = countries.code(re.sub(r"[^A-Z]", "", str(pick(row, "country")).strip().upper())[:3] or default_country or market, ticker)  # 02429 and 2429 are one Hong Kong company
        country, problem = resolve_country(con, row, ticker, default_country, market)
        ticker = countries.code(country, ticker)
        from_document = not ticker and not country and problem == "No ticker in this row" and not only_study
        if problem and not from_document:
            report(number, row, link, "failed", problem)
            continue
        if only_study and not con.execute("select 1 from companies where country=? and ticker=? and in_index=1", (country, ticker)).fetchone():
            report(number, row, link, "not in study", ticker)
            continue
        reread = bool(row.get("_reread"))  # read again with the current parser: the old figures go only once the link has opened
        force = bool(row.get("_force")) or reread
        if not force and con.execute("select 1 from documents where source_url=? union select 1 from skipped_links where link=?", (link, link)).fetchone():
            report(number, row, link, "already read", "This link was handled earlier")
            continue
        try:
            data, ext, how = fetch(link)
            if not data:
                raise ValueError("The file is empty")
            if row.get("_layout") and not ingest.layout_reads(data, ext, country, row["_layout"]):  # read again only where a layout now reads it
                report(number, row, link, "already read", "No approved layout reads this filing, so it was left as it was")
                continue
            if reread:
                ingest.forget_filing(con, link)
            if from_document:
                try:
                    country = country_from_document(con, data, ext, force)
                except ValueError:
                    if not market:
                        raise
                    country = market  # the company can then be chosen under To review
            ingest.NOTE["text"] = ""
            status = ingest.import_link(con, link, country, data, ext, ticker, str(pick(row, "title")).strip(), to_iso(pick(row, "date")), force)
            if force:
                con.execute("delete from skipped_links where link=?", (link,))
            con.commit()
            held = [(r["country"], r["ticker"]) for r in con.execute("select country, ticker from documents where source_url=?", (link,))]
            touched.update(x for x in held if x[1])
            if len(held) > 1:  # a report listing many companies
                row = {**row, "ticker": f"{len(held)} companies"}
            elif from_document:  # show which company the document turned out to be
                row = {**row, "ticker": (held[0][1] if held else "") or ""}
            kind = {"PARSED": "read", "NEEDS_REVIEW": "to review", "NOT_BUYBACK": "not a buyback"}.get(status, "already read")
            report(number, row, link, kind, ("Same content as a filing already read" if status == "already saved" else f"{status}; {how}") + (f". {ingest.NOTE['text']}" if ingest.NOTE["text"] else ""))
            failures_in_a_row = 0
        except ValueError as e:
            report(number, row, link, "failed", str(e))
            failures_in_a_row += 1
            if failures_in_a_row >= STOP_AFTER_FAILURES:
                if on_result:  # not a row, so it isn't counted as one
                    on_result(number, str(pick(row, "ticker")), "", "stopped", f"Stopped after {STOP_AFTER_FAILURES} failures in a row. Check the system, then run again.")
                break
        if delay:
            time.sleep(max(delay, 0))
    for market, code in touched:  # a backfill can arrive in any order, so settle each company's programmes by date
        ingest.replay(con, market, code)
    con.commit()
    if not (should_stop and should_stop()):
        ingest.mark_settled(con)  # every company touched was rebuilt, so the next start has nothing to do
    if not write_links(con) and on_result:
        on_result("-", "", "", "note", f"Couldn't update {LINKS_FILE.name} because another program has it open. Close it: the file updates on the next run, and the app keeps the links.")
    return counts
