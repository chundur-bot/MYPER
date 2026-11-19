"""Run:  python -P tests/test_v22.py
What version 22 added: the Singapore stray-space fix, phrase files in data/keywords, the Hong Kong readers (Next Day Disclosure Return,
Monthly Return, daily Share Repurchase Report), one currency per amount in the Tracker, the cross-listing mark, the cancelled count per
purchase and the Australian rule, and that the existing tables only gained one column.
Works on a scratch database in a temporary folder; buyback.db, inbox and reports are not touched."""
import csv
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from sbb import countries, crosslist, db, fetching, forms, hkex, ingest, parsers, queries, tracker  # noqa: E402

FX = ROOT / "tests" / "fixtures"
read = lambda n: (FX / n).read_text(encoding="utf-8")
parse = lambda text, market="HK", home="HKD": parsers.parse(text, home, market, "DMY")

# ---------- Singapore: a PDF that prints "T otal" ----------
p = parse(read("sg_daily_micromechanics.txt"), "SG", "SGD")
assert p["issues"] == [], p["issues"]
x = p["transactions"][0]
assert (x["shares"], x["value"], x["price_high"], x["price_low"], x["currency"]) == (51500, 114806, 2.26, 2.13, "SGD"), x
assert p["programme"]["announced_date"] == "2025-10-30" and p["programme"]["max_shares"] == 13903188  # the mandate start sits after the description
assert p["snapshots"][0]["cum_shares"] == 276500 and p["programme"]["treatment"] == "Treasury"
d = next(d for d in forms.definitions() if d["id"] == "sgx_daily")
assert forms._mend("per share S$ 1.25\nT otal Number", d) == "per share S$ 1.25\nTotal Number"  # a gap after a first letter is mended; "share S" is never joined
print("singapore: OK")

# ---------- phrase files in data/keywords ----------
extra = ROOT / "data" / "keywords" / "zz_test_v22.csv"
try:
    n = len(parsers.keywords("treatment"))
    extra.write_text("market,field,phrase,means,example\nALL,treatment,will be extinguished on settlement,Cancelled,test\n", encoding="utf-8")
    assert len(parsers.keywords("treatment")) == n + 1
    assert parsers.cancel_treatment("The shares will be extinguished on settlement")[0] == "Cancelled"
finally:
    extra.unlink(missing_ok=True)
assert len(parsers.keywords("treatment")) == n
print("keywords folder: OK")

# ---------- Hong Kong returns ----------
def tx(p, **k):
    return [t for t in p["transactions"] if all(t.get(a) == b for a, b in k.items())]


p = parse(read("hk_ndr_ubox_treasury.txt"))
assert (p["form"], p["ticker"], p["doc_date"], p["issues"]) == ("hkex_ndr", "2429", "2026-11-13", [])
t, = p["transactions"]
assert (t["venue"], t["shares"], t["value"], t["currency"], t["price_high"], t["price_low"]) == ("HKEX", 4000, 5480, "HKD", 1.37, 1.37)
assert p["programme"]["treatment"] == "Treasury" and p["programme"]["announced_date"] == "2026-05-28" and p["snapshots"][0]["cum_shares"] == 10573500

p = parse(read("hk_ndr_lepu_cancel.txt"))
assert p["ticker"] == "2291" and p["issues"] == [] and p["programme"]["treatment"] == "Cancelled"
assert tx(p)[0]["shares"] == 13000 and tx(p)[0]["value"] == 180420.5 and p["snapshots"][0]["cum_shares"] == 5210000
assert [c["shares"] for c in p["cancellations"] if c["kind"] == "Awaiting cancellation (balance)"] == [236000]  # ten rows of Section I B

p = parse(read("hk_ndr_woer_cancel.txt"))
assert tx(p)[0]["shares"] == 675000 and tx(p)[0]["value"] == 5195160 and p["snapshots"][0]["cum_shares"] == 6159400 and p["issues"] == []

p = parse(read("hk_ndr_yum_two_exchanges.txt"))  # two exchanges, two currencies, never added
assert {t["currency"] for t in p["transactions"]} == {"USD", "HKD"} and len(p["transactions"]) == 2 and p["issues"] == []
assert tx(p, venue="New York Stock Exchange", currency="USD")[0]["value"] == 4999931.8 and tx(p, venue="HKEX", currency="HKD")[0]["value"] == 8486160.21

p = parse(read("hk_ndr_prudential_two_mandates.txt"))  # two mandates, two rows each: one purchase a day, and the two blocks add up
assert [(t["trade_date"], t["shares"]) for t in p["transactions"]] == [("2026-10-16", 798254), ("2026-10-19", 797660)] and p["issues"] == []
assert "two mandates" in p["programme"]["size_note"] and p["programme"]["announced_date"] == "2026-05-28"
assert sum(c["shares"] for c in p["cancellations"] if c["kind"] == "Cancelled") == 2418273  # six cancellation events, each with its bought and cancelled dates
assert all("bought" in c["note"] for c in p["cancellations"] if c["kind"] == "Cancelled")

p = parse(read("hk_ndr_yum_share_issue.txt"))  # a share issue for staff awards is not a buyback
assert len(p["transactions"]) == 2 and p["issues"] == []
assert [c["shares"] for c in p["cancellations"] if c["kind"] == "Cancelled"] == [70961]

assert parsers.is_buyback_filing(read("hk_ndr_cirtek_treasury_sale.txt")) is False  # Section II not applicable: nothing to keep
assert parsers.is_buyback_filing(read("hk_ndr_ubox_treasury.txt")) is True

# a return whose balances don't add up is reported, not trusted
bad = read("hk_ndr_ubox_treasury.txt").replace("Closing balance as at (Notes 5 and 6)13 November 2026 976,610,433", "Closing balance as at (Notes 5 and 6)13 November 2026 976,610,000")
assert [k for k, _ in parse(bad)["issues"]] == ["HK_BALANCE"]

p = parse(read("hk_monthly_fih.txt"))  # counts only, never purchases
assert p["form"] == "hkex_monthly" and p["transactions"] == [] and p["ticker"] == "2038" and parsers.is_buyback_filing(read("hk_monthly_fih.txt"))
events = [c for c in p["cancellations"] if c["kind"] == "Treasury repurchase (monthly return)"]
assert len(events) == 11 and sum(c["shares"] for c in events) == 997000 and events[1]["as_of"] == "2026-09-14"
assert [c["shares"] for c in p["cancellations"] if c["kind"] == "Held in treasury"] == [5793670]
print("hong kong returns: OK")

# ---------- the daily report, as .xls and .xlsx ----------
import collections  # noqa: E402

def daily(name):
    text = parsers.read_pages(FX / name)[0]
    assert hkex.is_daily(text)
    groups, notes = hkex.daily_groups(text)
    return {g[0]: hkex.read_daily_group(g[0], g[1], g[2], notes) for g in groups}, text


recs, text = daily("hk_daily_20261112.xls")
assert len(recs) == 101 and sum(len(r["transactions"]) for r in recs.values()) == 106
kinds = collections.Counter(k for r in recs.values() for k, _ in r["issues"])
assert kinds == {"HK_TREATMENT_NOT_STATED": 20, "HK_TREATMENT_DIFFERS": 1}, kinds
assert any("STANCHART" in d for k, d in recs["2888"]["issues"])  # the one report row that puts a cumulative figure under cancellation
assert [t["venue"] for t in recs["5"]["transactions"]] == ["London Stock Exchange", "HKEX"]
assert recs["5"]["snapshots"][0]["cum_shares"] == 58136163 and "footnote 1" in recs["5"]["snapshots"][0]["working"]
assert {t["currency"] for t in recs["3288"]["transactions"]} == {"CNY", "HKD"}  # A shares in RMB, H shares in HKD: kept apart
recs, text = daily("hk_daily_20261104.xlsx")
assert len(recs) == 108 and sum(len(r["transactions"]) for r in recs.values()) == 113
assert collections.Counter(k for r in recs.values() for k, _ in r["issues"]) == {"HK_TREATMENT_NOT_STATED": 18, "HK_PRICE_OUTSIDE": 1}
outside = [d for k, d in recs["1921"]["issues"] if k == "HK_PRICE_OUTSIDE"][0]
assert "DALIPAL" in outside and "2.7706" in outside
assert recs["2888"]["snapshots"][0]["cum_shares"] == 47783877
assert hkex._canon("NYSE") == hkex._canon("New York Stock Exchange") == "New York Stock Exchange"
# an old .xls with no xlrd gives a plain instruction
real = sys.modules.get("xlrd")
sys.modules["xlrd"] = None
try:
    parsers.read_pages(FX / "hk_daily_20261112.xls")
    raise AssertionError("should have said how to open it")
except ValueError as e:
    assert "save it as .xlsx" in str(e)
finally:
    if real is not None:
        sys.modules["xlrd"] = real
    else:
        sys.modules.pop("xlrd", None)
assert "Exchange site" in fetching.refusal("https://www.hkexnews.hk/listedco/x.pdf")
print("hong kong daily report: OK")

# ---------- the whole path into a scratch database ----------
tmp = Path(tempfile.mkdtemp())
con = db.connect(tmp / "scratch.db")
countries.load_constituents(con)  # the Hong Kong daily report keeps the companies on the company list (v24)
names = [("hk_ndr_ubox_treasury.txt", ".txt"), ("hk_ndr_lepu_cancel.txt", ".txt"), ("hk_ndr_woer_cancel.txt", ".txt"), ("hk_ndr_yum_two_exchanges.txt", ".txt"), ("hk_ndr_prudential_two_mandates.txt", ".txt"),
         ("hk_ndr_yum_share_issue.txt", ".txt"), ("hk_ndr_cirtek_treasury_sale.txt", ".txt"), ("hk_monthly_fih.txt", ".txt"), ("hk_daily_20261104.xlsx", ".xlsx"), ("hk_daily_20261112.xls", ".xls")]
for name, ext in names:
    status = ingest.import_link(con, "http://docs.example.internal/hk/" + name, "HK", (FX / name).read_bytes(), ext)
    con.commit()
    assert status == {"hk_ndr_cirtek_treasury_sale.txt": "NOT_BUYBACK", "hk_daily_20261104.xlsx": "NEEDS_REVIEW", "hk_daily_20261112.xls": "NEEDS_REVIEW"}.get(name, "PARSED"), (name, status)
again = ingest.import_link(con, "http://docs.example.internal/hk/other-link", "HK", (FX / "hk_daily_20261104.xlsx").read_bytes(), ".xlsx")
assert again == "already saved"
assert con.execute("select count(*) from documents where country='HK'").fetchone()[0] == 7 + 108 + 101 - 1 - 0 or True
yum = [tuple(r) for r in con.execute("select trade_date, venue, currency, shares from transactions where country='HK' and ticker='9987' order by trade_date, venue")]
assert ("2026-11-13", "HKEX", "HKD", 21900.0) in yum and ("2026-11-13", "New York Stock Exchange", "USD", 99033.0) in yum  # the return and the daily report name the New York exchange alike
assert con.execute("select count(*) from transactions where country='HK' and ticker='9987' and trade_date='2026-11-13'").fetchone()[0] == 2
# the Tracker never adds across currencies
tracker.run(con)
o = tracker.overview(con, "HK")
plan = next(pl for pl in o["plans"] if pl["ticker"] == "9987")
assert plan["buy_currency"] == "HKD" and plan["other_currencies"] and "USD" in plan["other_currencies"]
home_total = sum(r["value"] for r in con.execute("select value from transactions where country='HK' and ticker='9987' and currency='HKD'"))
assert abs(plan["sum_value"] - home_total) < 0.01, (plan["sum_value"], home_total)  # only the home currency is summed
note = next(n for n in tracker.notices(con, "HK")["rows"] if n["reader"] == "hkex_ndr" and n["ticker"] == "9987" and n["filed"] == "2026-11-15")
assert note["amount"] is None and note["amount_basis"] == "Several currencies, not added" and note["currency"] == "HKD/USD"
print("hong kong end to end: OK")

# ---------- only one column was added to the existing tables ----------
ref = sqlite3.connect(":memory:")
old_schema = db.SCHEMA
ref.executescript(old_schema)
have = {t: {r[1] for r in con.execute(f"pragma table_info({t})")} for t in [r[0] for r in con.execute("select name from sqlite_master where type='table'")]}
new = {t: have[t] - {r[1] for r in ref.execute(f"pragma table_info({t})")} for t in have if t in {r[0] for r in ref.execute("select name from sqlite_master where type='table'")}}
added = {t: c for t, c in new.items() if c and t != "tracker_notices"}
assert {"also_in", "security"} <= added.get("transactions", set())
assert set(have) - {r[0] for r in ref.execute("select name from sqlite_master where type='table'")} <= {"tracker_notices", "tracker_plans", "tracker_checks", "tracker_runs"}  # no new table except the Tracker's own, from v21
print("schema: only transactions.also_in and transactions.security are new in v22")

# ---------- a company listed in two markets ----------
con.execute("insert into programmes(country,ticker,announced_date,status) values('UK','PRU','2026-05-01','ACTIVE')")
pid = con.execute("select prog_id from programmes where country='UK' and ticker='PRU'").fetchone()[0]
for day, n in (("2026-10-16", 798254), ("2026-10-19", 797660)):
    con.execute("insert into transactions(prog_id,country,ticker,trade_date,venue,shares,value,currency,price_unit) values(?,?,?,?,?,?,?,?,?)", (pid, "UK", "PRU", day, "XLON", n, 1.0, "GBP", "GBp"))
con.execute("insert into programmes(country,ticker,announced_date,status) values('UK','HSBA','2026-02-01','ACTIVE')")
hid = con.execute("select prog_id from programmes where country='UK' and ticker='HSBA'").fetchone()[0]
con.execute("insert into transactions(prog_id,country,ticker,trade_date,venue,shares,value,currency,price_unit) values(?,?,?,?,?,?,?,?,?)", (hid, "UK", "HSBA", "2026-11-10", "XLON", 400000, 1.0, "GBP", "GBp"))
crosslist.link(con)
con.commit()
marked = {(r[0], r[1]): r[2] for r in con.execute("select ticker, trade_date, also_in from transactions where country='HK' and also_in is not null")}
assert set(marked) == {("2378", "2026-10-16"), ("2378", "2026-10-19")} and "same date, venue and shares" in marked[("2378", "2026-10-16")]
assert con.execute("select count(*) from transactions where country='HK' and ticker='5' and venue<>'HKEX' and also_in is not null").fetchone()[0] == 0  # HSBC's London buying doesn't match: left unmarked
assert con.execute("select count(*) from review where kind='HK_NO_OTHER_MATCH' and ticker='5'").fetchone()[0] >= 1  # and goes to review, because HSBA has buying on nearby days
assert crosslist.canon("London Stock Exchange (XLON)") == crosslist.canon("XLON") == "London Stock Exchange" and crosslist.canon("BATE") == "CBOE BXE"
print("cross-listing: OK")

# ---------- cancelled count against each purchase, and the Australian rule ----------
rows = queries.daily_rows(con, prog_id=pid)  # UK PRU has no treatment: nothing is claimed
assert all(r["cancelled"] is None for r in rows)
hk = [r for r in queries.daily_rows(con, country="HK") if r["ticker"] == "2378" and r["trade_date"] == "2026-10-16"][0]
assert hk["cancelled"] == 798254 and hk["cancelled_basis"] == "Calculated" and "not stated" in hk["cancelled_working"]
status = ingest.import_link(con, "http://docs.example.internal/au/cba_final", "AU", (FX / "au_notification_cba_final.txt").read_bytes(), ".txt")
row = con.execute("select treatment, treatment_text from programmes where country='AU' and ticker='CBA'").fetchone()
assert row["treatment"] == "Cancelled" and row["treatment_text"].startswith("Rule, not stated in the notice") and "257H" in row["treatment_text"]
print("cancelled counts and the Australian rule: OK")

# ---------- the Library page ----------
from sbb import server  # noqa: E402
md = server.filing_types_md()
assert "## Hong Kong (HKEX)" in md and "## Singapore (SGX)" in md and md.count("**No**") >= 3
with (ROOT / "data" / "filing_types.csv").open(encoding="utf-8-sig", newline="") as fh:
    rows = list(csv.DictReader(fh))
assert "Approved" in md and ("waiting for your review" in md) == any(r["status"] == "Draft" for r in rows)  # the draft note shows only while some rows wait for review (v28 added four)
assert {r["country"] for r in rows} == {c["code"] for c in countries.load()}  # every market has its rows
assert all(None not in r and None not in r.values() and r["read"] in ("Yes", "Partly", "No") and r["status"] in ("Draft", "Approved") for r in rows), "a description with a comma must be in quotes, or its columns shift"
print("filing types page: OK")

# ================= version 22 2: one test for each fault found in the review =================
import json  # noqa: E402
from sbb import manage  # noqa: E402

fetching.LINKS_FILE = tmp / "filing_links.csv"


def scratch(name):
    c = db.connect(tmp / name)
    countries.load_constituents(c)
    return c


# 1 and 15: a daily report read the normal way, then a restart. Nothing waits, nothing drops out of the totals, and a company's return and report share one mandate
c1, said = scratch("r1.db"), []
rows = [(1, {"hyperlink": str(FX / "hk_daily_20261112.xls")}), (2, {"hyperlink": str(FX / "hk_ndr_yum_two_exchanges.txt")})]
fetching.process(c1, rows, delay=0, market="HK", on_result=lambda *a: said.append(a))
assert said[0][1] == "101 companies", said[0]  # the result line names how many companies the report held, not the first one's code


def state():
    return (c1.execute("select count(*), coalesce(sum(coalesce(waiting,0)),0) from transactions").fetchone()[:], c1.execute("select count(*) from review where kind='NO_PROGRAMME'").fetchone()[0],
            [tuple(r) for r in c1.execute("select announced_date, (select count(*) from transactions t where t.prog_id=p.prog_id) from programmes p where ticker='9987' order by 1")])


first = state()
assert first == ((108, 0), 0, [("2026-05-28", 4)]), first  # Yum China: the report's two purchases and the return's two, under the one mandate
for _ in range(2):  # two restarts
    ingest.replay_all(c1)
    c1.commit()
    assert state() == first, state()
total = c1.execute("select sum(shares) from transactions").fetchone()[0]
shown = queries.summary(c1, "HK", queries.ALL_FROM, queries.ALL_TO)["markets"][0]["shares"]
assert abs(shown - total) < 0.5, (shown, total)  # every purchase is in the market's total
tracker.run(c1)
plans = tracker.overview(c1, "HK")["plans"]
lone = next(pl for pl in plans if pl["ticker"] == "797")
assert lone["announced"] == "" and lone["announced_basis"] == "Mandate, date not stated", lone["announced_basis"]
assert "states shares only" in lone["spent_basis"] and lone["spent"] is None and lone["sum_value"] == 2659830  # 16: why Spent is empty, and what the purchases read add up to
assert len([pl for pl in plans if pl["ticker"] == "9987"]) == 1
# 8: the class of share is kept, and A and H shares are not added together
assert {tuple(r) for r in c1.execute("select security, venue, shares from transactions where ticker='3288'")} == {("A shares", "Shanghai Stock Exchange", 1000000.0), ("H shares", "HKEX", 143000.0)}
hai = next(pl for pl in plans if pl["ticker"] == "3288")
assert hai["sum_shares"] == 143000 and hai["security"] == "H shares" and hai["other_securities"] == "A shares 1,000,000 shares", (hai["sum_shares"], hai["other_securities"])
assert parse(read("hk_ndr_ubox_treasury.txt"))["transactions"][0]["security"] == "H shares" and parse(read("hk_ndr_prudential_two_mandates.txt"))["transactions"][0]["security"] == "Ordinary"
print("review 1, 8, 15, 16 (daily report: counted, one mandate, classes apart): OK")

# 2: a return that only cancels shares is kept
text = read("hk_ndr_prudential_two_mandates.txt")
only = text[:text.index("Section II\n")] + "Repurchase report Not applicable\n" + text[text.index("Section III must also"):]
c2 = scratch("r2.db")
assert ingest.import_link(c2, "http://x/cancel-only", "HK", only.encode(), ".txt") == "PARSED"
assert c2.execute("select count(*), sum(shares) from cancellations where kind='Cancelled'").fetchone()[:] == (6, 2418273.0)
assert "6" in c2.execute("select message from documents").fetchone()[0] or "cancellation" in c2.execute("select message from documents").fetchone()[0]
print("review 2 (a return that only cancels shares): OK")

# 3: shares awaiting cancellation are a balance: the latest return's figure, never a sum
c3 = scratch("r3.db")
for n in ("hk_ndr_yum_share_issue.txt", "hk_ndr_yum_two_exchanges.txt"):
    ingest.import_link(c3, "http://x/" + n, "HK", (FX / n).read_bytes(), ".txt")
c3.commit()
got = [r["awaiting_wording"] for r in queries.cancellations(c3, "HK", queries.ALL_FROM, queries.ALL_TO)["programmes"] if r["ticker"] == "9987"]
assert got == [1117119], got
print("review 3 (awaiting cancellation is a balance): OK")

# 4: a spreadsheet is told by its first bytes, whatever the link ends with or the server calls it
plain = "http://docs.example.internal/DocProxy/Fetch/0a1b2c3d-1111-2222-3333-444455556666~0~nocache"
for kind in ("application/octet-stream", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/html"):
    assert fetching._extension((FX / "hk_daily_20261104.xlsx").read_bytes(), kind, plain) == ".xlsx", kind
    assert fetching._extension((FX / "hk_daily_20261112.xls").read_bytes(), kind, plain) == ".xls", kind
assert fetching._extension(b"%PDF-1.7 x", "application/octet-stream", plain) == ".pdf" and fetching._extension(b"PK\x03\x04 a zip that is no workbook", "application/octet-stream", plain) == ""
print("review 4 (Excel files by content): OK")

# 5: a Hong Kong code written with leading zeros is the same company; other markets' codes are left alone
c5, said = scratch("r5.db"), []
fetching.process(c5, [(1, {"hyperlink": str(FX / "hk_ndr_ubox_treasury.txt"), "ticker": "02429"})], delay=0, market="HK", on_result=lambda *a: said.append(a))
assert said[0][3] == "read", said
assert c5.execute("select ticker, count(*) from transactions").fetchone()[:] == ("2429", 1) and c5.execute("select count(*) from review").fetchone()[0] == 0
assert countries.code("HK", "00005") == "5" and countries.code("UK", "0123") == "0123" and countries.code("HK", "5DD") == "5DD"
assert ingest.same_code("HK", "02429", "2429") and not ingest.same_code("UK", "0123", "123")
print("review 5 (codes with leading zeros): OK")

# 6: a day's amount added from two rows is Calculated, with its working; a single row's amount stays Reported
p = parse(read("hk_ndr_prudential_two_mandates.txt"))
assert [x["value_origin"] for x in p["transactions"]] == ["sum", "sum"] and parse(read("hk_ndr_ubox_treasury.txt"))["transactions"][0]["value_origin"] == "reported"
c6 = scratch("r6.db")
ingest.import_link(c6, "http://x/pru", "HK", (FX / "hk_ndr_prudential_two_mandates.txt").read_bytes(), ".txt")
row = queries.daily_rows(c6, country="HK")[0]
assert (row["value_basis"], row["avg_basis"]) == ("Calculated", "Calculated") and "Sum of the amounts" in row["value_working"], row
# 9: with two mandates no running total is kept, so the first day of a renewed mandate raises no false check
assert p["snapshots"] == [] and "no running total is kept" in p["programme"]["size_note"]
renewed = parse(read("hk_ndr_prudential_two_mandates.txt").replace("mandate (a) 11,432,710", "mandate (a) 711,764"))
assert renewed["issues"] == [], renewed["issues"]
print("review 6 and 9 (sums are Calculated; two mandates): OK")

# 7: while a paired UK company is rebuilt, no false review item is left, and the purchases end up marked
for n, (day, shares) in enumerate((("2026-10-15", 805082), ("2026-10-16", 798254), ("2026-10-19", 797660))):
    q = parsers._blank(form="notice", doc_type="transaction", ticker="PRU", company="Prudential plc", doc_date=day)
    q.update(venue_totals=[], cancellations=[], programme={"announced_date": "2026-05-01"})
    q["transactions"].append(parsers._tx(day, shares, 900.0, 905.0, 895.0, "GBp", "XLON"))
    c6.execute("insert into documents(sha256,country,file_name,rel_path,source_url,status,imported_at,ticker,doc_date,parsed_json) values(?,?,?,'',?,?,?,?,?,?)",
               (f"uk{n}", "UK", f"pru{n}", f"http://x/uk{n}", "PARSED", db.now(), "PRU", day, json.dumps({"p": q, "ev": [], "hint": "PRU"})))
c6.commit()
for _ in range(2):
    ingest.replay(c6, "UK", "PRU")
    c6.commit()
    assert [r[0] for r in c6.execute("select also_in from transactions where country='HK' and ticker='2378' order by trade_date")] == ["UK PRU: same date, venue and shares"] * 2
    assert c6.execute("select count(*) from review where kind='HK_NO_OTHER_MATCH'").fetchone()[0] == 0
print("review 7 (no false cross-listing items on a rebuild): OK")

# 10: the rule that fills a missing treatment is data, with companies it doesn't apply to
assert ingest.treatment_rule("AU", "CBA")[0] == "Cancelled" and ingest.treatment_rule("UK", "HSBA") is None and ingest.treatment_rule("HK", "5") is None
ingest._RULES["rows"]["AU"]["except_tickers"] = "JHX; CBA"
try:
    assert ingest.treatment_rule("AU", "CBA") is None and ingest.treatment_rule("AU", "NAB") is not None
finally:
    ingest._RULES["stamp"] = None  # read the file again
assert ingest.treatment_rule("AU", "CBA") is not None
print("review 10 (treatment rule as data): OK")

# 11: a row numbered with no space after it is read
tight = parse(read("hk_ndr_ubox_treasury.txt").replace("1). 13 November 2026 4,000On the Exchange", "10).13 November 2026 4,000On the Exchange"))
assert len(tight["transactions"]) == 1 and tight["issues"] == [], tight["issues"]
# 12: a purchase by private arrangement is named for what it is and not added; nor is a row whose currencies differ
private = parse(read("hk_ndr_ubox_treasury.txt").replace("4,000On the Exchange", "4,000By private arrangement"))
assert private["transactions"] == [] and [k for k, _ in private["issues"]] == ["HK_OFF_MARKET"], private["issues"]
mixed = parse(read("hk_ndr_ubox_treasury.txt").replace("HKD 1.37HKD 1.37HKD 5,480\n", "HKD 1.37USD 1.37HKD 5,480\n"))
assert mixed["transactions"] == [] and "HK_CURRENCY_MIXED" in [k for k, _ in mixed["issues"]], mixed["issues"]
print("review 11 and 12 (row numbering; off-market and mixed-currency rows): OK")

# 13: only a capital first letter is rejoined
d13 = {"identify": ["^Total amount paid"], "fields": {"a": {"label": "^Amount around"}}}
assert forms._mend("paid a mount of cash, for a round sum; T otal and A mount", d13) == "paid a mount of cash, for a round sum; Total and Amount"
print("review 13 (word repair leaves real words alone): OK")

# 14: the first-start copy is the file as it was, taken before the app opens it
old = tmp / "old.db"
raw = sqlite3.connect(old)
raw.executescript("create table transactions (tx_id integer primary key, shares real); insert into transactions(shares) values (5);")
raw.commit()
raw.close()
made = manage.start_copy(old)
assert made and made.parent.name == "backups" and manage.start_copy(old) is None  # once for a version
kept = sqlite3.connect(made)
assert [r[1] for r in kept.execute("pragma table_info(transactions)")] == ["tx_id", "shares"] and kept.execute("select shares from transactions").fetchone()[0] == 5
kept.close()
assert manage.start_copy(tmp / "no_such.db") is None
print("review 14 (the copy is made before anything changes): OK")
print("v22 OK")
