"""Run:  python -P tests/test_forms.py
Layouts described in data/forms: the SGX Daily Share Buy-Back Notice, read from three real notices as the app's reader sees them."""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from sbb import countries, db, fetching, forms, ingest, parsers, queries

FX = ROOT / "tests" / "fixtures"
text_of = lambda name: (FX / name).read_text(encoding="utf-8")
read = lambda text, market="SG", home="SGD": parsers.parse(text, home, market, "DMY")

# Singtel: a named programme, shares cancelled, and a Section C that doesn't add up
t = text_of("sg_daily_singtel.txt")
p = read(t)
assert (p["form"], p["definition"], p["ticker"], p["isin"], p["company"], p["doc_date"]) == ("sgx_daily", "sgx_daily", "Z74", "SG1T75931496", "SINGAPORE TELECOMMUNICATIONS LIMITED", "2026-10-12"), p
x, = p["transactions"]
assert (x["trade_date"], x["venue"], x["shares"], x["value"], x["currency"], x["price_high"], x["price_low"], x["value_origin"]) == ("2026-10-12", "", 2805200, 11775790.86, "SGD", 4.21, 4.17, "reported"), x
assert abs(x["price_avg"] - 11775790.86 / 2805200) < 1e-9  # worked out from the amount the form states
assert (p["programme"]["max_value"], p["programme"]["max_currency"], p["programme"]["announced_date"]) == (2e9, "SGD", "") and "max_shares" not in p["programme"] and "start_date" not in p["programme"], p["programme"]  # the named programme, not the mandate
assert (p["programme"]["treatment"], p["programme"]["shares_on_issue"]) == ("Cancelled", 16279513376), p["programme"]
assert [k for k, _ in p["issues"]] == ["TOTAL_MISMATCH"] and "40,551,300" in p["issues"][0][1] and "40,511,300" in p["issues"][0][1], p["issues"]
assert p["snapshots"] == [] and p["mandate"] == {"start": "2026-07-29", "max_shares": 815992956, "cum_shares": None, "cum_percent": None}, (p["snapshots"], p["mandate"])  # neither total is picked
assert [(c["kind"], c["shares"], c["basis"]) for c in p["cancellations"]] == [("Cancelled", 2805200, "Reported count"), ("Held in treasury", 14413479, "Reported count")], p["cancellations"]
ev = {(e["key"].split("|")[0], e["field"]): (e["page"], e["text"]) for e in parsers.evidence(t, p)}
assert ev[("tx", "trade_date")] == (2, "12/10/2026") and ev[("tx", "value")] == (2, "11,775,790.86") and ev[("prog", "max_value")] == (1, "S$2Bn"), ev  # the purchase date in the form, not the broadcast date above it

# Hong Fok: no named programme, so the mandate; shares held as treasury
t = text_of("sg_daily_hongfok.txt")
p = read(t)
assert (p["ticker"], p["isin"], p["doc_date"], p["issues"]) == ("H30", "SG1J14885763", "2026-11-10", []), p
x, = p["transactions"]
assert (x["trade_date"], x["shares"], x["value"], x["currency"], x["price_high"], x["price_low"]) == ("2026-11-10", 191000, 177138.06, "SGD", 0.935, 0.92), x
prog = p["programme"]
assert (prog["announced_date"], prog["start_date"], prog["max_shares"], prog["buyback_type"], prog["treatment"], prog["shares_on_issue"]) == ("2026-04-30", "2026-04-30", 80371314, "On-market, under shareholder mandate", "Treasury", 784691340), prog
assert "max_value" not in prog  # a mandate has a share limit and no amount: none is made up
assert [(s["as_of"], s["cum_shares"], s["cum_value"], s["origin"]) for s in p["snapshots"]] == [("2026-11-10", 19021800, None, "reported")], p["snapshots"]
assert [(c["kind"], c["shares"]) for c in p["cancellations"]] == [("Held in treasury", 2577400)], p["cancellations"]

# Sarine: a second column for Tel Aviv with nothing bought there; the date bought comes from the form, and the typing errors in its description don't matter
t = text_of("sg_daily_sarine.txt")
p = read(t)
assert (p["ticker"], p["isin"], p["doc_date"], p["issues"]) == ("U77", "IL0010927254", "2026-11-08", []), p
x, = p["transactions"]
assert (x["trade_date"], x["venue"], x["shares"], x["value"], x["currency"]) == ("2026-11-06", "", 30000, 4163.29, "SGD"), x
assert p["programme"]["announced_date"] == "2026-04-29" and p["snapshots"][0]["cum_shares"] == 512200 and p["mandate"]["cum_percent"] == 0.15, p

# Bought on both exchanges: two purchases, each in its own currency, never added together
both = t.replace("Total Number of shares purchased 30,000 0", "Total Number of shares purchased 30,000 5,000").replace("Number of shares held as treasury shares 30,000 0", "Number of shares held as treasury shares 30,000 5,000")
both = both.replace("SGD 0.138 ILS0", "SGD 0.138 ILS0.36").replace("SGD 0.132 ILS0", "SGD 0.132 ILS0.35").replace("ILS\n0\n", "ILS\n1,790.00\n").replace("Total 512,200 0.15", "Total 512,200 0.15")
assert both.count("5,000") == 2 and "ILS0.36" in both and "1,790.00" in both
p = read(both)
sg, il = p["transactions"]
assert (sg["venue"], sg["shares"], sg["value"], sg["currency"]) == ("", 30000, 4163.29, "SGD"), sg
assert (il["venue"], il["trade_date"], il["shares"], il["value"], il["currency"], il["price_unit"], il["price_high"], il["price_low"]) == ("Tel Aviv Stock Exchange", "2026-11-06", 5000, 1790, "ILS", "ILS", 0.36, 0.35), il
assert not p["issues"], p["issues"]
# the overseas column bought, but its exchange isn't named: not added, and never placed on SGX
nameless = both.replace("Name of Overseas exchange where company has dual listing", "Overseas listing")
p = read(nameless)
assert len(p["transactions"]) == 1 and [k for k, _ in p["issues"]] == ["PURCHASE_UNCLEAR"], p

# What isn't read is said, not guessed
p = read(text_of("sg_daily_hongfok.txt").replace("equal access scheme\nNo", "equal access scheme\nYes"))
assert [k for k, _ in p["issues"]] == ["OFF_MARKET"], p["issues"]
p = read(text_of("sg_daily_hongfok.txt").replace("Number of shares held as treasury shares 191,000", "Number of shares held as treasury shares 190,000"))
assert [k for k, _ in p["issues"]] == ["TREATMENT_MISMATCH"], p["issues"]
p = read(text_of("sg_daily_hongfok.txt").replace("SGD\n177,138.06", "SGD\n177.138,06"))  # an amount in another convention is left unread
assert p["transactions"][0]["value"] is None and [k for k, _ in p["issues"]] == ["NO_AVG_PRICE"], p
p = read(text_of("sg_daily_hongfok.txt").replace("Date of Purchase 10/11/2026", "Date of Purchase"))
assert p["transactions"] == [] and {k for k, _ in p["issues"]} == {"FIELD_MISSING", "PURCHASE_UNCLEAR"}, p["issues"]

# A filing matching no layout of a market that has layouts goes to review as an unknown layout; markets without layouts are read as before
odd = "Example Holdings Limited\n12 October 2026\nShare buy-back\nThe Company refers to its share buy-back and attaches the schedule in the new format.\n"
assert [k for k, _ in read(odd)["issues"]] == ["UNKNOWN_LAYOUT"]
assert "UNKNOWN_LAYOUT" not in [k for k, _ in read(odd, "UK", "GBP")["issues"]] and "UNKNOWN_LAYOUT" not in [k for k, _ in parsers.parse(odd, "GBP")["issues"]]
uk = parsers.parse((FX / "uk_labels.txt").read_text(encoding="utf-8"), "GBP", "UK")
assert uk["form"] == "notice" and "definition" not in uk

# Only an approved definition is used: a draft reads nothing, and the filing waits as an unknown layout
tmp = Path(tempfile.mkdtemp())
keep = forms.FORMS_DIR
(tmp / "forms").mkdir()
(tmp / "forms" / "SG_daily_buyback.json").write_text((keep / "SG_daily_buyback.json").read_text(encoding="utf-8").replace('"status": "approved"', '"status": "draft"'), encoding="utf-8")
forms.FORMS_DIR, forms._CACHE["stamp"] = tmp / "forms", None
p = read(text_of("sg_daily_hongfok.txt"))
assert "definition" not in p and p["form"] == "notice", p["form"]
forms.FORMS_DIR, forms._CACHE["stamp"] = keep, None
assert read(text_of("sg_daily_hongfok.txt"))["definition"] == "sgx_daily"

# The exchange's own site is refused, like the others
for link in ("https://links.sgx.com/1.0.0/corporate-announcements/X/abc", "https://www.sgx.com/securities/company-announcements"):
    assert "Exchange site" in (fetching.refusal(link) or ""), link

# Stored as the app stores it, in a scratch database
assert db.ROOT.name == ROOT.name
con = db.connect(tmp / "sg.db")
countries.load_constituents(con)
day2 = text_of("sg_daily_hongfok.txt").replace("10-Nov-2026 17:35:29", "11-Nov-2026 17:40:00").replace("Date of Purchase 10/11/2026", "Date of Purchase 11/11/2026").replace("purchased 191,000", "purchased 100,000")
day2 = day2.replace("treasury shares 191,000", "treasury shares 100,000").replace("SGD\n177,138.06", "SGD\n93,000.00").replace("19,021,800", "19,121,800").replace("784,691,340", "784,591,340").replace("2,577,400", "2,677,400")
for name, text, hint in (("hf1", text_of("sg_daily_hongfok.txt"), "H30"), ("hf2", day2, "H30"), ("sar", text_of("sg_daily_sarine.txt"), ""), ("st", text_of("sg_daily_singtel.txt"), "Z74"), ("both", both.replace("08-Nov-2026 23:15:17", "08-Nov-2026 23:20:00"), "U77")):
    ingest.import_link(con, "http://x/" + name, "SG", text.encode(), ".txt", hint)
for tk in ("H30", "U77", "Z74"):
    ingest.replay(con, "SG", tk)
con.commit()
docs = {r["source_url"][9:]: dict(r) for r in con.execute("select * from documents")}
assert (docs["hf1"]["ticker"], docs["hf1"]["status"], docs["hf1"]["appendix"], docs["hf1"]["filing_type"]) == ("H30", "PARSED", "SGX Daily Share Buy-Back Notice", "Daily buy-back notice"), docs["hf1"]
assert docs["sar"]["ticker"] == "U77" and docs["st"]["status"] == "NEEDS_REVIEW", (docs["sar"], docs["st"])
progs = {(r["ticker"], r["announced_date"]): dict(r) for r in con.execute("select * from programmes where country='SG'")}
assert set(progs) == {("H30", "2026-04-30"), ("U77", "2026-04-29"), ("Z74", "")}, set(progs)
hf = progs[("H30", "2026-04-30")]
assert (hf["max_shares"], hf["max_value"], hf["start_date"], hf["treatment"], hf["shares_on_issue"]) == (80371314, None, "2026-04-30", "Treasury", 784591340), hf
assert [tuple(r) for r in con.execute("select trade_date, shares, value, currency from transactions where prog_id=? order by 1", (hf["prog_id"],))] == [("2026-11-10", 191000, 177138.06, "SGD"), ("2026-11-11", 100000, 93000, "SGD")]
assert [tuple(r) for r in con.execute("select as_of, cum_shares, cum_value from snapshots where prog_id=? order by 1", (hf["prog_id"],))] == [("2026-11-10", 19021800, None), ("2026-11-11", 19121800, None)]
assert [tuple(r) for r in con.execute("select as_of, shares from share_counts where ticker='H30' order by 1")] == [("2026-11-10", 784691340), ("2026-11-11", 784591340)]
sar = progs[("U77", "2026-04-29")]
assert [tuple(r) for r in con.execute("select venue, shares, value, currency from transactions where prog_id=? order by venue", (sar["prog_id"],))] == [("", 30000, 4163.29, "SGD"), ("Tel Aviv Stock Exchange", 5000, 1790, "ILS")]
# Singtel names a programme whose announcement hasn't been read, so its purchase waits and says so
st = progs[("Z74", "")]
assert (st["max_value"], st["max_currency"]) == (2e9, "SGD") and con.execute("select waiting from transactions where prog_id=?", (st["prog_id"],)).fetchone()[0] == 1
assert {r[0] for r in con.execute("select kind from review where ticker='Z74'")} == {"TOTAL_MISMATCH", "NO_PROGRAMME"}
rows = {r["ticker"]: r for r in queries.programme_rows(con, "SG", "2000-01-01", "2099-12-31")}
assert abs(rows["H30"]["avg_price"] - (177138.06 + 93000) / 291000) < 1e-9 and rows["H30"]["avg_currency"] == "SGD", rows["H30"]
assert rows["U77"]["avg_price"] is None  # two currencies are never combined into one average
con.close()
shutil.rmtree(tmp, ignore_errors=True)
print("forms OK")
