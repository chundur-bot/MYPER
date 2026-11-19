"""Run:  python -P tests/test_v25.py
Version 25: Add by hand. Programme announcements, changes of terms, purchases and completions entered by hand for any market, each with its
source; edited and deleted (with a reason) and kept in a history; marked "Entered by hand" in every figure; checked against the filings read;
kept through a full rebuild; and the purchases typed before version 25 moved in once.
Works on scratch files in a temporary folder; buyback.db and the inbox of the real app are not touched."""
import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from sbb import countries, db, fetching, hand, ingest, parsers, periods, queries as q, server, tracker  # noqa: E402

tmp = Path(tempfile.mkdtemp())
fetching.LINKS_FILE = tmp / "filing_links.csv"
ingest.scan = lambda con: {}  # the real inbox is the user's; these tests don't read it
real_root = db.ROOT
SRC = "NZX announcement of 22 May 2025"


def refused(body, words):
    try:
        hand.save(con, body)
    except ValueError as e:
        assert words in str(e), (words, str(e))
        return
    raise AssertionError(f"should have refused: {body}")


con = db.connect(tmp / "hand.db")
for c, t, name in (("NZ", "NPH", "Napier Port Holdings"), ("NZ", "FBU", "Fletcher Building"), ("AU", "BHP", "BHP Group")):
    con.execute("insert into companies(country,ticker,company,in_index) values(?,?,?,1)", (c, t, name))
con.commit()

# ---------- 1. what is refused ----------
base = {"kind": "programme", "country": "NZ", "ticker": "NPH", "announced_date": "2025-05-22", "source": SRC}
refused({**base, "source": ""}, "Source is required")
refused({**base, "ticker": "ZZZ"}, "not in the NZ company list")
refused({**base, "country": "XX"}, "Choose the exchange")
refused({**base, "kind": "guess"}, "Choose what you are adding")
refused({**base, "announced_date": ""}, "Announced on is required")
refused({**base, "max_pct": "150"}, "no more than 100")
refused({**base, "start_date": "2025-06-01", "end_date": "2025-05-01"}, "Ends is before Starts")
refused({**base, "max_value": "1000000"}, "choose the currency")
refused({**base, "max_shares": "12.5"}, "whole number")
refused({**base, "kind": "change", "programme": "2025-05-22", "change_date": "2025-06-01", "end_date": "2026-05-22"}, "No programme announced 2025-05-22")
print("refusals: OK")

# ---------- 2. a programme stated as a percentage, with an intended number; the end date typed, never worked out ----------
napier = hand.save(con, {**base, "buyback_type": "On market buy-back", "start_date": "2025-05-26", "end_date": "2026-05-22", "max_pct": "0.5", "intended_shares": "260,000",
                          "treatment": "Treasury", "note": "Up to 12 months from the date of this notice"})
assert napier["kind"] == "programme" and "0.5% of shares" in napier["what"] and "about 260,000 intended" in napier["what"], napier
prog = con.execute("select * from programmes where ticker='NPH'").fetchone()
assert (prog["announced_date"], prog["start_date"], prog["end_date"], prog["max_pct"], prog["intended_shares"], prog["max_shares"]) == ("2025-05-22", "2025-05-26", "2026-05-22", 0.5, 260000, None)
assert prog["treatment"] == "Treasury" and prog["treatment_text"].startswith("Entered by hand") and prog["status"] == "ACTIVE"
doc = con.execute("select * from documents where doc_id=?", (napier["doc_id"],)).fetchone()
assert doc["form"] == "manual" and doc["appendix"] == "Entered by hand" and doc["filing_type"] == "Programme announcement" and doc["source_url"] is None and doc["status"] == "PARSED"
row = next(r for r in q.programme_rows(con, "NZ", q.ALL_FROM, q.ALL_TO) if r["ticker"] == "NPH")
assert row["hand_announced"] == SRC and row["hand_terms"] == SRC and row["hand_treatment"] == SRC and row["max_pct"] == 0.5 and row["intended_shares"] == 260000
assert not row["document_needed"]  # a size as a percentage is a size
refused({**base, "max_pct": "0.4"}, "already entered by hand")  # the same programme twice
print("programme by hand: OK")

# ---------- 3. a purchase, a change of terms and a completion ----------
buy = hand.save(con, {"kind": "purchase", "country": "NZ", "ticker": "NPH", "programme": "2025-05-22", "trade_date": "2025-06-03", "venue": "NZX", "shares": "12,000", "price_avg": "3.10",
                      "currency": "NZD", "source": "NZX daily notice of 4 June 2025, not in the document system"})
t = con.execute("select * from transactions where doc_id=?", (buy["doc_id"],)).fetchone()
assert (t["shares"], round(t["value"], 2), t["value_origin"], t["venue"], t["currency"]) == (12000, 37200.0, "hand_product", "NZX", "NZD")  # the amount worked out from what was typed, and marked so
d = next(r for r in q.daily_rows(con, t["prog_id"]) if r["doc_id"] == buy["doc_id"])
assert d["value_basis"] == "Calculated" and "both entered by hand" in d["value_working"] and d["avg_basis"] == "Entered by hand" and d["hand_source"].startswith("NZX daily notice")
buy2 = hand.save(con, {"kind": "purchase", "country": "NZ", "ticker": "NPH", "programme": "2025-05-22", "trade_date": "2025-06-04", "venue": "NZX", "shares": "8000", "value": "25,000.00",
                       "currency": "NZD", "source": "NZX daily notice of 5 June 2025"})
d2 = next(r for r in q.daily_rows(con, t["prog_id"]) if r["doc_id"] == buy2["doc_id"])
assert d2["value_basis"] == "Entered by hand" and d2["avg_basis"] is None  # nothing worked out that wasn't asked for
refused({"kind": "purchase", "country": "NZ", "ticker": "NPH", "trade_date": "2025-06-05", "venue": "NZX", "shares": "100", "value": "300", "source": "x y z"}, "choose the currency")
refused({"kind": "purchase", "country": "NZ", "ticker": "NPH", "trade_date": "2025-06-05", "venue": "", "shares": "100", "source": "x y z"}, "Bought on")
refused({"kind": "purchase", "country": "NZ", "ticker": "NPH", "trade_date": "2025-06-05", "venue": "NZX", "shares": "100", "currency": "NZD", "price_high": "3", "price_low": "4", "source": "x y z"}, "Lowest price is above")
change = hand.save(con, {"kind": "change", "country": "NZ", "ticker": "NPH", "programme": "2025-05-22", "change_date": "2025-11-20", "end_date": "2026-11-20", "source": "NZX announcement of 20 November 2025"})
assert con.execute("select end_date, max_pct from programmes where ticker='NPH'").fetchone()[:] == ("2026-11-20", 0.5)  # the new end; the size stays
row = next(r for r in q.programme_rows(con, "NZ", q.ALL_FROM, q.ALL_TO) if r["ticker"] == "NPH")
assert row["hand_terms"] == "NZX announcement of 20 November 2025" and row["hand_announced"] == SRC and row["hand_purchases"] == 2
span = periods.for_company(con, "NZ", "NPH")[prog["prog_id"]]
assert span["count"] == 1 and span["rows"][0]["hand"] and "end date 2026-05-22 changed to 2026-11-20" in span["rows"][0]["changes"][0], span  # the terms before the change are kept
refused({"kind": "change", "country": "NZ", "ticker": "NPH", "programme": "2025-05-22", "change_date": "2025-12-01", "source": "x y z"}, "Type what changed")
refused({"kind": "completion", "country": "NZ", "ticker": "NPH", "programme": "2025-05-22", "completed_on": "2025-01-01", "source": "x y z"}, "before the programme was announced")
done = hand.save(con, {"kind": "completion", "country": "NZ", "ticker": "NPH", "programme": "2025-05-22", "completed_on": "2026-03-31", "source": "NZX announcement of 31 March 2026"})
row = next(r for r in q.programme_rows(con, "NZ", q.ALL_FROM, q.ALL_TO) if r["ticker"] == "NPH")
assert row["status"] == "COMPLETED" and row["status_basis"] == "Entered by hand" and "2026-03-31" in row["status_working"] and row["hand_status"] == "NZX announcement of 31 March 2026"
assert row["shares"] == 20000  # with no final totals, the totals stay as the purchases held
assert con.execute("select doc_type from documents where doc_id=?", (done["doc_id"],)).fetchone()[0] == "completion"
print("purchase, change of terms, completion: OK")

# ---------- 4. edit, history, delete ----------
edited = hand.save(con, {"entry_id": buy["entry_id"], "kind": "purchase", "country": "NZ", "ticker": "NPH", "programme": "2025-05-22", "trade_date": "2025-06-03", "venue": "NZX",
                         "shares": "12,500", "price_avg": "3.10", "currency": "NZD", "source": "NZX daily notice of 4 June 2025, not in the document system"})
assert edited["doc_id"] == buy["doc_id"] and con.execute("select shares from transactions where doc_id=?", (buy["doc_id"],)).fetchone()[0] == 12500
try:
    hand.save(con, {**edited["fields"], "entry_id": buy["entry_id"], "kind": "purchase", "country": "NZ", "ticker": "NPH", "source": edited["source"]})
    raise AssertionError("an edit that changes nothing should be refused")
except ValueError as e:
    assert "Nothing was changed" in str(e)
try:
    hand.save(con, {**base, "entry_id": buy["entry_id"], "announced_date": "2025-06-01"})
    raise AssertionError("an entry can't change its kind")
except ValueError as e:
    assert "can't become" in str(e)
try:
    hand.delete(con, buy2["entry_id"], "")
    raise AssertionError("a delete needs its reason")
except ValueError as e:
    assert "reason" in str(e)
hand.delete(con, buy2["entry_id"], "Entered twice")
assert not con.execute("select 1 from transactions where doc_id=?", (buy2["doc_id"],)).fetchone() and not con.execute("select 1 from documents where doc_id=?", (buy2["doc_id"],)).fetchone()
gone = con.execute("select * from hand_entries where entry_id=?", (buy2["entry_id"],)).fetchone()
assert gone["status"] == "DELETED" and gone["delete_reason"] == "Entered twice" and json.loads(gone["fields"])["shares"] == 8000  # out of the figures, kept in the history
listed = hand.listing(con, "NZ")
assert len(listed["entries"]) == 4 and len(listed["deleted"]) == 1
log = {(x["entry_id"], x["action"]) for x in listed["log"]}
assert (buy["entry_id"], "ADDED") in log and (buy["entry_id"], "EDITED") in log and (buy2["entry_id"], "DELETED") in log
assert next(x for x in listed["log"] if x["action"] == "EDITED")["changes"] == "shares: 12000.0 → 12500.0"
try:
    hand.delete(con, buy2["entry_id"], "again")
    raise AssertionError("should have refused")
except ValueError as e:
    assert "already deleted" in str(e)
for refuse in (lambda: ingest.remove_filing(con, buy["doc_id"]), lambda: ingest.move_filing(con, buy["doc_id"], "FBU")):
    try:
        refuse()
        raise AssertionError("a hand entry is changed on Add by hand only")
    except ValueError as e:
        assert "entered by hand" in str(e)
moved = hand.save(con, {**edited["fields"], "entry_id": buy["entry_id"], "kind": "purchase", "country": "NZ", "ticker": "FBU", "programme": "", "source": edited["source"]})
assert moved["ticker"] == "FBU" and con.execute("select ticker from transactions where doc_id=?", (buy["doc_id"],)).fetchone()[0] == "FBU"  # another company: both rebuilt
assert not con.execute("select 1 from transactions where ticker='NPH' and doc_id=?", (buy["doc_id"],)).fetchone()
hand.save(con, {**moved["fields"], "entry_id": buy["entry_id"], "kind": "purchase", "country": "NZ", "ticker": "NPH", "programme": "2025-05-22", "source": edited["source"]})
print("edit, history, delete: OK")


# ---------- 5. a hand entry against a filing read ----------
def read_filing(ticker, filed, doc_type, terms, buys=(), venue="NZX"):
    p = parsers._blank(form="notice", doc_type=doc_type, ticker=ticker, company=ticker, doc_date=filed)
    p.update(venue_totals=[], cancellations=[], programme=dict(terms), date_stated=True)
    for day, shares in buys:
        p["transactions"].append({**parsers._tx(day, shares, 3.0, 3.1, 2.9, "NZD", venue), "value_origin": "reported", "value": shares * 3.0})
    cur = con.execute("insert into documents(sha256,country,file_name,rel_path,source_url,status,imported_at,ticker,doc_date,doc_type,form,parsed_json,heading) values(?,?,?,'',?,?,?,?,?,?,?,?,?)",
                      (f"r{filed}{doc_type}{venue}", "NZ", f"{ticker} {filed}", f"http://docs/{ticker}/{filed}/{venue}", "PARSED", db.now(), ticker, filed, doc_type, "notice", json.dumps({"p": p, "ev": [], "hint": ticker}), f"{ticker} filing {filed}"))
    con.commit()
    return cur.lastrowid


read_filing("NPH", "2025-05-22", "programme", {"announced_date": "2025-05-22", "start_date": "2025-05-26", "max_pct": 0.4})
r1 = read_filing("NPH", "2025-06-04", "transaction", {"announced_date": "2025-05-22"}, [("2025-06-03", 12000)])
ingest.replay(con, "NZ", "NPH")
counted = con.execute("select shares, doc_id, value_origin from transactions where ticker='NPH' and trade_date='2025-06-03'").fetchall()
assert [tuple(x) for x in counted] == [(12000, r1, "reported")]  # the same day and venue: the filing's figure is the one counted
open_ = [x["detail"] for x in con.execute("select detail from review where ticker='NPH' and kind='HAND_DIFFERS' and status='OPEN'")]
assert any("maximum % 0.5 by hand, 0.4 in the filing" in x for x in open_) and any("shares 12,500 by hand, 12,000 in the filing" in x for x in open_), open_
assert con.execute("select count(*) from hand_entries where status='ACTIVE' and ticker='NPH'").fetchone()[0] == 4  # both kept
read_filing("NPH", "2025-06-06", "transaction", {"announced_date": "2025-05-22"}, [("2025-06-03", 500)], venue="ASX")
ingest.replay(con, "NZ", "NPH")
assert con.execute("select count(*) from review where ticker='NPH' and kind='HAND_TWICE' and status='OPEN'").fetchone()[0] == 1  # another venue the same day: both counted, and asked about
rid = con.execute("select review_id from review where ticker='NPH' and kind='HAND_TWICE'").fetchone()[0]
con.execute("update review set status='RESOLVED' where review_id=?", (rid,))
con.commit()
ingest.replay(con, "NZ", "NPH")
assert con.execute("select status from review where kind='HAND_TWICE'").fetchone()[0] == "RESOLVED" and con.execute("select count(*) from review where kind='HAND_TWICE'").fetchone()[0] == 1  # marked as checked stays checked
print("against the filings read: OK")

# ---------- 6. the Tracker, and a full rebuild ----------
assert tracker.classify("Entered by hand: Purchase", "manual", "transaction") == ("Daily transaction", "kind chosen when it was entered by hand")
assert tracker.classify("x", "manual", "completion")[0] == "Completion" and tracker.classify("x", "manual", "update")[0] == "Change to terms"
assert tracker.confidence("Daily transaction", {"form": "manual", "transactions": []}) == ("entered by hand", None)
tracker.run(con)
plan = next(json.loads(r["data"]) for r in con.execute("select data from tracker_plans where ticker='NPH'"))
assert plan["planned_pct"] == 0.4 and plan["intended_shares"] == 260000  # the filing read on the same day as the hand entry is the one in force and plan["hand_notices"] == 4 and plan["status"] == "Completed", plan
notice = next(n for n in tracker._notices(con) if n["doc_id"] == change["doc_id"])
assert notice["type"] == "Change to terms" and notice["confidence"] == "entered by hand"
before = {r["doc_id"]: r["parsed_json"] for r in con.execute("select doc_id, parsed_json from documents where form='manual'")}
shares_before = con.execute("select sum(shares) from transactions").fetchone()[0]
res = ingest.rebuild(con)
assert res["hand_kept"] == 4 and {r["doc_id"]: r["parsed_json"] for r in con.execute("select doc_id, parsed_json from documents where form='manual'")} == before  # kept, under their own numbers
assert con.execute("select sum(shares) from transactions").fetchone()[0] == shares_before
assert con.execute("select count(*) from review where kind='HAND_DIFFERS' and status='OPEN'").fetchone()[0] >= 2  # asked again after a rebuild
sig = ingest.state_signature(con)
hand.save(con, {"kind": "purchase", "country": "NZ", "ticker": "NPH", "programme": "2025-05-22", "trade_date": "2025-07-01", "venue": "NZX", "shares": "1", "source": "x y z"})
assert ingest.state_signature(con) != sig  # the next start rebuilds once
print("Tracker and rebuild: OK")

# ---------- 7. purchases typed before version 25 move in once ----------
db.ROOT = tmp
try:
    old = tmp / "inbox" / "AU"
    old.mkdir(parents=True)
    (old / "manual_entries.csv").write_text("ticker,trade_date,shares,value,currency\nBHP,2026-02-02,1000,45000,AUD\n", encoding="utf-8")
    m = db.connect(tmp / "moved.db")
    m.execute("insert into companies(country,ticker,company,in_index) values('AU','BHP','BHP Group',1)")
    cur = m.execute("insert into documents(sha256,country,file_name,rel_path,status,imported_at,doc_type) values('typed','AU','manual_entries.csv','inbox/AU/manual_entries.csv','PARSED','2026-02-03 10:00:00','transactions csv')")
    ingest.store(m, cur.lastrowid, "AU", "BHP", {"programme": {"announced_date": ""}, "snapshots": [], "doc_date": "2026-02-02",
                                                 "transactions": [{"trade_date": "2026-02-02", "venue": "", "shares": 1000, "value": 45000, "currency": "AUD", "price_unit": "AUD", "price_avg": 45.0, "price_high": None, "price_low": None}]})
    m.commit()
    assert hand.migrate(m) == 1
    e = hand.listing(m, "AU")["entries"]
    assert len(e) == 1 and e[0]["fields"]["shares"] == 1000 and e[0]["fields"]["value"] == 45000 and e[0]["fields"]["venue"] == "ASX" and "no source was recorded" in e[0]["source"]
    assert m.execute("select count(*) from transactions").fetchone()[0] == 1 and m.execute("select d.form from transactions t join documents d on d.doc_id=t.doc_id").fetchone()[0] == "manual"
    assert not (old / "manual_entries.csv").exists() and len(list(old.glob("manual_entries_moved_to_Add_by_hand_*.csv.bak"))) == 1  # the old file kept, renamed so it isn't read again
    assert hand.listing(m, "AU")["log"][0]["action"] == "MOVED"
    assert hand.migrate(m) == 0  # once only
    m.execute("insert into documents(sha256,country,file_name,rel_path,status,imported_at,doc_type) values('typed2','AU','manual_entries.csv','inbox/AU/manual_entries.csv','PARSED','x','transactions csv')")
    doc2 = m.execute("select max(doc_id) from documents").fetchone()[0]
    ingest.store(m, doc2, "AU", "BHP", {"programme": {"announced_date": ""}, "snapshots": [], "doc_date": "2026-02-02",
                                        "transactions": [{"trade_date": "2026-02-02", "venue": "x", "shares": 1000, "value": 45000, "currency": "AUD", "price_unit": "AUD", "price_avg": 45.0, "price_high": None, "price_low": None}]})
    m.commit()
    assert hand.migrate(m) == 0 and len(hand.listing(m, "AU")["entries"]) == 1  # the old file put back in the inbox: its rows are not added twice
    assert m.execute("select count(*) from transactions").fetchone()[0] == 1
    m.close()
finally:
    db.ROOT = real_root
print("move from manual_entries.csv: OK")

# ---------- 8. the page's requests; and the read-only copy refuses them ----------
assert "/api/hand/save" not in server.OPEN_TO_READERS and "/api/hand/delete" not in server.OPEN_TO_READERS
con.close()
db.DB_PATH, kept_path = tmp / "hand.db", db.DB_PATH
srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}"


def call(path, body=None):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


try:
    code, ch = call("/api/hand/choices?market=NZ&company=NPH")
    assert code == 200 and ch["programmes"][0]["announced_date"] == "2025-05-22" and any(m["label"] == "NZX · New Zealand" for m in ch["markets"]) and "NZX" in ch["venues"] and {"NPH", "FBU"} <= {c["ticker"] for c in ch["companies"]}
    code, made = call("/api/hand/save", {"kind": "programme", "country": "NZ", "ticker": "FBU", "announced_date": "2026-03-02", "max_shares": "25,000,000", "source": "NZX announcement of 2 March 2026"})
    assert code == 200 and made["ticker"] == "FBU", made
    code, bad = call("/api/hand/save", {"kind": "programme", "country": "NZ", "ticker": "FBU", "announced_date": "2026-03-02"})
    assert code == 400 and "Source is required" in bad["error"]
    code, got = call("/api/hand?country=NZ")
    assert code == 200 and any(x["entry_id"] == made["entry_id"] for x in got["entries"])
    code, panel = call(f"/api/document?id={made['doc_id']}")
    assert code == 200 and panel["form"] == "manual" and panel["hand"]["source"] == "NZX announcement of 2 March 2026"
    code, co = call("/api/company?country=NZ&ticker=NPH")
    assert code == 200 and co["programmes"][0]["hand_announced"] == SRC and any(t["hand_source"] for t in co["transactions"])
    assert call("/api/hand/delete", {"entry_id": made["entry_id"], "reason": "Test entry"})[0] == 200
    server.READ_ONLY["on"] = True
    code, body = call("/api/hand/save", {"kind": "programme", "country": "NZ", "ticker": "FBU", "announced_date": "2026-03-02", "source": "x y z"})
    assert code == 403 and "read-only copy" in body["error"]
    assert call("/api/hand?country=NZ")[0] == 200  # reading still works
finally:
    server.READ_ONLY["on"] = False
    srv.shutdown()
    srv.server_close()
    db.DB_PATH = kept_path
print("page requests and read-only: OK")
print("v25 OK")
