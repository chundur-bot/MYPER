"""Run:  python -P tests/test_v26.py
Version 26: running totals from ASX daily notices (Appendix 3C, field 4.3/4.4 "before the previous day") are dated to the programme's last
purchase day, not the calendar day before; never a weekend; a total worked out never replaces one a notice states; a total that disagrees with
the one held goes to review (TOTAL_GAP). The readings are built as earlier versions kept them, so the rebuild corrects them from parsed_json.
Works on scratch files in a temporary folder; buyback.db and the inbox of the real app are not touched."""
import hashlib
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from sbb import db, fetching, ingest  # noqa: E402

tmp = Path(tempfile.mkdtemp())
fetching.LINKS_FILE = tmp / "filing_links.csv"
con = db.connect(tmp / "totals.db")
for t in ("AMP", "GAP", "NEW", "FIN"):
    con.execute("insert into companies(country,ticker,company,in_index) values('AU',?,?,1)", (t, t))
PROG = {"announced_date": "2022-08-01", "buyback_type": "On market buy-back", "start_date": "2022-08-15", "end_date": "2023-08-14", "max_shares": None,
        "max_value": 1100000000.0, "max_currency": "AUD", "max_text": "A$1.1 billion", "shares_on_issue": 3200000000.0}
n = [0]


def weekday_after(d):
    x = date.fromisoformat(d) + timedelta(days=1)
    while x.weekday() > 4:
        x += timedelta(days=1)
    return x.isoformat()


def add(ticker, p):
    n[0] += 1
    sha = hashlib.sha256(f"{ticker}{n[0]}".encode()).hexdigest()
    con.execute("insert into documents(sha256,country,ticker,doc_type,doc_date,status,form,parsed_json,imported_at) values(?,?,?,?,?,?,?,?,?)",
                (sha, "AU", ticker, p["doc_type"], p["doc_date"], "imported", p["form"], json.dumps({"p": p, "ev": [], "hint": ticker}), db.now()))


def daily(ticker, trade, before_sh, before_v, sh, v, cur="AUD"):
    """A daily notice as the reader keeps it, including the old dating of the 'before' total: the calendar day before."""
    prev = (date.fromisoformat(trade) - timedelta(days=1)).isoformat()
    add(ticker, {"form": "appendix_3c", "ticker": ticker, "company": ticker, "doc_type": "daily", "doc_date": weekday_after(trade), "programme": dict(PROG),
                 "transactions": [{"trade_date": trade, "venue": "", "shares": sh, "value": v, "currency": cur, "price_unit": cur, "price_avg": v / sh, "price_high": None, "price_low": None, "value_origin": "reported"}],
                 "snapshots": [{"as_of": prev, "cum_shares": before_sh, "cum_value": before_v, "currency": cur, "origin": "reported"},
                               {"as_of": trade, "cum_shares": before_sh + sh, "cum_value": before_v + v, "currency": cur, "origin": "sum", "working": f"{cur} {before_v:,.2f} before that day + {cur} {v:,.2f} on the day"}],
                 "issues": [], "reason": "Daily buy-back notification", "previous_date": trade})


def totals(ticker):
    return [(s["as_of"], s["cum_shares"], round(s["cum_value"], 2) if s["cum_value"] is not None else None, s["origin"]) for s in
            con.execute("select s.* from snapshots s join programmes p using(prog_id) where p.ticker=? order by as_of", (ticker,))]


# ---------- 1. AMP, August 2022: the case reported ----------
days = [("2022-08-25", 4054085, 4540169.79), ("2022-08-26", 2252400, 2536427.64), ("2022-08-29", 3965387, 4373028.78), ("2022-08-30", 4905954, 5475535.26), ("2022-08-31", 10160642, 11653240.31)]
bs, bv = 0.0, 0.0
for d, sh, v in days:
    daily("AMP", d, bs, bv, float(sh), v)
    bs, bv = bs + sh, bv + v
con.commit()
ingest.replay(con, "AU", "AMP")
got = totals("AMP")
for row in got:
    print("  ", row)
assert [(a, s, v) for a, s, v, o in got] == [("2022-08-25", 4054085, 4540169.79), ("2022-08-26", 6306485, 7076597.43), ("2022-08-29", 10271872, 11449626.21),
                                            ("2022-08-30", 15177826, 16925161.47), ("2022-08-31", 25338468, 28578401.78)], got
assert all(date.fromisoformat(a).weekday() < 5 for a, *_ in got), "a weekend date"
assert [o for *_, o in got] == ["reported", "reported", "reported", "reported", "sum"], got  # each day's total is stated by the next day's notice; only the newest is worked out
w = con.execute("select working from snapshots where as_of='2022-08-31'").fetchone()[0]
assert w == "AUD 16,925,161.47 before that day + AUD 11,653,240.31 on the day", w
assert con.execute("select count(*) from transactions t join programmes p using(prog_id) where p.ticker='AMP'").fetchone()[0] == 5
assert not con.execute("select 1 from review where kind='TOTAL_GAP'").fetchone()
print("AMP totals: OK")

# a second rebuild changes nothing
ingest.replay(con, "AU", "AMP")
assert totals("AMP") == got
print("rebuild again: OK")

# ---------- 2. a notice whose 'before' total disagrees with the total held: dated the weekday before, sent to review ----------
daily("GAP", "2022-09-01", 0.0, 0.0, 1000.0, 10000.0)        # Thursday
daily("GAP", "2022-09-06", 5000.0, 50000.0, 1000.0, 10000.0)  # Tuesday: says 5,000 before, but only 1,000 were read (2 and 5 Sep missing)
con.commit()
ingest.replay(con, "AU", "GAP")
g = totals("GAP")
assert [(a, s, o) for a, s, v, o in g] == [("2022-09-01", 1000, "sum"), ("2022-09-05", 5000, "reported"), ("2022-09-06", 6000, "sum")], g
r = con.execute("select detail from review where kind='TOTAL_GAP' and ticker='GAP'").fetchall()
assert len(r) == 1 and "before 2022-09-06" in r[0][0] and "on 2022-09-01" in r[0][0] and "dated 2022-09-05" in r[0][0], r
ingest.replay(con, "AU", "GAP")
assert con.execute("select count(*) from review where kind='TOTAL_GAP' and ticker='GAP'").fetchone()[0] == 1  # not repeated
print("gap goes to review: OK")

# ---------- 3. no earlier purchase: the weekday before; a total of 0 is not kept ----------
daily("NEW", "2022-09-05", 7000.0, 70000.0, 100.0, 1000.0)    # Monday, first notice read, 7,000 already bought
con.commit()
ingest.replay(con, "AU", "NEW")
assert [(a, s, o) for a, s, v, o in totals("NEW")] == [("2022-09-02", 7000, "reported"), ("2022-09-05", 7100, "sum")], totals("NEW")
assert not any(s == 0 for a, s, v, o in got)
print("first notice: OK")

# ---------- 4. a total worked out never replaces one a notice states for the same day; amounts agree to the cent ----------
daily("FIN", "2022-09-07", 0.0, 0.0, 300.0, 3000.1)
daily("FIN", "2022-09-08", 300.0, 3000.1000000001, 200.0, 2000.2)   # the sum held is 3000.1 with float noise: still the same total
add("FIN", {"form": "appendix_3c", "ticker": "FIN", "company": "FIN", "doc_type": "final", "doc_date": "2022-09-08", "programme": {**PROG, "status": "COMPLETED"}, "transactions": [],
            "snapshots": [{"as_of": "2022-09-08", "cum_shares": 500.0, "cum_value": 5000.0, "currency": "AUD", "origin": "reported"}], "issues": [], "reason": "Final buy-back notification"})
con.commit()
ingest.replay(con, "AU", "FIN")
f = totals("FIN")
assert ("2022-09-08", 500, 5000.0, "reported") in f, f   # the final notice's figure stays, though the daily notice for the 8th was filed after it
assert ("2022-09-07", 300, 3000.1, "reported") in f, f
assert not con.execute("select 1 from review where kind='TOTAL_GAP' and ticker='FIN'").fetchone()
print("stated total kept: OK")

# ---------- 5. the same shares but a different amount: the same day, the notice's figure kept, sent to review ----------
daily("FIN", "2022-09-09", 500.0, 5000.37, 50.0, 500.0)   # the final notice above held 5,000.00 for 500 shares
con.commit()
ingest.replay(con, "AU", "FIN")
f = totals("FIN")
assert ("2022-09-08", 500, 5000.37, "reported") in f and not any(a == "2022-09-09" and o == "reported" for a, s, v, o in f), f
r = con.execute("select detail from review where kind='TOTAL_DIFFERS' and ticker='FIN'").fetchall()
assert len(r) == 1 and "AUD 5,000.37" in r[0][0] and "AUD 5,000.00" in r[0][0], r
assert not con.execute("select 1 from review where kind='TOTAL_GAP' and ticker='FIN'").fetchone()
print("amount differs goes to review: OK")

# ---------- 6. the reader itself is unchanged ----------
assert "timedelta(days=1)" in (ROOT / "sbb" / "parsers.py").read_text(encoding="utf-8")
print("ALL v26 TESTS PASSED")
