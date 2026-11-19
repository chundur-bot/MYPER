"""Run:  python -P tests/test_v28.py
Version 28: readers for the ASX forms used for buy-backs announced before 5 June 2021 (Appendix 3D changes, 3E daily notice, 3F final notice)
and for Appendix 3G (securities issued, transferred or converted), kept in the new table "issues".
The 3D, 3E and 3G fixtures are the text the app's own PDF reader gives for real filings (CSL 2015, Regal Investment Fund 2019, Woodside 2026);
the 3F fixture was typed from a scanned filing (Infratil 2013) in the same layout, as that PDF has no text.
Works on scratch files in a temporary folder; buyback.db and the inbox of the real app are not touched."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from sbb import db, fetching, ingest, parsers, queries as q, tracker  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
text = lambda name: (FIX / name).read_text(encoding="utf-8")
tmp = Path(tempfile.mkdtemp())
fetching.LINKS_FILE = tmp / "filing_links.csv"
ingest.scan = lambda con: {}
con = db.connect(tmp / "asx.db")
for t, name in (("RF1", "Regal Investment Fund"), ("IFT", "Infratil Limited"), ("CSL", "CSL Limited"), ("WDS", "Woodside Energy Group Ltd")):
    con.execute("insert into companies(country,ticker,company,in_index) values('AU',?,?,1)", (t, name))
con.commit()
n = [0]


def read(body, ticker, title=""):
    n[0] += 1
    return ingest.import_link(con, f"https://docs.example.test/{ticker}/{n[0]}.txt", "AU", body.encode("utf-8"), ".txt", ticker_hint=ticker, title=title)


# ---------- 1. the readers ----------
p = parsers.parse(text("asx_3e_regal_2019.txt"), "AUD", "AU", "DMY")
assert (p["form"], p["doc_type"], p["doc_date"], p["programme"]["announced_date"], p["programme"]["buyback_type"]) == ("appendix_3e", "daily", "2019-12-04", "2019-09-06", "On-market buy-back"), p
t = p["transactions"][0]
assert (t["trade_date"], t["shares"], t["value"], t["currency"], t["price_high"], t["price_low"]) == ("2019-12-03", 33996, 88486.83, "AUD", 2.6, 2.6), t
assert [(s["cum_shares"], s["cum_value"], s["origin"]) for s in p["snapshots"]] == [(1229107, 3331541.77, "reported"), (1263103, 3331541.77 + 88486.83, "sum")]
assert "10,007,999 Units" in p["programme"]["size_note"] and not p["issues"]
p = parsers.parse(text("asx_3f_infratil_2013_typed.txt"), "AUD", "AU", "DMY")
assert (p["form"], p["doc_type"], p["doc_date"], p["programme"]["status"], p["programme"]["buyback_type"]) == ("appendix_3f", "final", "2013-12-13", "COMPLETED", "On-market (NZX only)"), p
assert p["snapshots"] == [{"as_of": "2013-12-13", "cum_shares": 1183615, "cum_value": 2681133.96, "currency": "NZD", "origin": "reported"}]
p = parsers.parse(text("asx_3d_csl_2015.txt"), "AUD", "AU", "DMY")
assert (p["form"], p["doc_type"], p["previous_date"], p["reason"], p["programme"]) == ("appendix_3d", "update", "2015-02-25", "Appointment of broker.", {}), p
assert [k for k, _ in p["issues"]] == ["CHANGE_UNCLEAR"] and "Item 2 (broker)" in p["issues"][0][1] and "UBS AG" in p["issues"][0][1]
p = parsers.parse(text("asx_3g_woodside_2026.txt"), "AUD", "AU", "DMY")
assert (p["form"], p["ticker"], p["doc_date"], len(p["issued"]), p["on_issue"]["shares"]) == ("appendix_3g", "WDS", "2026-10-08", 4, 1901100143), p
assert [(x["shares"], x["issued_on"], x["from_security"].split(" :")[0], x["provided_by"]) for x in p["issued"]] == [
    (34216, "2026-09-01", "WDSAL", "Transfer of existing securities"), (690, "2026-10-01", "WDSAE", "Transfer of existing securities"),
    (8370, "2026-09-01", "WDSAL", "Transfer of existing securities"), (8299, "2026-09-01", "WDSAE", "Transfer of existing securities")]
assert "Supplementary Woodside Equity Plan" in p["issued"][0]["other_info"] and not p["issues"]
broken = text("asx_3g_woodside_2026.txt").replace("Number of +securities\n34,216", "Number of +securities\n34,215")
assert any(k == "CHECK_FAILED" for k, _ in parsers.parse(broken, "AUD", "AU", "DMY")["issues"])  # the detail no longer adds up to the summary
print("readers: OK")

# ---------- 2. Appendix 3E read and stored: the purchase date worked out, the totals dated as in version 26 ----------
assert read(text("asx_3e_regal_2019.txt"), "RF1") == "PARSED"
tx = con.execute("select * from transactions where ticker='RF1'").fetchone()
assert (tx["trade_date"], tx["shares"], tx["value"], tx["value_origin"]) == ("2019-12-03", 33996, 88486.83, "reported")
snaps = [(s["as_of"], s["cum_shares"], s["origin"]) for s in con.execute("select s.* from snapshots s join programmes p using(prog_id) where p.ticker='RF1' order by as_of")]
assert snaps == [("2019-12-02", 1229107, "reported"), ("2019-12-03", 1263103, "sum")], snaps
c = q.company(con, "AU", "RF1", q.ALL_FROM, q.ALL_TO)
assert "trading day before the notice dated 2019-12-04" in c["transactions"][0]["date_working"]
prog = con.execute("select * from programmes where ticker='RF1'").fetchone()
assert (prog["announced_date"], prog["buyback_type"]) == ("2019-09-06", "On-market buy-back")
# the next day's notice (signed Thursday 5 December): its 'before' total is the 3 December closing total, so the two are one
nxt = text("asx_3e_regal_2019.txt").replace("1,229,107", "1,263,103").replace("33,996", "10,000").replace("$3,331,541.77 $88,486.83", "$3,420,028.60 $26,000.00").replace("Date: 04 December 2019", "Date: 05 December 2019")
assert read(nxt, "RF1") == "PARSED"
snaps = [(s["as_of"], s["cum_shares"], s["origin"]) for s in con.execute("select s.* from snapshots s join programmes p using(prog_id) where p.ticker='RF1' order by as_of")]
assert snaps == [("2019-12-02", 1229107, "reported"), ("2019-12-03", 1263103, "reported"), ("2019-12-04", 1273103, "sum")], snaps
monday = text("asx_3e_regal_2019.txt").replace("Date: 04 December 2019", "Date: 09 December 2019").replace("33,996", "5,000").replace("1,229,107", "1,273,103").replace("$3,331,541.77 $88,486.83", "$3,446,028.60 $13,000.00")
assert read(monday, "RF1") == "PARSED"
assert con.execute("select trade_date from transactions where ticker='RF1' and shares=5000").fetchone()[0] == "2019-12-06"  # a Monday notice: the Friday before
print("3E: OK")

# ---------- 3. Appendix 3F: the final totals; the programme Completed ----------
assert read(text("asx_3f_infratil_2013_typed.txt"), "IFT") == "PARSED"
s = con.execute("select s.*, p.status from snapshots s join programmes p using(prog_id) where p.ticker='IFT'").fetchone()
assert (s["as_of"], s["cum_shares"], s["cum_value"], s["currency"], s["origin"], s["status"]) == ("2013-12-13", 1183615, 2681133.96, "NZD", "reported", "COMPLETED")
print("3F: OK")

# ---------- 4. Appendix 3D: a change it can tell apart is taken; one it can't goes to review, and nothing is guessed ----------
con.execute("insert into programmes(country,ticker,announced_date,start_date,end_date,status) values('AU','CSL','2014-08-13','2014-11-13','2015-11-12','ACTIVE')")
assert read(text("asx_3d_csl_2015.txt"), "CSL") == "NEEDS_REVIEW"
assert con.execute("select count(*) from review where ticker='CSL' and kind='CHANGE_UNCLEAR'").fetchone()[0] == 1
assert con.execute("select end_date from programmes where ticker='CSL'").fetchone()[0] == "2015-11-12"
extended = text("asx_3d_csl_2015.txt").replace("Date: 21 April 2015", "Date: 01 October 2015")
NL = chr(10)  # the fixture's lines end in a space; written out so no editor can trim them
extended = extended.replace(NL.join(["at any time. ", "No change. ", "    ", "7 If"]),
                            NL.join(["at any time. ", "The Company intends to buy back shares in the period 13 November 2015 to 12 November 2016 (inclusive). ", "    ", "7 If"]))
extended = extended.replace("Appointment of broker.", "Extension of the buy-back period.")
extended = extended.replace(NL.join(["Citigroup Global Markets ", "Australia Pty Ltd, for ", "purchases with a total ", "consideration of up to ", "approximately A$350 ", "million. ",
                                     "UBS AG, Australia ", "Branch, for purchases ", "with a total consideration ", "of up to approximately ", "A$250 million. "]),
                            NL.join(["Citigroup Global Markets ", "Australia Pty Ltd ", "No change. "]))
assert "13 November 2015 to 12 November 2016" in extended and "UBS AG" not in extended
assert read(extended, "CSL") == "PARSED"
g = con.execute("select start_date, end_date from programmes where ticker='CSL'").fetchone()
assert tuple(g) == ("2015-11-13", "2016-11-12"), tuple(g)
assert con.execute("select reason from documents where reason like 'Extension%'").fetchone()
print("3D: OK")

# ---------- 5. Appendix 3G: the issues, kept apart; the shares on issue afterwards ----------
assert read(text("asx_3g_woodside_2026.txt"), "WDS") == "PARSED"
rows = con.execute("select * from issues where ticker='WDS' order by n").fetchall()
assert [(r["shares"], r["issued_on"], r["provided_by"]) for r in rows][:2] == [(34216, "2026-09-01", "Transfer of existing securities"), (690, "2026-10-01", "Transfer of existing securities")] and len(rows) == 4
assert con.execute("select shares from share_counts where ticker='WDS' and as_of='2026-10-08'").fetchone()[0] == 1901100143
assert not con.execute("select 1 from programmes where ticker='WDS'").fetchone()  # an issue is not a buy-back: no programme is made
c = q.company(con, "AU", "WDS", q.ALL_FROM, q.ALL_TO)
assert len(c["issues"]) == 4 and c["issues"][0]["security_code"] == "WDS"
assert len(q.issues(con, "AU", q.ALL_FROM, q.ALL_TO)["rows"]) == 4
print("3G: OK")

# ---------- 6. labels, the Tracker, rebuilds and removal ----------
db.fill_labels(con)
labels = {r["form"]: (r["appendix"], r["filing_type"]) for r in con.execute("select form, appendix, filing_type from documents")}
assert labels["appendix_3e"] == ("Appendix 3E", "Daily share buy-back notice") and labels["appendix_3g"] == ("Appendix 3G", "Issue or transfer of securities"), labels
tracker.run(con)
kinds = {r["reader"]: (r["type"], r["in_scope"], r["confidence"]) for r in con.execute("select reader, type, in_scope, confidence from tracker_notices")}
assert kinds["appendix_3e"] == ("Daily transaction", 1, "high") and kinds["appendix_3f"][0] == "Final notice" and kinds["appendix_3g"][:2] == ("Issue of securities", 0), kinds
before = {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("transactions", "snapshots", "issues", "share_counts")}
for tk in ("RF1", "IFT", "CSL", "WDS"):
    ingest.replay(con, "AU", tk)
assert {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in before} == before
ingest.rebuild(con)
assert {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in before} == before, "a full rebuild leaves nothing behind"
doc = con.execute("select doc_id from documents where form='appendix_3g'").fetchone()[0]
ingest.remove_filing(con, doc)
assert not con.execute("select 1 from issues").fetchone()
print("rebuild and removal: OK")
print("ALL v28 TESTS PASSED")
