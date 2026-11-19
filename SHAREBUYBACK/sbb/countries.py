"""Market settings live in data/countries.json, so a new country needs no code or UI change.

The companies studied are in data/study_companies.csv (country,ticker,company). Any company with a saved notice joins them.
Each country also has an inbox folder. data/constituents_<code>.csv is only a lookup for names and sectors, and is optional.
"""
import csv
import json
import re

from .db import ROOT

CONFIG = ROOT / "data" / "countries.json"
INBOX = ROOT / "inbox"


def load():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def get(code):
    return next((c for c in load() if c["code"] == code), None)


def code(country, ticker):
    """A company code as this market keeps it. Where "code_zeros" is "ignore" (Hong Kong: 02429 and 2429 are one company), a code of digits loses its leading zeros."""
    ticker = str(ticker or "")
    if ticker.isdigit() and (get(country or "") or {}).get("code_zeros") == "ignore":
        return ticker.lstrip("0") or "0"
    return ticker


def add(body):
    """Add a country from the Collect page. Returns the new entry."""
    code = str(body.get("code", "")).strip().upper()
    if not re.fullmatch(r"[A-Z]{2,3}", code):
        raise ValueError("Country code must be 2 or 3 letters, for example SG.")
    currency = str(body.get("currency", "")).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Currency must be a 3-letter code, for example SGD.")
    for key in ("name", "exchange"):
        if not str(body.get(key, "")).strip():
            raise ValueError(f"Please fill in {key}.")
    all_c = load()
    if any(c["code"] == code for c in all_c):
        raise ValueError(f"{code} already exists.")
    entry = {"code": code, "name": body["name"].strip(), "flag": str(body.get("flag", "")).strip(), "exchange": body["exchange"].strip(),
             "currency": currency, "search_terms": []}
    all_c.append(entry)
    CONFIG.write_text(json.dumps(all_c, ensure_ascii=False, indent=2), encoding="utf-8")
    (INBOX / code).mkdir(parents=True, exist_ok=True)
    return entry


STUDY = ROOT / "data" / "study_companies.csv"


def remove_study(country, ticker):
    """Take a company off the study list. True if it was on it."""
    if not STUDY.exists():
        return False
    with STUDY.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    keep = [r for r in rows if not (len(r) >= 2 and r[0].strip().upper() == country and r[1].strip().upper() == ticker)]
    if len(keep) == len(rows):
        return False
    with STUDY.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(keep)
    return True


def add_study(body):
    """Add a company to the study list, by country and code."""
    country = str(body.get("country", "")).strip().upper()
    ticker = str(body.get("ticker", "")).strip().upper()
    if not get(country):
        raise ValueError("Choose a country.")
    if not re.fullmatch(r"[A-Z0-9.]{1,8}", ticker):
        raise ValueError("Enter the company's code, for example BHP.")
    with STUDY.open(encoding="utf-8-sig", newline="") as fh:
        if any(r["country"] == country and r["ticker"].strip().upper() == ticker for r in csv.DictReader(fh)):
            raise ValueError(f"{ticker} is already in the study list.")
    company = re.sub(r"[\r\n,]+", " ", str(body.get("company", ""))).strip()
    with STUDY.open("a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow([country, ticker, company])
    return {"country": country, "ticker": ticker}


def load_constituents(con):
    """Refresh the companies table. The in_index column now means 'in the study': on the study list, or has a saved notice."""
    con.execute("update companies set in_index=0")
    for c in load():
        (INBOX / c["code"]).mkdir(parents=True, exist_ok=True)
        f = ROOT / "data" / f"constituents_{c['code']}.csv"
        if not f.exists():
            continue
        with f.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                con.execute("""insert into companies(country,ticker,company,sector,as_of,source,in_index) values(?,?,?,?,?,?,0)
                    on conflict(country,ticker) do update set company=excluded.company, sector=excluded.sector, as_of=excluded.as_of, source=excluded.source""",
                            (c["code"], r["ticker"].strip().upper(), r["company"].strip(), r.get("sector", "").strip(), r.get("as_of", ""), r.get("source", "")))
    if STUDY.exists():
        with STUDY.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                name = (r.get("company") or "").strip() or None
                con.execute("""insert into companies(country,ticker,company,in_index) values(?,?,?,1)
                    on conflict(country,ticker) do update set company=coalesce(?,company), in_index=1""", (r["country"].strip().upper(), r["ticker"].strip().upper(), name or r["ticker"].strip().upper(), name))
    con.execute("""update companies set in_index=1 where exists (select 1 from documents d where d.country=companies.country and d.ticker=companies.ticker)
        or exists (select 1 from programmes p where p.country=companies.country and p.ticker=companies.ticker)""")
    con.commit()
