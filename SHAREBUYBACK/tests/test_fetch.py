"""Run:  python -P tests/test_fetch.py

Tests fetch_from_list.py in a temporary folder against a local server. Sends nothing to any exchange: refusals happen before any request.
"""
import http.server
import importlib.util
import shutil
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
spec = importlib.util.spec_from_file_location("f", Path(__file__).resolve().parent.parent / "fetch_from_list.py")
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
PDF = b"%PDF-1.4 test file"
hits = []
VIEWED = b"""Shell plc
6 March 2026
Transaction in Own Shares
Date of purchase: 5 March 2026
Number of ordinary shares purchased: 140,000
Volume weighted average price paid per share (pence): 2,800.00
"""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        hits.append(self.path)
        if self.path == "/Docproxy/Fetch/My%20Notice%20(1)%20%C3%A9.txt" or self.path == "/Docproxy/Fetch/already%20encoded.txt":
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(NOTICE)
        elif self.path == "/docproxy/abc-123":  # a viewer page, with the document behind a frame
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(b'<html><body><iframe class="v" src="/raw/abc-123?x=1&amp;y=2"></iframe></body></html>')
        elif self.path == "/raw/abc-123?x=1&y=2":
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(VIEWED)
        elif self.path == "/docproxy/script":  # the document address only inside a script
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(b'<script>var d={"file":"\\/raw\\/s.pdf"}</script>')
        elif self.path == "/raw/s.pdf":
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(VIEWED)
        elif self.path == "/docproxy/empty":  # a viewer with nothing to follow
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(b"<html><body><div id=app></div></body></html>")
        elif self.path == "/director.txt":
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(b"Example plc\n5 March 2026\nDirector's interest notice\nThe director acquired 5,000 ordinary shares at an average price of 10.50 pence.\n")
        elif self.path == "/toviewer":
            self.send_response(302); self.send_header("Location", "https://www.asx.com.au/x.pdf"); self.end_headers()
        elif self.path == "/notice.txt":
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(NOTICE)
        elif self.path == "/notice2.txt":
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(NOTICE.replace(b"120,000", b"125,000").replace(b"4 March", b"3 March"))
        elif self.path == "/ok.pdf":
            self.send_response(200); self.send_header("Content-Type", "application/pdf"); self.end_headers(); self.wfile.write(PDF)
        elif self.path == "/noext":
            self.send_response(200); self.send_header("Content-Type", "application/octet-stream"); self.end_headers(); self.wfile.write(PDF)
        elif self.path == "/page":
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(b"<p>x</p>")
        elif self.path == "/zip":
            self.send_response(200); self.send_header("Content-Type", "application/zip"); self.end_headers(); self.wfile.write(b"PK")
        elif self.path == "/toasx":
            self.send_response(302); self.send_header("Location", "https://www.asx.com.au/asx/x.pdf"); self.end_headers()
        elif self.path == "/toinner":
            self.send_response(302); self.send_header("Location", "/ok.pdf"); self.end_headers()
        else:
            self.send_response(404); self.end_headers()


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = f"http://127.0.0.1:{srv.server_port}"
tmp = Path(tempfile.mkdtemp())
from sbb import fetching
fetching.SETTINGS = tmp / "settings.json"  # the real filing location stays untouched
fetching.LINKS_FILE = tmp / "filing_links.csv"
share = tmp / "share.txt"

# --- refusal: no request is made
for u, want in [("https://www.asx.com.au/asx/v2/x.pdf", "Exchange"), ("https://announcements.asx.com.au/asxpdf/1.pdf", "Exchange"), ("https://cdn-api.markitdigital.com/x", "Exchange"), ("https://www.londonstockexchange.com/x", "Exchange"), ("https://www.rns-pdf.londonstockexchange.com/rns/1.pdf", "Exchange"), ("https://announcements.nzx.com/a/1.pdf", "Exchange"), ("https://www.lse.co.uk/rns", "Exchange"), ("ftp://x/y", "Not a web")]:
    assert want in (f.refusal(u) or ""), (u, f.refusal(u))
assert f.refusal(B + "/ok.pdf") is None and f.refusal(r"\\server\share\a.pdf") is None
print("refusals ok")

# --- csv run: figures and links are kept, no filing is saved
NOTICE = b"""Shell plc
5 March 2026
Transaction in Own Shares
Date of purchase: 4 March 2026
Number of ordinary shares purchased: 120,000
Highest price paid per share (pence): 2,810.50
Lowest price paid per share (pence): 2,790.00
Volume weighted average price paid per share (pence): 2,801.25
"""
csvf = tmp / "list.csv"
csvf.write_text("Some report title,,\n\nCode,Date,Headline,Link,Country\n"
                f"SHEL,05/03/2026,Own shares,{B}/notice.txt,UK\n"
                f"SHEL,05/03/2026,Same link again,{B}/notice.txt,UK\n"
                f"AZJ,2026-01-06,Exchange,https://www.asx.com.au/asx/x.pdf,AU\n"
                f"AZJ,2026-01-07,Redirects to ASX,{B}/toasx,AU\n"
                f"AZJ,2026-01-09,Wrong type,{B}/zip,AU\n"
                f"AZJ,2026-01-10,Missing,{B}/missing,AU\n"
                f"AZJ,2026-01-11,No link,,AU\n", encoding="utf-8")
root = tmp / "app"
root.mkdir()
assert f.main([str(csvf), "--root", str(root), "--delay", "0", "--dry-run"]) == 0
assert not hits, hits
f.main([str(csvf), "--root", str(root), "--delay", "0"])
assert not (root / "inbox").exists()
import sqlite3
con = sqlite3.connect(root / "buyback.db")
con.row_factory = sqlite3.Row
doc = con.execute("select * from documents").fetchone()
assert con.execute("select count(*) from documents").fetchone()[0] == 1 and doc["source_url"] == B + "/notice.txt" and doc["ticker"] == "SHEL" and doc["status"] == "PARSED" and doc["rel_path"] == "" and doc["file_name"] == "Own shares", dict(doc)
tx = con.execute("select * from transactions").fetchone()
assert (tx["ticker"], tx["trade_date"], tx["shares"]) == ("SHEL", "2026-03-04", 120000) and abs(tx["value"] - 3361500) < 0.01, dict(tx)
assert con.execute("select count(*) from evidence where doc_id=?", (doc["doc_id"],)).fetchone()[0] >= 4
assert con.execute("select count(*) from doc_pages").fetchone()[0] == 0  # no stored text
assert hits.count("/notice.txt") == 1 and "/toasx" in hits, hits
log = next((root / "logs").glob("*.csv")).read_text(encoding="utf-8")
assert "Exchange site" in log and "The server answered 404" in log and "Not a filing type" in log and "No link in this row" in log, log
con.close()
print("run ok; a second run reads nothing again")
before = len(hits)
f.main([str(csvf), "--root", str(root), "--delay", "0"])
assert "/notice.txt" not in hits[before:], hits[before:]

# --- a re-read of the folders keeps link filings
from sbb import countries, db, ingest, queries
countries.INBOX = tmp / "no_inbox"
c2 = db.connect(root / "buyback.db")
res = ingest.rebuild(c2)
assert res["links_kept"] == 1 and c2.execute("select count(*) from transactions").fetchone()[0] == 1, res
row = [r for r in queries.programme_rows(c2, "UK", queries.ALL_FROM, queries.ALL_TO) if r["ticker"] == "SHEL"][0]
assert row["source_url"] == B + "/notice.txt" and row["shares"] == 120000, row
assert all("parsed_json" not in d for d in queries.documents(c2, "UK"))
c2.close()
print("re-read keeps them")

# --- excel, with a hyperlink behind display text and a real date cell; a mapped or local path
from sbb import countries as reset_countries, db as reset_db, ingest as reset_ingest, parsers as order_parsers
keep_get = fetching._get
page_text = "Meridian completes share buyback. " * 20


def fake_get(link):
    if "tracker" in link:
        raise ValueError("Public internet address")
    body = ('<html><iframe src="https://tracker.example.com/ns.html"></iframe>' + (page_text if "withtext" in link else "") + "</html>").encode()
    return body, "text/html", link


fetching._get = fake_get
assert fetching.fetch("http://x/withtext")[2] == "web page, read as it is"  # a tracker frame doesn't hide the page's own text
try:
    fetching.fetch("http://x/empty")
    assert False, "an empty viewer page must fail"
except ValueError as e:
    assert "Public internet address" in str(e)
fetching._get = keep_get
ANN = "Shell plc\n{d}\nShare buyback programme announcement\nShell plc announces the commencement of a share buyback programme of up to US$3.5 billion.\nPurchases will take place during the period running from {s} and ending no later than {e}.\n"
DAILY = "Shell plc\n{d}\nTransaction in Own Shares\nDate of purchase: {t}\nNumber of ordinary shares purchased: {n}\nVolume weighted average price paid per share (pence): 2,800.00\n"
A1 = ("A1", ANN.format(d="2 January 2026", s="3 January 2026", e="30 April 2026"))
D1 = ("D1", DAILY.format(d="11 February 2026", t="10 February 2026", n="100,000"))
B1 = ("B1", ANN.format(d="1 May 2026", s="2 May 2026", e="30 July 2026"))
D2 = ("D2", DAILY.format(d="11 June 2026", t="10 June 2026", n="200,000"))
D3 = ("D3", DAILY.format(d="12 June 2026", t="11 June 2026", n="300,000"))


def read_in_order(name, order):
    oc = reset_db.connect(tmp / f"order_{name}.db")
    reset_countries.load_constituents(oc)
    for n, text in order:
        reset_ingest.import_link(oc, "http://x/" + n, "UK", text.encode(), ".txt", "SHEL")
    reset_ingest.replay(oc, "UK", "SHEL")
    oc.commit()
    placed = {}
    for r in oc.execute("select p.announced_date a, t.trade_date d from programmes p join transactions t on t.prog_id=p.prog_id where p.ticker='SHEL' order by 1,2"):
        placed.setdefault(r["a"], []).append(r["d"])
    flags = [r["detail"] for r in oc.execute("select detail from review where kind='NO_PROGRAMME' and status='OPEN'")]
    terms = oc.execute("select announced_date, end_date from programmes where ticker='SHEL' order by 1").fetchall()
    oc.close()
    return placed, flags, [tuple(x) for x in terms]


right = {"2026-01-02": ["2026-02-10"], "2026-05-01": ["2026-06-10", "2026-06-11"]}
base_terms = read_in_order("oldest", [A1, D1, B1, D2, D3])
assert base_terms[0] == right and base_terms[1] == [], base_terms
for i, order in enumerate(([D3, D2, B1, D1, A1], [D3, D2, D1, B1, A1], [A1, D3, D2, D1, B1], [B1, D3, A1, D1, D2])):
    assert read_in_order(str(i), order) == base_terms, order  # the same result in any order
missing = read_in_order("missing_new", [A1, D2])  # the later announcement isn't in the list
assert missing[0] == {"2026-01-02": ["2026-06-10"]} and "after the end date" in missing[1][0], missing
missing = read_in_order("missing_old", [D1, D2])  # no announcement at all
assert set(missing[0]) == {""} and len(missing[1]) == 2 and "before any programme announcement" in missing[1][0], missing
again = reset_db.connect(tmp / "order_oldest.db")
reset_ingest.replay(again, "UK", "SHEL")
reset_ingest.replay(again, "UK", "SHEL")
assert again.execute("select count(*) from transactions").fetchone()[0] == 3 and again.execute("select count(*) from programmes").fetchone()[0] == 2
again.close()
assert order_parsers.is_buyback_filing("menu " * 900 + "Meridian completes share buyback")
assert not order_parsers.is_buyback_filing("menu " * 2000 + "share buyback")

# Appendix 3H: captured apart, linked by date, and the latest filing overwrites
FX3H = (Path(__file__).resolve().parent / "fixtures" / "au_3h_mixed.txt").read_text(encoding="utf-8")
LATER3H = FX3H.replace("2,070,144", "2,070,000").replace("15/1/2025", "20/1/2025")
ANN_IPH = ("P1", ANN.format(d="1 June 2024", s="2 June 2024", e="30 June 2025"))


def read_3h(name, order):
    oc = reset_db.connect(tmp / f"h3_{name}.db")
    reset_countries.load_constituents(oc)
    for n, text in order:
        reset_ingest.import_link(oc, "http://x/" + n, "AU", text.encode(), ".txt", "IPH")
    reset_ingest.replay(oc, "AU", "IPH")
    oc.commit()
    rows = [tuple(r) for r in oc.execute("select e.security_code, e.shares, e.is_buyback, p.announced_date from cessations e left join programmes p on p.prog_id=e.prog_id order by 1")]
    bought = oc.execute("select count(*) from transactions").fetchone()[0]
    flags = oc.execute("select count(*) from review where kind='NO_PROGRAMME' and status='OPEN'").fetchone()[0]
    oc.close()
    return rows, bought, flags


want = ([("IPH", 2070000, 1, "2024-06-01"), ("IPHAA", 116236, 0, None)], 0, 0)
assert read_3h("a", [ANN_IPH, ("H1", FX3H), ("H2", LATER3H)]) == want, read_3h("a2", [ANN_IPH, ("H1", FX3H), ("H2", LATER3H)])
assert read_3h("b", [("H2", LATER3H), ("H1", FX3H), ANN_IPH]) == want  # read back to front, the later filing still overwrites
assert read_3h("c", [("H1", FX3H)])[2] == 1  # no programme read yet, so it is flagged

# Removing a filing reconciles its company, and it stays out if a list is read again
rm = reset_db.connect(tmp / "remove.db")
reset_countries.load_constituents(rm)
for n, text in (ANN_IPH, ("H1", FX3H), ("H2", LATER3H), A1, B1, D2):
    reset_ingest.import_link(rm, "http://x/" + n, "AU" if n in ("P1", "H1", "H2") else "UK", text.encode(), ".txt", "IPH" if n in ("P1", "H1", "H2") else "SHEL")
reset_ingest.replay(rm, "AU", "IPH")
reset_ingest.replay(rm, "UK", "SHEL")
rm.commit()
doc = lambda n: rm.execute("select doc_id from documents where source_url=?", ("http://x/" + n,)).fetchone()[0]
kept = lambda: rm.execute("select shares from cessations where security_code='IPH'").fetchone()[0]
assert kept() == 2070000
reset_ingest.remove_filing(rm, doc("H2"))  # what the later filing overwrote comes back
assert kept() == 2070144
assert rm.execute("select reason, heading from skipped_links where link='http://x/H2'").fetchone()["reason"] == "Removed by you"
assert reset_ingest.import_link(rm, "http://x/H2", "AU", LATER3H.encode(), ".txt", "IPH", force=True) == "PARSED"  # Read anyway brings it back
rm.execute("delete from skipped_links where link='http://x/H2'")
reset_ingest.replay(rm, "AU", "IPH")
assert kept() == 2070000
reset_ingest.remove_filing(rm, doc("P1"))  # no programme now, so the cancellation says so
assert rm.execute("select prog_id from cessations where security_code='IPH'").fetchone()[0] is None
assert rm.execute("select count(*) from programmes where ticker='IPH'").fetchone()[0] == 0
assert rm.execute("select count(*) from review where kind='NO_PROGRAMME' and ticker='IPH' and status='OPEN'").fetchone()[0] == 1
placed = lambda: {r["a"]: r["n"] for r in rm.execute("select p.announced_date a, count(t.tx_id) n from programmes p left join transactions t on t.prog_id=p.prog_id where p.ticker='SHEL' group by 1")}
assert placed() == {"2026-01-02": 0, "2026-05-01": 1}
reset_ingest.remove_filing(rm, doc("B1"))  # the purchase falls back to the earlier programme, and is flagged as after its end date
assert placed() == {"2026-01-02": 1}
assert rm.execute("select count(*) from review where kind='NO_PROGRAMME' and ticker='SHEL' and status='OPEN'").fetchone()[0] == 1
reset_ingest.remove_filing(rm, doc("D2"))
reset_ingest.remove_filing(rm, doc("A1"))  # the company's last filing leaves nothing behind
assert not rm.execute("select 1 from programmes where ticker='SHEL'").fetchone() and not rm.execute("select 1 from review where ticker='SHEL'").fetchone()
try:
    reset_ingest.remove_filing(rm, 99999)
    assert False
except ValueError:
    pass
rm.execute("insert into documents(sha256,country,file_name,rel_path,status,imported_at) values('typed','AU','manual_entries.csv','inbox/AU/manual_entries.csv','PARSED','t')")
try:
    reset_ingest.remove_filing(rm, rm.execute("select doc_id from documents where sha256='typed'").fetchone()[0])
    assert False, "typed entries stay"
except ValueError as e:
    assert "Typed entries" in str(e)
rm.close()

# The market chosen on the page
mk = reset_db.connect(tmp / "market.db")
mk.execute("insert into companies(country,ticker,company,in_index) values('UK','HSBA','HSBC',1),('AU','CSL','CSL',1),('AU','DUAL','A',1),('UK','DUAL','B',0)")
rc_ = lambda ticker, row=None, market="": fetching.resolve_country(mk, row or {}, ticker, None, market)
assert rc_("MACF", market="UK") == ("UK", None)  # not known anywhere
assert "choose its market" in rc_("MACF")[1]
assert rc_("CSL", market="UK") == ("AU", None)  # known only elsewhere, so it isn't moved
assert rc_("DUAL", market="UK") == ("UK", None) and rc_("DUAL") == ("AU", None)  # the chosen market wins over the study list
assert rc_("MACF", {"country": "NZ"}, "UK") == ("NZ", None)  # a Country column wins
mk.close()

# With no date in the filing, the list's date is used, and the result says where the date came from
FXT = (Path(__file__).resolve().parent / "fixtures" / "uk_treasury_today.txt").read_bytes()
ds = reset_db.connect(tmp / "dated.db")
reset_countries.load_constituents(ds)
reset_ingest.import_link(ds, "http://x/r1", "UK", FXT, ".txt", "RKT")
reset_ingest.import_link(ds, "http://x/r2", "UK", FXT.replace(b"49,570", b"49,571"), ".txt", "RKT", list_date="2026-01-08")
rows = {r["source_url"][-2:]: (r["doc_date"], r["message"]) for r in ds.execute("select source_url, doc_date, message from documents")}
assert rows["r1"][0] == "2026-01-07" and "dated from purchase date" in rows["r1"][1], rows
assert rows["r2"][0] == "2026-01-08" and "dated from your list" in rows["r2"][1], rows
assert not ds.execute("select 1 from review where kind='DATE_DIFFERS'").fetchone()
assert ds.execute("select as_of from share_counts where as_of='2026-01-08'").fetchone()
assert ds.execute("select treatment from programmes where ticker='RKT'").fetchone()[0] == "Treasury"
ds.close()

# The data dictionary page is built from the two CSV files, so every field and phrase appears
from sbb import server as dd_server
import csv as dd_csv
page = dd_server.data_dictionary_md()
assert "## Purchase" in page and "| Broker |" in page and "## Phrases the parser looks for" in page and "intends to cancel" in page, page[:300]
dd_rows = list(dd_csv.DictReader(open(dd_server.ROOT / "data" / "data_dictionary.csv", encoding="utf-8-sig")))
kw_rows = list(dd_csv.DictReader(open(dd_server.ROOT / "data" / "keywords.csv", encoding="utf-8-sig")))
assert all(f"| {r['field']} |" in page for r in dd_rows) and all(r["phrase"] in page for r in kw_rows)

# Waiting for programme: left out of totals, listed by company, linked once the announcement is read, or removed as not needed
from sbb import queries as q_wait
wt = reset_db.connect(tmp / "waiting.db")
reset_countries.load_constituents(wt)
for n, text in (D1, D2):
    reset_ingest.import_link(wt, "http://x/w" + n, "UK", text.encode(), ".txt", "SHEL")
reset_ingest.replay(wt, "UK", "SHEL")
wt.commit()
assert wt.execute("select count(*) from transactions where waiting=1").fetchone()[0] == 2
shel = [r for r in q_wait.programme_rows(wt, "UK", q_wait.ALL_FROM, q_wait.ALL_TO) if r["ticker"] == "SHEL"]
assert sum(r["shares"] for r in shel) == 0, shel  # waiting purchases count nowhere
group = q_wait.waiting(wt, "UK")
assert len(group) == 1 and group[0]["purchases"] == 2 and group[0]["shares"] == 300000 and group[0]["filings"] == 2, group
assert not [r for r in q_wait.quality(wt, "UK", q_wait.ALL_FROM, q_wait.ALL_TO)["review"] if r["kind"] == "NO_PROGRAMME"]  # not on To review
reset_ingest.import_link(wt, "http://x/wA1", "UK", A1[1].encode(), ".txt", "SHEL")
reset_ingest.import_link(wt, "http://x/wB1", "UK", B1[1].encode(), ".txt", "SHEL")
reset_ingest.replay(wt, "UK", "SHEL")
wt.commit()
assert wt.execute("select count(*) from transactions where waiting=1").fetchone()[0] == 0 and q_wait.waiting(wt, "UK") == []
shel = {r["announced_date"]: r["shares"] for r in q_wait.programme_rows(wt, "UK", q_wait.ALL_FROM, q_wait.ALL_TO) if r["ticker"] == "SHEL"}
assert shel == {"2026-01-02": 100000, "2026-05-01": 200000}, shel  # linked, and counted again
assert not any(r["document_needed"] for r in q_wait.programme_rows(wt, "UK", q_wait.ALL_FROM, q_wait.ALL_TO) if r["ticker"] == "SHEL")
wt.close()
nn = reset_db.connect(tmp / "notneeded.db")
reset_countries.load_constituents(nn)
for n, text in (D1, D2):
    reset_ingest.import_link(nn, "http://x/n" + n, "UK", text.encode(), ".txt", "SHEL")
reset_ingest.replay(nn, "UK", "SHEL")
for doc_id in q_wait.waiting(nn, "UK")[0]["doc_ids"]:
    reset_ingest.remove_filing(nn, doc_id)
assert q_wait.waiting(nn, "UK") == [] and not nn.execute("select 1 from documents").fetchone()
assert nn.execute("select count(*) from skipped_links where reason='Removed by you'").fetchone()[0] == 2  # they won't come back
nn.close()
dn = reset_db.connect(tmp / "docneeded.db")
reset_countries.load_constituents(dn)
cited = DAILY.format(d="11 February 2026", t="10 February 2026", n="100,000") + "These purchases form part of the programme as announced on 30 January 2026.\n"
reset_ingest.import_link(dn, "http://x/c1", "UK", cited.encode(), ".txt", "SHEL")
reset_ingest.replay(dn, "UK", "SHEL")
row = [r for r in q_wait.programme_rows(dn, "UK", q_wait.ALL_FROM, q_wait.ALL_TO) if r["ticker"] == "SHEL"][0]
assert row["announced_date"] == "2026-01-30" and row["document_needed"] and row["shares"] == 100000, row  # linked by the cited date, counted, but its terms need the announcement
dn.close()

# Re-reading a company: figures from an older parser are replaced, links stay, removed filings stay out, and a link that fails keeps its figures
rr = reset_db.connect(tmp / "reread.db")
reset_countries.load_constituents(rr)
AVIVA = (Path(__file__).resolve().parent / "fixtures" / "uk_rns_aviva.html").read_bytes()
reset_ingest.import_link(rr, "http://x/av1", "UK", AVIVA, ".html", "AV.")
reset_ingest.import_link(rr, "http://x/av2", "UK", AVIVA.replace(b"07 July 2026", b"06 July 2026").replace(b"08 July 2026", b"07 July 2026"), ".html", "AV.")
reset_ingest.replay(rr, "UK", "AV.")
rr.execute("update transactions set price_avg=null, price_high=null, price_low=null, value=null where doc_id=(select doc_id from documents where source_url='http://x/av1')")  # as an older parser left it
rr.commit()
assert [r[1]["hyperlink"] for r in reset_ingest.reread_rows(rr, "UK", "AV.", only_gaps=True)] == ["http://x/av1"]
assert len(reset_ingest.reread_rows(rr, "UK", "AV.")) == 2
served = {"http://x/av1": AVIVA}
keep_get = fetching._get
fetching._get = lambda link: (served[link], "text/html", link) if link in served else (_ for _ in ()).throw(ValueError("The server answered 500"))
fetching.ALLOWED_HOSTS.add("x")
counts = fetching.process(rr, reset_ingest.reread_rows(rr, "UK", "AV."), "", None, 0)
fetching._get = keep_get
assert counts["read"] == 1 and counts["failed"] == 1, counts
prices = {r["source_url"]: (r["price_avg"], r["value"]) for r in rr.execute("select d.source_url, t.price_avg, t.value from transactions t join documents d on d.doc_id=t.doc_id")}
assert prices["http://x/av1"][0] == 678.0 and abs(prices["http://x/av1"][1] - 680956.08) < 0.01, prices  # filled in
assert prices["http://x/av2"][0] == 678.0, prices  # its link failed, so its figures stayed as they were
assert rr.execute("select count(*) from documents").fetchone()[0] == 2
rr.close()

# Filing date decides, and a same-day correction always follows what it corrects
order = lambda date, kind, prev, sha: reset_ingest._filing_order({"doc_date": date, "sha256": sha, "parsed_json": __import__("json").dumps({"p": {"doc_type": kind, "previous_date": prev}})})
assert order("2026-02-16", "update", "2026-02-13", "z") < order("2026-02-16", "update", "2026-02-16", "a") < order("2026-02-17", "update", "2026-02-16", "a")
assert order("2026-02-16", "programme", "", "z") < order("2026-02-16", "daily", "", "a")

# a skipped filing can be read anyway, and a list row can ask for that
sk = reset_db.connect(tmp / "skip.db")
reset_countries.load_constituents(sk)
plain = b"Shell plc\n2 January 2026\nDirector dealing notice about a change of address for a director, long enough to count as text.\n"
assert reset_ingest.import_link(sk, "http://x/s1", "UK", plain, ".txt", "SHEL") == "NOT_BUYBACK"
assert tuple(sk.execute("select ticker, country, reason from skipped_links").fetchone()) == ("SHEL", "UK", "Not a buyback filing")
assert reset_ingest.import_link(sk, "http://x/s1", "UK", plain, ".txt", "SHEL", force=True) != "NOT_BUYBACK"
assert sk.execute("select 1 from documents where source_url='http://x/s1'").fetchone()
sk.close()

from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws.append(["Company", "Code", "Filing Date", "Link"])
ws.append(["Shell", "SHEL", datetime(2026, 3, 5), "Open"])
ws["D2"].hyperlink = B + "/notice2.txt"
share.write_bytes(NOTICE.replace(b"120,000", b"130,000").replace(b"4 March", b"5 March"))
ws.append(["Shell", "SHEL", datetime(2026, 3, 6), str(share)])
xl = tmp / "list.xlsx"
wb.save(xl)
rows = f.read_rows(xl)
assert rows[0][1]["link"] == B + "/notice2.txt" and f.to_iso(rows[0][1]["filing_date"]) == "2026-03-05", rows
root2 = tmp / "app2"
root2.mkdir()
f.main([str(xl), "--root", str(root2), "--delay", "0", "--country", "UK"])
con = sqlite3.connect(root2 / "buyback.db")
assert {r[0] for r in con.execute("select source_url from documents")} == {B + "/notice2.txt", str(share)}, list(con.execute("select source_url,status from documents"))
con.close()
# --- your DAM: no https:// on the link, viewer pages, filings that aren't buybacks, a named host
assert f.clean_link("xxxx.prod.companyname.com/docproxy/abc-123") == "http://xxxx.prod.companyname.com/docproxy/abc-123"
assert f.clean_link(r"\\server\share\a.pdf") == r"\\server\share\a.pdf" and f.clean_link("http://a.b/c") == "http://a.b/c"
real = f.socket.getaddrinfo
f.socket.getaddrinfo = lambda host, port: [(0, 0, 0, "", ("8.8.8.8", port))] if "prod.companyname" in host or "other.example" in host else real(host, port)
assert "filing location" in f.refusal("https://xxxx.prod.companyname.com/docproxy/a")
f.ALLOWED_HOSTS.add("xxxx.prod.companyname.com")
assert f.refusal("https://xxxx.prod.companyname.com/docproxy/a") is None and "filing location" in f.refusal("https://other.example/a")
f.ALLOWED_HOSTS.add("www.asx.com.au")  # even if an exchange were named, it stays refused
assert "Exchange" in f.refusal("https://www.asx.com.au/a")
f.ALLOWED_HOSTS.clear()
f.socket.getaddrinfo = real
assert f.document_in_viewer(b'<a href="/d/x.pdf?t=1">x</a>', "http://h/v") == "http://h/d/x.pdf?t=1"
assert f.document_in_viewer(b"<p>nothing</p>", "http://h/v") is None
dam = tmp / "dam.csv"
dam.write_text("Ticker,Date,Link,Country\n"
               f"SHEL,2026-03-06,{B}/docproxy/abc-123,UK\nSHEL,2026-03-06,{B}/docproxy/script,UK\nXXX,2026-03-05,{B}/director.txt,UK\nSHEL,2026-03-07,{B}/docproxy/empty,UK\nZZZ,2026-03-08,{B}/notice2.txt,UK\n", encoding="utf-8")
root3 = tmp / "app3"
root3.mkdir()
before = len(hits)
f.main([str(dam), "--root", str(root3), "--delay", "0", "--probe", "2"])
assert not (root3 / "buyback.db").exists(), "probe keeps nothing"
f.main([str(dam), "--root", str(root3), "--delay", "0"])
con = sqlite3.connect(root3 / "buyback.db")
con.row_factory = sqlite3.Row
docs = {r["source_url"].rsplit("/", 1)[-1]: dict(r) for r in con.execute("select * from documents")}
assert docs["abc-123"]["status"] == "PARSED" and docs["abc-123"]["ticker"] == "SHEL" and docs["abc-123"]["source_url"] == B + "/docproxy/abc-123", docs
assert "script" not in docs  # same content as abc-123, so it counts as the same filing
assert "director.txt" not in docs, "a director's notice is not a buyback"
assert con.execute("select count(*) from skipped_links where link=?", (B + "/director.txt",)).fetchone()[0] == 1
assert "empty" not in docs, docs  # a viewer with no document is a failure, so it's tried again next time
log3 = next((root3 / "logs").glob("*.csv")).read_text(encoding="utf-8")
assert "no document address found" in log3, log3
tx = con.execute("select shares from transactions where trade_date='2026-03-05'").fetchone()
assert tx["shares"] == 140000
assert con.execute("select count(*) from transactions where trade_date='2026-03-05' and shares=5000").fetchone()[0] == 0
con.close()
before = len(hits)
f.main([str(dam), "--root", str(root3), "--delay", "0", "--only-study"])
assert "/director.txt" not in hits[before:] and "/notice2.txt" not in hits[before:] and "/docproxy/abc-123" not in hits[before:], hits[before:]
print("DAM cases ok")
# --- the real link pattern: file names with spaces, already-encoded names, and a host from the settings file
assert f.fetch(B + "/Docproxy/Fetch/My Notice (1) \u00e9.txt")[0] == NOTICE
assert f.fetch(B + "/Docproxy/Fetch/already%20encoded.txt")[0] == NOTICE
assert f.clean_link("ffdocproxy.prod.factset.com/DocProxy/Fetch/a b.pdf") == "http://ffdocproxy.prod.factset.com/DocProxy/Fetch/a b.pdf"  # as the system's own links
assert f.clean_link("ffdocproxy.prod.factset.com/x", "https") == "https://ffdocproxy.prod.factset.com/x"
assert f.request_address("https://h.example.com/Docproxy/Fetch/a b.pdf?x=1 2") == "https://h.example.com/Docproxy/Fetch/a%20b.pdf?x=1%202"
f.ALLOWED_HOSTS.clear()
f.load_allowed_hosts(Path(__file__).resolve().parent.parent)
assert "ffdocproxy.prod.factset.com" in f.ALLOWED_HOSTS and f.refusal("https://FFDOCPROXY.prod.factset.com/DocProxy/Fetch/x") is None
assert "public" in (f.refusal("https://www.factset.com/x") or "").lower() or "not found" in (f.refusal("https://www.factset.com/x") or "").lower()  # only the exact host
f.ALLOWED_HOSTS.clear()
# --- date, ticker and file name, joined to a location
names = tmp / "names.csv"
names.write_text("Date,Ticker,File Name,Title\n05/03/2026,SHEL,My Notice (1) \u00e9.txt,Own shares\n05/03/2026,SHEL,../secret.txt,Bad\n", encoding="utf-8")
root4 = tmp / "app4"
root4.mkdir()
f.main([str(names), "--root", str(root4), "--delay", "0", "--country", "UK", "--location", B + "/Docproxy/Fetch/"])
con = sqlite3.connect(root4 / "buyback.db")
assert [r[0] for r in con.execute("select source_url from documents")] == [B + "/Docproxy/Fetch/My Notice (1) \u00e9.txt"]
con.close()
log4 = next((root4 / "logs").glob("*.csv")).read_text(encoding="utf-8")
assert "isn't allowed" in log4, log4
assert f.link_for({"file_name": "a b.pdf"}, r"\\server\filings" + "\\")[0] == r"\\server\filings\a b.pdf"
P = "http://ffdocproxy.prod.factset.com/DocProxy/Fetch/"
assert fetching.DEFAULT_LOCATION == P
fetching.SETTINGS.write_text('{"filing_location": "https://ffdocproxy.prod.factset.com/DocProxy/Fetch/"}', encoding="utf-8")
assert fetching.get_location() == P  # an earlier version's saved default moves to http
fetching.SETTINGS.write_text('{"filing_location": "https://other.example.com/Fetch/"}', encoding="utf-8")
assert fetching.get_location() == "https://other.example.com/Fetch/"  # an address you chose stays
fetching.SETTINGS.unlink()
assert f.link_for({"hyperlink": "A0F895C2-8094-F111-AC2E-020716C124E7"}, P)[0] == P + "A0F895C2-8094-F111-AC2E-020716C124E7~0~nocache"  # a document ID as written in your workbook
ID = "24b885ac-386e-f111-ac2c-12bc89a8f273"
assert f.link_for({"hyperlink": ID}, P) == (P + ID + "~0~nocache", None)  # a document ID, as in your Excel list
assert f.link_for({"hyperlink": ID + "~0~nocache"}, P) == (P + ID + "~0~nocache", None)  # no second ending
assert f.link_for({"hyperlink": P + ID + "~0~nocache"}, "") == (P + ID + "~0~nocache", None)  # a pasted full link needs no location
assert f.request_address(P + ID + "~0~nocache") == P + ID + "~0~nocache"
pasted = fetching.parse_pasted(f"{P}{ID}~0~nocache\n\nHSBA {P}abc~0~nocache\nCBA\t{ID}\n", "cba")
assert [(r["ticker"], r["hyperlink"]) for _, r in pasted] == [("CBA", P + ID + "~0~nocache"), ("HSBA", P + "abc~0~nocache"), ("CBA", ID)], pasted
assert fetching.parse_pasted(P + ID) == [(1, {"ticker": "", "hyperlink": P + ID})]  # the document says which company
assert fetching.base_location(P + ID + "~0~nocache") == P and fetching.base_location(P + ID + "/{file name}") == P and fetching.base_location(P) == P
from sbb import countries as reset_countries, db as reset_db, ingest as reset_ingest
keep_inbox = reset_countries.INBOX
reset_countries.INBOX = tmp / "reset_inbox"
(reset_countries.INBOX / "AU").mkdir(parents=True)
(reset_countries.INBOX / "AU" / "x.pdf").write_bytes(b"x")  # not read, and left alone
(reset_countries.INBOX / "AU" / "manual_entries.csv").write_bytes(b"x")
(reset_countries.INBOX / "prices.csv").write_bytes(b"x")
rc = reset_db.connect(tmp / "reset.db")
rc.execute("insert into documents(sha256,country,file_name,rel_path,source_url,status,imported_at) values('s','AU','x','','u','PARSED','t')")
rc.execute("insert into skipped_links(link,reason,skipped_at) values('l','r','t')")
rc.commit()
assert 'AU,,,,,PARSED,u,t' in fetching.links_csv(rc).replace("\r", "")
assert fetching.write_links(rc) and fetching.LINKS_FILE.read_text(encoding="utf-8-sig").startswith("Market,Ticker")
keep_links = fetching.LINKS_FILE
fetching.LINKS_FILE = tmp  # a folder can't be written as a file, like a CSV open in Excel
assert fetching.write_links(rc) is False
fetching.LINKS_FILE = keep_links
assert reset_ingest.reset(rc) == {"documents": 1, "files": 1}
assert not rc.execute("select 1 from documents union select 1 from skipped_links").fetchone()
assert not (reset_countries.INBOX / "AU" / "manual_entries.csv").exists() and not (reset_countries.INBOX / "prices.csv").exists()
assert (reset_countries.INBOX / "AU" / "x.pdf").exists()
rc.close()
reset_countries.INBOX = keep_inbox
keep_lists = fetching.LISTS_FOLDER
fetching.LISTS_FOLDER = tmp / "lists"
assert fetching.lists_in_folder() == []
(fetching.LISTS_FOLDER / "a.xlsx").write_bytes(b"x")
(fetching.LISTS_FOLDER / "~$a.xlsx").write_bytes(b"x")
(fetching.LISTS_FOLDER / "note.txt").write_bytes(b"x")
assert [x["name"] for x in fetching.lists_in_folder()] == ["a.xlsx"]
fetching.LISTS_FOLDER = keep_lists
assert f.link_for({"hyperlink": "abc 123.pdf"}, P) == (P + "abc 123.pdf", None)  # a file name in the Hyperlink column
assert f.link_for({"hyperlink": "abc-123"}, P) == (P + "abc-123", None)
assert f.link_for({"hyperlink": P + "abc.pdf"}, "") == (P + "abc.pdf", None)  # a full link is used as it is
assert f.link_for({"hyperlink": "ffdocproxy.prod.factset.com/DocProxy/Fetch/abc.pdf"}, "") == (P + "abc.pdf", None)
assert f.link_for({"hyperlink": "../secret"}, P)[1]
assert f.link_for({"file_name": "a.pdf"}, "")[1] and f.link_for({"file_name": "x/../../a.pdf"}, "https://h/f/")[1]
try:
    try:
        f.use_location("https://www.asx.com.au/x/")
        raise AssertionError("an exchange can't be a location")
    except ValueError as e:
        assert "Exchange" in str(e)
    assert f.use_location("ffdocproxy.prod.example.com/Docproxy/Fetch/") == "http://ffdocproxy.prod.example.com/Docproxy/Fetch/"
    assert f.get_location().startswith("http://") and "ffdocproxy.prod.example.com" in f.ALLOWED_HOSTS
finally:
    f.ALLOWED_HOSTS.clear()
# --- a filing naming another company isn't added to the listed one; a wrong list date is flagged, with the filing's date used
c5 = db.connect(tmp / "c5.db")
form = (Path(__file__).resolve().parent / "fixtures" / "uk_labels.txt").read_bytes()
assert ingest.import_link(c5, "http://h/a", "UK", form, ".txt", "SHEL", "", "2026-01-01") == "PARSED"
assert c5.execute("select kind from review").fetchone()["kind"] == "DATE_DIFFERS" and c5.execute("select doc_date from documents").fetchone()[0] == "2026-03-05"
threec = b"Appendix 3C - Notification of buy-back\n1.1 Name of entity\nXYZ LIMITED\n1.3 ASX issuer code\nXYZ\n1.5 Date of this announcement\n5/3/2026\n5.1 Total number of +securities bought back\n100\n5.2 Total consideration paid or payable for the securities\nAUD 500.00\n"
assert ingest.import_link(c5, "http://h/b", "AU", threec, ".txt", "ABC") == "NEEDS_REVIEW"
assert c5.execute("select count(*) from programmes where ticker in ('ABC','XYZ')").fetchone()[0] == 0
assert {r["kind"] for r in c5.execute("select kind from review where doc_id=2")} == {"COMPANY_DIFFERS", "NO_COMPANY"}
ingest.assign_company(c5, 2, "XYZ")
assert c5.execute("select count(*) from programmes where ticker='XYZ'").fetchone()[0] == 1
# --- daily rows and the chart data
act = queries.activity(c5, c5.execute("select prog_id from programmes where ticker='SHEL'").fetchone()[0])
assert act["daily"][0]["shares"] == 120000 and act["daily"][0]["value_basis"] == "Calculated" and act["paid"][0]["basis"] == "Calculated"
# --- two filings of one type on one date are flagged, and nothing is removed
c5.execute("update documents set doc_type='transaction', doc_date='2026-03-05', ticker='SHEL', country='UK'")
c5.commit()
assert any(k["check"] == "Possible duplicate" and k["ticker"] == "SHEL" for k in queries.quality(c5, "UK", queries.ALL_FROM, queries.ALL_TO)["checks"])
assert c5.execute("select count(*) from documents").fetchone()[0] == 2
c5.close()
print("list and activity ok")
# --- a list with no link column
bad = tmp / "bad.csv"
bad.write_text("Code,Date\nCPU,2025-01-01\n", encoding="utf-8")
try:
    f.read_rows(bad)
    raise AssertionError("should refuse")
except ValueError as e:
    assert "File Name" in str(e)
# --- stops after repeated failures
many = tmp / "many.csv"
many.write_text("code,date,url\n" + "".join(f"AZJ,2026-02-{i:02d},{B}/missing{i}\n" for i in range(1, 11)), encoding="utf-8")
before = len(hits)
f.main([str(many), "--root", str(root), "--delay", "0"])
assert len(hits) - before == f.STOP_AFTER_FAILURES, hits[before:]
from sbb import countries as reset_countries, db as reset_db, ingest as reset_ingest, parsers as order_parsers
keep_get = fetching._get
page_text = "Meridian completes share buyback. " * 20


def fake_get(link):
    if "tracker" in link:
        raise ValueError("Public internet address")
    body = ('<html><iframe src="https://tracker.example.com/ns.html"></iframe>' + (page_text if "withtext" in link else "") + "</html>").encode()
    return body, "text/html", link


fetching._get = fake_get
assert fetching.fetch("http://x/withtext")[2] == "web page, read as it is"  # a tracker frame doesn't hide the page's own text
try:
    fetching.fetch("http://x/empty")
    assert False, "an empty viewer page must fail"
except ValueError as e:
    assert "Public internet address" in str(e)
fetching._get = keep_get
ANN = "Shell plc\n{d}\nShare buyback programme announcement\nShell plc announces the commencement of a share buyback programme of up to US$3.5 billion.\nPurchases will take place during the period running from {s} and ending no later than {e}.\n"
DAILY = "Shell plc\n{d}\nTransaction in Own Shares\nDate of purchase: {t}\nNumber of ordinary shares purchased: {n}\nVolume weighted average price paid per share (pence): 2,800.00\n"
A1 = ("A1", ANN.format(d="2 January 2026", s="3 January 2026", e="30 April 2026"))
D1 = ("D1", DAILY.format(d="11 February 2026", t="10 February 2026", n="100,000"))
B1 = ("B1", ANN.format(d="1 May 2026", s="2 May 2026", e="30 July 2026"))
D2 = ("D2", DAILY.format(d="11 June 2026", t="10 June 2026", n="200,000"))
D3 = ("D3", DAILY.format(d="12 June 2026", t="11 June 2026", n="300,000"))


def read_in_order(name, order):
    oc = reset_db.connect(tmp / f"order_{name}.db")
    reset_countries.load_constituents(oc)
    for n, text in order:
        reset_ingest.import_link(oc, "http://x/" + n, "UK", text.encode(), ".txt", "SHEL")
    reset_ingest.replay(oc, "UK", "SHEL")
    oc.commit()
    placed = {}
    for r in oc.execute("select p.announced_date a, t.trade_date d from programmes p join transactions t on t.prog_id=p.prog_id where p.ticker='SHEL' order by 1,2"):
        placed.setdefault(r["a"], []).append(r["d"])
    flags = [r["detail"] for r in oc.execute("select detail from review where kind='NO_PROGRAMME' and status='OPEN'")]
    terms = oc.execute("select announced_date, end_date from programmes where ticker='SHEL' order by 1").fetchall()
    oc.close()
    return placed, flags, [tuple(x) for x in terms]


right = {"2026-01-02": ["2026-02-10"], "2026-05-01": ["2026-06-10", "2026-06-11"]}
base_terms = read_in_order("oldest", [A1, D1, B1, D2, D3])
assert base_terms[0] == right and base_terms[1] == [], base_terms
for i, order in enumerate(([D3, D2, B1, D1, A1], [D3, D2, D1, B1, A1], [A1, D3, D2, D1, B1], [B1, D3, A1, D1, D2])):
    assert read_in_order(str(i), order) == base_terms, order  # the same result in any order
missing = read_in_order("missing_new", [A1, D2])  # the later announcement isn't in the list
assert missing[0] == {"2026-01-02": ["2026-06-10"]} and "after the end date" in missing[1][0], missing
missing = read_in_order("missing_old", [D1, D2])  # no announcement at all
assert set(missing[0]) == {""} and len(missing[1]) == 2 and "before any programme announcement" in missing[1][0], missing
again = reset_db.connect(tmp / "order_oldest.db")
reset_ingest.replay(again, "UK", "SHEL")
reset_ingest.replay(again, "UK", "SHEL")
assert again.execute("select count(*) from transactions").fetchone()[0] == 3 and again.execute("select count(*) from programmes").fetchone()[0] == 2
again.close()
assert order_parsers.is_buyback_filing("menu " * 900 + "Meridian completes share buyback")
assert not order_parsers.is_buyback_filing("menu " * 2000 + "share buyback")

# Appendix 3H: captured apart, linked by date, and the latest filing overwrites
FX3H = (Path(__file__).resolve().parent / "fixtures" / "au_3h_mixed.txt").read_text(encoding="utf-8")
LATER3H = FX3H.replace("2,070,144", "2,070,000").replace("15/1/2025", "20/1/2025")
ANN_IPH = ("P1", ANN.format(d="1 June 2024", s="2 June 2024", e="30 June 2025"))


def read_3h(name, order):
    oc = reset_db.connect(tmp / f"h3_{name}.db")
    reset_countries.load_constituents(oc)
    for n, text in order:
        reset_ingest.import_link(oc, "http://x/" + n, "AU", text.encode(), ".txt", "IPH")
    reset_ingest.replay(oc, "AU", "IPH")
    oc.commit()
    rows = [tuple(r) for r in oc.execute("select e.security_code, e.shares, e.is_buyback, p.announced_date from cessations e left join programmes p on p.prog_id=e.prog_id order by 1")]
    bought = oc.execute("select count(*) from transactions").fetchone()[0]
    flags = oc.execute("select count(*) from review where kind='NO_PROGRAMME' and status='OPEN'").fetchone()[0]
    oc.close()
    return rows, bought, flags


want = ([("IPH", 2070000, 1, "2024-06-01"), ("IPHAA", 116236, 0, None)], 0, 0)
assert read_3h("a", [ANN_IPH, ("H1", FX3H), ("H2", LATER3H)]) == want, read_3h("a2", [ANN_IPH, ("H1", FX3H), ("H2", LATER3H)])
assert read_3h("b", [("H2", LATER3H), ("H1", FX3H), ANN_IPH]) == want  # read back to front, the later filing still overwrites
assert read_3h("c", [("H1", FX3H)])[2] == 1  # no programme read yet, so it is flagged

# Removing a filing reconciles its company, and it stays out if a list is read again
rm = reset_db.connect(tmp / "remove.db")
reset_countries.load_constituents(rm)
for n, text in (ANN_IPH, ("H1", FX3H), ("H2", LATER3H), A1, B1, D2):
    reset_ingest.import_link(rm, "http://x/" + n, "AU" if n in ("P1", "H1", "H2") else "UK", text.encode(), ".txt", "IPH" if n in ("P1", "H1", "H2") else "SHEL")
reset_ingest.replay(rm, "AU", "IPH")
reset_ingest.replay(rm, "UK", "SHEL")
rm.commit()
doc = lambda n: rm.execute("select doc_id from documents where source_url=?", ("http://x/" + n,)).fetchone()[0]
kept = lambda: rm.execute("select shares from cessations where security_code='IPH'").fetchone()[0]
assert kept() == 2070000
reset_ingest.remove_filing(rm, doc("H2"))  # what the later filing overwrote comes back
assert kept() == 2070144
assert rm.execute("select reason, heading from skipped_links where link='http://x/H2'").fetchone()["reason"] == "Removed by you"
assert reset_ingest.import_link(rm, "http://x/H2", "AU", LATER3H.encode(), ".txt", "IPH", force=True) == "PARSED"  # Read anyway brings it back
rm.execute("delete from skipped_links where link='http://x/H2'")
reset_ingest.replay(rm, "AU", "IPH")
assert kept() == 2070000
reset_ingest.remove_filing(rm, doc("P1"))  # no programme now, so the cancellation says so
assert rm.execute("select prog_id from cessations where security_code='IPH'").fetchone()[0] is None
assert rm.execute("select count(*) from programmes where ticker='IPH'").fetchone()[0] == 0
assert rm.execute("select count(*) from review where kind='NO_PROGRAMME' and ticker='IPH' and status='OPEN'").fetchone()[0] == 1
placed = lambda: {r["a"]: r["n"] for r in rm.execute("select p.announced_date a, count(t.tx_id) n from programmes p left join transactions t on t.prog_id=p.prog_id where p.ticker='SHEL' group by 1")}
assert placed() == {"2026-01-02": 0, "2026-05-01": 1}
reset_ingest.remove_filing(rm, doc("B1"))  # the purchase falls back to the earlier programme, and is flagged as after its end date
assert placed() == {"2026-01-02": 1}
assert rm.execute("select count(*) from review where kind='NO_PROGRAMME' and ticker='SHEL' and status='OPEN'").fetchone()[0] == 1
reset_ingest.remove_filing(rm, doc("D2"))
reset_ingest.remove_filing(rm, doc("A1"))  # the company's last filing leaves nothing behind
assert not rm.execute("select 1 from programmes where ticker='SHEL'").fetchone() and not rm.execute("select 1 from review where ticker='SHEL'").fetchone()
try:
    reset_ingest.remove_filing(rm, 99999)
    assert False
except ValueError:
    pass
rm.execute("insert into documents(sha256,country,file_name,rel_path,status,imported_at) values('typed','AU','manual_entries.csv','inbox/AU/manual_entries.csv','PARSED','t')")
try:
    reset_ingest.remove_filing(rm, rm.execute("select doc_id from documents where sha256='typed'").fetchone()[0])
    assert False, "typed entries stay"
except ValueError as e:
    assert "Typed entries" in str(e)
rm.close()

# The market chosen on the page
mk = reset_db.connect(tmp / "market.db")
mk.execute("insert into companies(country,ticker,company,in_index) values('UK','HSBA','HSBC',1),('AU','CSL','CSL',1),('AU','DUAL','A',1),('UK','DUAL','B',0)")
rc_ = lambda ticker, row=None, market="": fetching.resolve_country(mk, row or {}, ticker, None, market)
assert rc_("MACF", market="UK") == ("UK", None)  # not known anywhere
assert "choose its market" in rc_("MACF")[1]
assert rc_("CSL", market="UK") == ("AU", None)  # known only elsewhere, so it isn't moved
assert rc_("DUAL", market="UK") == ("UK", None) and rc_("DUAL") == ("AU", None)  # the chosen market wins over the study list
assert rc_("MACF", {"country": "NZ"}, "UK") == ("NZ", None)  # a Country column wins
mk.close()

# Filing date decides, and a same-day correction always follows what it corrects
order = lambda date, kind, prev, sha: reset_ingest._filing_order({"doc_date": date, "sha256": sha, "parsed_json": __import__("json").dumps({"p": {"doc_type": kind, "previous_date": prev}})})
assert order("2026-02-16", "update", "2026-02-13", "z") < order("2026-02-16", "update", "2026-02-16", "a") < order("2026-02-17", "update", "2026-02-16", "a")
assert order("2026-02-16", "programme", "", "z") < order("2026-02-16", "daily", "", "a")

# a skipped filing can be read anyway, and a list row can ask for that
sk = reset_db.connect(tmp / "skip.db")
reset_countries.load_constituents(sk)
plain = b"Shell plc\n2 January 2026\nDirector dealing notice about a change of address for a director, long enough to count as text.\n"
assert reset_ingest.import_link(sk, "http://x/s1", "UK", plain, ".txt", "SHEL") == "NOT_BUYBACK"
assert tuple(sk.execute("select ticker, country, reason from skipped_links").fetchone()) == ("SHEL", "UK", "Not a buyback filing")
assert reset_ingest.import_link(sk, "http://x/s1", "UK", plain, ".txt", "SHEL", force=True) != "NOT_BUYBACK"
assert sk.execute("select 1 from documents where source_url='http://x/s1'").fetchone()
sk.close()

from openpyxl import Workbook
wb = Workbook()
wb.active.append(["Ticker", "Hyperlink"])
wb.active.append(["CBA", '=HYPERLINK("https://a.example.com/Fetch/x~0~nocache","Open")'])
wb.active.append(["CBA", "Open"])
wb.active["B3"].hyperlink = "https://a.example.com/Fetch/y~0~nocache"
wb.active.append(["CBA", ID])
wb.active["B4"].hyperlink = "https://other.example.com/hidden"
wb.save(tmp / "links.xlsx")
assert [r["hyperlink"] for _, r in fetching.read_rows(tmp / "links.xlsx")] == ["https://a.example.com/Fetch/x~0~nocache", "https://a.example.com/Fetch/y~0~nocache", ID]  # an ID in the cell beats a link hidden behind it

# A programme still marked ACTIVE shows COMPLETED, tagged Calculated, once its target is used or a later programme starts buying after it
st = reset_db.connect(tmp / "status.db")
reset_countries.load_constituents(st)
day = lambda d, n, avg: {"trade_date": d, "venue": "", "shares": n, "value": n * avg / 100, "currency": "GBP", "price_unit": "GBp", "price_avg": avg, "price_high": None, "price_low": None, "value_origin": "product"}
put = lambda doc, ann, txs, prog=None: reset_ingest.store(st, doc, "UK", "LLOY", {"programme": {"announced_date": ann, **(prog or {})}, "transactions": txs, "snapshots": [], "doc_date": txs[-1]["trade_date"] if txs else ann})
put(1, "2025-01-30", [day("2025-02-03", 1000, 100)])  # older, finished before the next began
put(2, "2026-01-30", [day("2026-02-02", 1000, 100), day("2026-09-25", 1000, 100)], {"max_value": 2000, "max_currency": "GBP"})  # reached its target of GBP 2,000
put(3, "2026-07-31", [day("2026-09-28", 500, 100)], {"max_value": 1000, "max_currency": "GBP"})  # still buying
put(4, "2024-01-30", [], {"status": "COMPLETED"})  # the notice says so
rows_ = queries.programme_rows(st, "UK", queries.ALL_FROM, queries.ALL_TO)
got = {r["announced_date"]: (r["status"], r["status_basis"]) for r in rows_}
assert got == {"2025-01-30": ("COMPLETED", "Calculated"), "2026-01-30": ("COMPLETED", "Calculated"), "2026-07-31": ("ACTIVE", None), "2024-01-30": ("COMPLETED", "Reported")}, got
why = {r["announced_date"]: r["status_working"] for r in rows_}
assert why["2026-01-30"] == "100.0% of its target used" and "began buying on 2026-02-02" in why["2025-01-30"], why
assert st.execute("select count(*) from programmes where status='COMPLETED'").fetchone()[0] == 1  # worked out on display, not saved over what the notices say
# a running total of shares with no amount is kept, but the amounts still come from the daily purchases
reset_ingest.store(st, 5, "UK", "LLOY", {"programme": {"announced_date": "2026-07-31"}, "transactions": [], "doc_date": "2026-09-29",
                   "snapshots": [{"as_of": "2026-09-28", "cum_shares": 500, "cum_value": None, "currency": None, "origin": "reported", "working": "Shares only"}]})
r3 = [r for r in queries.programme_rows(st, "UK", queries.ALL_FROM, queries.ALL_TO) if r["announced_date"] == "2026-07-31"][0]
assert r3["amounts"] == {"GBP": 500.0} and r3["method"] == "Daily notices", (r3["amounts"], r3["method"])
st.close()
print("status ok")

# a viewer page holding only script, whose document can't be fetched, fails: script isn't the page's own text
def script_only_get(link):
    if "tracker" in link:
        raise ValueError("Public internet address")
    return ('<html><iframe src="https://tracker.example.com/ns.html"></iframe><script>' + "var settings = 1;" * 40 + "</script></html>").encode(), "text/html", link


saved_get, fetching._get = fetching._get, script_only_get
try:
    fetching.fetch("http://x/scriptonly")
    assert False, "a page with only script must fail"
except ValueError as e:
    assert "Public internet address" in str(e), e
fetching._get = saved_get
print("script page ok")

# Each filing names its Appendix and type; a filing read before these columns existed is named from what was saved
fl = reset_db.connect(tmp / "labels.db")
reset_countries.load_constituents(fl)
fl.execute("""insert into documents(sha256,country,source_url,doc_type,status,parsed_json) values('3c','AU','http://x/3C','daily','PARSED','{"p": {"form": "appendix_3c", "doc_type": "daily"}}')""")
for n, text, cc, code in ((*ANN_IPH, "AU", "IPH"), ("H1", FX3H, "AU", "IPH"), (*D1, "UK", "SHEL"), ("odd", "Shell plc announcement about nothing the parser knows, a buyback of sorts, with enough text to be read.", "UK", "SHEL")):
    reset_ingest.import_link(fl, "http://x/" + n, cc, text.encode(), ".txt", code, force=True)
fl.commit()
names = lambda: {r["source_url"][9:]: (r["form"], r["appendix"], r["filing_type"]) for r in fl.execute("select source_url, form, appendix, filing_type from documents")}
got = names()
assert got["3C"] == ("appendix_3c", "Appendix 3C", "Daily buy-back notification"), got
assert got[ANN_IPH[0]] == ("notice", "None (company notice)", "Programme announcement"), got
assert got["H1"] == ("appendix_3h", "Appendix 3H", "Cessation of securities"), got
assert got[D1[0]] == ("notice", "None (company notice)", "Purchase notice"), got
assert got["odd"][1:] == ("Not identified", "Not identified"), got  # never guessed
fl.execute("update documents set form=null, appendix=null, filing_type=null")
reset_db.fill_labels(fl)
assert names() == got, names()
print("labels ok")

# Programme figures: cancelled shares come only from counts filed; the average is blank unless it can be worked out in one currency
from sbb import queries as q_prog
assert q_prog._cancelled(None)["cancelled_shares"] is None
two = q_prog._cancelled([("Appendix 3H", "2024-04-03", 803060.0, 7), ("Appendix 3H", "2024-05-16", 268516.0, 9)])
assert two["cancelled_shares"] == 1071576 and two["cancelled_basis"] == "Calculated" and two["cancelled_docs"] == [7, 9] and "803,060 on 2024-04-03" in two["cancelled_working"], two
buy = lambda shares, value, cur="AUD": {"shares": shares, "value": value, "currency": cur}
assert q_prog._average([buy(100, 1000), buy(300, 2000)], "AUD")["avg_price"] == 7.5
assert q_prog._average([buy(100, 1000), buy(300, 2000)], "AUD")["avg_working"] == "AUD 3,000.00 paid / 400 shares"
for ev in ([], [buy(100, None)], [buy(None, 500)], [buy(100, 1000), buy(100, 1000, "USD")]):
    assert q_prog._average(ev, "AUD")["avg_price"] is None, ev
pr = reset_db.connect(tmp / "prog.db")
reset_countries.load_constituents(pr)
for n, text in (ANN_IPH, ("H1", FX3H)):
    reset_ingest.import_link(pr, "http://x/" + n, "AU", text.encode(), ".txt", "IPH")
reset_ingest.replay(pr, "AU", "IPH")
row = next(r for r in q_prog.programme_rows(pr, "AU", "2000-01-01", "2099-12-31") if r["ticker"] == "IPH")
assert row["cancelled_shares"] == 2070144, row["cancelled_working"]  # the buy-back line only: the same filing's other security isn't counted
print("programme figures ok")

# v19 corrections: a figure in another convention is left unread, never misread
from sbb import parsers as pv
assert pv.num("1.234,56") is None and pv.num("12,5") is None and pv.num("1,234,567.89") == 1234567.89 and pv.num("2,706,964") == 2706964 and pv.num("641.43p") == 641.43
assert pv.unit_of("The call is at 5 p.m. Bought at US$12.10", "USD") == "USD" and pv.unit_of("C$45.10", "CAD") == "CAD" and pv.unit_of("641.43p", "GBP") == "GBp" and pv.unit_of("A$12.10", "AUD") == "AUD"
assert pv._money_match("it repurchased shares for a total of $126.6 million under its $2.0 billion share repurchase program", "USD")[:2] == (2e9, "USD")  # the size, not the spend
assert pv._money_match("a buy-back of up to HK$500 million", "GBP")[:2] == (5e8, "HKD")
us = "Acme Inc\n03/04/2026\nShare repurchase\nDate of purchase: 03/03/2026\nNumber of shares purchased: 1,000\nWeighted average price: $10.00\n"
assert pv.parse(us, "USD")["doc_date"] == "2026-04-03" and pv.parse(us, "USD", "US", "MDY")["doc_date"] == "2026-03-04" and pv.to_date("03/04/2026") == "2026-04-03"  # a market's date order ends with its filing
weekly = "Example plc\n9 March 2026\nTransaction in own shares\nThe Company purchased the following shares from 2 March 2026 to 6 March 2026 as part of its buyback programme.\nNumber of ordinary shares purchased: 10,000\nVolume weighted average price paid per share (pence): 250.00\n"
assert "start_date" not in pv.parse(weekly, "GBP")["programme"]  # the days bought, not the programme's dates
runs = "Example plc\n9 March 2026\nShare buyback programme\nThe buyback of up to GBP 10 million will run from 10 March 2026 until 30 June 2026.\n"
assert pv.parse(runs, "GBP")["programme"]["end_date"] == "2026-06-30"
leap = "Example plc\n29 February 2028\nThe buyback of up to GBP 10 million will run up until the 12-month anniversary of the date of this announcement.\n"
assert pv.parse(leap, "GBP")["programme"]["end_date"] == "2029-02-28"
quarter = "Acme Corp\nFebruary 5, 2026\nAcme Corp announced that during the quarter ended December 31, 2025 it repurchased 1,250,000 shares of common stock at an average price of $101.25 per share under its share repurchase program.\n"
pq = pv.parse(quarter, "USD")
assert pq["transactions"] == [] and "PERIOD_PURCHASE" in [k for k, _ in pq["issues"]], pq
hk = "NEXT DAY DISCLOSURE RETURN\nExample Holdings Limited\n4 March 2026\nShare repurchases\nDate of purchase: 3 March 2026\nNumber of shares repurchased 500,000\nHighest price paid HK$ 12.50\nLowest price paid HK$ 12.10\nAggregate price paid HK$ 6,150,000\n"
xh = pv.parse(hk, "HKD")["transactions"][0]
assert (xh["value"], xh["value_origin"], xh["currency"], xh["price_avg"]) == (6150000, "reported", "HKD", 12.3), xh
assert pv.is_buyback_filing("Announcement Summary\n" + "x " * 400 + "\nAppendix 3H - Notification of cessation of securities\n1.3 ASX issuer code\nCBA", "Notification of cessation of +securities")
kw_keep = pv.KEYWORDS_FILE
(tmp / "kw.csv").write_text("market,field,phrase,means,example\nUK,treatment,will be extinguished,Cancelled,\n", encoding="utf-8")
pv.KEYWORDS_FILE, pv._KW["stamp"] = tmp / "kw.csv", None
gone = "Example plc\n9 March 2026\nTransaction in own shares\nDate of purchase: 6 March 2026\nNumber of ordinary shares purchased: 10,000\nThe shares will be extinguished.\n"
assert pv.parse(gone, "GBP", "UK")["programme"].get("treatment") == "Cancelled" and not pv.parse(gone, "AUD", "AU")["programme"].get("treatment")  # a market's own phrase is used for that market only
pv.KEYWORDS_FILE, pv._KW["stamp"] = kw_keep, None

# a notice restating an open programme's size, with no dates of its own, joins that programme and is flagged; one with its own dates is a new programme
rs = reset_db.connect(tmp / "restated.db")
reset_countries.load_constituents(rs)
SAME = ("S1", "Shell plc\n5 March 2026\nShare buyback update\nShell plc confirms that its share buyback programme of up to US$3.5 billion continues.\n")
for n, text in (A1, SAME, B1):
    reset_ingest.import_link(rs, "http://x/" + n, "UK", text.encode(), ".txt", "SHEL")
reset_ingest.replay(rs, "UK", "SHEL")
assert [r[0] for r in rs.execute("select announced_date from programmes where ticker='SHEL' order by 1")] == ["2026-01-02", "2026-05-01"], list(rs.execute("select announced_date from programmes"))
assert rs.execute("select count(*) from review where kind='PROGRAMME_RESTATED'").fetchone()[0] == 1

# a cancellation goes to the programme that had bought by then, not to a later one with no buying
lk = reset_db.connect(tmp / "link.db")
lk.execute("insert into programmes(prog_id,country,ticker,announced_date) values(1,'AU','XYZ','2024-01-01'),(2,'AU','XYZ','2024-03-01')")
lk.execute("insert into transactions(prog_id,country,ticker,trade_date,shares) values(1,'AU','XYZ','2024-02-01',100)")
lk.execute("insert into cessations(doc_id,n,country,ticker,security_code,shares,reason,is_buyback,ceased_on) values(9,0,'AU','XYZ','XYZ',100,'buy-back',1,'2024-04-01'),(9,1,'AU','XYZ','XYZAA',5,'lapse',0,'2024-04-01')")
reset_ingest._link_cessations(lk, "AU", "XYZ")
assert [r[0] for r in lk.execute("select prog_id from cessations order by n")] == [1, None]
print("v19 corrections ok")

srv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print("ALL OK")
