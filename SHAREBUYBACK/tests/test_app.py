"""Run:  python -P tests/test_app.py
The app's own rules on a scratch database: a layout described as data, the checks on every filing, the ticker filter, running-total gaps,
reading filings in review again, a size increase, moving a filing, Manage tickers, and the Tracker section.
Works in a temporary folder, so data/forms, reports, filing_links.csv and buyback.db are not touched."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from sbb import countries, db, fetching, forms, ingest, parsers

FILING = """ACME HOLDINGS LIMITED
Notice of Share Repurchase

Company: Acme Holdings Limited
Date of announcement 11/11/2026
Trading date 10/11/2026
Number of shares repurchased 120,000
Highest price paid per share S$ 1.25
Lowest price paid per share S$ 1.21
Aggregate consideration paid
S$ 147,600.00
Summary of repurchases to date
Number of shares repurchased 1,500,000
Issued shares after repurchase 98,500,000
"""

tmp = Path(tempfile.mkdtemp())
try:
    forms.FORMS_DIR = tmp / "forms"
    shutil.copytree(ROOT / "data" / "forms", forms.FORMS_DIR, ignore=shutil.ignore_patterns("discarded"))
    shutil.copy(ROOT / "tests" / "fixtures" / "sg_acme_layout.json", forms.FORMS_DIR / "SG_acme_notice.json")  # a made-up form, described as data
    fetching.LINKS_FILE = tmp / "filing_links.csv"  # reading a list rewrites this file, so the test keeps its own
    forms._CACHE["stamp"] = None
    did = "sg_acme_notice"
    sample = tmp / "acme_notice.txt"
    sample.write_text(FILING, encoding="utf-8")
    link = str(sample)
    con = db.connect(tmp / "scratch.db")
    countries.load_constituents(con)

    # 1. A layout described in data/forms reads its filing; a filing in no layout goes to review with what the general reader found
    p = parsers.parse(FILING, "SGD", "SG", "DMY")
    assert p["definition"] == did and p["company"] == "Acme Holdings Limited" and p["doc_date"] == "2026-11-11" and [k for k, _ in p["issues"]] == [], p
    assert ingest.import_link(con, link, "SG", sample.read_bytes(), ".txt", "ACM", force=True) == "PARSED"
    con.commit()
    tx, = db.rows(con.execute("select * from transactions"))
    assert (tx["ticker"], tx["trade_date"], tx["shares"], tx["value"], tx["currency"], tx["value_origin"]) == ("ACM", "2026-11-10", 120000, 147600.0, "SGD", "reported"), tx
    snap, = db.rows(con.execute("select * from snapshots"))
    assert (snap["cum_shares"], snap["cum_value"]) == (1500000, None), snap
    other = tmp / "beta_notice.txt"
    other.write_text(FILING.replace("ACME HOLDINGS LIMITED", "BETA LIMITED").replace("Acme Holdings Limited", "Beta Limited").replace("Notice of Share Repurchase", "Buy-back update").replace("Trading date", "Dealt on"), encoding="utf-8")
    assert ingest.import_link(con, str(other), "SG", other.read_bytes(), ".txt", "BET", force=True) == "NEEDS_REVIEW"
    con.commit()
    assert not any((ROOT / "sbb" / name).exists() for name in ("ai_draft.py", "drafts.py")) and not (ROOT / "data" / "ai_settings.json").exists()  # the AI drafting tool is not part of the app
    page = (ROOT / "sbb" / "static" / "app.js").read_text(encoding="utf-8") + (ROOT / "sbb" / "server.py").read_text(encoding="utf-8")
    assert not any(word in page for word in ("api_key", "auth_token", "Anthropic", "/api/layouts", "sessionStorage"))

    # 11. Checks on every filing's figures, whichever reader read it. Nothing is changed; a failure is reported
    from sbb import validate
    kinds = lambda p: [d for k, d in validate.check(p) if k == "CHECK_FAILED"]
    good = parsers.parse(FILING, "SGD", "SG", "DMY")
    assert good["definition"] == did and kinds(good) == [] and not [k for k, _ in good["issues"] if k == "CHECK_FAILED"]
    tx = lambda **kw: {"doc_date": "2026-11-11", "programme": {}, "snapshots": [], "transactions": [{"trade_date": "2026-11-10", "shares": 1000, "value": 1230.0, "currency": "SGD", "price_avg": 1.23, "price_high": 1.25, "price_low": 1.21, **kw}]}
    assert kinds(tx()) == []
    for change, words in (({"trade_date": "2026-11-12"}, "after the filing's own date"), ({"trade_date": "2031-01-05"}, "in the future"), ({"trade_date": "10 Nov"}, "no real date"), ({"shares": 0}, "no positive number of shares"),
                          ({"shares": 1000.5}, "isn't a whole number"), ({"price_low": 1.30}, "lowest price (1.3) above its highest"), ({"price_avg": 12.3, "value": 12300.0}, "average price (12.3) above its highest"),
                          ({"price_avg": 0.123, "value": 123.0}, "below its lowest price"), ({"value": -5.0}, "isn't above zero"), ({"currency": "S$"}, "no recognised currency")):
        found = kinds(tx(**change))
        assert len(found) == 1 and words in found[0], (change, found)
    assert kinds({**tx(price_avg=1.26, value=1260.0)}) == []  # duties and fees can lift the average a little above the highest price
    assert "more than the shares in issue" in kinds({**tx(), "programme": {"shares_on_issue": 500}})[0]
    assert "smaller than the 1,000 shares" in kinds({**tx(), "snapshots": [{"as_of": "2026-11-10", "cum_shares": 400, "cum_value": None}]})[0]
    assert "above the maximum" in kinds({**tx(), "programme": {"max_shares": 5000}, "snapshots": [{"as_of": "2026-11-10", "cum_shares": 9000, "cum_value": None}]})[0]
    assert "before its start date" in kinds({**tx(), "programme": {"start_date": "2026-05-01", "end_date": "2026-04-01"}})[0]
    misread = FILING.replace("S$ 147,600.00", "S$ 1,476,000.00")  # an amount ten times too large for the prices beside it
    p = parsers.parse(misread, "SGD", "SG", "DMY")
    assert [k for k, _ in p["issues"]] == ["CHECK_FAILED"] and "average price (12.3) above its highest price (1.25)" in p["issues"][0][1], p["issues"]
    wrong = tmp / "acme_wrong.txt"
    wrong.write_text(misread, encoding="utf-8")
    assert ingest.import_link(con, str(wrong), "SG", wrong.read_bytes(), ".txt", "ACM", force=True) == "NEEDS_REVIEW"  # stored, and sent to Quality to be checked
    con.commit()
    assert "average price" in con.execute("select detail from review where kind='CHECK_FAILED'").fetchone()[0]

    # 12. The ticker chosen at the top of the page limits every list to that company; the company chooser on Quality keeps them all
    from sbb import queries
    span = (queries.ALL_FROM, queries.ALL_TO)
    assert {t["ticker"] for t in queries.transactions(con, "SG", *span)} >= {"ACM", "BET"}
    known = {r["prog_id"]: r["announced_date"] for r in con.execute("select prog_id, announced_date from programmes")}  # each purchase carries its programme's announced date, for the grouped Purchases view
    assert all(t["programme_announced"] == known.get(t["prog_id"]) for t in queries.transactions(con, "ALL", *span))
    queries.only_ticker("acm")
    try:
        assert {t["ticker"] for t in queries.transactions(con, "SG", *span)} == {"ACM"} and {r["ticker"] for r in queries.programme_rows(con, "SG", *span)} == {"ACM"}
        assert {d["ticker"] for d in queries.documents(con, "SG")} == {"ACM"} and {c["ticker"] for c in queries.companies(con, "ALL", *span)} == {"ACM"}
        assert {r["ticker"] for r in queries.daily_rows(con, None, "SG", *span)} == {"ACM"}
        for run in (queries.summary, queries.venues, queries.cancellations, queries.cessations, queries.analysis, queries.quality):
            run(con, "SG", *span)
        queries.waiting(con, "SG")
        assert {t["ticker"] for t in queries.quality(con, "SG", *span)["tickers"]} >= {"ACM", "BET"}
    finally:
        queries.only_ticker("")
    assert {t["ticker"] for t in queries.transactions(con, "SG", *span)} >= {"ACM", "BET"}

    # 13. Running totals against the purchases between them: a missed filing shows as a shortfall, a misread as an excess
    gap = db.connect(tmp / "gap.db")
    gap.execute("insert into programmes(prog_id, country, ticker, announced_date) values (1, 'AU', 'XYZ', '2026-01-02')")
    for day, shares, total in (("2026-11-02", 30000, 450000), ("2026-11-03", 50000, 500000), ("2026-11-05", 40000, 620000), ("2026-11-06", 10000, 630000), ("2026-11-09", 25000, 650000)):
        gap.execute("insert into transactions(prog_id, country, ticker, trade_date, venue, shares) values (1, 'AU', 'XYZ', ?, '', ?)", (day, shares))
        gap.execute("insert into snapshots(prog_id, as_of, cum_shares, doc_id) values (1, ?, ?, 7)", (day, total))
    gap.execute("insert into transactions(prog_id, country, ticker, trade_date, venue, shares, waiting) values (1, 'AU', 'XYZ', '2026-11-04', '', 99999, 1)")  # waiting purchases count nowhere
    found = queries.total_gaps(gap, {"prog_id": 1, "country": "AU", "ticker": "XYZ"})
    assert [(f["check"], f["doc_id"]) for f in found] == [("Purchases missing between filings", 7), ("Purchases exceed the running total", 7)], found
    assert "rose by 120,000 shares from 2026-11-03 (500,000) to 2026-11-05 (620,000)" in found[0]["detail"] and "add up to 40,000. 80,000 shares aren't covered" in found[0]["detail"], found[0]
    assert "rose by 20,000 shares" in found[1]["detail"] and "5,000 more than the totals allow" in found[1]["detail"], found[1]
    gap.execute("insert into transactions(prog_id, country, ticker, trade_date, venue, shares) values (1, 'AU', 'XYZ', '2026-11-04', 'Cboe', 80000)")  # the missed filing is read: the shortfall goes
    assert [f["check"] for f in queries.total_gaps(gap, {"prog_id": 1, "country": "AU", "ticker": "XYZ"})] == ["Purchases exceed the running total"]
    assert any(c["check"] == "Purchases exceed the running total" for c in queries.quality(gap, "AU", *span)["checks"])
    gap.close()

    # 14. Every filing under To review can be read again at once; resolved items, removed filings and waiting purchases are left alone
    listed = ingest.review_rows(con, "SG")
    assert str(wrong) in [r["hyperlink"] for _, r in listed] and all(r["_reread"] and r["country"] == "SG" for _, r in listed), listed
    assert ingest.review_rows(con, "UK") == [] and all(r["ticker"] == "ACM" for _, r in ingest.review_rows(con, "ALL", "ACM"))
    wrong.write_text(FILING.replace("10/11/2026", "09/11/2026"), encoding="utf-8")  # the filing at that link now reads cleanly
    counts = fetching.process(con, [x for x in listed if x[1]["hyperlink"] == str(wrong)], "", None, 0)
    con.commit()
    assert counts["read"] == 1 and str(wrong) not in [r["hyperlink"] for _, r in ingest.review_rows(con, "SG")], counts
    assert con.execute("select count(*) from review where kind='CHECK_FAILED' and status='OPEN'").fetchone()[0] == 0
    con.execute("update review set status='RESOLVED' where doc_id in (select doc_id from documents where ticker='BET')")
    assert "BET" not in [r["ticker"] for _, r in ingest.review_rows(con, "SG")]
    con.execute("update review set status='OPEN' where doc_id in (select doc_id from documents where ticker='BET')")
    con.commit()

    # 15. A size increase updates the programme it belongs to; removing that filing puts the programme back as it was
    def put(name, body, ticker="RAZ"):
        f = tmp / name
        f.write_text(body, encoding="utf-8")
        status = ingest.import_link(con, str(f), "AU", f.read_bytes(), ".txt", ticker, force=True)
        ingest.replay(con, "AU", ticker)
        con.commit()
        return status, con.execute("select doc_id from documents where source_url=?", (str(f),)).fetchone()[0]
    raz = lambda: db.rows(con.execute("select announced_date, max_value, max_currency, end_date, size_note from programmes where country='AU' and ticker='RAZ' order by announced_date"))
    put("raz_start.txt", "Raz Limited\n19 May 2022\nRaz today announces an on-market share buy-back of up to $1.0 billion. The program will run until 31 May 2023.")
    assert raz() == [{"announced_date": "2022-05-19", "max_value": 1e9, "max_currency": "AUD", "end_date": "2023-05-31", "size_note": None}], raz()
    status, raised = put("raz_increase.txt", "Raz Limited\n15 May 2023\nToday Raz is announcing an increase to its existing on-market share buy-back program by up to a further $500 million. This brings the total program size to up to $1.5 billion and the program will run up to 31 May 2024.")
    assert status == "PARSED" and raz() == [{"announced_date": "2022-05-19", "max_value": 1.5e9, "max_currency": "AUD", "end_date": "2024-05-31", "size_note": "Size raised to AUD 1,500,000,000 on 2023-05-15, an increase of AUD 500,000,000"}], (status, raz())
    assert con.execute("select doc_type, filing_type from documents where doc_id=?", (raised,)).fetchone()["doc_type"] == "update"
    ingest.remove_filing(con, raised)
    assert raz() == [{"announced_date": "2022-05-19", "max_value": 1e9, "max_currency": "AUD", "end_date": "2023-05-31", "size_note": None}], raz()
    assert con.execute("select count(*) from documents where doc_id=?", (raised,)).fetchone()[0] == 0 and con.execute("select count(*) from evidence where doc_id=?", (raised,)).fetchone()[0] == 0

    # 16. A filing stored under a wrong code is moved to the right one; the wrong code leaves the company list; a code not in the list is asked about first
    _, stray = put("razx_new.txt", "Raz Limited\n3 March 2026\nRaz today announces an on-market share buy-back of up to $200 million.", "RAZX")
    assert [r["max_value"] for r in con.execute("select max_value from programmes where country='AU' and ticker='RAZX'")] == [2e8] and len(raz()) == 1
    for bad, why in (("ZZZ9", "not in the AU company list"), ("RAZX", "already under"), ("", "Type the code")):
        try:
            ingest.move_filing(con, stray, bad)
            raise SystemExit("a wrong move was accepted")
        except ValueError as e:
            assert why in str(e), e
    moved = ingest.move_filing(con, stray, " raz ")
    assert moved == {"from": "RAZX", "to": "RAZ", "stated": None, "old_code_removed": True}, moved
    assert [(r["announced_date"], r["max_value"]) for r in raz()] == [("2022-05-19", 1e9), ("2026-03-03", 2e8)], raz()
    assert con.execute("select count(*) from programmes where ticker='RAZX'").fetchone()[0] == 0 and con.execute("select count(*) from companies where ticker='RAZX'").fetchone()[0] == 0
    assert con.execute("select ticker, status from documents where doc_id=?", (stray,)).fetchone()[:] == ("RAZ", "PARSED") and con.execute("select count(*) from evidence where doc_id=?", (stray,)).fetchone()[0] > 0
    ask = fetching.unknown_codes(con, [(1, {"ticker": "RAZ", "hyperlink": "a"}), (2, {"ticker": "RAZZLE", "hyperlink": "b"}), (3, {"ticker": "", "hyperlink": "c"}), (4, {"ticker": "RAZZLE", "hyperlink": "d"}), (5, {"ticker": "NEWCO", "hyperlink": "e", "_reread": True})], "AU")
    assert [(u["code"], u["country"]) for u in ask] == [("RAZZLE", "AU")] and "RAZ" in [s["ticker"] for s in ask[0]["suggestions"]], ask

    # 17. Manage tickers: the listing, and deleting one ticker from one exchange after a backup; other tickers and exchanges are untouched
    from sbb import countries as cc, manage
    real_study = cc.STUDY
    cc.STUDY = tmp / "study_companies.csv"  # the test keeps its own study list
    try:
        cc.STUDY.write_text("country,ticker,company\nAU,RAZ,Raz Limited\nSG,ACM,Acme\n", encoding="utf-8")
        cc.load_constituents(con)
        seen = {e["code"]: {t["ticker"]: t for t in e["tickers"]} for e in manage.listing(con)["exchanges"]}
        r0 = seen["AU"]["RAZ"]
        assert (r0["filings"], r0["programmes"], r0["listed"]) == (2, 2, "Study list") and seen["SG"]["ACM"]["filings"] > 0, r0
        totals = lambda: [con.execute(f"select count(*) from {t} where not (country='AU' and ticker='RAZ')").fetchone()[0] for t in ("documents", "programmes", "transactions", "review")]
        others, raz_links = totals(), [r[0] for r in con.execute("select source_url from documents where country='AU' and ticker='RAZ'")]
        for bad in (("XX", "RAZ"), ("AU", ""), ("AU", "NOPE9")):
            try:
                manage.delete_ticker(con, *bad)
                raise SystemExit("a wrong delete was accepted")
            except ValueError:
                pass
        gone = manage.delete_ticker(con, "au", " raz ")
        assert (gone["filings"], gone["programmes"], gone["links"], gone["off_study_list"], gone["still_listed"], gone["files_left"]) == (2, 2, "remembered", True, False, 0), gone
        saved = tmp / "backups" / gone["backup"]
        was = db.connect(saved)
        assert saved.is_file() and was.execute("select count(*) from documents where country='AU' and ticker='RAZ'").fetchone()[0] == 2  # the backup still holds it
        was.close()
        for t in ("documents", "programmes", "transactions", "review", "companies", "share_counts", "cessations", "cancellations"):
            assert con.execute(f"select count(*) from {t} where country='AU' and ticker='RAZ'").fetchone()[0] == 0, t
        assert con.execute("select count(*) from evidence where doc_id not in (select doc_id from documents)").fetchone()[0] == 0 and con.execute("select count(*) from doc_pages where doc_id not in (select doc_id from documents)").fetchone()[0] == 0
        assert totals() == others and "RAZ" not in cc.STUDY.read_text(encoding="utf-8") and "ACM" in cc.STUDY.read_text(encoding="utf-8")
        assert all(con.execute("select reason from skipped_links where link=?", (l,)).fetchone()[0] == "Removed by you" for l in raz_links) and len(raz_links) == 2
        assert "RAZ" not in {t["ticker"] for e in manage.listing(con)["exchanges"] for t in e["tickers"]}
        _, again = put("raz_back.txt", "Raz Limited\n4 March 2026\nRaz today announces an on-market share buy-back of up to $300 million.")
        gone = manage.delete_ticker(con, "AU", "RAZ", forget_links=True)  # links forgotten: nothing is remembered as removed for it
        assert gone["links"] == "forgotten" and con.execute("select count(*) from skipped_links where country='AU' and ticker='RAZ'").fetchone()[0] == 0, gone
    finally:
        cc.STUDY = real_study
        cc.load_constituents(con)

    # 18. The Tracker: built from the readings held, one exchange at a time; it writes only its own tables and rebuilds itself when filings change
    from sbb import report, tracker
    assert tracker.classify("Update - Notification of buy-back - XYZ", "appendix_3c", "daily") == ("Daily transaction", "form type")
    assert tracker.classify("Completion of share buyback", None, None) == ("Completion", "title") and tracker.classify("Something else", None, None) == ("Not identified", "none")
    assert tracker.confidence("Daily transaction", {"transactions": []}) == ("low", "No purchase was read")
    assert tracker.confidence("Daily transaction", {"form": "appendix_3c", "transactions": [{"shares": 5, "value": 9.0}]}) == ("high", None)
    assert tracker.confidence("Daily transaction", {"transactions": [{"shares": 5, "price_avg": 1.8}]}) == ("medium", None) and tracker.confidence("Completion", {}) == ("n/a", None)
    put("raz_one.txt", "Raz Limited\n19 May 2022\nRaz today announces an on-market share buy-back of up to $1.0 billion. The program will run until 31 May 2023.")
    put("raz_two.txt", "Raz Limited\n3 March 2026\nRaz today announces an on-market share buy-back of up to $200 million.")
    core = ("documents", "programmes", "transactions", "snapshots", "review", "evidence", "companies", "skipped_links")
    size = lambda: [con.execute(f"select count(*) from {t}").fetchone()[0] for t in core]
    before = size()
    built = tracker.run(con)
    assert size() == before and built["programmes"] >= 3 and built["in scope"] == con.execute("select count(*) from tracker_notices where in_scope=1").fetchone()[0], built
    for wrong in ("ALL", "", "XX"):
        try:
            tracker.overview(con, wrong)
            raise SystemExit("the tracker showed more than one exchange")
        except ValueError as e:
            assert "one exchange at a time" in str(e)
    au = tracker.overview(con, "AU")
    assert [(x["ticker"], x["announced"], x["planned_amount"], x["planned_currency"], x["status"]) for x in au["plans"]] == [("RAZ", "2022-05-19", 1e9, "AUD", "Ended, no final notice"), ("RAZ", "2026-03-03", 2e8, "AUD", "In progress")], au["plans"]
    assert all(x["country"] == "AU" for x in au["plans"]) and au["counts"]["notices"] == 2 and not au["behind"] and au["built"]
    sg = tracker.overview(con, "SG")
    assert {x["ticker"] for x in sg["plans"]} >= {"ACM", "BET"} and all(x["country"] == "SG" for x in sg["plans"]) and tracker.overview(con, "SG", "acm")["plans"][0]["ticker"] == "ACM"
    acm = tracker.overview(con, "SG", "ACM")["plans"][0]
    assert (acm["announced"], acm["shares_bought"], acm["spent"], acm["spent_origin"], acm["pct_used"]) == ("", 1500000, None, "Reported", None), acm  # the running total is used; nothing is worked out without a planned amount
    assert any("could not be tied" in x for x in sg["not_covered"])
    rows = tracker.notices(con, "SG", "ACM")["rows"]
    mine = next(r for r in rows if r["link"] == link)
    assert (mine["type"], mine["confidence"], mine["shares"], mine["amount"], mine["amount_basis"], mine["currency"], mine["tie_method"]) == ("Daily transaction", "high", 120000, 147600.0, "Reported", "SGD", "No programme announcement found"), mine
    one = tracker.notice(con, mine["notice_id"])
    assert {f["name"]: f["value"] for f in one["fields"]}["Shares bought on the day"] == 120000 and one["plan_label"].startswith("ACM")
    full = tracker.plan(con, acm["plan_id"])
    shown = {f["key"]: f for f in full["fields"]}
    assert shown["shares_bought"]["value"] == 1500000 and shown["check"]["value"] in ("Match", "Difference", "Not checkable") and "spent_origin" not in shown and not any(f["form_name"] for f in full["fields"]), full["fields"]
    assert one["company"] == "Acme" and one["type_basis"] == "reading" and one["reader"] == "sg_acme_notice"
    assert [c["name"] for c in full["checks"]] == ["Purchases before the first running total", "Shares between running totals", "Amount between running totals", "Spent against planned amount"] and len(full["timeline"]) == acm["notices"]
    assert {c["result"] for c in tracker.checks(con, "SG")["rows"]} <= {"Match", "Difference", "Not checkable"} and all(r["ticker"] for r in tracker.checks(con, "AU")["rows"])
    con.execute("insert into skipped_links(link, reason, skipped_at, ticker, country, heading) values ('x://gone', 'Removed by you', ?, 'RAZ', 'AU', 'Old notice')", (db.now(),))
    con.commit()
    assert tracker.overview(con, "AU", busy=True)["behind"] and tracker.excluded(con, "AU", busy=True)["rows"] == []  # while a list is being read the tracker waits
    assert [(r["ticker"], r["reason"]) for r in tracker.excluded(con, "AU")["rows"]] == [("RAZ", "Removed by you")] and not tracker.overview(con, "AU")["behind"]  # afterwards it rebuilds itself
    real_reports, report.REPORTS = report.REPORTS, tmp / "reports"
    try:
        book = tracker.workbook(con, "AU")
        from openpyxl import load_workbook
        wb = load_workbook(book)
        assert wb.sheetnames == ["Summary", "Programmes", "Notices", "Cross-check", "Excluded"] and wb["Programmes"].max_row == 3 and book.parent == tmp / "reports", wb.sheetnames
        assert [c.value for c in wb["Summary"]["A"]][:2] == ["Item", "Exchange"] and wb["Summary"]["B2"].value == "Australia (ASX)"
        wb.close()
    finally:
        report.REPORTS = real_reports
    from sbb import manage
    real_study, countries.STUDY = countries.STUDY, tmp / "study_companies.csv"
    try:
        countries.STUDY.write_text("country,ticker,company\n", encoding="utf-8")
        manage.delete_ticker(con, "AU", "RAZ")
    finally:
        countries.STUDY = real_study
        countries.load_constituents(con)
    assert tracker.overview(con, "AU")["plans"] == [] and {x["ticker"] for x in tracker.overview(con, "SG")["plans"]} >= {"ACM", "BET"}  # a deleted ticker leaves the tracker; other exchanges are untouched
    con.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("app OK")
