"""Import saved files from inbox/<country>/ into the database. A file is read once, keyed on its content hash."""
import csv
import functools
import hashlib
import json
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path

from . import countries, crosslist, db, hkex, parsers


def _labelled(read):
    """Name the form and type of whatever was just read, by every route."""
    @functools.wraps(read)
    def run(con, *a, **k):
        result = read(con, *a, **k)
        db.fill_labels(con)
        return result
    return run

_RULES = {"stamp": None, "rows": {}}
NOTE = {"text": ""}  # something to tell the user about the filing just read, beyond its status
_REPLAY = {"on": False}  # while a company is rebuilt, the cross-listing check waits until every purchase is back


def treatment_rule(country, ticker):
    """(treatment, text) that law gives a market's buybacks when a notice doesn't say, from data/treatment_rules.csv, or None.
    except_tickers lists companies it doesn't apply to, such as one incorporated elsewhere. The text must start with "Rule"."""
    f = db.ROOT / "data" / "treatment_rules.csv"
    try:
        stamp = f.stat().st_mtime_ns
    except OSError:
        return None
    if _RULES["stamp"] != stamp:
        with f.open(encoding="utf-8-sig", newline="") as fh:
            _RULES["rows"] = {r["country"].strip().upper(): r for r in csv.DictReader(fh) if (r.get("text") or "").startswith("Rule") and (r.get("treatment") or "").strip()}
        _RULES["stamp"] = stamp
    r = _RULES["rows"].get(country)
    if not r or str(ticker or "").upper() in {t.strip().upper() for t in re.split(r"[;, ]+", r.get("except_tickers") or "") if t.strip()}:
        return None
    return r["treatment"].strip(), r["text"].strip()


def same_code(country, a, b):
    """Whether two company codes are the same company's, as that market writes them."""
    return countries.code(country, str(a or "").upper()) == countries.code(country, str(b or "").upper())


FILE_TYPES = {".csv"}  # typed entries only; filings are read from links and not saved
CSV_COLUMNS = ["ticker", "trade_date", "shares", "value", "currency", "avg_price", "high", "low", "venue", "announced_date"]


def programme_id(con, country, ticker, prog, trade_date=None):
    """Find or create the programme. A notice that names no announcement date joins the company's latest programme."""
    announced = (prog or {}).get("announced_date") or ""
    if not announced:
        row = con.execute("""select prog_id from programmes where country=? and ticker=? and (coalesce(?3,'') = '' or announced_date <= ?3)
            order by announced_date desc limit 1""", (country, ticker, trade_date)).fetchone()
        if row:
            return row["prog_id"]
    row = con.execute("select prog_id from programmes where country=? and ticker=? and announced_date=?", (country, ticker, announced)).fetchone()
    if row:
        return row["prog_id"]
    # a notice that restates an open programme's size, and gives no dates of its own, is that programme and not a new one
    if (prog or {}).get("announced_assumed") and not prog.get("start_date") and not prog.get("end_date"):
        same = con.execute("""select prog_id from programmes where country=?1 and ticker=?2 and announced_date<>'' and announced_date<?3 and coalesce(status,'ACTIVE')<>'COMPLETED' and (end_date is null or end_date>=?3)
            and ((max_value is not null and max_value=?4 and max_currency is ?5) or (max_value is null and max_shares is not null and max_shares=?6)) order by announced_date desc limit 1""",
                           (country, ticker, announced, prog.get("max_value"), prog.get("max_currency"), prog.get("max_shares"))).fetchone()
        if same:
            return same["prog_id"]
    cur = con.execute("insert into programmes(country,ticker,announced_date) values(?,?,?)", (country, ticker, announced))
    return cur.lastrowid


def store(con, doc_id, country, ticker, p):
    """Save programme terms, purchases and running totals. Newer notices fill gaps and update what they restate."""
    last_date = max([x["trade_date"] for x in p["transactions"]] + [s["as_of"] for s in p["snapshots"] if s["as_of"]] + [p.get("doc_date") or ""], default=None)
    pid = programme_id(con, country, ticker, p["programme"], last_date)
    prog = p["programme"]
    if parsers.covering_dates(p):  # a reading kept from an earlier version: the week a purchase notice covers is not the programme's start and end
        prog = {k: v for k, v in prog.items() if k not in ("start_date", "end_date")}
    if prog.get("treatment"):  # a notice's own wording replaces a rule stored earlier, in whatever order the notices are read
        con.execute("update programmes set treatment=null, treatment_text=null, treatment_doc=null where prog_id=? and treatment_text like 'Rule%'", (pid,))
    if prog.get("announced_assumed"):
        first = con.execute("select announced_date from programmes where prog_id=?", (pid,)).fetchone()["announced_date"]
        if first != prog.get("announced_date"):
            _review(con, doc_id, country, ticker, "PROGRAMME_RESTATED", f"This notice states the same size as the programme announced {first}, which is still open, so it was added to that programme and not started as a new one. Check that it isn't a new programme.")
    # Files can arrive in any order, and terms change (CSL raised a size in February 2026): the newest notice's terms win; an older one only fills gaps.
    held = con.execute("select terms_date from programmes where prog_id=?", (pid,)).fetchone()["terms_date"]
    doc_date = p.get("doc_date") or ""
    newer = not held or doc_date >= held
    if newer and doc_date:
        con.execute("update programmes set terms_date=? where prog_id=?", (doc_date, pid))
    size_given = prog.get("max_value") is not None
    for field in ("broker", "buyback_type", "start_date", "end_date", "max_shares", "max_value", "max_currency", "shares_on_issue", "status", "treatment", "treatment_text", "end_note", "size_note", "max_pct", "intended_shares"):
        value = prog.get(field)
        if field == "max_currency" and not size_given:
            continue
        if value is not None:
            con.execute(f"update programmes set {field}={'?' if newer else f'coalesce({field},?)'} where prog_id=?", (value, pid))
    if newer and any(prog.get(k) is not None for k in ("start_date", "end_date", "max_shares", "max_value", "max_pct", "intended_shares")):
        con.execute("update programmes set terms_doc=? where prog_id=?", (doc_id, pid))  # which filing or hand entry the terms in force came from
    if newer and prog.get("status") is not None:
        con.execute("update programmes set status_doc=? where prog_id=?", (doc_id, pid))
    con.execute("update programmes set source_doc=coalesce(source_doc,?) where prog_id=?", (doc_id, pid))
    rule = None if prog.get("treatment") else treatment_rule(country, ticker)
    if rule:  # the law says what happens to the shares and a notice need not: a rule, marked as one, and it only fills a gap
        con.execute("update programmes set treatment=?, treatment_text=?, treatment_doc=? where prog_id=? and treatment is null", (rule[0], rule[1], doc_id, pid))
    if prog.get("treatment"):
        con.execute(f"update programmes set treatment_doc={'?' if newer else 'coalesce(treatment_doc,?)'} where prog_id=?", (doc_id, pid))
    if prog.get("shares_on_issue") and doc_date:
        con.execute("insert or replace into share_counts values(?,?,?,?,?)", (country, ticker, doc_date, prog["shares_on_issue"], doc_id))
    for c in p.get("cancellations", []):
        con.execute("insert or replace into cancellations(doc_id,prog_id,country,ticker,as_of,venue,shares,kind,note,basis) values(?,?,?,?,?,?,?,?,?,?)", (doc_id, pid, country, ticker, c["as_of"], c["venue"], c["shares"], c["kind"], c["note"], c.get("basis")))
    for x in p["transactions"]:
        con.execute("""insert into transactions(prog_id,country,ticker,trade_date,venue,shares,value,currency,price_avg,price_high,price_low,price_unit,doc_id,value_origin,broker,broker_role,broker_text,security)
            values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict(prog_id,trade_date,venue,price_unit) do update set shares=excluded.shares, value=excluded.value,
            currency=excluded.currency, price_avg=excluded.price_avg, price_high=excluded.price_high, price_low=excluded.price_low, doc_id=excluded.doc_id, value_origin=excluded.value_origin,
            broker=excluded.broker, broker_role=excluded.broker_role, broker_text=excluded.broker_text, security=excluded.security""",
                    (pid, country, ticker, x["trade_date"], x.get("venue") or "", x["shares"], x["value"], x["currency"], x["price_avg"], x["price_high"], x["price_low"], x.get("price_unit") or "", doc_id, x.get("value_origin") or "entered",
                     x.get("broker"), x.get("broker_role"), x.get("broker_text"), x.get("security")))
    for v in p.get("venue_totals", []):
        con.execute("insert or replace into venue_totals values(?,?,?,?,?,?,?,?,?)", (pid, v["venue"], v["trade_date"], v["shares"], v["price_avg"], v.get("price_unit") or "", v["value"], v["currency"], doc_id))
    for s in _dated_totals(con, pid, doc_id, country, ticker, p):
        if s["as_of"]:  # a total worked out (origin sum, product) never replaces one a notice states on the same day
            con.execute("""insert into snapshots(prog_id,as_of,cum_shares,cum_value,currency,doc_id,origin,working) values(?,?,?,?,?,?,?,?)
                on conflict(prog_id,as_of) do update set cum_shares=excluded.cum_shares, cum_value=coalesce(excluded.cum_value,cum_value), currency=excluded.currency, doc_id=excluded.doc_id, origin=excluded.origin, working=excluded.working
                where excluded.origin in ('reported', 'rounded', 'hand') or coalesce(snapshots.origin, '') not in ('reported', 'rounded', 'hand')""",
                        (pid, s["as_of"], s["cum_shares"], s["cum_value"], s["currency"], doc_id, s.get("origin"), s.get("working")))
    return pid


STATED = ("reported", "rounded", "hand")


def _weekday_before(day):
    d = date.fromisoformat(day) - timedelta(days=1)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d.isoformat()


def _same(a, b):
    """Two totals agree: the same shares, and amounts equal to the cent where both are stated."""
    return a["cum_shares"] == b["cum_shares"] and (a.get("currency") or "") == (b.get("currency") or "") and (a["cum_value"] is None or b["cum_value"] is None or abs(a["cum_value"] - b["cum_value"]) < 0.005)


def _dated_totals(con, pid, doc_id, country, ticker, p):
    """An ASX daily notice states the total 'before the previous day' (field 4.3/4.4) and the purchase on that day D. The reading dates the
    'before' total D minus one calendar day, which can be a weekend. Here it is dated to the programme's last purchase day before D, where
    the closing total held for that day agrees with it. Where it doesn't agree, purchases are missing between the two, so it is dated the
    weekday before D and goes to review (TOTAL_GAP). Where only the amount differs (the same shares), it is the same day: dated there, the notice's
    figure kept, and the difference goes to review (TOTAL_DIFFERS). With no earlier purchase it is dated the weekday before D, and a total of 0 is not kept.
    Nothing else is changed. Works on readings kept from earlier versions, so a rebuild corrects them without reading filings again."""
    snaps = [dict(s) for s in p["snapshots"]]
    if not (p.get("form") in ("appendix_3c", "appendix_3e") and p.get("doc_type") == "daily" and len(snaps) == 2 and p["transactions"] and snaps[0].get("origin") == "reported"):
        return snaps
    before, day = snaps[0], p["transactions"][0]["trade_date"]
    if not day:
        return snaps
    last = con.execute("select max(trade_date) from transactions where prog_id=? and trade_date<?", (pid, day)).fetchone()[0]
    if not last:
        if not before["cum_shares"] and not before["cum_value"]:
            return snaps[1:]  # nothing bought before: a total of 0 says nothing
        before["as_of"] = _weekday_before(day)
        return snaps
    held = con.execute("select cum_shares, cum_value, currency from snapshots where prog_id=? and as_of=?", (pid, last)).fetchone()
    if held is None or _same(dict(held), before):
        before["as_of"] = last
        return snaps
    v = lambda x: f"{before['currency']} {x:,.2f}" if x is not None else "no amount"
    if held["cum_shares"] == before["cum_shares"] and (held["currency"] or "") == (before["currency"] or ""):  # the same shares: the same day, only the amount differs
        before["as_of"] = last
        _review(con, doc_id, country, ticker, "TOTAL_DIFFERS",
                f"This notice states {v(before['cum_value'])} paid for {before['cum_shares']:,.0f} shares bought before {day}. The total held for {last}, worked out from the notices read, "
                f"is {v(held['cum_value'])} for the same shares. The notice's figure is kept, as Reported.")
        return snaps
    before["as_of"] = _weekday_before(day)
    _review(con, doc_id, country, ticker, "TOTAL_GAP",
            f"This notice states {before['cum_shares']:,.0f} shares ({v(before['cum_value'])}) bought before {day}, but the total held after the last purchase read, on {last}, "
            f"is {held['cum_shares']:,.0f} shares ({v(held['cum_value'])}). Notices for days in between may be missing from your list. The notice's total is dated {before['as_of']}.")
    return snaps


def _ensure_company(con, country, ticker, name):
    con.execute("insert into companies(country,ticker,company,in_index) values(?,?,?,1) on conflict(country,ticker) do update set in_index=1", (country, ticker, name or ticker))  # a saved notice puts a company in the study


def _review(con, doc_id, country, ticker, kind, detail):
    if con.execute("select 1 from review where doc_id is ? and kind=? and detail=?", (doc_id, kind, detail)).fetchone():  # a filing read again doesn't repeat it, or undo a dismissal
        return
    con.execute("insert into review(doc_id,country,ticker,kind,detail,created_at) values(?,?,?,?,?,?)", (doc_id, country, ticker, kind, detail, db.now()))


def _norm(header):
    return re.sub(r"[^a-z0-9]+", "_", (header or "").strip().lower()).strip("_")


def import_announcement_list(con, path, country, rows):
    """A list exported by hand, such as an FCA National Storage Mechanism search. It shows which notices exist; it holds no figures."""
    pick = lambda r, names: next((r[n] for n in names if r.get(n)), "")
    saved = 0
    terms = [t.lower() for t in countries.get(country).get("search_terms", [])] + ["own shares", "buyback", "buy-back", "repurchase"]
    for r in rows:
        title = pick(r, ("title", "headline", "headline_name", "subject", "document_title", "announcement"))
        if not any(t in title.lower() for t in terms):
            continue
        raw = pick(r, ("date", "publication_date", "published", "release_date", "document_date"))
        con.execute("insert or ignore into announcement_list values(?,?,?,?,?,?)",
                    (country, pick(r, ("company", "organisation_name", "organisation", "issuer", "company_name", "name")), parsers.to_date(raw[:10]) or raw, title, pick(r, ("url", "link", "download_link", "document_link")), path.name))
        saved += 1
    return saved


def import_programmes(con, rows, country, doc_id):
    saved, problems = 0, []
    for i, r in enumerate(rows, 2):
        ticker, announced = r.get("ticker", "").upper(), parsers.to_date(r.get("announced_date"))
        if not ticker or not announced:
            problems.append(f"Row {i}: needs ticker and announced_date.")
            continue
        _ensure_company(con, country, ticker, r.get("company"))
        store(con, doc_id, country, ticker, {"transactions": [], "snapshots": [], "doc_date": announced, "programme": {"announced_date": announced, "buyback_type": r.get("type") or None,
              "end_date": parsers.to_date(r.get("end_date")), "max_value": parsers.num(r.get("max_value")), "max_currency": (r.get("currency") or countries.get(country)["currency"]).upper(),
              "max_shares": parsers.num(r.get("max_shares")), "status": (r.get("status") or "ACTIVE").upper()}})
        saved += 1
    return saved, problems


def import_csv(con, path, country, doc_id):
    """A hand-entry template or an exported announcement list. Returns (rows saved, problems, kind)."""
    home = countries.get(country)["currency"]
    saved, problems = 0, []
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        reader.fieldnames = [_norm(h) for h in (reader.fieldnames or [])]
        if "ticker" in reader.fieldnames and "announced_date" in reader.fieldnames and "trade_date" not in reader.fieldnames:
            return (*import_programmes(con, [{k: (v or "").strip() for k, v in r.items() if k} for r in reader], country, doc_id), "programmes csv")
        if "ticker" not in reader.fieldnames or "trade_date" not in reader.fieldnames:
            return import_announcement_list(con, path, country, [{k: (v or "").strip() for k, v in r.items() if k} for r in reader]), [], "announcement list"
        for i, r in enumerate(reader, 2):
            ticker, trade = (r.get("ticker") or "").strip().upper(), parsers.to_date(r.get("trade_date"))
            shares = parsers.num(r.get("shares"))
            if not ticker or not trade or shares is None:
                problems.append(f"Row {i}: needs ticker, trade_date and shares.")
                continue
            cur = (r.get("currency") or home).strip().upper()
            value, avg = parsers.num(r.get("value")), parsers.num(r.get("avg_price"))
            value = value if value is not None else (shares * avg if avg is not None else None)
            _ensure_company(con, country, ticker, None)
            store(con, doc_id, country, ticker, {"programme": {"announced_date": parsers.to_date(r.get("announced_date")) or ""}, "snapshots": [], "doc_date": trade,
                  "transactions": [{"trade_date": trade, "venue": (r.get("venue") or "").strip(), "shares": shares, "value": value, "currency": cur, "price_unit": cur,
                                    "price_avg": avg if avg is not None else (value / shares if value and shares else None), "price_high": parsers.num(r.get("high")), "price_low": parsers.num(r.get("low"))}]})
            saved += 1
    return saved, problems, "transactions csv"


def import_prices(con):
    """Optional closing prices for the reaction study: inbox/prices.csv with country,ticker,date,close."""
    f = countries.INBOX / "prices.csv"
    if not f.exists():
        return 0
    n = 0
    with f.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            d, c = parsers.to_date(r.get("date")), parsers.num(r.get("close"))
            if d and c is not None:
                con.execute("insert or replace into prices values(?,?,?,?)", (r["country"].strip().upper(), r["ticker"].strip().upper(), d, c))
                n += 1
    return n


@_labelled
def import_file(con, path, country, sha):
    home = countries.get(country)["currency"]
    rel = str(path.relative_to(db.ROOT)).replace("\\", "/")
    cur = con.execute("insert into documents(sha256,country,file_name,rel_path,status,imported_at) values(?,?,?,?,?,?)", (sha, country, path.name, rel, "NEW", db.now()))
    doc_id = cur.lastrowid
    if path.suffix.lower() == ".csv":
        saved, problems, kind = import_csv(con, path, country, doc_id)
        for x in problems:
            _review(con, doc_id, country, None, "CSV_ROW", x)
        status = "NEEDS_REVIEW" if problems else "PARSED"
        con.execute("update documents set doc_type=?, status=?, message=? where doc_id=?", (kind, status, f"{saved} rows saved", doc_id))
        return status
    try:
        pages = parsers.read_pages(path)
        for n, page in enumerate(pages, 1):
            con.execute("insert or replace into doc_pages values(?,?,?)", (doc_id, n, page))
        text = parsers.PAGE_BREAK.join(pages)
    except Exception as e:  # a damaged or protected file must not stop the rest of the folder
        _review(con, doc_id, country, None, "UNREADABLE", f"The file could not be read: {e}")
        con.execute("update documents set status='NEEDS_REVIEW', message='Unreadable' where doc_id=?", (doc_id,))
        return "NEEDS_REVIEW"
    if len(re.sub(r"\s", "", text)) < 40:
        _review(con, doc_id, country, None, "NO_TEXT", "No readable text. This may be a scanned PDF: it can be viewed, but it needs text recognition (OCR) before it can be read or highlighted. Please enter the figures by hand.")
        con.execute("update documents set status='NEEDS_REVIEW', message='No text' where doc_id=?", (doc_id,))
        return "NEEDS_REVIEW"
    p = parsers.parse(text, home, country, countries.get(country).get("date_order"))
    companies = db.rows(con.execute("select ticker, company from companies where country=?", (country,)))
    ticker = p["ticker"] or parsers.match_company(path.name, text, companies)
    if ticker:
        _ensure_company(con, country, ticker, p["company"])
    for kind, detail in p["issues"]:
        _review(con, doc_id, country, ticker, kind, detail)
    is_3h = p["form"] == "appendix_3h"
    has_facts = p["transactions"] or p["snapshots"] or p["doc_type"] == "programme" or p["form"] == "appendix_3c" or (is_3h and p.get("cessations")) or (p["form"] == "notice" and p["doc_type"] == "update") or (p["form"] in ("hkex_monthly", "hkex_ndr") and p.get("cancellations")) or (p["form"] == "appendix_3g" and (p.get("issued") or p.get("on_issue"))) or (p["form"] == "appendix_3d" and any(v is not None for v in (p.get("programme") or {}).values()))
    if has_facts and not ticker:
        _review(con, doc_id, country, None, "NO_COMPANY", "Figures were found, but not the company. Choose the company for this file.")
    if has_facts and ticker:
        if is_3h:
            store_cessations(con, doc_id, country, ticker, p)
            _link_cessations(con, country, ticker)
        elif p["form"] == "appendix_3g":
            store_issues(con, doc_id, country, ticker, p)
        else:
            store(con, doc_id, country, ticker, p)
    save_evidence(con, doc_id, text, p)
    status = "PARSED" if has_facts and ticker and not p["issues"] else "NEEDS_REVIEW"
    message = f"{len(p['cessations'])} cessations" if is_3h else f"{len(p.get('issued') or [])} issues of securities" if p["form"] == "appendix_3g" else f"{len(p['transactions'])} purchases, {len(p['snapshots'])} totals"
    if p.get("date_basis"):
        message += f". No filing date stated, so dated from {p['date_basis']}"
    con.execute("update documents set ticker=?, company_raw=?, doc_type=?, doc_date=?, status=?, message=?, reason=?, form=? where doc_id=?",
                (ticker, p["company"], p["doc_type"], p["doc_date"], status, message, p.get("reason"), p["form"], doc_id))
    return status


def save_evidence(con, doc_id, text, p):
    con.execute("delete from evidence where doc_id=?", (doc_id,))
    for e in parsers.evidence(text, p):
        con.execute("insert into evidence(doc_id,key,field,page,text,context) values(?,?,?,?,?,?)", (doc_id, e["key"], e["field"], e["page"], e["text"], e["context"]))


def merge_undated(con):
    """A notice read before its programme's announcement can leave an undated programme; join it to the dated one it belongs to."""
    for u in db.rows(con.execute("select * from programmes where announced_date=''")):
        first = con.execute("select min(d) d from (select trade_date d from transactions where prog_id=?1 union select as_of from snapshots where prog_id=?1)", (u["prog_id"],)).fetchone()["d"]
        dated = con.execute("""select prog_id from programmes where country=? and ticker=? and announced_date<>'' and announced_date<=coalesce(?,'9999') order by announced_date desc limit 1""",
                            (u["country"], u["ticker"], first)).fetchone()
        if dated:
            for table in ("transactions", "snapshots", "venue_totals", "cancellations"):
                con.execute(f"update or replace {table} set prog_id=? where prog_id=?", (dated["prog_id"], u["prog_id"]))
            for field in ("max_value", "max_currency", "shares_on_issue", "max_shares", "treatment", "treatment_text", "treatment_doc"):
                if u[field] is not None:
                    con.execute(f"update programmes set {field}=coalesce({field},?) where prog_id=?", (u[field], dated["prog_id"]))
            con.execute("delete from programmes where prog_id=?", (u["prog_id"],))


def _apply_link(con, doc_id, country, hint, p, ev):
    """Save what a link filing's figures say. Shared by the first read, choosing a company, and a re-read of the folders."""
    ticker = p["ticker"] or hint
    if ticker:
        _ensure_company(con, country, ticker, p["company"])
    for kind, detail in p["issues"]:
        _review(con, doc_id, country, ticker, kind, detail)
    is_3h = p["form"] == "appendix_3h"
    has_facts = p["transactions"] or p["snapshots"] or p["doc_type"] == "programme" or p["form"] == "appendix_3c" or (is_3h and p.get("cessations")) or (p["form"] == "notice" and p["doc_type"] == "update") or (p["form"] in ("hkex_monthly", "hkex_ndr") and p.get("cancellations")) or p["form"] == "manual" or (p["form"] == "appendix_3g" and (p.get("issued") or p.get("on_issue"))) or (p["form"] == "appendix_3d" and any(v is not None for v in (p.get("programme") or {}).values()))  # an entry made by hand always holds what you typed
    if has_facts and not ticker:
        _review(con, doc_id, country, None, "NO_COMPANY", "Figures were found, but not the company. Choose the company for this filing.")
    if has_facts and ticker:
        if is_3h:
            store_cessations(con, doc_id, country, ticker, p)
        elif p["form"] == "appendix_3g":
            store_issues(con, doc_id, country, ticker, p)
        else:
            store(con, doc_id, country, ticker, p)
    con.execute("delete from evidence where doc_id=?", (doc_id,))
    for e in ev:
        con.execute("insert into evidence(doc_id,key,field,page,text,context) values(?,?,?,?,?,?)", (doc_id, e["key"], e["field"], e["page"], e["text"], e["context"]))
    status = "PARSED" if has_facts and ticker and not p["issues"] else "NEEDS_REVIEW"
    message = f"{len(p['cessations'])} cessations" if is_3h else f"{len(p.get('issued') or [])} issues of securities" if p["form"] == "appendix_3g" else f"{len(p['transactions'])} purchases, {len(p['snapshots'])} totals"
    if p.get("date_basis"):
        message += f". No filing date stated, so dated from {p['date_basis']}"
    con.execute("update documents set ticker=?, company_raw=?, doc_type=?, doc_date=?, status=?, message=?, reason=? where doc_id=?",
                (ticker, p["company"], p["doc_type"], p["doc_date"], status, message, p.get("reason"), doc_id))
    if not p["transactions"] and not p["snapshots"] and p.get("cancellations") and str(p["form"]).startswith("hkex_"):
        con.execute("update documents set message=? where doc_id=?", (f"{len(p['cancellations'])} cancellation or treasury counts, no purchase", doc_id))
    if p["form"] == "manual":
        con.execute("update documents set message=? where doc_id=?", ("Entered by hand. Source: " + str((p.get("manual") or {}).get("source") or "")[:200], doc_id))
    if crosslist.concerns(country, ticker) and not _REPLAY["on"]:  # a company listed in two markets: mark a purchase that the other market's notices also report
        crosslist.link(con)
    if ticker and has_facts and not _REPLAY["on"]:
        from . import hand  # imported here: hand uses this module
        if hand.has_updates(con, country, ticker):  # a new filing may restate a figure Updated Manually: the update stays in force
            hand.apply_updates(con, country, ticker, rebuilt=False)
    return status


def store_issues(con, doc_id, country, ticker, p):
    """Appendix 3G: securities issued, transferred or converted, one row each, and the securities on issue afterwards. Kept apart from purchases."""
    con.execute("delete from issues where doc_id=?", (doc_id,))
    for i, x in enumerate(p.get("issued") or []):
        con.execute("""insert into issues(doc_id,n,country,ticker,security_code,security,shares,issued_on,from_security,provided_by,other_info) values(?,?,?,?,?,?,?,?,?,?,?)""",
                    (doc_id, i, country, ticker, x["security_code"], x["security"], x["shares"], x["issued_on"], x.get("from_security"), x.get("provided_by"), x.get("other_info")))
    held = p.get("on_issue")
    if held and held.get("shares") and p.get("doc_date"):
        con.execute("insert or replace into share_counts values(?,?,?,?,?)", (country, ticker, p["doc_date"], held["shares"], doc_id))


def store_cessations(con, doc_id, country, ticker, p):
    """Appendix 3H entries. A later filing restating the same security, date and reason replaces the earlier one."""
    for i, c in enumerate(p["cessations"]):
        con.execute("delete from cessations where country=? and ticker=? and security_code=? and ceased_on=? and reason=? and doc_id<>?", (country, ticker, c["security_code"], c["ceased_on"], c["reason"], doc_id))
        con.execute("""insert or replace into cessations(doc_id,n,country,ticker,security_code,security,quoted,shares,reason,is_buyback,ceased_on,consideration,currency,other_info,issued_after)
            values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (doc_id, i, country, ticker, c["security_code"], c["security"], c["quoted"], c["shares"], c["reason"], c["is_buyback"], c["ceased_on"], c["consideration"], c["currency"], c["other_info"], c["issued_after"]))


def _link_cessations(con, country, ticker):
    """A buy-back cancellation belongs to the latest programme announced by its date that had bought by then; failing that, the latest announced. Other cessations, such as lapsed rights, belong to none."""
    con.execute("update cessations set prog_id=null where country=? and ticker=?", (country, ticker))
    for c in con.execute("select doc_id, n, ceased_on from cessations where country=? and ticker=? and is_buyback=1", (country, ticker)).fetchall():
        found = con.execute("""select p.prog_id from programmes p where p.country=? and p.ticker=? and p.announced_date<>'' and p.announced_date<=?1
            order by (exists (select 1 from transactions t where t.prog_id=p.prog_id and t.trade_date<=?1) or exists (select 1 from snapshots s where s.prog_id=p.prog_id and s.as_of<=?1)) desc,
            p.announced_date desc limit 1""".replace("p.country=? and p.ticker=?", "p.country=?2 and p.ticker=?3"), (c["ceased_on"], country, ticker)).fetchone()
        if found:
            con.execute("update cessations set prog_id=? where doc_id=? and n=?", (found["prog_id"], c["doc_id"], c["n"]))
    for r in con.execute("select doc_id, ceased_on from cessations where country=? and ticker=? and is_buyback=1 and prog_id is null", (country, ticker)).fetchall():
        _review(con, r["doc_id"], country, ticker, "NO_PROGRAMME", f"A buy-back cancellation on {r['ceased_on']} is before any programme announcement read for {ticker}. The announcement may be missing from your list.")


def _flag_placement(con, country, ticker, docs):
    """Notices that name no programme are placed by date. Say when no announcement read so far really covers the date, rather than guessing."""
    con.execute("delete from review where country=? and ticker=? and kind='NO_PROGRAMME' and status='OPEN'", (country, ticker))
    con.execute("update transactions set waiting=null where country=? and ticker=?", (country, ticker))
    con.execute("update snapshots set waiting=null where prog_id in (select prog_id from programmes where country=? and ticker=?)", (country, ticker))
    for d in docs:
        named = json.loads(d["parsed_json"])["p"]["programme"]
        if named.get("announced_date") or named.get("mandate_undated"):  # bought under a mandate whose date the filing doesn't state: counted, not waiting
            continue
        rows = con.execute("""select p.announced_date a, p.end_date e, max(x.d) d from (select prog_id, trade_date d from transactions where doc_id=?1
            union select prog_id, as_of from snapshots where doc_id=?1) x join programmes p on p.prog_id=x.prog_id group by p.prog_id""", (d["doc_id"],)).fetchall()
        for r in rows:
            if not r["a"] or (r["e"] and r["d"] > r["e"]):  # waiting for its programme document: left out of every total until linked
                con.execute("update transactions set waiting=1 where doc_id=?", (d["doc_id"],))
                con.execute("update snapshots set waiting=1 where doc_id=?", (d["doc_id"],))
            if not r["a"]:
                _review(con, d["doc_id"], country, ticker, "NO_PROGRAMME", f"Buying on {r['d']} is before any programme announcement read for {ticker}. The announcement may be missing from your list.")
            elif r["e"] and r["d"] > r["e"]:
                _review(con, d["doc_id"], country, ticker, "NO_PROGRAMME", f"Buying on {r['d']} is after the end date ({r['e']}) of the programme announced {r['a']}, and no later announcement has been read. It's shown under that programme for now. The later announcement may be missing from your list.")


def _filing_order(d):
    """Filing date decides, so the latest filing overwrites. On one day: the announcement first, then a correction after what it corrects,
    as a correction names that same day as its previous announcement. The file's own hash settles any tie, so reading order never does."""
    saved = json.loads(d["parsed_json"])["p"]
    # an entry made by hand goes before a filing of the same date, so where both state a figure the filing's is the one in force (both are kept, and the difference goes to review)
    return (d["doc_date"] or saved.get("doc_date") or "9999", 0 if saved.get("form") == "manual" else 1, 0 if saved["doc_type"] == "programme" else 1, saved.get("previous_date") or "", d["sha256"] or "")


def _undated_mandate(d):
    """A filing that says the buying was under a mandate but not when the mandate was granted (the Hong Kong daily report)."""
    return bool(json.loads(d["parsed_json"])["p"].get("programme", {}).get("mandate_undated"))


def replay(con, country, ticker):
    """Rebuild a company's programmes from its link filings, oldest first, so the result doesn't depend on the order they were read in.
    A notice that names no programme joins the latest one announced by its date. Typed entries stay as they are."""
    docs = db.rows(con.execute("select doc_id, sha256, doc_date, parsed_json from documents where country=? and ticker=? and parsed_json is not null", (country, ticker)))
    ids = ",".join(str(d["doc_id"]) for d in docs)
    for table in ("transactions", "snapshots", "venue_totals", "cancellations", "cessations", "issues"):
        con.execute(f"delete from {table} where doc_id in ({ids})")
    con.execute(f"delete from share_counts where doc_id in ({ids})")
    con.execute("""delete from programmes where country=? and ticker=? and coalesce(source_doc,0) not in (select doc_id from documents where parsed_json is null)
        and prog_id not in (select prog_id from transactions union select prog_id from snapshots)""", (country, ticker))
    con.execute("update programmes set terms_date=null, size_note=null, terms_doc=null, status_doc=null where country=? and ticker=?", (country, ticker))  # the note comes back only if its filing is still there

    _REPLAY["on"] = True
    try:
        for d in sorted(docs, key=lambda d: (_undated_mandate(d), _filing_order(d))):
            saved = json.loads(d["parsed_json"])
            _apply_link(con, d["doc_id"], country, ticker, saved["p"], saved["ev"])
    finally:
        _REPLAY["on"] = False
    if crosslist.concerns(country, ticker):  # once, with every purchase back in place
        crosslist.link(con)
    _flag_placement(con, country, ticker, docs)
    _link_cessations(con, country, ticker)
    from . import hand  # imported here: hand uses this module
    hand.apply_updates(con, country, ticker)  # figures Updated Manually go back in force on what was just rebuilt
    hand.check(con, country, ticker)  # an entry made by hand that a filing read disagrees with, or may duplicate, goes to review


def forget_filing(con, link):
    """Drop what was read from one link, so it can be read again with the current parser. Nothing is remembered as removed."""
    for d in con.execute("select doc_id from documents where source_url=?", (link,)).fetchall():
        for table in ("transactions", "snapshots", "venue_totals", "cancellations", "cessations", "issues", "share_counts", "evidence", "review", "doc_pages"):
            con.execute(f"delete from {table} where doc_id=?", (d["doc_id"],))
        con.execute("delete from documents where doc_id=?", (d["doc_id"],))
    con.execute("delete from skipped_links where link=? and reason<>'Removed by you'", (link,))


def reread_rows(con, country, ticker, only_gaps=False):
    """A company's filings as list rows to read again. Removed filings aren't included. With only_gaps, just those with
    a purchase missing its price or value, or still to review."""
    gaps = """and (d.status<>'PARSED' or exists (select 1 from transactions t where t.doc_id=d.doc_id and (t.price_avg is null or t.value is null))
        or exists (select 1 from review r where r.doc_id=d.doc_id and r.status='OPEN'))""" if only_gaps else ""
    docs = con.execute(f"""select d.source_url, d.ticker from documents d where d.country=? and d.ticker=? and coalesce(d.source_url,'')<>''
        and d.source_url not in (select link from skipped_links where reason='Removed by you') {gaps} order by d.doc_date, d.doc_id""", (country, ticker)).fetchall()
    return [(i + 1, {"ticker": r["ticker"], "hyperlink": r["source_url"], "country": country, "_reread": True}) for i, r in enumerate(docs)]


def layout_reads(data, ext, country, layout):
    """Whether a fetched filing is in the given layout from data/forms ("*" for any approved one). Nothing is stored."""
    from . import forms
    with tempfile.TemporaryDirectory() as folder:
        f = Path(folder) / f"filing{ext}"
        f.write_bytes(data)
        try:
            text = parsers.PAGE_BREAK.join(parsers.read_pages(f))
        except Exception:
            return False
    found = forms.match(text, country)
    return bool(found) and layout in ("*", found["id"])


def review_rows(con, country=None, ticker=None):
    """Every link filing with an item open under To review, as list rows to read again with the current reader.
    Purchases only waiting for a programme document, and filings you removed, aren't included."""
    where, args = "", []
    if country and country != "ALL":
        where, args = where + " and d.country=?", args + [country]
    if ticker:
        where, args = where + " and d.ticker=?", args + [ticker]
    docs = con.execute(f"""select d.source_url, d.ticker, d.country from documents d where coalesce(d.source_url,'')<>''
        and exists (select 1 from review r where r.doc_id=d.doc_id and r.status='OPEN' and r.kind<>'NO_PROGRAMME')
        and d.source_url not in (select link from skipped_links where reason='Removed by you') {where} order by d.country, d.ticker, d.doc_date, d.doc_id""", args).fetchall()
    return [(i + 1, {"ticker": r["ticker"] or "", "hyperlink": r["source_url"], "country": r["country"], "_reread": True}) for i, r in enumerate(docs)]


def move_filing(con, doc_id, ticker):
    """Put a link filing under another code of its market, as the user says, and settle both companies again by filing date.
    The code it was under goes from the company list if it was there only because of this filing."""
    d = con.execute("select * from documents where doc_id=?", (doc_id,)).fetchone()
    if not d:
        raise ValueError("That filing isn't there any more.")
    if not d["parsed_json"]:
        raise ValueError("Only filings read from a link can be moved.")
    if d["form"] == "manual":
        raise ValueError("This was entered by hand. Change its company on Add data > Add by hand.")
    ticker = re.sub(r"[^A-Z0-9.]", "", str(ticker or "").strip().upper())
    if not ticker:
        raise ValueError("Type the code to move this filing to.")
    old, country = d["ticker"], d["country"]
    if ticker == old:
        raise ValueError(f"This filing is already under {ticker}.")
    if not con.execute("select 1 from companies where country=? and ticker=? and (in_index=1 or source is not null)", (country, ticker)).fetchone():
        raise ValueError(f"{ticker} is not in the {country} company list. Add it on Companies first, then move the filing.")
    saved = json.loads(d["parsed_json"])
    stated = saved["p"].get("ticker")
    saved["p"]["ticker"], saved["hint"] = None, ticker  # the user's code is used, whatever the filing states
    con.execute("update documents set parsed_json=?, ticker=? where doc_id=?", (json.dumps(saved), ticker, doc_id))
    con.execute("delete from review where doc_id=? and kind in ('NO_COMPANY', 'COMPANY_DIFFERS')", (doc_id,))
    con.execute("update review set ticker=? where doc_id=?", (ticker, doc_id))
    replay(con, country, ticker)
    if old:
        replay(con, country, old)
    con.commit()
    countries.load_constituents(con)
    gone = bool(old) and con.execute("delete from companies where country=? and ticker=? and in_index=0 and source is null", (country, old)).rowcount > 0
    con.commit()
    return {"from": old, "to": ticker, "stated": stated, "old_code_removed": gone}


def remove_filing(con, doc_id):
    """Take a filing out and reconcile its company by filing date, so anything it had overwritten comes back. Its link is remembered, so a list read again doesn't bring it back."""
    d = con.execute("select * from documents where doc_id=?", (doc_id,)).fetchone()
    if not d:
        raise ValueError("That filing isn't there any more.")
    if d["form"] == "manual":
        raise ValueError("This was entered by hand. Edit or delete it on Add data > Add by hand, where a reason is kept.")
    if not d["source_url"]:
        raise ValueError("Typed entries can't be removed here. Edit the file in the inbox folder, then restart the app.")
    for table in ("transactions", "snapshots", "venue_totals", "cancellations", "cessations", "issues", "share_counts", "evidence", "review", "doc_pages"):
        con.execute(f"delete from {table} where doc_id=?", (doc_id,))
    con.execute("delete from documents where doc_id=?", (doc_id,))
    con.execute("insert or replace into skipped_links(link,reason,skipped_at,ticker,country,heading) values(?,?,?,?,?,?)", (d["source_url"], "Removed by you", db.now(), d["ticker"], d["country"], d["heading"]))
    if d["ticker"]:
        replay(con, d["country"], d["ticker"])
    con.commit()
    countries.load_constituents(con)


def state_signature(con):
    """What the settled figures depend on: this version, the filings held and their readings, and the data files that shape them.
    If it equals the signature kept at the last full rebuild, a start has nothing to rebuild."""
    d = con.execute("select count(*), coalesce(max(doc_id),0), coalesce(sum(length(parsed_json)),0), coalesce(max(imported_at),''), coalesce(sum(ticker is not null),0) from documents").fetchone()
    files = []
    for f in sorted((db.ROOT / "data").glob("constituents_*.csv")) + [db.ROOT / "data" / n for n in ("study_companies.csv", "countries.json", "treatment_rules.csv", "cross_listings.csv", "filing_forms.csv")]:
        files.append((f.name, hashlib.sha1(f.read_bytes()).hexdigest() if f.exists() else ""))
    made = [con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("transactions", "programmes", "snapshots", "cancellations", "cessations", "companies")]
    return hashlib.sha1(repr((db.VERSION, tuple(d), files, made)).encode()).hexdigest()


def mark_settled(con):
    db.state(con, "settled", state_signature(con))
    con.commit()


def replay_all(con):
    for r in con.execute("select distinct country, ticker from documents where ticker is not null and parsed_json is not null").fetchall():
        replay(con, r["country"], r["ticker"])
    con.commit()


@_labelled
def import_link(con, link, country, data, ext, ticker_hint="", title="", list_date="", force=False):
    """Read a filing fetched from a link, keep its figures, the page and words they came from, and the link. The file itself isn't kept."""
    sha = hashlib.sha256(data).hexdigest()
    if con.execute("select 1 from documents where sha256=?", (sha,)).fetchone():  # the same file under another link, or saved by hand
        con.execute("insert or replace into skipped_links(link,reason,skipped_at,ticker,country) values(?,?,?,?,?)", (link, "Same content as a filing already read", db.now(), ticker_hint or None, country))
        return "already saved"
    home = countries.get(country)["currency"]
    name = title or re.split(r"[\\/]", link)[-1][:120] or link[:120]
    cur = con.execute("insert into documents(sha256,country,file_name,rel_path,source_url,status,imported_at) values(?,?,?,'',?,?,?)", (sha, country, name, link, "NEW", db.now()))
    doc_id = cur.lastrowid
    with tempfile.TemporaryDirectory() as folder:
        f = Path(folder) / f"filing{ext}"
        f.write_bytes(data)
        try:
            pages = parsers.read_pages(f)
        except Exception as e:  # a damaged filing must not stop the rest of the list
            _review(con, doc_id, country, ticker_hint or None, "UNREADABLE", f"The filing could not be read: {e}")
            con.execute("update documents set ticker=?, status='NEEDS_REVIEW', message='Unreadable' where doc_id=?", (ticker_hint or None, doc_id))
            return "NEEDS_REVIEW"
    text = parsers.PAGE_BREAK.join(pages)
    written = parsers.heading(text, title)
    con.execute("update documents set heading=? where doc_id=?", (written, doc_id))
    if len(re.sub(r"\s", "", text)) < 40:
        _review(con, doc_id, country, ticker_hint or None, "NO_TEXT", "No readable text. This may be a scanned PDF, which needs text recognition (OCR). Please enter the figures by hand.")
        con.execute("update documents set ticker=?, status='NEEDS_REVIEW', message='No text' where doc_id=?", (ticker_hint or None, doc_id))
        return "NEEDS_REVIEW"
    if hkex.is_daily(text):  # one report lists every company that bought: each company's rows become a filing of their own
        con.execute("delete from documents where doc_id=?", (doc_id,))
        return import_daily(con, link, country, sha, text, name)
    if not force and not parsers.is_buyback_filing(text, title):  # lists can't always be filtered; remember the link so it isn't read again, and keep nothing else
        con.execute("delete from documents where doc_id=?", (doc_id,))
        con.execute("insert or replace into skipped_links(link,reason,skipped_at,ticker,country,heading) values(?,?,?,?,?,?)", (link, "Not a buyback filing", db.now(), ticker_hint or None, country if ticker_hint else None, written))
        return "NOT_BUYBACK"
    p = parsers.parse(text, home, country, countries.get(country).get("date_order"))
    if p.get("date_basis") and list_date:  # the filing states no date of its own, so the list's date is better than a purchase date
        parsers.set_filing_date(p, list_date, "your list")
    companies = db.rows(con.execute("select ticker, company from companies where country=?", (country,)))
    hint = ticker_hint if ticker_hint and not p["ticker"] else (p["ticker"] or parsers.match_company("", text, companies))
    ev = parsers.evidence(text, p)
    con.execute("update documents set parsed_json=? where doc_id=?", (json.dumps({"p": p, "ev": ev, "hint": hint}), doc_id))
    if ticker_hint and p["ticker"] and not same_code(country, p["ticker"], ticker_hint):  # never add one company's figures to another
        _review(con, doc_id, country, ticker_hint, "COMPANY_DIFFERS", f"Your list says {ticker_hint}, but the filing says {p['ticker']}. It was not added. Choose the company to add it.")
        _review(con, doc_id, country, None, "NO_COMPANY", "Choose the company for this filing.")
        con.execute("update documents set ticker=?, doc_type=?, doc_date=?, status='NEEDS_REVIEW', message='Company differs from your list' where doc_id=?", (None, p["doc_type"], p["doc_date"], doc_id))
        return "NEEDS_REVIEW"
    status = _apply_link(con, doc_id, country, hint, p, ev)
    if list_date and p["doc_date"] and not p.get("date_basis") and abs((date.fromisoformat(list_date) - date.fromisoformat(p["doc_date"])).days) > 1:
        _review(con, doc_id, country, hint, "DATE_DIFFERS", f"Your list says {list_date}; the filing says {p['doc_date']}. The filing's date is used.")
    return status


def import_daily(con, link, country, sha, text, name):
    """The daily Share Repurchase Report. Each company's rows are kept as a filing of their own, with the report's link, so each can be re-read or removed by itself.
    Nothing but figures and the words they came from is kept: the report is not saved."""
    groups, notes = hkex.daily_groups(text)
    results = []
    if (countries.get(country) or {}).get("report_companies") == "list":  # a daily report lists every company that bought: keep those on your company list
        listed = {r["ticker"] for r in con.execute("select ticker from companies where country=? and (in_index=1 or source is not null)", (country,))}
        left = [g for g in groups if g[0] not in listed]
        groups = [g for g in groups if g[0] in listed]
        if left:
            NOTE["text"] = f"{len(left)} of {len(left) + len(groups)} companies in this report are not on your {country} company list, so they were left out. Add a company to the list and read the report again to include it"
        if not groups:
            con.execute("insert or replace into skipped_links(link,reason,skipped_at,country,heading) values(?,?,?,?,?)", (link, "Daily report: none of its companies is on your company list", db.now(), country, "Share Repurchase Report"))
            return "NOT_BUYBACK"
    for code, company, rows in groups:
        child = hashlib.sha256(f"{sha}:{code}".encode()).hexdigest()
        if con.execute("select 1 from documents where sha256=?", (child,)).fetchone():
            results.append("already saved")
            continue
        cur = con.execute("insert into documents(sha256,country,file_name,rel_path,source_url,status,imported_at,heading) values(?,?,?,'',?,?,?,?)",
                          (child, country, f"{name} | {company} ({code})"[:160], link, "NEW", db.now(), "Share Repurchase Report"))
        doc_id = cur.lastrowid
        kept = hkex.render_group(text, rows, notes)
        p = hkex.read_daily_group(code, company, rows, notes)
        ev = parsers.evidence(kept, p)
        con.execute("update documents set parsed_json=? where doc_id=?", (json.dumps({"p": p, "ev": ev, "hint": code}), doc_id))
        results.append(_apply_link(con, doc_id, country, code, p, ev))
    if not results:
        return "NEEDS_REVIEW"
    return "NEEDS_REVIEW" if "NEEDS_REVIEW" in results else ("already saved" if set(results) == {"already saved"} else "PARSED")


def reset(con):
    """Wipes every filing and figure, with the typed entries and prices, and starts empty. Settings stay: countries, study list and Excel lists."""
    documents = con.execute("select count(*) from documents").fetchone()[0]
    con.commit()
    con.execute("pragma foreign_keys=off")
    for (table,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
        con.execute(f"delete from {table}")
    con.commit()
    con.execute("pragma foreign_keys=on")
    files = list(_folder_files())
    for _, f in files:
        f.unlink()
    (countries.INBOX / "prices.csv").unlink(missing_ok=True)
    con.execute("vacuum")
    countries.load_constituents(con)
    con.commit()
    return {"documents": documents, "files": len(files)}


def _folder_files():
    for c in countries.load():
        folder = countries.INBOX / c["code"]
        folder.mkdir(parents=True, exist_ok=True)
        for f in sorted(folder.rglob("*")):
            if f.is_file() and f.suffix.lower() in FILE_TYPES:
                yield c["code"], f


def scan(con):
    seen = imported = review = failed = 0
    known = {r["sha256"] for r in con.execute("select sha256 from documents")}
    for country, f in _folder_files():
        seen += 1
        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        if sha in known:
            continue
        known.add(sha)
        rel = str(f.relative_to(db.ROOT)).replace("\\", "/")
        for old in con.execute("select doc_id from documents where rel_path=?", (rel,)).fetchall():
            for table in ("documents", "doc_pages", "evidence", "review"):
                con.execute(f"delete from {table} where doc_id=?", (old["doc_id"],))
        try:
            status = import_file(con, f, country, sha)
        except Exception as e:
            con.rollback()
            failed += 1
            con.execute("insert into documents(sha256,country,file_name,rel_path,status,message,imported_at) values(?,?,?,?,?,?,?)",
                        (sha, country, f.name, str(f.relative_to(db.ROOT)).replace("\\", "/"), "FAILED", repr(e)[:300], db.now()))
            con.commit()
            continue
        imported += 1
        review += status == "NEEDS_REVIEW"
        con.commit()
    merge_undated(con)
    prices = import_prices(con)
    if imported or failed or prices:  # the Add data page checks the folders often; only real imports belong in the history
        con.execute("insert into runs(started_at,seen,imported,review,failed,note) values(?,?,?,?,?,?)", (db.now(), seen, imported, review, failed, f"{prices} prices" if prices else ""))
    con.commit()
    return {"seen": seen, "imported": imported, "review": review, "failed": failed, "prices": prices}


@_labelled
def rebuild(con):
    """Clear everything derived from files and read them all again, for example after a parser fix. Hand entries in the CSV files are kept, as they are files too.

    Link filings have no file to read again, so their saved figures are put back as they were.
    """
    links = db.rows(con.execute("select * from documents where source_url is not null"))
    hand = db.rows(con.execute("select * from documents where form='manual' and source_url is null"))  # entries made by hand have no file to read again; they are put back as they are
    for t in ("transactions", "snapshots", "venue_totals", "cancellations", "issues", "share_counts", "programmes", "review", "documents", "doc_pages", "evidence", "announcement_list"):
        con.execute(f"delete from {t}")
    con.commit()
    for d in hand:  # back first and under their own numbers, which the hand entries and their history refer to
        con.execute("insert into documents(doc_id,sha256,country,file_name,rel_path,ticker,doc_type,doc_date,status,message,parsed_json,imported_at,heading,form) values(?,?,?,?,'',?,?,?,?,?,?,?,?,?)",
                    (d["doc_id"], d["sha256"], d["country"], d["file_name"], d["ticker"], d["doc_type"], d["doc_date"], d["status"], d["message"], d["parsed_json"], d["imported_at"], d["heading"], "manual"))
    result = scan(con)
    for d in links:
        cur = con.execute("insert into documents(sha256,country,file_name,rel_path,source_url,status,message,parsed_json,imported_at) values(?,?,?,'',?,?,?,?,?)",
                          (d["sha256"], d["country"], d["file_name"], d["source_url"], d["status"], d["message"], d["parsed_json"], d["imported_at"]))
        if d["parsed_json"]:
            saved = json.loads(d["parsed_json"])
            _apply_link(con, cur.lastrowid, d["country"], d["ticker"] or saved["hint"], saved["p"], saved["ev"])
        else:
            con.execute("update documents set ticker=? where doc_id=?", (d["ticker"], cur.lastrowid))
    for r in {(d["country"], d["ticker"]) for d in hand}:
        replay(con, *r)
    con.commit()
    result["links_kept"] = len(links)
    result["hand_kept"] = len(hand)
    return result


def assign_company(con, doc_id, ticker):
    """Apply the user's choice of company to a file that could not be matched, and read it again."""
    doc = con.execute("select * from documents where doc_id=?", (doc_id,)).fetchone()
    if not doc:
        raise ValueError("File not found.")
    if doc["parsed_json"]:
        saved = json.loads(doc["parsed_json"])
        saved["p"]["ticker"] = None
        saved["hint"] = ticker
        con.execute("update documents set parsed_json=? where doc_id=?", (json.dumps(saved), doc_id))
        con.execute("delete from review where doc_id=? and kind='NO_COMPANY'", (doc_id,))
        _apply_link(con, doc_id, doc["country"], ticker, saved["p"], saved["ev"])
        replay(con, doc["country"], ticker)
        con.commit()
        return
    path = db.ROOT / doc["rel_path"]
    text = parsers.read_text(path)
    p = parsers.parse(text, countries.get(doc["country"])["currency"], doc["country"], countries.get(doc["country"]).get("date_order"))
    _ensure_company(con, doc["country"], ticker, p["company"])
    store(con, doc_id, doc["country"], ticker, p)
    save_evidence(con, doc_id, text, p)
    con.execute("update documents set ticker=?, doc_type=?, doc_date=?, status='PARSED', message=? where doc_id=?",
                (ticker, p["doc_type"], p["doc_date"], f"Company chosen by hand. {len(p['transactions'])} purchases, {len(p['snapshots'])} totals", doc_id))
    con.execute("update review set status='RESOLVED', ticker=? where doc_id=? and kind='NO_COMPANY'", (ticker, doc_id))
    con.commit()
