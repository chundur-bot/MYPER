"""Run:  python -P tests/test_v23.py
Version 23: the periods of a programme whose terms changed (renewed for another year, an end date moved, a size raised), set out from the readings already stored.
Works on a scratch database in a temporary folder; buyback.db is not touched."""
import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from sbb import db, ingest, parsers, periods, queries, tracker  # noqa: E402

tmp = Path(tempfile.mkdtemp())
con = db.connect(tmp / "scratch.db")
n = [0]


def filing(country, ticker, filed, doc_type, terms, buys=(), total=None, form="appendix_3c", reason=""):
    """One filing's reading, stored as the app stores it."""
    p = parsers._blank(form=form, doc_type=doc_type, ticker=ticker, company=f"{ticker} Ltd", doc_date=filed)
    p.update(venue_totals=[], cancellations=[], programme=dict(terms), reason=reason, date_stated=True)
    for day, shares, value in buys:
        x = parsers._tx(day, shares, None, None, None, "AUD" if country == "AU" else "GBP", "")
        x.update(value=value, price_avg=value / shares if value else None, value_origin="reported")
        p["transactions"].append(x)
    if total:
        p["snapshots"].append({"as_of": filed, "cum_shares": total, "cum_value": None, "currency": None, "origin": "reported", "working": ""})
    n[0] += 1
    con.execute("insert into documents(sha256,country,file_name,rel_path,source_url,status,imported_at,ticker,doc_date,doc_type,form,parsed_json) values(?,?,?,'',?,?,?,?,?,?,?,?)",
                (f"s{n[0]}", country, f"f{n[0]}", f"http://x/{n[0]}", "PARSED", db.now(), ticker, filed, doc_type, form, json.dumps({"p": p, "ev": [], "hint": ticker})))


# A: a buy-back renewed for a second year under the same date of initial notification, as an ASX company files it
first = {"announced_date": "2023-04-26", "start_date": "2023-05-12", "end_date": "2024-05-10", "max_shares": 1000}
second = {"announced_date": "2023-04-26", "start_date": "2024-05-13", "end_date": "2025-05-12", "max_shares": 900}
filing("AU", "AAA", "2023-04-26", "programme", first)
filing("AU", "AAA", "2023-06-01", "daily", first, [("2023-05-31", 100, 500.0)])
filing("AU", "AAA", "2024-04-26", "update", second, reason="Renew period of buy-back from 13/05/2024 to 12/05/2025")
filing("AU", "AAA", "2024-04-29", "daily", first, [("2024-04-26", 50, 260.0)])  # filed after the renewal, still carrying the terms it replaced
filing("AU", "AAA", "2024-06-03", "daily", second, [("2024-05-31", 200, 1100.0)])
filing("AU", "AAA", "2025-05-12", "final", second, total=400)  # the final notice states 400; the purchases read add up to 350
# B: one period whose size is raised and whose end is moved
size = {"announced_date": "2025-01-10", "start_date": "2025-01-20", "end_date": "2025-12-31", "max_value": 1000.0, "max_currency": "AUD"}
filing("AU", "BBB", "2025-01-10", "programme", {"announced_date": "2025-01-10", "max_value": 1000.0, "max_currency": "AUD"})  # the size first, the dates in a later form
filing("AU", "BBB", "2025-01-21", "daily", size, [("2025-01-20", 10, 300.0)])
filing("AU", "BBB", "2025-06-02", "update", {**size, "max_value": 1500.0, "end_date": "2026-03-31"})
filing("AU", "BBB", "2025-06-03", "daily", {**size, "max_value": 1500.0, "end_date": "2026-03-31"}, [("2025-06-02", 20, 600.0)])
# C: a programme whose terms never change, and D: UK purchase notices whose dates are the week each one covers
same = {"announced_date": "2025-02-01", "start_date": "2025-02-10", "end_date": "2025-12-31", "max_shares": 500}
filing("AU", "CCC", "2025-02-01", "programme", same)
filing("AU", "CCC", "2025-02-11", "daily", same, [("2025-02-10", 5, 20.0)])
for week, (a, b) in enumerate((("2026-09-14", "2026-09-18"), ("2026-09-21", "2026-09-25"))):
    filing("UK", "DDD", b, "transaction", {"announced_date": "2026-09-01", "start_date": a, "end_date": b}, [(a, 1000 + week, 9000.0)], form="notice")
con.commit()
for country, ticker in (("AU", "AAA"), ("AU", "BBB"), ("AU", "CCC"), ("UK", "DDD")):
    ingest.replay(con, country, ticker)
con.commit()

pid = lambda t: con.execute("select prog_id from programmes where ticker=?", (t,)).fetchone()[0]
a = periods.for_company(con, "AU", "AAA")[pid("AAA")]
assert (a["count"], a["from"], a["to"]) == (2, "2023-05-12", "2025-05-12"), a
one, two = a["rows"]
assert (one["start"], one["end"], one["max_shares"], one["bought_shares"], one["days"], one["filed"], one["doc_type"], one["current"]) == ("2023-05-12", "2024-05-10", 1000, 150, 2, "2023-04-26", "programme", False), one
assert (two["start"], two["end"], two["max_shares"], two["bought_shares"], two["filed"], two["doc_type"], two["current"]) == ("2024-05-13", "2025-05-12", 900, 200, "2024-04-26", "update", True), two
assert round(one["used_pct"], 1) == 15.0 and round(two["used_pct"], 1) == 22.2 and "the period's maximum" in one["used_working"]  # a share limit is measured against its own period
assert one["amounts"] == {"AUD": 760.0} and one["changes"] == [] and a["outside"] is None  # the stale daily form made no change back
assert a["gap"] == {"as_of": "2025-05-12", "stated": 400, "read": 350, "missing": 50}, a["gap"]
row = con.execute("select start_date, end_date, max_shares from programmes where ticker='AAA'").fetchone()
assert tuple(row) == ("2024-05-13", "2025-05-12", 900.0)  # the programme row still holds the newest terms, as before
print("a renewed buy-back is set out period by period: OK")

b = periods.for_company(con, "AU", "BBB")[pid("BBB")]
assert b["count"] == 1 and (b["rows"][0]["start"], b["rows"][0]["end"], b["rows"][0]["max_value"]) == ("2025-01-20", "2026-03-31", 1500.0), b["rows"]
assert b["rows"][0]["changes"] == ["2025-06-02: end date 2025-12-31 changed to 2026-03-31; size AUD 1,000 changed to AUD 1,500"], b["rows"][0]["changes"]
assert round(b["rows"][0]["used_pct"], 1) == 60.0 and "from the programme's first purchase" in b["rows"][0]["used_working"]  # 900 paid / 1,500: a money size is measured against all paid so far
assert b["rows"][0]["filed"] == "2025-01-10"  # the period is the announcement's, although its dates came in a later form
print("a size raised and an end date moved are changes within one period: OK")

assert periods.for_company(con, "AU", "CCC") == {} and periods.for_company(con, "UK", "DDD") == {} and periods.for_company(con, "AU", "NONE") == {}
print("terms that never change, and weekly purchase notices, make no periods: OK")

card = queries.company(con, "AU", "AAA", queries.ALL_FROM, queries.ALL_TO)["programmes"][0]
assert card["periods"]["count"] == 2 and (card["start_date"], card["end_date"], card["max_shares"]) == ("2024-05-13", "2025-05-12", 900.0)
assert queries.company(con, "AU", "CCC", queries.ALL_FROM, queries.ALL_TO)["programmes"][0]["periods"] is None
tracker.run(con)
plan_id = next(p["plan_id"] for p in tracker.overview(con, "AU")["plans"] if p["ticker"] == "AAA")
assert tracker.plan(con, plan_id)["periods"]["count"] == 2
print("the company card and the Tracker's programme panel carry the periods: OK")

# nothing is stored for it: no new table or column, and the module only reads
tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
assert not any("period" in t or "terms" in t for t in tables), tables
src = inspect.getsource(periods).lower()
assert not any(w in src for w in ("insert into", "update ", "delete from", "alter table", "create table")), "periods.py must only read"
print("nothing new is stored: OK")
print("v23 OK")
