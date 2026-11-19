"""The Manage tickers page: every exchange with its tickers and what is held for each, and deleting one ticker with its filings.
A backup copy of the database is made before anything is deleted."""
import csv
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from . import countries, db


def _study():
    """(country, ticker) of every company the user added to the study list by hand."""
    if not countries.STUDY.exists():
        return set()
    with countries.STUDY.open(encoding="utf-8-sig", newline="") as fh:
        return {(r["country"].strip().upper(), r["ticker"].strip().upper()) for r in csv.DictReader(fh)}


def listing(con):
    """Each exchange in data/countries.json with its tickers: filings, programmes, purchases, dates and items to review."""
    def counts(sql):
        return {(r[0], r[1]): r for r in con.execute(sql)}
    docs = counts("""select country, ticker, count(*) n, sum(coalesce(source_url,'')<>'') links, sum(coalesce(rel_path,'')<>'') files, min(doc_date) first, max(doc_date) last
        from documents where ticker is not null group by country, ticker""")
    progs = counts("select country, ticker, count(*) n from programmes group by country, ticker")
    buys = counts("select country, ticker, count(*) n from transactions group by country, ticker")
    open_items = counts("select country, ticker, count(*) n from review where status='OPEN' and ticker is not null group by country, ticker")
    loose = {r[0]: r[1] for r in con.execute("select country, count(*) from documents where ticker is null group by country")}
    study = _study()
    out = []
    for c in countries.load():
        rows = []
        for r in con.execute("select ticker, company, sector, source from companies where country=? order by ticker", (c["code"],)):
            key = (c["code"], r["ticker"])
            d = docs.get(key)
            rows.append({"ticker": r["ticker"], "company": r["company"] or "", "sector": r["sector"] or "",
                         "filings": d["n"] if d else 0, "link_filings": d["links"] if d else 0, "file_filings": d["files"] if d else 0,
                         "first": d["first"] if d else None, "last": d["last"] if d else None,
                         "programmes": progs[key]["n"] if key in progs else 0, "purchases": buys[key]["n"] if key in buys else 0,
                         "review": open_items[key]["n"] if key in open_items else 0,
                         "listed": "Study list" if key in study else "Index list" if r["source"] is not None else "Filings only"})
        out.append({"code": c["code"], "name": c["name"], "flag": c.get("flag", ""), "exchange": c.get("exchange", ""), "index": c.get("index", ""),
                    "currency": c.get("currency", ""), "tickers": rows, "no_company": loose.get(c["code"], 0)})
    return {"version": db.VERSION, "exchanges": out}


def backup(con, label):
    """A full copy of the database in the 'backups' folder beside it, made before a delete. Returns the file."""
    con.commit()
    folder = Path(con.execute("pragma database_list").fetchone()[2]).parent / "backups"
    folder.mkdir(exist_ok=True)
    stem = f"buyback_{datetime.now():%Y%m%d_%H%M%S}_before_delete_{re.sub(r'[^A-Za-z0-9.]+', '_', label)}"
    f, n = folder / f"{stem}.db", 1
    while f.exists():
        n += 1
        f = folder / f"{stem}_{n}.db"
    copy = sqlite3.connect(f)
    try:
        con.backup(copy)
    finally:
        copy.close()
    return f


def start_copy(path=None):
    """A full copy of the database file as it is, made the first time this version starts and before the app opens it, so before any column is added
    or filing read again. In the 'backups' folder beside it. Does nothing if there is no database yet or this version has already made one. Returns the file, or None."""
    path = Path(path or db.DB_PATH)
    if not path.exists():
        return None
    con = sqlite3.connect(path)
    try:
        return _start_copy(con, path.parent / "backups")
    finally:
        con.close()


def _start_copy(con, folder):
    tag = re.sub(r"[^A-Za-z0-9.]+", "_", db.VERSION)
    if folder.exists() and list(folder.glob(f"*_start_of_{tag}.db")):
        return None
    folder.mkdir(exist_ok=True)
    f = folder / f"buyback_{datetime.now():%Y%m%d_%H%M%S}_start_of_{tag}.db"
    copy = sqlite3.connect(f)
    try:
        con.backup(copy)
    finally:
        copy.close()
    return f


def delete_ticker(con, country, ticker, forget_links=False):
    """Take one ticker out of one exchange: its filings and every figure, programme and review item that came from them.
    Its links are remembered as removed, so a list read again doesn't bring them back, unless forget_links is set.
    A ticker on the index list stays on the list, with nothing held for it."""
    country = str(country or "").strip().upper()
    ticker = re.sub(r"[^A-Z0-9.]", "", str(ticker or "").strip().upper())
    if not countries.get(country) or not ticker:
        raise ValueError("Choose an exchange and a ticker.")
    who = (country, ticker)
    mine = "select doc_id from documents where country=? and ticker=?"
    held = "select prog_id from programmes where country=? and ticker=?"
    docs = db.rows(con.execute("select doc_id, source_url, rel_path, heading from documents where country=? and ticker=?", who))
    n = lambda table: con.execute(f"select count(*) from {table} where country=? and ticker=?", who).fetchone()[0]
    done = {"country": country, "ticker": ticker, "filings": len(docs), "programmes": n("programmes"), "purchases": n("transactions"), "review": n("review"),
            "files_left": sum(1 for d in docs if d["rel_path"])}
    if not (docs or done["programmes"] or done["purchases"] or con.execute("select 1 from companies where country=? and ticker=?", who).fetchone()):
        raise ValueError(f"{ticker} isn't on {country} any more.")
    done["backup"] = backup(con, f"{country}_{ticker}").name
    for table in ("evidence", "doc_pages"):
        con.execute(f"delete from {table} where doc_id in ({mine})", who)
    for table in ("snapshots", "venue_totals"):
        con.execute(f"delete from {table} where prog_id in ({held}) or doc_id in ({mine})", who + who)
    for table in ("transactions", "cancellations", "cessations", "review"):
        con.execute(f"delete from {table} where (country=? and ticker=?) or doc_id in ({mine})", who + who)
    con.execute("delete from share_counts where country=? and ticker=?", who)
    con.execute("delete from programmes where country=? and ticker=?", who)
    if forget_links:
        con.execute(f"delete from skipped_links where (country=? and ticker=?) or link in (select source_url from documents where country=? and ticker=?)", who + who)
    else:
        con.executemany("insert or replace into skipped_links(link,reason,skipped_at,ticker,country,heading) values(?,?,?,?,?,?)",
                        [(d["source_url"], "Removed by you", db.now(), ticker, country, d["heading"]) for d in docs if d["source_url"]])
    from . import hand
    hand.forget_company(con, country, ticker, "Ticker deleted on Manage")  # its entries made by hand leave the figures with it, and stay in the history
    con.execute("delete from documents where country=? and ticker=?", who)
    done["links"] = "forgotten" if forget_links else "remembered"
    done["off_study_list"] = countries.remove_study(country, ticker)
    con.commit()
    countries.load_constituents(con)
    con.execute("delete from companies where country=? and ticker=? and in_index=0 and source is null", who)
    con.commit()
    done["still_listed"] = bool(con.execute("select 1 from companies where country=? and ticker=?", who).fetchone())
    return done
