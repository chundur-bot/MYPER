"""Run:  python -P tests/test_v27.py
Version 27: Updated Manually. One figure read from a filing (a programme's terms, a purchase, a running total) is changed by you, with its source
and reason; the filing's reading is kept unchanged; the update is applied again after every rebuild and after a single filing is read; figures
worked out from it are worked out again and stay Calculated; a row read wrongly can be set aside; every update can be edited or undone and is kept
in the history; questions go to review; the Tracker and Excel use and show it.
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
from sbb import db, fetching, hand, ingest, queries as q, tracker  # noqa: E402

tmp = Path(tempfile.mkdtemp())
fetching.LINKS_FILE = tmp / "filing_links.csv"
ingest.scan = lambda con: {}
con = db.connect(tmp / "upd.db")
con.execute("insert into companies(country,ticker,company,in_index) values('AU','AMP','AMP Limited',1)")
PROG = {"announced_date": "2022-08-01", "buyback_type": "On market buy-back", "start_date": "2022-08-15", "end_date": "2023-08-14", "max_shares": None,
        "max_value": 1100000000.0, "max_currency": "AUD", "max_text": "A$1.1 billion", "shares_on_issue": 3200000000.0}
n = [0]


def weekday_after(d):
    x = date.fromisoformat(d) + timedelta(days=1)
    while x.weekday() > 4:
        x += timedelta(days=1)
    return x.isoformat()


def add(p):
    n[0] += 1
    sha = hashlib.sha256(f"AMP{n[0]}".encode()).hexdigest()
    cur = con.execute("insert into documents(sha256,country,ticker,doc_type,doc_date,status,form,parsed_json,imported_at,source_url) values(?,?,?,?,?,?,?,?,?,?)",
                      (sha, "AU", "AMP", p["doc_type"], p["doc_date"], "PARSED", p["form"], json.dumps({"p": p, "ev": [], "hint": "AMP"}), db.now(), f"https://example.test/amp/{n[0]}.pdf"))
    return cur.lastrowid


def daily(trade, bs, bv, sh, v):
    prev = (date.fromisoformat(trade) - timedelta(days=1)).isoformat()
    return {"form": "appendix_3c", "ticker": "AMP", "company": "AMP", "doc_type": "daily", "doc_date": weekday_after(trade), "programme": dict(PROG),
            "transactions": [{"trade_date": trade, "venue": "", "shares": sh, "value": v, "currency": "AUD", "price_unit": "AUD", "price_avg": v / sh, "price_high": None, "price_low": None, "value_origin": "reported"}],
            "snapshots": [{"as_of": prev, "cum_shares": bs, "cum_value": bv, "currency": "AUD", "origin": "reported"},
                          {"as_of": trade, "cum_shares": bs + sh, "cum_value": bv + v, "currency": "AUD", "origin": "sum", "working": f"AUD {bv:,.2f} before that day + AUD {v:,.2f} on the day"}],
            "issues": [], "reason": "Daily buy-back notification", "previous_date": trade}


days = [("2022-08-25", 4054085, 4540169.79), ("2022-08-26", 2252400, 2536427.64), ("2022-08-29", 3965387, 4373028.78), ("2022-08-30", 4905954, 5475535.26), ("2022-08-31", 10160642, 11653240.31)]
docs, bs, bv = {}, 0.0, 0.0
for d, sh, v in days:
    docs[d] = add(daily(d, bs, bv, float(sh), v))
    bs, bv = bs + sh, bv + v
con.commit()
ingest.replay(con, "AU", "AMP")
pid = lambda: con.execute("select prog_id from programmes where ticker='AMP'").fetchone()[0]
tx = lambda d: con.execute("select * from transactions where trade_date=?", (d,)).fetchone()
snap = lambda d: con.execute("select * from snapshots where as_of=?", (d,)).fetchone()
before = {t: tuple(r) for t in ("transactions", "snapshots", "programmes") for r in [sorted(map(tuple, con.execute(f"select * from {t}").fetchall()))]}
assert snap("2022-08-31")["cum_shares"] == 25338468 and snap("2022-08-31")["origin"] == "sum"
BASE = {"kind": "update", "country": "AU", "ticker": "AMP", "programme": "2022-08-01", "source": "AMP Appendix 3C of 1 September 2022, page 2", "note": "Digits misread"}


def refused(body, words):
    try:
        hand.save(con, body)
    except ValueError as e:
        assert words in str(e), (words, str(e))
        return
    raise AssertionError(f"should have refused: {body}")


# ---------- 1. what is refused ----------
P31 = {**BASE, "target": "purchase", "trade_date": "2022-08-31", "venue": "", "price_unit": "AUD", "field": "shares"}
refused({**P31, "value": "10,160,742", "source": ""}, "Source is required")
refused({**P31, "value": "10,160,742", "note": ""}, "Reason is required")
refused({**P31, "value": "10,160,642"}, "already 10,160,642")
refused({**P31, "value": "0"}, "must be more than 0")
refused({**P31, "trade_date": "2022-08-27", "value": "5"}, "No purchase on 2022-08-27")
refused({**P31, "field": "colour", "value": "5"}, "Choose the figure")
refused({**P31, "programme": "2021-01-01", "value": "5"}, "No programme announced 2021-01-01")
print("refusals: OK")

# ---------- 2. a purchase's shares: the row, its average (worked out from amount / shares) and the day's closing total are worked out again ----------
u1 = hand.save(con, {**P31, "value": "10,160,742"})
assert u1["kind_label"] == "Updated Manually" and "10,160,642 → 10,160,742" in u1["what"], u1
t = tx("2022-08-31")
assert t["shares"] == 10160742 and t["value_origin"] == "reported" and abs(t["price_avg"] - 11653240.31 / 10160742) < 1e-9, dict(t)
s = snap("2022-08-31")
assert s["cum_shares"] == 25338568 and abs(s["cum_value"] - 28578401.78) < 0.005 and s["origin"] == "sum" and "Updated Manually, update" in s["working"], dict(s)
refused({**P31, "value": "10,160,743"}, "already has an update")
print("purchase shares: OK")

# ---------- 3. a purchase's amount: marked updated; the day's total stated by the next notice is not changed ----------
u2 = hand.save(con, {**BASE, "target": "purchase", "trade_date": "2022-08-30", "venue": "", "price_unit": "AUD", "field": "value", "value": "5,475,536.26"})
t = tx("2022-08-30")
assert t["value"] == 5475536.26 and t["value_origin"] == "updated", dict(t)
assert snap("2022-08-30")["origin"] == "reported" and abs(snap("2022-08-30")["cum_value"] - 16925161.47) < 0.005
print("purchase amount: OK")

# ---------- 4. a running total, and the programme's terms and status ----------
u3 = hand.save(con, {**BASE, "target": "total", "as_of": "2022-08-29", "field": "cum_value", "value": "11,449,627.21"})
s = snap("2022-08-29")
assert s["cum_value"] == 11449627.21 and s["origin"] == "updated" and "as read AUD 11,449,626.21" in s["working"], dict(s)
u4 = hand.save(con, {**BASE, "target": "programme", "field": "end_date", "value": "2023-08-31", "source": "AMP announcement of 1 Aug 2022, para 4"})
u5 = hand.save(con, {**BASE, "target": "programme", "field": "status", "value": "COMPLETED", "source": "AMP notice of 1 Sep 2022"})
p = con.execute("select * from programmes where ticker='AMP'").fetchone()
assert p["end_date"] == "2023-08-31" and p["status"] == "COMPLETED"
row = next(r for r in q.programme_rows(con, "AU", q.ALL_FROM, q.ALL_TO) if r["ticker"] == "AMP")
assert row["status_basis"] == "Updated Manually" and "end_date" in row["updated"] and row["updated_count"] == 5 and "5 figure(s) Updated Manually" in row["hand_text"], row["updated"]
print("total, terms and status: OK")

# ---------- 5. set aside a purchase read wrongly: it leaves every figure; the day's worked-out total follows ----------
u6 = hand.save(con, {**BASE, "target": "purchase", "trade_date": "2022-08-25", "venue": "", "price_unit": "AUD", "field": "set_aside", "note": "Not a buyback purchase"})
assert tx("2022-08-25") is None and "Set aside" in u6["what"]
assert snap("2022-08-25")["origin"] == "reported" and snap("2022-08-25")["cum_shares"] == 4054085  # stated by the next notice: never changed
print("set aside: OK")

# ---------- 6. the screens' figures carry the marks ----------
c = q.company(con, "AU", "AMP", q.ALL_FROM, q.ALL_TO)
t31 = next(x for x in c["transactions"] if x["trade_date"] == "2022-08-31")
assert "shares" in t31["updated"] and "derived" in t31["updated"] and c["updates"] == 6, t31["updated"]
d = {r["trade_date"]: r for r in q.daily_rows(con, pid())}
assert d["2022-08-30"]["value_basis"] == "Updated Manually" and d["2022-08-29"]["cum_basis"] == "Updated Manually" and d["2022-08-31"]["cum_basis"] == "Calculated"
assert "Updated Manually" in (d["2022-08-31"]["cum_working"] or "")
x = q.transactions(con, "AU", q.ALL_FROM, q.ALL_TO)
assert any(r["updated"].get("value") for r in x)
print("screens: OK")

# ---------- 7. a rebuild gives the same figures; applying again changes nothing ----------
after = {t: sorted(map(tuple, con.execute(f"select * from {t}").fetchall())) for t in ("transactions", "snapshots")}
ingest.replay(con, "AU", "AMP")
ingest.replay(con, "AU", "AMP")
again = {t: sorted(map(tuple, con.execute(f"select * from {t}").fetchall())) for t in ("transactions", "snapshots")}
strip = lambda rows: [r[1:] for r in rows]  # row ids change in a rebuild
assert strip(after["transactions"]) == strip(again["transactions"]) and strip(after["snapshots"]) == strip(again["snapshots"])
hand.apply_updates(con, "AU", "AMP", rebuilt=False)
assert strip(sorted(map(tuple, con.execute("select * from snapshots").fetchall()))) == strip(again["snapshots"])
assert not con.execute("select 1 from review where kind like 'UPDATE_%'").fetchone()
print("rebuild: OK")

# ---------- 8. a new filing read for the company keeps the updates in force ----------
new = add(daily("2022-09-01", 25338468.0, 28578401.78, 1000.0, 1100.0))
saved = json.loads(con.execute("select parsed_json from documents where doc_id=?", (new,)).fetchone()[0])
ingest._apply_link(con, new, "AU", "AMP", saved["p"], saved["ev"])
assert tx("2022-08-31")["shares"] == 10160742 and tx("2022-08-25") is None and snap("2022-08-29")["cum_value"] == 11449627.21
print("new filing: OK")

# ---------- 9. questions at the rebuild ----------
pj = json.loads(con.execute("select parsed_json from documents where doc_id=?", (docs["2022-08-30"],)).fetchone()[0])
pj["p"]["transactions"][0]["value"] = 5475536.26  # the reader now reads your value
con.execute("update documents set parsed_json=? where doc_id=?", (json.dumps(pj), docs["2022-08-30"]))
pj = json.loads(con.execute("select parsed_json from documents where doc_id=?", (docs["2022-08-31"],)).fetchone()[0])
pj["p"]["transactions"][0]["shares"] = 10160000.0  # the reader now reads something else
con.execute("update documents set parsed_json=? where doc_id=?", (json.dumps(pj), docs["2022-08-31"]))
ingest.replay(con, "AU", "AMP")
kinds = {r["kind"]: r["detail"] for r in con.execute("select kind, detail from review where kind like 'UPDATE_%' and status='OPEN'")}
assert "UPDATE_NOW_READ" in kinds and f"Update {u2['entry_id']} (" in kinds["UPDATE_NOW_READ"], kinds
assert "UPDATE_READ_CHANGED" in kinds and "now reads 10,160,000" in kinds["UPDATE_READ_CHANGED"] and tx("2022-08-31")["shares"] == 10160742, kinds
listed = {e["entry_id"]: e for e in hand.listing(con, "AU")["entries"]}
assert listed[u2["entry_id"]]["review"] and listed[u1["entry_id"]]["review"]
ingest.remove_filing(con, docs["2022-08-30"])  # its filing removed on the company panel
ingest.replay(con, "AU", "AMP")
kinds = [r["kind"] for r in con.execute("select kind from review where kind like 'UPDATE_%' and status='OPEN'")]
assert "UPDATE_NOT_FOUND" in kinds, kinds
print("review questions: OK")

# ---------- 10. edit and undo; history ----------
e1 = hand.save(con, {**P31, "value": "10,160,842", "entry_id": u1["entry_id"]})
assert tx("2022-08-31")["shares"] == 10160842 and "→ 10,160,842" in e1["what"] and "10,160,642 →" in e1["what"]  # 'as read' is kept from when it was made
hand.delete(con, u1["entry_id"], "Checked: the reading was right after all")
assert tx("2022-08-31")["shares"] == 10160000  # what the filing reads now comes back
hand.delete(con, u6["entry_id"], "It was a purchase")
assert tx("2022-08-25")["shares"] == 4054085
L = hand.listing(con, "AU")
assert any(r["entry_id"] == u1["entry_id"] and r["delete_reason"].startswith("Checked") for r in L["deleted"])
acts = [x["action"] for x in L["log"] if x["entry_id"] == u1["entry_id"]]
assert acts == ["DELETED", "EDITED", "ADDED"], acts
print("edit, undo, history: OK")

# ---------- 11. the Tracker uses the updated figures and says so ----------
tracker.run(con)
conf = {r["confidence"] for r in con.execute("select confidence from tracker_notices where ticker='AMP'")}
assert "updated manually" in conf, conf
pl = json.loads(con.execute("select data from tracker_plans where ticker='AMP'").fetchone()[0])
assert pl.get("end") == "2023-08-31" or pl.get("end_date") == "2023-08-31" or "2023-08-31" in json.dumps(pl), "the Tracker plan uses the end date Updated Manually"
print("tracker: OK")

# ---------- 12. the form's choices: the figure as held, and where it was read ----------
ch = hand.update_choices(con, "AU", "AMP", "2022-08-01", "purchase", "2022-08-29||AUD", "shares")
assert ch["asread"]["value"] == 3965387 and ch["asread"]["doc_id"] == docs["2022-08-29"] and any(p["key"] == "2022-08-29||AUD" for p in ch["purchases"]), ch["asread"]
assert hand.update_choices(con, "AU", "AMP", "2022-08-01", "total", "2022-08-29", "cum_value")["asread"]["already"] == u3["entry_id"]
print("form choices: OK")

# ---------- 13. a full rebuild (Reset > Rebuild) keeps the updates ----------
ingest.scan = lambda con: {}
ingest.rebuild(con)
assert snap("2022-08-29")["cum_value"] == 11449627.21 and con.execute("select end_date from programmes where ticker='AMP'").fetchone()[0] == "2023-08-31"
print("full rebuild: OK")
print("ALL v27 TESTS PASSED")
