"""A throwaway database for testing the viewer, built through the app's own reading code from the real samples. The project's buyback.db is not touched."""
import sys
import tempfile
from pathlib import Path

R = Path(__file__).resolve().parents[2]  # the project folder
sys.path.insert(0, str(R))
sys.dont_write_bytecode = True
from sbb import countries, db, fetching, ingest

fetching.LINKS_FILE = Path(tempfile.mkdtemp()) / "links.csv"
countries.INBOX = Path(tempfile.mkdtemp())
out = Path(tempfile.gettempdir()) / "sbb_viewer_test.db"  # outside the project, so buyback.db is never touched
out.unlink(missing_ok=True)
con = db.connect(out)
countries.load_constituents(con)
OLD = R / "old_saved_filings_2026-11-05" / "inbox"
n = 0
if not OLD.exists():  # the saved sample filings aren't in the package: the test fixtures alone still check the viewer
    print("sample filings not found, so only the test fixtures are used")
for code in ("UK", "AU", "NZ") if OLD.exists() else ():
    for f in sorted((OLD / code).iterdir()):
        if f.suffix.lower() in (".pdf", ".html"):
            ingest.import_link(con, "http://example.test/" + f.name, code, f.read_bytes(), f.suffix.lower(), f.name.split("_")[0].upper())
            n += 1
FX = R / "tests" / "fixtures"
for name, code, ticker, ext in (("uk_rns_aviva.html", "UK", "AV.", ".html"), ("uk_rns_macfarlane.html", "UK", "MACF", ".html"), ("uk_rns_cells.html", "UK", "RKT", ".html"), ("uk_rns_frontier.html", "UK", "FDEV", ".html"),("au_3h_mixed.txt", "AU", "IPH", ".txt"), ("au_3h_daily.txt", "AU", "RF1", ".txt"), ("au_3h_lapse.txt", "AU", "CSL", ".txt")):
    ingest.import_link(con, "http://example.test/" + name, code, (FX / name).read_bytes(), ext, ticker)
    n += 1
waiting = """Shell plc
11 February 2026
Transaction in Own Shares
Date of purchase: 10 February 2026
Number of ordinary shares purchased: 100,000
Volume weighted average price paid per share (pence): 2,800.00
"""
ingest.import_link(con, "http://example.test/shell_waiting.txt", "UK", waiting.encode(), ".txt", "SHEL")
n += 1
ingest.replay_all(con)
con.commit()
print("filings read:", n)
for t in ("documents", "programmes", "transactions", "snapshots", "cessations", "review"):
    print(f"  {t}: {con.execute(f'select count(*) from {t}').fetchone()[0]}")
print("companies with filings:", [tuple(r) for r in con.execute("select country, ticker, count(*) from documents where ticker is not null group by 1, 2 order by 1, 2")])
con.close()
