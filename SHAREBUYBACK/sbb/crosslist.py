"""Companies listed in two markets: a purchase made abroad can be reported twice, once by each market's filing.

data/cross_listings.csv names the pairs (a Hong Kong code and the same company's code in another market). A Hong Kong purchase on another
exchange is marked "Also in <market> filings" when that market's own notices hold the same purchase: the same date and venue and shares, or,
failing that, the same total shares for the day. Nothing is guessed: a purchase with no clear match stays unmarked, and goes to the review
list only when the other market has buying for that company on nearby days, so a missing match can't simply mean nothing was loaded yet.
Rows are kept as they are; the mark only says the figure is also in the other market's filings, so it is known to be one purchase and not two.
"""
import csv
from datetime import date

from . import db

FILE = db.ROOT / "data" / "cross_listings.csv"
HOME_VENUE = "HKEX"
ALIASES = {"xlon": "London Stock Exchange", "aimx": "London Stock Exchange", "london stock exchange": "London Stock Exchange", "bate": "CBOE BXE", "cboe bxe": "CBOE BXE",
           "chix": "CBOE CXE", "cboe cxe": "CBOE CXE", "aqxe": "Aquis", "trqx": "Turquoise"}
_CACHE = {"stamp": None, "rows": []}


def pairs():
    try:
        stamp = FILE.stat().st_mtime_ns
    except OSError:
        return []
    if _CACHE["stamp"] != stamp:
        with FILE.open(encoding="utf-8-sig", newline="") as fh:
            _CACHE["rows"] = [{"code": r["hk_code"].strip().lstrip("0") or "0", "country": r["country"].strip().upper(), "ticker": r["ticker"].strip().upper()}
                              for r in csv.DictReader(fh) if r.get("hk_code") and r.get("ticker")]
        _CACHE["stamp"] = stamp
    return _CACHE["rows"]


def concerns(country, ticker):
    """Whether a company is one of the listed pairs, in Hong Kong or in the other market."""
    return any((country == "HK" and p["code"] == ticker) or (country == p["country"] and p["ticker"] == ticker) for p in pairs())


def canon(venue):
    """One name for a venue however it is written: 'London Stock Exchange (XLON)', 'XLON' and 'London Stock Exchange' are one."""
    v = (venue or "").strip()
    inside = v[v.rfind("(") + 1:v.rfind(")")].strip() if "(" in v and v.endswith(")") else ""
    return ALIASES.get(inside.lower()) or ALIASES.get(v.lower()) or v


def _flag(con, doc_id, ticker, detail):
    if not con.execute("select 1 from review where doc_id is ? and kind='HK_NO_OTHER_MATCH' and detail=?", (doc_id, detail)).fetchone():
        con.execute("insert into review(doc_id,country,ticker,kind,detail,status,created_at) values(?,?,?,?,?,?,?)", (doc_id, "HK", ticker, "HK_NO_OTHER_MATCH", detail, "OPEN", db.now()))


def link(con):
    """Mark, or unmark, Hong Kong purchases made abroad against the other market's notices. Safe to run again at any time."""
    for pr in pairs():
        con.execute("delete from review where kind='HK_NO_OTHER_MATCH' and status='OPEN' and country='HK' and ticker=?", (pr["code"],))  # asked again below; one you dismissed stays dismissed
        hk = db.rows(con.execute("select * from transactions where country='HK' and ticker=? and venue<>? and venue<>'' and venue not in ('Private arrangement','General offer')", (pr["code"], HOME_VENUE)))
        if not hk:
            continue
        other = db.rows(con.execute("select * from transactions where country=? and ticker=?", (pr["country"], pr["ticker"])))
        by_day = {}
        for t in other:
            by_day.setdefault(t["trade_date"], []).append(t)
        hk_day = {}
        for t in hk:
            hk_day.setdefault(t["trade_date"], []).append(t)
        for day, rows in hk_day.items():
            theirs = by_day.get(day, [])
            day_ok = bool(theirs) and abs(sum(t["shares"] or 0 for t in theirs) - sum(t["shares"] or 0 for t in rows)) < 0.5
            for t in rows:
                match = next((o for o in theirs if canon(o["venue"]) == canon(t["venue"]) and abs((o["shares"] or 0) - (t["shares"] or 0)) < 0.5), None)
                mark = f"{pr['country']} {pr['ticker']}: same date, venue and shares" if match else f"{pr['country']} {pr['ticker']}: same total shares for the day" if day_ok else None
                if (t.get("also_in") or None) != mark:
                    con.execute("update transactions set also_in=? where tx_id=?", (mark, t["tx_id"]))
                if not mark and any(abs((date.fromisoformat(d) - date.fromisoformat(day)).days) <= 3 for d in by_day):
                    _flag(con, t["doc_id"], pr["code"], f"The {t['venue']} purchase of {t['shares']:,.0f} shares on {day} has no matching purchase in {pr['country']} {pr['ticker']}'s own notices, although they hold buying on nearby days. It is left unmarked: check whether it is the same purchase.")
