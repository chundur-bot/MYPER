"""Run:  python -P tests/test_v24.py
Version 24: a purchase notice's covering dates are not the programme's; a start rebuilds nothing when nothing changed; the Hong Kong daily report keeps
the companies on the company list; publishing a read-only copy, listing and trimming backups, compacting; and the read-only mode that shows a published copy.
Works on scratch files in a temporary folder; buyback.db, backups and the shared folder of the real app are not touched."""
import hashlib
import json
import sqlite3
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
from sbb import countries, db, fetching, ingest, parsers, server, tracker  # noqa: E402
import maintain  # noqa: E402

FX = ROOT / "tests" / "fixtures"
tmp = Path(tempfile.mkdtemp())
fetching.LINKS_FILE = tmp / "filing_links.csv"
ingest.scan = lambda con: None  # the real inbox is the user's; these tests don't read it
sha = lambda f: hashlib.sha256(Path(f).read_bytes()).hexdigest()
n = [0]


def filing(con, country, ticker, filed, doc_type, terms, buys=(), form="notice"):
    p = parsers._blank(form=form, doc_type=doc_type, ticker=ticker, company=f"{ticker} plc", doc_date=filed)
    p.update(venue_totals=[], cancellations=[], programme=dict(terms), date_stated=True)
    for day, shares in buys:
        p["transactions"].append(parsers._tx(day, shares, 100.0, 101.0, 99.0, "GBp", "XLON"))
    n[0] += 1
    con.execute("insert into documents(sha256,country,file_name,rel_path,source_url,status,imported_at,ticker,doc_date,doc_type,form,parsed_json) values(?,?,?,'',?,?,?,?,?,?,?,?)",
                (f"s{n[0]}", country, f"f{n[0]}", f"http://x/{n[0]}", "PARSED", db.now(), ticker, filed, doc_type, form, json.dumps({"p": p, "ev": [], "hint": ticker})))
    return p


# ---------- 1. the days a purchase notice covers are not the programme's start and end ----------
week = {"announced_date": "2026-09-01", "start_date": "2026-09-14", "end_date": "2026-09-18"}
con = db.connect(tmp / "one.db")
p = filing(con, "UK", "WWW", "2026-09-21", "transaction", week, [("2026-09-14", 100), ("2026-09-18", 200)])
assert parsers.covering_dates(p)
assert not parsers.covering_dates({**p, "doc_type": "programme"})  # an announcement's dates are the programme's
assert not parsers.covering_dates({**p, "form": "appendix_3c"})  # a form has fields for them
assert not parsers.covering_dates({**p, "programme": {**week, "end_date": "2027-03-31"}})  # a long run is the programme's
assert not parsers.covering_dates({**p, "programme": {**week, "start_date": "2026-09-15"}})  # a purchase outside the two dates: not the days it covers
assert not parsers.covering_dates({**p, "transactions": []})
filing(con, "UK", "WWW", "2026-09-28", "transaction", {"announced_date": "2026-09-01", "start_date": "2026-09-21", "end_date": "2026-09-25"}, [("2026-09-21", 300)])
filing(con, "UK", "YYY", "2026-03-02", "programme", {"announced_date": "2026-03-02", "start_date": "2026-03-02", "end_date": "2026-12-31", "max_value": 5e6, "max_currency": "GBP"})
filing(con, "UK", "YYY", "2026-03-09", "transaction", {"announced_date": "2026-03-02", "start_date": "2026-03-02", "end_date": "2026-03-06"}, [("2026-03-03", 50)])
con.commit()
ingest.replay(con, "UK", "WWW")
ingest.replay(con, "UK", "YYY")
assert tuple(con.execute("select start_date, end_date from programmes where ticker='WWW'").fetchone()) == (None, None)  # readings kept from an earlier version are corrected without reading the filings again
assert tuple(con.execute("select start_date, end_date from programmes where ticker='YYY'").fetchone()) == ("2026-03-02", "2026-12-31")  # the announcement's dates stand; the weekly notice no longer replaces them
assert con.execute("select count(*) from transactions where ticker in ('WWW','YYY')").fetchone()[0] == 4  # the purchases themselves are untouched
print("purchase-notice dates: OK")

# ---------- 2. a start rebuilds nothing when nothing changed ----------
assert server.settle(con) == "rebuilt" and server.settle(con) == "unchanged" and server.settle(con, force=True) == "rebuilt"
filing(con, "UK", "WWW", "2026-10-05", "transaction", {"announced_date": "2026-09-01"}, [("2026-09-28", 10)])
con.commit()
assert server.settle(con) == "rebuilt" and server.settle(con) == "unchanged"  # a filing added: rebuilt once
was = db.VERSION
db.VERSION = "another version"
try:
    assert server.settle(con) == "rebuilt"  # a new version rebuilds once
finally:
    db.VERSION = was
assert server.settle(con) == "rebuilt" and server.settle(con) == "unchanged"
before = con.execute("select count(*) from transactions").fetchone()[0]
ingest.replay_all(con)
assert con.execute("select count(*) from transactions").fetchone()[0] == before
print("start-up skip: OK")

# ---------- 3. the Hong Kong daily report keeps the companies on the company list ----------
hk = db.connect(tmp / "hk.db")
countries.load_constituents(hk)
hk.execute("delete from companies where country='HK' and ticker not in ('5','797')")
hk.commit()
said = []
fetching.process(hk, [(1, {"hyperlink": str(FX / "hk_daily_20261112.xls")})], delay=0, market="HK", on_result=lambda *a: said.append(a))
assert sorted(r[0] for r in hk.execute("select distinct ticker from documents")) == ["5", "797"], said
assert "99 of 101 companies in this report are not on your HK company list" in said[0][4], said[0]
assert server.settle(hk) == "unchanged"  # a finished run leaves the database settled
hk.execute("delete from companies where country='HK'")
hk.execute("delete from documents")
hk.commit()
said.clear()
fetching.process(hk, [(1, {"hyperlink": str(FX / "hk_daily_20261104.xlsx")})], delay=0, market="HK", on_result=lambda *a: said.append(a))
assert said[0][3] == "not a buyback" and hk.execute("select count(*) from documents").fetchone()[0] == 0 and hk.execute("select reason from skipped_links").fetchone()[0].startswith("Daily report: none")
assert countries.get("HK")["report_companies"] == "list" and "report_companies" not in countries.get("UK")
print("hong kong report by company list: OK")

# ---------- 4. publish a read-only copy ----------
live = tmp / "live" / "buyback.db"
live.parent.mkdir()
src = db.connect(live)
for country, ticker in (("UK", "WWW"), ("UK", "YYY")):
    for d in con.execute("select * from documents where ticker=?", (ticker,)).fetchall():
        src.execute("insert into documents(sha256,country,file_name,rel_path,source_url,status,imported_at,ticker,doc_date,doc_type,form,parsed_json) values(?,?,?,'',?,?,?,?,?,?,?,?)",
                    (d["sha256"], d["country"], d["file_name"], d["source_url"], d["status"], d["imported_at"], d["ticker"], d["doc_date"], d["doc_type"], d["form"], d["parsed_json"]))
src.commit()
db.DB_PATH, kept_path = live, db.DB_PATH
try:
    assert server.settle(src) == "rebuilt"
    tracker.current(src)
    src.close()
    shared = tmp / "shared"
    shared.mkdir()
    mark = sha(live)
    out = maintain.publish(shared, live, keep=2)
    assert out == shared / "buyback_published.db" and sha(live) == mark  # the live database is only read
    pub = sqlite3.connect(out)
    assert pub.execute("pragma integrity_check").fetchone()[0] == "ok" and pub.execute("select count(*) from documents").fetchone()[0] == 5
    assert dict(pub.execute("select key, value from app_state"))["published_version"] == db.VERSION and len(dict(pub.execute("select key, value from app_state"))["published_at"]) == 19
    pub.close()
    import time
    for _ in range(2):
        time.sleep(1.1)
        maintain.publish(shared, live, keep=2)
    assert len(list((shared / "history").glob("buyback_*.db"))) == 2 and not (shared / "buyback_published.part").exists()  # the newest two published copies are kept
    for bad, words in ((live.parent, "different folder"), (tmp / "nowhere", "Folder not found")):
        try:
            maintain.publish(bad, live)
            raise AssertionError("should have refused")
        except ValueError as e:
            assert words in str(e), e
    print("publish: OK")

    # ---------- 5. backups and compact ----------
    backups = tmp / "backups"
    backups.mkdir()
    for i in range(4):
        (backups / f"buyback_2026110{i}_before_delete.db").write_bytes(b"x" * (i + 1))
        import os
        os.utime(backups / f"buyback_2026110{i}_before_delete.db", (1_700_000_000 + i, 1_700_000_000 + i))
    assert [f.name[8:16] for f in maintain.list_backups(backups)] == ["20261103", "20261102", "20261101", "20261100"]
    assert maintain.prune_backups(1, backups, confirm=lambda _: "yes") == [] and len(list(backups.glob("*.db"))) == 4  # only YES deletes
    assert len(maintain.prune_backups(1, backups, confirm=lambda _: "YES")) == 3 and [f.name[8:16] for f in backups.glob("*.db")] == ["20261103"]
    assert maintain.prune_backups(5, backups, confirm=lambda _: "YES") == []
    size_before, size_after, copy = maintain.compact(live)
    assert copy.exists() and copy.parent.name == "backups" and size_after <= size_before
    assert sqlite3.connect(live).execute("select count(*) from documents").fetchone()[0] == 5
    print("backups and compact: OK")

    # ---------- 6. read-only mode: the published file is never written to ----------
    mark = sha(shared / "buyback_published.db")
    copy = server.open_read_only(shared)
    assert server.READ_ONLY["on"] and db.DB_PATH == copy and copy.parent.name == "sbb_read_only" and copy != shared / "buyback_published.db"
    ro = db.connect()
    assert server.settle(ro) == "unchanged"  # the published copy was settled by its owner, on the same version
    tracker.current(ro)
    info = server.read_only_info(ro)
    assert info["on"] and info["version"] == db.VERSION and info["published"] and not info["newer"]
    ro.close()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, post=False):
        req = urllib.request.Request(base + path, data=b"{}" if post else None, method="POST" if post else "GET", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    try:
        assert call("/api/periods")[1]["read_only"]["on"] is True
        assert len(call("/api/company?country=UK&ticker=YYY")[1]["programmes"]) == 1  # reading works
        for path in ("/api/filings/stop", "/api/reset", "/api/manage/delete", "/api/remove", "/api/countries"):
            code, body = call(path, post=True)
            assert code == 403 and "read-only copy" in body["error"], (path, code, body)  # nothing that changes data is answered
        assert call("/api/read_only/refresh", post=True)[1]["loaded"] is False  # nothing newer yet
        time.sleep(1.1)
        again = sqlite3.connect(live)
        again.execute("update documents set file_name='renamed' where sha256='s1'")
        again.commit()
        again.close()
        maintain.publish(shared, live, keep=2)
        assert call("/api/periods")[1]["read_only"]["newer"] is True  # a newer published copy is noticed
        code, body = call("/api/read_only/refresh", post=True)
        assert code == 200 and body["loaded"] is True and body["newer"] is False, (code, body)
        assert db.connect().execute("select file_name from documents where sha256='s1'").fetchone()[0] == "renamed"  # and loaded
    finally:
        srv.shutdown()
        srv.server_close()
    assert sha(shared / "buyback_published.db") != mark  # it changed only because it was published again
    newest = sha(shared / "buyback_published.db")
    ro = db.connect()
    server.settle(ro, force=True)
    tracker.run(ro)
    ro.close()
    assert sha(shared / "buyback_published.db") == newest  # rebuilding everything in read-only mode writes to the private copy alone
    try:
        server.open_read_only(tmp / "nowhere")
        raise AssertionError("should have refused")
    except ValueError as e:
        assert "No published database found" in str(e)
    print("read-only mode: OK")
finally:
    db.DB_PATH = kept_path
    server.READ_ONLY.update(on=False, source=None, copy=None, seen=None)
print("v24 OK")
