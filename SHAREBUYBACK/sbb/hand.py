"""Entries made by hand: a programme announcement, a change of terms, a purchase, or a completion, for any market; and (version 27) an update
of one figure read from a filing, marked "Updated Manually" (see the section at the end).

Some buybacks exist only as announcements in prose that no reader can take apart (NZX programmes and completions among them), and some filings
are not in the document system at all. Each entry is kept twice:
  - hand_entries holds what was typed, with its source; hand_log keeps every add, edit and delete, with the old and new values and when.
  - a documents row holds the same entry as a reading (parsed_json, form "manual"), so rebuilding, the Tracker and Periods treat it like any
    filing read. Editing replaces that reading and rebuilds the company; deleting takes it out of every figure, and the entry stays in the history
    with the reason.
Every figure keeps the mark "Entered by hand". Nothing is worked out for you: an end date stated as a period is typed by you, and a size
stated as a percentage stays a percentage. A hand entry and a filing read that disagree are both kept, and the pair goes to review.
"""
import hashlib
import json
import re

from . import countries, db, ingest, parsers

KINDS = {"programme": "Programme announcement", "change": "Change of terms", "purchase": "Purchase", "completion": "Completion"}
DOC_TYPE = {"programme": "programme", "change": "update", "purchase": "transaction"}  # a completion is "final" when it states totals, else "completion"
TYPES = ["On market buy-back", "Off market buy-back", "Equal access buy-back", "Selective buy-back", "Employee share scheme buy-back", "On-market, under shareholder mandate"]
TREATMENTS = ["Cancelled", "Treasury"]
_CUR = re.compile(r"^[A-Z]{3}$")


# ---------- checking what was typed ----------
def _date(v, label, need=False):
    v = str(v or "").strip()
    if not v:
        if need:
            raise ValueError(f"{label} is required.")
        return None
    d = parsers.to_date(v)
    if not d:
        raise ValueError(f"{label}: '{v}' is not a date.")
    return d


def _num(v, label, need=False, whole=False):
    v = str(v if v is not None else "").strip()
    if not v:
        if need:
            raise ValueError(f"{label} is required.")
        return None
    n = parsers.num(v)
    if n is None or n < 0:
        raise ValueError(f"{label}: '{v}' is not a number.")
    if whole and n != int(n):
        raise ValueError(f"{label} must be a whole number of shares.")
    return n


def _cur(v, label, need):
    v = str(v or "").strip().upper()
    if not v:
        if need:
            raise ValueError(f"{label}: choose the currency the amount is in. Amounts are never converted.")
        return None
    if not _CUR.match(v):
        raise ValueError(f"{label}: '{v}' is not a three-letter currency code, such as NZD.")
    return v


def _programme_dates(con, country, ticker):
    return {r["announced_date"] for r in con.execute("select announced_date from programmes where country=? and ticker=? and announced_date<>''", (country, ticker))}


def clean(con, body):
    """The entry as it will be kept, or ValueError with a plain reason. Only what you typed is kept: nothing is filled in or worked out."""
    kind = str(body.get("kind") or "")
    if kind not in KINDS:
        raise ValueError("Choose what you are adding: Programme announcement, Change of terms, Purchase or Completion.")
    country = str(body.get("country") or "").strip().upper()
    if not countries.get(country):
        raise ValueError("Choose the exchange.")
    ticker = re.sub(r"[^A-Z0-9.]", "", str(body.get("ticker") or "").strip().upper())
    if not ticker:
        raise ValueError("Choose the company.")
    if not con.execute("select 1 from companies where country=? and ticker=? and (in_index=1 or source is not null)", (country, ticker)).fetchone():
        raise ValueError(f"{ticker} is not in the {country} company list. Check the code, or add the company on Companies first.")
    source = re.sub(r"\s+", " ", str(body.get("source") or "")).strip()
    if len(source) < 3:
        raise ValueError("Source is required: a link, or where it came from, such as \"NZX announcement of 2 March 2026\".")
    note = str(body.get("note") or "").strip()
    f = {}
    if kind in ("programme", "change"):
        if kind == "programme":
            f["announced_date"] = _date(body.get("announced_date"), "Announced on", True)
            f["buyback_type"] = str(body.get("buyback_type") or "").strip() or None
            f["broker"] = str(body.get("broker") or "").strip() or None
            t = str(body.get("treatment") or "").strip()
            if t and t not in TREATMENTS:
                raise ValueError("Shares are: choose Cancelled or Treasury, or leave it as Not stated.")
            f["treatment"] = t or None
        else:
            f["programme"] = _date(body.get("programme"), "Programme", True)
            f["change_date"] = _date(body.get("change_date"), "Date of the change", True)
        f["start_date"] = _date(body.get("start_date"), "Starts")
        f["end_date"] = _date(body.get("end_date"), "Ends")
        f["max_shares"] = _num(body.get("max_shares"), "Maximum shares", whole=True)
        f["max_value"] = _num(body.get("max_value"), "Maximum amount")
        f["max_currency"] = _cur(body.get("max_currency"), "Maximum amount", f["max_value"] is not None) if f["max_value"] is not None else None
        f["max_pct"] = _num(body.get("max_pct"), "Maximum as % of shares")
        if f["max_pct"] is not None and not 0 < f["max_pct"] <= 100:
            raise ValueError("Maximum as % of shares must be more than 0 and no more than 100.")
        f["intended_shares"] = _num(body.get("intended_shares"), "Intended number", whole=True)
        if f["start_date"] and f["end_date"] and f["end_date"] < f["start_date"]:
            raise ValueError("Ends is before Starts.")
        if kind == "change" and not any(f[k] is not None for k in ("start_date", "end_date", "max_shares", "max_value", "max_pct", "intended_shares")):
            raise ValueError("Type what changed: a new start or end date, or a new size.")
    elif kind == "purchase":
        f["programme"] = _date(body.get("programme"), "Programme")
        f["trade_date"] = _date(body.get("trade_date"), "Purchase date", True)
        f["venue"] = re.sub(r"\s+", " ", str(body.get("venue") or "")).strip()
        if not f["venue"]:
            raise ValueError("Bought on: choose the exchange the shares were bought on.")
        f["shares"] = _num(body.get("shares"), "Shares", True, whole=True)
        if not f["shares"]:
            raise ValueError("Shares must be more than 0.")
        f["value"] = _num(body.get("value"), "Amount paid")
        f["price_avg"] = _num(body.get("price_avg"), "Average price")
        f["price_high"] = _num(body.get("price_high"), "Highest price")
        f["price_low"] = _num(body.get("price_low"), "Lowest price")
        priced = any(f[k] is not None for k in ("value", "price_avg", "price_high", "price_low"))
        f["currency"] = _cur(body.get("currency"), "Currency", priced)
        if f["price_high"] is not None and f["price_low"] is not None and f["price_low"] > f["price_high"]:
            raise ValueError("Lowest price is above the highest price.")
        f["broker"] = str(body.get("broker") or "").strip() or None
    else:
        f["programme"] = _date(body.get("programme"), "Programme", True)
        f["completed_on"] = _date(body.get("completed_on"), "Completed on", True)
        f["final_shares"] = _num(body.get("final_shares"), "Total shares bought", whole=True)
        f["final_value"] = _num(body.get("final_value"), "Total amount paid")
        f["final_currency"] = _cur(body.get("final_currency"), "Total amount paid", f["final_value"] is not None) if f["final_value"] is not None else None
        if f["final_value"] is not None and f["final_shares"] is None:
            raise ValueError("Type the total shares bought with the total amount paid, as the announcement states them.")
    held = _programme_dates(con, country, ticker)
    if f.get("programme") and f["programme"] not in held:
        raise ValueError(f"No programme announced {f['programme']} is held for {ticker}. Choose one from the list, or add its announcement first.")
    day = f.get("change_date") or f.get("completed_on")
    if f.get("programme") and day and day < f["programme"]:
        raise ValueError(f"The date {day} is before the programme was announced ({f['programme']}).")
    return {"kind": kind, "country": country, "ticker": ticker, "source": source, "note": note, "fields": f}


# ---------- the entry as a reading, as a filing read would give it ----------
def reading(e, entry_id):
    """The entry in the shape every reader returns, so it is stored, rebuilt and tracked like a filing read."""
    f, kind = e["fields"], e["kind"]
    p = {"form": "manual", "ticker": e["ticker"], "company": None, "issues": [], "transactions": [], "snapshots": [], "cancellations": [], "cessations": [], "venue_totals": [],
         "reason": None, "manual": {"entry_id": entry_id, "kind": kind, "source": e["source"], "note": e["note"]}}
    if kind == "programme":
        g = {k: f.get(k) for k in ("announced_date", "buyback_type", "start_date", "end_date", "max_shares", "max_value", "max_currency", "max_pct", "intended_shares", "broker", "treatment")}
        if g["treatment"]:
            g["treatment_text"] = "Entered by hand. Source: " + e["source"]
        p.update(doc_type="programme", doc_date=f["announced_date"], programme=g)
    elif kind == "change":
        g = {"announced_date": f["programme"], **{k: f.get(k) for k in ("start_date", "end_date", "max_shares", "max_value", "max_currency", "max_pct", "intended_shares")}}
        p.update(doc_type="update", doc_date=f["change_date"], programme=g, reason="Change of terms entered by hand")
    elif kind == "purchase":
        value, origin = f["value"], "hand"
        if value is None and f["price_avg"] is not None:  # the amount, if not typed, is worked out from what was typed, and marked so
            value, origin = f["shares"] * f["price_avg"], "hand_product"
        p.update(doc_type="transaction", doc_date=f["trade_date"], programme={"announced_date": f["programme"] or ""},
                 transactions=[{"trade_date": f["trade_date"], "venue": f["venue"], "shares": f["shares"], "value": value, "currency": f["currency"], "price_avg": f["price_avg"],
                                "price_high": f["price_high"], "price_low": f["price_low"], "price_unit": f["currency"] or "", "value_origin": origin, "broker": f["broker"]}])
    else:
        snaps = [{"as_of": f["completed_on"], "cum_shares": f["final_shares"], "cum_value": f["final_value"], "currency": f["final_currency"], "origin": "hand",
                  "working": "Final totals entered by hand"}] if f["final_shares"] is not None else []
        p.update(doc_type="final" if snaps else "completion", doc_date=f["completed_on"], programme={"announced_date": f["programme"], "status": "COMPLETED"}, snapshots=snaps)
    return p


def title(e):
    f = e["fields"]
    day = f.get("announced_date") or f.get("change_date") or f.get("trade_date") or f.get("completed_on") or ""
    return f"Entered by hand: {KINDS[e['kind']]} {e['ticker']} {day}"


def summary(kind, f):
    """One line saying what the entry holds, for the list of hand entries."""
    n = lambda v: f"{v:,.0f}"
    size = lambda: "; ".join(x for x in (f"up to {n(f['max_shares'])} shares" if f.get("max_shares") is not None else "",
                                          f"up to {f['max_currency']} {f['max_value']:,.2f}" if f.get("max_value") is not None else "",
                                          f"up to {f['max_pct']:g}% of shares" if f.get("max_pct") is not None else "",
                                          f"about {n(f['intended_shares'])} intended" if f.get("intended_shares") is not None else "") if x)
    if kind in ("programme", "change"):
        dates = ", ".join(x for x in (f"starts {f['start_date']}" if f.get("start_date") else "", f"ends {f['end_date']}" if f.get("end_date") else "") if x)
        head = f"Programme of {f['programme']}: " if kind == "change" else ""
        return head + "; ".join(x for x in (dates, size(), f.get("buyback_type") or "", f"shares {f['treatment'].lower()}" if f.get("treatment") else "") if x) or head + "no terms typed"
    if kind == "purchase":
        paid = f"{f['currency']} {f['value']:,.2f}" if f.get("value") is not None else (f"average {f['currency']} {f['price_avg']:,.4f}" if f.get("price_avg") is not None else "no price")
        return f"{n(f['shares'])} shares, {paid}, on {f['venue']}" + (f" (programme of {f['programme']})" if f.get("programme") else "")
    totals = f"{n(f['final_shares'])} shares" + (f", {f['final_currency']} {f['final_value']:,.2f}" if f.get("final_value") is not None else "") if f.get("final_shares") is not None else "no final totals stated"
    return f"Programme of {f['programme']} completed; {totals}"


# ---------- saving, editing, deleting ----------
def _put_document(con, e, entry_id, doc_id=None):
    p = reading(e, entry_id)
    saved = json.dumps({"p": p, "ev": [], "hint": e["ticker"]})
    sha = hashlib.sha256(f"hand:{entry_id}:{saved}:{db.now()}".encode()).hexdigest()
    name = title(e)
    if doc_id is None:
        cur = con.execute("""insert into documents(sha256,country,file_name,rel_path,ticker,doc_type,doc_date,status,message,parsed_json,imported_at,heading,form)
            values(?,?,?,'',?,?,?,'PARSED','Entered by hand',?,?,?,'manual')""", (sha, e["country"], name, e["ticker"], p["doc_type"], p["doc_date"], saved, db.now(), name))
        return cur.lastrowid
    con.execute("""update documents set sha256=?, country=?, file_name=?, ticker=?, doc_type=?, doc_date=?, parsed_json=?, heading=?, form='manual', appendix=null, filing_type=null where doc_id=?""",
                (sha, e["country"], name, e["ticker"], p["doc_type"], p["doc_date"], saved, name, doc_id))
    return doc_id


def _clear_figures(con, doc_id):
    for table in ("transactions", "snapshots", "venue_totals", "cancellations", "cessations", "share_counts", "evidence", "doc_pages"):
        con.execute(f"delete from {table} where doc_id=?", (doc_id,))
    con.execute("delete from review where doc_id=? and status='OPEN'", (doc_id,))


def _settle(con, *companies):
    for c in dict.fromkeys(companies):
        ingest.replay(con, *c)
    db.fill_labels(con)
    con.commit()


def _log(con, entry_id, action, old=None, new=None, reason=None):
    con.execute("insert into hand_log(entry_id,action,at,old_fields,new_fields,reason) values(?,?,?,?,?,?)",
                (entry_id, action, db.now(), json.dumps(old) if old is not None else None, json.dumps(new) if new is not None else None, reason))


def _kept(e):
    return {"kind": e["kind"], "country": e["country"], "ticker": e["ticker"], "source": e["source"], "note": e["note"], **e["fields"]}


def save(con, body):
    """Add an entry, or with entry_id change one. Returns the entry as listed. An update of a figure read from a filing (kind "update") is saved by save_update."""
    if str(body.get("kind") or "") == "update":
        return save_update(con, body)
    e = clean(con, body)
    entry_id = body.get("entry_id")
    if e["kind"] == "programme":
        same = con.execute("""select entry_id from hand_entries where status='ACTIVE' and kind='programme' and country=? and ticker=? and json_extract(fields,'$.announced_date')=?
            and entry_id is not ?""", (e["country"], e["ticker"], e["fields"]["announced_date"], int(entry_id) if entry_id else None)).fetchone()
        if same:
            raise ValueError(f"A programme announced {e['fields']['announced_date']} for {e['ticker']} is already entered by hand. Edit that entry instead.")
    if not entry_id:
        cur = con.execute("insert into hand_entries(kind,country,ticker,fields,source,note,status,created_at,updated_at) values(?,?,?,?,?,?,'ACTIVE',?,?)",
                          (e["kind"], e["country"], e["ticker"], json.dumps(e["fields"]), e["source"], e["note"], db.now(), db.now()))
        entry_id = cur.lastrowid
        doc_id = _put_document(con, e, entry_id)
        con.execute("update hand_entries set doc_id=? where entry_id=?", (doc_id, entry_id))
        _log(con, entry_id, "ADDED", new=_kept(e))
        _settle(con, (e["country"], e["ticker"]))
        return entry(con, entry_id)
    old = con.execute("select * from hand_entries where entry_id=? and status='ACTIVE'", (int(entry_id),)).fetchone()
    if not old:
        raise ValueError("That entry isn't there any more, or was deleted.")
    if old["kind"] != e["kind"]:
        raise ValueError(f"This entry is a {KINDS[old['kind']]}; it can't become a {KINDS[e['kind']]}. Delete it and add a new one.")
    was = {"kind": old["kind"], "country": old["country"], "ticker": old["ticker"], "source": old["source"], "note": old["note"], **json.loads(old["fields"])}
    if was == _kept(e):
        raise ValueError("Nothing was changed.")
    con.execute("update hand_entries set country=?, ticker=?, fields=?, source=?, note=?, updated_at=? where entry_id=?",
                (e["country"], e["ticker"], json.dumps(e["fields"]), e["source"], e["note"], db.now(), old["entry_id"]))
    if old["doc_id"]:
        _clear_figures(con, old["doc_id"])
    doc_id = _put_document(con, e, old["entry_id"], old["doc_id"] if old["doc_id"] and con.execute("select 1 from documents where doc_id=?", (old["doc_id"],)).fetchone() else None)
    con.execute("update hand_entries set doc_id=? where entry_id=?", (doc_id, old["entry_id"]))
    _log(con, old["entry_id"], "EDITED", old=was, new=_kept(e))
    _settle(con, (e["country"], e["ticker"]), (old["country"], old["ticker"]))  # the company it is under now first, then the one it left
    return entry(con, old["entry_id"])


def delete(con, entry_id, reason):
    """Take an entry out of every figure. It stays in the history, with when and why."""
    reason = re.sub(r"\s+", " ", str(reason or "")).strip()
    if len(reason) < 3:
        raise ValueError("Type the reason for deleting it, such as \"Entered twice\".")
    old = con.execute("select * from hand_entries where entry_id=? and status='ACTIVE'", (int(entry_id or 0),)).fetchone()
    if not old:
        raise ValueError("That entry isn't there any more, or was already deleted.")
    if old["doc_id"]:
        _clear_figures(con, old["doc_id"])
        con.execute("delete from review where doc_id=?", (old["doc_id"],))
        con.execute("delete from documents where doc_id=?", (old["doc_id"],))
    con.execute("update hand_entries set status='DELETED', deleted_at=?, delete_reason=?, doc_id=null where entry_id=?", (db.now(), reason, old["entry_id"]))
    _log(con, old["entry_id"], "DELETED", old={"kind": old["kind"], "country": old["country"], "ticker": old["ticker"], "source": old["source"], "note": old["note"], **json.loads(old["fields"])}, reason=reason)
    _settle(con, (old["country"], old["ticker"]))
    return {"deleted": old["entry_id"]}


def forget_company(con, country, ticker, reason):
    """When a ticker is deleted on Manage, its hand entries leave the figures with it, and stay in the history."""
    for r in con.execute("select * from hand_entries where status='ACTIVE' and country=? and ticker=?", (country, ticker)).fetchall():
        con.execute("update hand_entries set status='DELETED', deleted_at=?, delete_reason=?, doc_id=null where entry_id=?", (db.now(), reason, r["entry_id"]))
        _log(con, r["entry_id"], "DELETED", old={"kind": r["kind"], "country": r["country"], "ticker": r["ticker"], "source": r["source"], "note": r["note"], **json.loads(r["fields"])}, reason=reason)


# ---------- moving the entries typed before version 25 ----------
def migrate(con):
    """Before version 25, Add by hand wrote purchases to inbox/<market>/manual_entries.csv. Each one becomes an entry here once, so it can be edited and
    deleted. The file is kept beside, renamed so it is not read again. Returns how many purchases were moved."""
    moved = 0
    for d in con.execute("select * from documents where parsed_json is null and lower(rel_path) like '%manual_entries.csv'").fetchall():
        txs = con.execute("select t.*, p.announced_date from transactions t left join programmes p on p.prog_id=t.prog_id where t.doc_id=? order by t.trade_date", (d["doc_id"],)).fetchall()
        for t in txs:
            if con.execute("""select 1 from hand_entries h join hand_log l on l.entry_id=h.entry_id and l.action='MOVED' where h.kind='purchase' and h.country=? and h.ticker=?
                    and json_extract(h.fields,'$.trade_date')=? and json_extract(h.fields,'$.shares')=?""", (t["country"], t["ticker"], t["trade_date"], t["shares"])).fetchone():
                continue  # the same row moved before, from a copy of the file put back in the inbox: not added twice
            fields = {"programme": t["announced_date"] or None, "trade_date": t["trade_date"], "venue": t["venue"] or (countries.get(d["country"]) or {}).get("exchange") or "Not stated",
                      "shares": t["shares"], "value": t["value"], "price_avg": t["price_avg"], "price_high": t["price_high"], "price_low": t["price_low"], "currency": t["currency"], "broker": t["broker"]}
            e = {"kind": "purchase", "country": t["country"], "ticker": t["ticker"], "fields": fields, "note": "Moved from manual_entries.csv. The figures are as they were held; the amount may have been worked out from the average price.",
                 "source": "Typed on Add by hand before version 25 (no source was recorded). Edit this entry to add it."}
            cur = con.execute("insert into hand_entries(kind,country,ticker,fields,source,note,status,created_at,updated_at) values(?,?,?,?,?,?,'ACTIVE',?,?)",
                              ("purchase", e["country"], e["ticker"], json.dumps(fields), e["source"], e["note"], d["imported_at"] or db.now(), db.now()))
            doc_id = _put_document(con, e, cur.lastrowid)
            con.execute("update hand_entries set doc_id=? where entry_id=?", (doc_id, cur.lastrowid))
            _log(con, cur.lastrowid, "MOVED", new=_kept(e), reason=f"Moved from {d['rel_path']}")
            moved += 1
        for table in ("transactions", "snapshots", "venue_totals", "evidence", "review", "doc_pages"):
            con.execute(f"delete from {table} where doc_id=?", (d["doc_id"],))
        con.execute("delete from documents where doc_id=?", (d["doc_id"],))
        f = db.ROOT / d["rel_path"]
        if f.is_file():  # kept as it was, under a name the inbox doesn't read
            target = f.with_name(f"manual_entries_moved_to_Add_by_hand_{db.now()[:10]}.csv.bak")
            n = 1
            while target.exists():
                n += 1
                target = f.with_name(f"manual_entries_moved_to_Add_by_hand_{db.now()[:10]}_{n}.csv.bak")
            f.rename(target)
        for c in {(t["country"], t["ticker"]) for t in txs}:
            ingest.replay(con, *c)
    if moved:
        db.fill_labels(con)
    con.commit()
    return moved


# ---------- a hand entry against the filings read ----------
def check(con, country, ticker):
    """Where a filing read states the same thing as a hand entry, both are kept. If they differ, or the same purchase may be counted twice, the pair goes to review.
    Run after the company is rebuilt; the questions are worked out again each time, and one you marked as checked stays checked."""
    con.execute("delete from review where country=? and ticker=? and kind in ('HAND_DIFFERS','HAND_TWICE') and status='OPEN'", (country, ticker))
    hand = [d for d in con.execute("select doc_id, doc_date, parsed_json from documents where country=? and ticker=? and form='manual' and parsed_json is not null", (country, ticker))]
    if not hand:
        return
    read = []
    for d in con.execute("select doc_id, doc_date, doc_type, coalesce(heading, file_name) heading, parsed_json from documents where country=? and ticker=? and coalesce(form,'')<>'manual' and parsed_json is not null", (country, ticker)):
        try:
            read.append((d, json.loads(d["parsed_json"])["p"]))
        except (ValueError, KeyError, TypeError):
            continue
    said = lambda d: f"the filing \"{(d['heading'] or '')[:80]}\" filed {d['doc_date'] or 'with no date'}"
    fmt = lambda k, v: "not stated" if v is None else f"{v:,.2f}" if k in ("max_value", "value", "cum_value") else f"{v:,.0f}" if k in ("max_shares", "shares", "cum_shares", "intended_shares") else str(v)
    names = {"start_date": "starts", "end_date": "ends", "max_shares": "maximum shares", "max_value": "maximum amount", "max_currency": "currency", "max_pct": "maximum %",
             "shares": "shares", "value": "amount", "cum_shares": "total shares", "cum_value": "total amount"}
    for h in hand:
        p = json.loads(h["parsed_json"])["p"]
        m, g = p.get("manual") or {}, p.get("programme") or {}
        flag = lambda kind, text: ingest._review(con, h["doc_id"], country, ticker, kind, text)
        if m.get("kind") in ("programme", "change"):
            for d, q in read:
                o = q.get("programme") or {}
                same = (o.get("announced_date") == g.get("announced_date") and (q.get("doc_type") == "programme" if m["kind"] == "programme" else d["doc_date"] == h["doc_date"]))
                if not same:
                    continue
                differ = [k for k in ("start_date", "end_date", "max_shares", "max_value", "max_currency", "max_pct") if g.get(k) is not None and o.get(k) is not None and g[k] != o[k]]
                if differ:
                    flag("HAND_DIFFERS", f"Your {KINDS[m['kind']].lower()} entered by hand and {said(d)} differ: " + "; ".join(f"{names[k]} {fmt(k, g[k])} by hand, {fmt(k, o[k])} in the filing" for k in differ)
                         + ". Both are kept; where both are dated the same day the filing's figure is the one in force. Edit or delete the hand entry, or mark this as checked.")
        elif m.get("kind") == "purchase":
            mine = p["transactions"][0]
            for d, q in read:
                for t in q.get("transactions") or []:
                    if t.get("trade_date") != mine["trade_date"]:
                        continue
                    if (t.get("venue") or "") == (mine.get("venue") or "") and (t.get("price_unit") or "") == (mine.get("price_unit") or ""):
                        differ = [k for k in ("shares", "value") if mine.get(k) is not None and t.get(k) is not None and abs(mine[k] - t[k]) > 0.005]
                        if differ:
                            flag("HAND_DIFFERS", f"Your purchase on {mine['trade_date']} entered by hand and {said(d)} differ: " + "; ".join(f"{names[k]} {fmt(k, mine[k])} by hand, {fmt(k, t[k])} in the filing" for k in differ)
                                 + ". Both are kept; the filing's figure is the one counted. Edit or delete the hand entry, or mark this as checked.")
                    else:
                        flag("HAND_TWICE", f"Your purchase on {mine['trade_date']} on {mine.get('venue')} entered by hand ({fmt('shares', mine['shares'])} shares), and {said(d)} reports buying that day on {t.get('venue') or 'a venue not stated'} "
                             f"({fmt('shares', t.get('shares'))} shares). Both are counted. If they are the same purchase, delete the hand entry.")
        elif m.get("kind") == "completion" and p.get("snapshots"):
            mine = p["snapshots"][0]
            for d, q in read:
                if (q.get("programme") or {}).get("announced_date") not in (g.get("announced_date"), None, ""):
                    continue
                for s in q.get("snapshots") or []:
                    if s.get("as_of") != mine["as_of"]:
                        continue
                    differ = [k for k in ("cum_shares", "cum_value") if mine.get(k) is not None and s.get(k) is not None and abs(mine[k] - s[k]) > 0.005]
                    if differ:
                        flag("HAND_DIFFERS", f"Your completion entered by hand and {said(d)} differ at {mine['as_of']}: " + "; ".join(f"{names[k]} {fmt(k, mine[k])} by hand, {fmt(k, s[k])} in the filing" for k in differ)
                             + ". Both are kept; the filing's figure is the one in force. Edit or delete the hand entry, or mark this as checked.")


# ---------- what the page shows ----------
def _row(r):
    f = json.loads(r["fields"])
    upd = r["kind"] == "update"
    day = (f.get("trade_date") or f.get("as_of") or f.get("programme")) if upd else f.get("announced_date") or f.get("change_date") or f.get("trade_date") or f.get("completed_on")
    return {"entry_id": r["entry_id"], "kind": r["kind"], "kind_label": UPDATED if upd else KINDS[r["kind"]], "country": r["country"], "ticker": r["ticker"], "date": day, "fields": f,
            "what": update_summary(f) if upd else summary(r["kind"], f), "source": r["source"], "note": r["note"], "status": r["status"], "doc_id": r["doc_id"], "created_at": r["created_at"],
            "updated_at": r["updated_at"], "deleted_at": r["deleted_at"], "delete_reason": r["delete_reason"]}


def entry(con, entry_id):
    r = con.execute("select * from hand_entries where entry_id=?", (int(entry_id),)).fetchone()
    return _row(r) if r else None


def listing(con, country=None, ticker=None):
    """Every entry made by hand, the deleted ones, and the history of changes, for the market and company chosen."""
    w, a = "", []
    if country and country != "ALL":
        w, a = w + " and country=?", a + [country]
    if ticker:
        w, a = w + " and ticker=?", a + [ticker]
    rows = [_row(r) for r in con.execute(f"select * from hand_entries where 1=1 {w} order by coalesce(updated_at, created_at) desc, entry_id desc", a)]
    for r in rows:
        r["review"] = [dict(x) for x in con.execute("select review_id, kind, detail from review where doc_id=? and status='OPEN'", (r["doc_id"],))] if r["doc_id"] else []
        if r["kind"] == "update":  # its questions name it, and sit on the filing it updates
            r["review"] = [dict(x) for x in con.execute("select review_id, kind, detail from review where status='OPEN' and country=? and ticker=? and detail like ?", (r["country"], r["ticker"], f"Update {r['entry_id']} (%"))]
        r["company"] = (con.execute("select company from companies where country=? and ticker=?", (r["country"], r["ticker"])).fetchone() or {"company": ""})["company"]
    ids = [r["entry_id"] for r in rows]
    log = [dict(x) for x in con.execute(f"select l.*, h.kind, h.country, h.ticker from hand_log l join hand_entries h on h.entry_id=l.entry_id where l.entry_id in ({','.join('?' * len(ids))}) order by l.log_id desc limit 500", ids)] if ids else []
    for x in log:
        x["changes"] = _changes(x)
    return {"entries": [r for r in rows if r["status"] == "ACTIVE"], "deleted": [r for r in rows if r["status"] != "ACTIVE"], "log": log}


def _changes(x):
    old, new = json.loads(x["old_fields"] or "{}"), json.loads(x["new_fields"] or "{}")
    if x["action"] != "EDITED":
        return ""
    if x.get("kind") == "update":
        return "; ".join(f"{k}: {old.get(k) if old.get(k) not in (None, '') else '–'} → {new.get(k) if new.get(k) not in (None, '') else '–'}" for k in ("value", "value_currency", "source", "note") if old.get(k) != new.get(k))
    return "; ".join(f"{k}: {old.get(k) if old.get(k) not in (None, '') else '–'} → {new.get(k) if new.get(k) not in (None, '') else '–'}" for k in dict.fromkeys([*old, *new]) if old.get(k) != new.get(k))


def choices(con, country, ticker):
    """For the form: the company's programmes to choose from, newest first, and the exchanges and currencies to choose from."""
    progs, companies = [], []
    if country:
        companies = [dict(r) for r in con.execute("select ticker, company from companies where country=? and (in_index=1 or source is not null) order by ticker", (country,))]
    if country and ticker:
        progs = [dict(r) for r in con.execute("""select prog_id, announced_date, start_date, end_date, status, max_shares, max_value, max_currency, max_pct from programmes
            where country=? and ticker=? and announced_date<>'' order by announced_date desc""", (country, ticker))]
    markets = countries.load()
    currencies = sorted({c["currency"] for c in markets if c.get("currency")} | {"USD", "EUR", "GBP", "AUD", "NZD", "HKD", "SGD", "CNY", "JPY", "CAD", "CHF"})
    venues = list(dict.fromkeys(c["exchange"] for c in markets if c.get("exchange")))
    return {"programmes": progs, "companies": companies, "currencies": currencies, "venues": venues, "types": TYPES, "treatments": TREATMENTS,
            "markets": [{"code": c["code"], "label": f"{c['exchange']} · {c['name']}", "currency": c.get("currency"), "exchange": c.get("exchange")} for c in markets]}


# ---------- Updated Manually: one figure read from a filing, changed by you (version 27) ----------
# The filing's reading is never changed. The update is kept with the entries made by hand (kind "update", in hand_entries and hand_log), with its
# source and reason, and is applied again after every rebuild, from the reading, so applying it twice gives the same result. A row read wrongly
# can be set aside: it leaves every figure, and comes back when the update is undone.
UPDATED = "Updated Manually"
UPD_TARGETS = {"programme": "Programme terms", "purchase": "Purchase", "total": "Running total"}
UPD_FIELDS = {
    "programme": {"buyback_type": ("Type", "text"), "start_date": ("Starts", "date"), "end_date": ("Ends", "date"), "max_shares": ("Maximum shares", "whole"),
                  "max_value": ("Maximum amount", "money"), "shares_on_issue": ("Shares on issue", "whole"), "treatment": ("Shares are", "treatment"),
                  "status": ("Status", "status"), "broker": ("Broker", "text")},
    "purchase": {"shares": ("Shares", "whole"), "value": ("Amount paid", "num"), "currency": ("Currency", "cur"), "price_avg": ("Average price", "num"),
                 "price_high": ("Highest price", "num"), "price_low": ("Lowest price", "num"), "set_aside": ("Set aside: not a buyback purchase", "aside")},
    "total": {"cum_shares": ("Total shares", "whole"), "cum_value": ("Total amount", "num"), "currency": ("Currency", "cur"), "set_aside": ("Set aside: not a running total", "aside")},
}
STATUSES = ["ACTIVE", "COMPLETED"]
UPD_REVIEWS = ("UPDATE_NOT_FOUND", "UPDATE_NOW_READ", "UPDATE_READ_CHANGED")


def _prog_row(con, country, ticker, announced):
    return con.execute("select * from programmes where country=? and ticker=? and announced_date=?", (country, ticker, announced or "")).fetchone()


def _target_row(con, prog_id, f):
    if f["target"] == "purchase":
        return con.execute("select rowid rid, * from transactions where prog_id=? and trade_date=? and coalesce(venue,'')=? and coalesce(price_unit,'')=?",
                           (prog_id, f["trade_date"], f.get("venue") or "", f.get("price_unit") or "")).fetchone()
    if f["target"] == "total":
        return con.execute("select rowid rid, * from snapshots where prog_id=? and as_of=?", (prog_id, f["as_of"])).fetchone()
    return con.execute("select rowid rid, * from programmes where prog_id=?", (prog_id,)).fetchone()


def _reading(con, doc_id):
    d = con.execute("select form, parsed_json from documents where doc_id=?", (doc_id,)).fetchone() if doc_id else None
    try:
        return json.loads(d["parsed_json"])["p"] if d and d["parsed_json"] else None
    except (ValueError, KeyError, TypeError):
        return None


def _read_tx(con, row):
    """The purchase as the filing's reading holds it, before any update."""
    p = _reading(con, row["doc_id"])
    for t in (p or {}).get("transactions") or []:
        if t.get("trade_date") == row["trade_date"] and (t.get("venue") or "") == (row["venue"] or "") and (t.get("price_unit") or "") == (row["price_unit"] or ""):
            return t
    return None


def _read_snap(con, row):
    """The running total as the filing's reading holds it. An ASX daily notice's 'before' total is dated again when it is stored (version 26),
    so where the dates differ it is the notice's first total."""
    p = _reading(con, row["doc_id"])
    snaps = (p or {}).get("snapshots") or []
    for s in snaps:
        if s.get("as_of") == row["as_of"]:
            return s
    if p and p.get("form") == "appendix_3c" and len(snaps) == 2:
        return snaps[0] if row["origin"] == "reported" else snaps[1]
    return None


def _same_value(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.005
    return str(a) == str(b)


def _show(kind, v, cur=None):
    if v is None or v == "":
        return "Not stated"
    if kind == "whole":
        return f"{v:,.0f}"
    if kind in ("num", "money"):
        return (f"{cur} " if cur else "") + (f"{v:,.2f}" if abs(v) >= 100 else f"{v:,.4f}".rstrip("0").rstrip("."))
    if kind == "aside":
        return "Set aside"
    return str(v)


def _upd_value(kind, raw, label, currency_in=None):
    raw = raw if raw is not None else ""
    if kind == "aside":
        return None, None
    if kind == "date":
        return _date(raw, label), None
    if kind == "whole":
        return _num(raw, label, True, whole=True), None
    if kind == "num":
        return _num(raw, label), None
    if kind == "money":
        v = _num(raw, label)
        return v, (_cur(currency_in, label, v is not None) if v is not None else None)
    if kind == "cur":
        return _cur(raw, label, True), None
    if kind == "treatment":
        t = str(raw or "").strip()
        if t and t not in TREATMENTS:
            raise ValueError("Shares are: choose Cancelled or Treasury, or leave it as Not stated.")
        return t or None, None
    if kind == "status":
        s = str(raw or "").strip().upper()
        if s not in STATUSES:
            raise ValueError("Status: choose ACTIVE or COMPLETED.")
        return s, None
    v = re.sub(r"\s+", " ", str(raw or "")).strip()
    return v or None, None


def clean_update(con, body, entry_id=None):
    """An update as it will be kept, or ValueError with a plain reason."""
    country = str(body.get("country") or "").strip().upper()
    if not countries.get(country):
        raise ValueError("Choose the exchange.")
    ticker = re.sub(r"[^A-Z0-9.]", "", str(body.get("ticker") or "").strip().upper())
    if not ticker:
        raise ValueError("Choose the company.")
    target = str(body.get("target") or "")
    if target not in UPD_FIELDS:
        raise ValueError("Choose what you are updating: Programme terms, Purchase or Running total.")
    announced = _date(body.get("programme"), "Programme", True)
    prog = _prog_row(con, country, ticker, announced)
    if not prog:
        raise ValueError(f"No programme announced {announced} is held for {ticker}.")
    field = str(body.get("field") or "")
    if field not in UPD_FIELDS[target]:
        raise ValueError("Choose the figure to update.")
    label, kind = UPD_FIELDS[target][field]
    source = re.sub(r"\s+", " ", str(body.get("source") or "")).strip()
    if len(source) < 3:
        raise ValueError("Source is required: the filing and page, a link, or where the right figure comes from.")
    reason = re.sub(r"\s+", " ", str(body.get("note") or "")).strip()
    if len(reason) < 3:
        raise ValueError("Reason is required, such as \"Digits transposed in the reading\".")
    f = {"target": target, "programme": announced, "field": field}
    if target == "purchase":
        f["trade_date"] = _date(body.get("trade_date"), "Purchase", True)
        f["venue"], f["price_unit"] = str(body.get("venue") or ""), str(body.get("price_unit") or "")
    elif target == "total":
        f["as_of"] = _date(body.get("as_of"), "Running total", True)
    row = _target_row(con, prog["prog_id"], f)
    old = con.execute("select * from hand_entries where entry_id=?", (int(entry_id),)).fetchone() if entry_id else None
    oldf = json.loads(old["fields"]) if old else {}
    same_place = old and all(oldf.get(k) == f.get(k) for k in ("target", "programme", "trade_date", "venue", "price_unit", "as_of", "field"))
    if not row and not same_place:
        raise ValueError({"purchase": f"No purchase on {f.get('trade_date')} is held for this programme.", "total": f"No running total at {f.get('as_of')} is held for this programme.",
                          "programme": "The programme isn't held."}[target])
    value, money_cur = _upd_value(kind, body.get("value"), label, body.get("value_currency"))
    if kind in ("whole",) and not value:
        raise ValueError(f"{label} must be more than 0. To leave a row out, choose Set aside.")
    if target == "purchase" and field in ("price_high", "price_low") and value is not None and row:
        hi, lo = (value, row["price_low"]) if field == "price_high" else (row["price_high"], value)
        if hi is not None and lo is not None and lo > hi:
            raise ValueError("Lowest price is above the highest price.")
    f["value"] = value
    if money_cur:
        f["value_currency"] = money_cur
    if same_place:
        f["was"], f["doc_id"], f["currency_shown"] = oldf.get("was"), oldf.get("doc_id"), oldf.get("currency_shown")
        if "row_read" in oldf:
            f["row_read"] = oldf["row_read"]
    else:
        f["was"] = None if kind == "aside" else row[field if field != "max_value" else "max_value"]
        f["doc_id"] = row["doc_id"] if target != "programme" else (row["terms_doc"] or row["source_doc"])
        f["currency_shown"] = row["currency"] if target != "programme" else row["max_currency"]
        if target == "total":
            f["row_read"] = {"cum_shares": row["cum_shares"], "cum_value": row["cum_value"]}
        if kind != "aside" and _same_value(f["was"], value) and (field != "max_value" or (money_cur or row["max_currency"]) == row["max_currency"]):
            raise ValueError(f"{label} is already {_show(kind, value, f['currency_shown'])}. Nothing to update.")
    dup = con.execute("""select entry_id from hand_entries where status='ACTIVE' and kind='update' and country=? and ticker=? and entry_id is not ?
        and json_extract(fields,'$.target')=? and json_extract(fields,'$.programme')=? and coalesce(json_extract(fields,'$.trade_date'),'')=? and coalesce(json_extract(fields,'$.venue'),'')=?
        and coalesce(json_extract(fields,'$.price_unit'),'')=? and coalesce(json_extract(fields,'$.as_of'),'')=? and (json_extract(fields,'$.field')=? or json_extract(fields,'$.field')='set_aside' or ?='set_aside')""",
                      (country, ticker, int(entry_id) if entry_id else None, target, announced, f.get("trade_date") or "", f.get("venue") or "", f.get("price_unit") or "", f.get("as_of") or "", field, field)).fetchone()
    if dup:
        raise ValueError(f"This figure already has an update (entry {dup['entry_id']}). Edit that entry instead.")
    return {"kind": "update", "country": country, "ticker": ticker, "source": source, "note": reason, "fields": f}


def update_summary(f):
    target, field = f.get("target"), f.get("field")
    label, kind = UPD_FIELDS.get(target, {}).get(field, (field, "text"))
    where = {"programme": f"Programme {f.get('programme')}", "purchase": f"Purchase {f.get('trade_date')}" + (f" on {f['venue']}" if f.get("venue") else ""),
             "total": f"Running total {f.get('as_of')}"}.get(target, "")
    if kind == "aside":
        return f"{where}: {label}"
    cur = f.get("value_currency") or f.get("currency_shown") if kind in ("num", "money") else None
    return f"{where} · {label}: {_show(kind, f.get('was'), cur)} → {_show(kind, f.get('value'), cur)}"


def save_update(con, body):
    entry_id = body.get("entry_id")
    e = clean_update(con, body, entry_id)
    if not entry_id:
        cur = con.execute("insert into hand_entries(kind,country,ticker,fields,source,note,status,created_at,updated_at) values('update',?,?,?,?,?,'ACTIVE',?,?)",
                          (e["country"], e["ticker"], json.dumps(e["fields"]), e["source"], e["note"], db.now(), db.now()))
        _log(con, cur.lastrowid, "ADDED", new=_kept(e))
        _settle(con, (e["country"], e["ticker"]))
        return entry(con, cur.lastrowid)
    old = con.execute("select * from hand_entries where entry_id=? and status='ACTIVE'", (int(entry_id),)).fetchone()
    if not old or old["kind"] != "update":
        raise ValueError("That update isn't there any more, or was undone.")
    was = {"kind": "update", "country": old["country"], "ticker": old["ticker"], "source": old["source"], "note": old["note"], **json.loads(old["fields"])}
    if was == _kept(e):
        raise ValueError("Nothing was changed.")
    con.execute("update hand_entries set country=?, ticker=?, fields=?, source=?, note=?, updated_at=? where entry_id=?",
                (e["country"], e["ticker"], json.dumps(e["fields"]), e["source"], e["note"], db.now(), old["entry_id"]))
    _log(con, old["entry_id"], "EDITED", old=was, new=_kept(e))
    _settle(con, (e["country"], e["ticker"]), (old["country"], old["ticker"]))
    return entry(con, old["entry_id"])


def _active_updates(con, country, ticker):
    return [(r["entry_id"], json.loads(r["fields"]), r) for r in con.execute(
        "select * from hand_entries where status='ACTIVE' and kind='update' and country=? and ticker=? order by entry_id", (country, ticker))]


def has_updates(con, country, ticker):
    return bool(con.execute("select 1 from hand_entries where status='ACTIVE' and kind='update' and country=? and ticker=? limit 1", (country, ticker)).fetchone())


def _sum_total(con, tx):
    """The closing total worked out for the day of this purchase from the same notice ('before' + the day), if there is one."""
    return con.execute("select rowid rid, * from snapshots where prog_id=? and as_of=? and doc_id=? and origin='sum'", (tx["prog_id"], tx["trade_date"], tx["doc_id"])).fetchone()


def apply_updates(con, country, ticker, rebuilt=True):
    """Put every update in force on the figures just stored. Run at the end of a company's rebuild (rebuilt=True), and after a single filing is read.
    Each one is applied from the filing's reading, so applying it again changes nothing. Figures worked out from an updated one are worked out again
    and stay Calculated. Questions go to review: the row is gone, the filing now reads your value, or it now reads something else."""
    ups = _active_updates(con, country, ticker)
    if rebuilt:
        con.execute(f"delete from review where country=? and ticker=? and status='OPEN' and kind in ({','.join('?' * len(UPD_REVIEWS))})", (country, ticker, *UPD_REVIEWS))
    for entry_id, f, r in ups:
        label, kind = UPD_FIELDS.get(f["target"], {}).get(f["field"], (f["field"], "text"))
        flag = lambda k, text: ingest._review(con, f.get("doc_id"), country, ticker, k, f"Update {entry_id} ({update_summary(f)}): {text}")
        prog = _prog_row(con, country, ticker, f["programme"])
        row = _target_row(con, prog["prog_id"], f) if prog else None
        if not row:
            if not rebuilt:  # outside a rebuild a row set aside is already out; the question is asked at the next rebuild
                continue
            flag("UPDATE_NOT_FOUND", "the figure it updates is no longer held (the filing may have been removed or moved). The update is kept and not applied. Undo it, or add the filing back.")
            continue
        cur_shown = f.get("value_currency") or f.get("currency_shown")
        if f["target"] == "purchase":
            read = _read_tx(con, row) or {}
            day_total = _sum_total(con, row)
            read_total = _read_snap(con, day_total) if day_total else None
            if f["field"] == "set_aside":
                con.execute("delete from transactions where rowid=?", (row["rid"],))
                new = None
            else:
                rv = read.get(f["field"]) if read else row[f["field"]]
                if rebuilt and read:
                    if _same_value(rv, f["value"]):
                        flag("UPDATE_NOW_READ", f"the filing now reads {_show(kind, rv, cur_shown)}, the same as your update. You can undo the update.")
                    elif not _same_value(rv, f["was"]):
                        flag("UPDATE_READ_CHANGED", f"when you made the update the filing read {_show(kind, f['was'], cur_shown)}; it now reads {_show(kind, rv, cur_shown)}. Your value stays in force until you look.")
                new = {k: row[k] for k in ("shares", "value", "currency", "price_avg", "price_high", "price_low", "value_origin")}
                new[f["field"]] = f["value"]
                if f["field"] in ("shares", "price_avg") and new["value_origin"] in ("product", "hand_product") and new["shares"] and new["price_avg"] is not None:
                    new["value"] = new["shares"] * new["price_avg"]  # the amount was worked out from these: worked out again, still Calculated
                if f["field"] == "value":
                    new["value_origin"] = "updated"  # the amount itself is the one you gave
                if f["field"] in ("shares", "value") and new["value_origin"] in ("reported", "sum", "updated") and new["value"] is not None and new["shares"]:
                    new["price_avg"] = new["value"] / new["shares"]  # the average was worked out from these: worked out again, still Calculated
                con.execute("update transactions set shares=?, value=?, currency=?, price_avg=?, price_high=?, price_low=?, value_origin=? where rowid=?",
                            (new["shares"], new["value"], new["currency"], new["price_avg"], new["price_high"], new["price_low"], new["value_origin"], row["rid"]))
            if day_total and read_total and read and (day_total["currency"] or "") == (row["currency"] or "") and not any(
                    e2 for _, f2, e2 in ups if f2["target"] == "total" and f2["programme"] == f["programme"] and f2.get("as_of") == row["trade_date"]):
                ds = (new["shares"] if new else 0) - (read.get("shares") or 0)
                dv = None if read_total.get("cum_value") is None or (new and new["value"] is None) or read.get("value") is None else ((new["value"] if new else 0) - read["value"])
                what = "set aside" if not new else f"{label.lower()} {_show(kind, f['was'], cur_shown)} updated to {_show(kind, f['value'], cur_shown)}"
                con.execute("update snapshots set cum_shares=?, cum_value=?, working=? where rowid=?",
                            (read_total["cum_shares"] + ds, None if dv is None else read_total["cum_value"] + dv,
                             (read_total.get("working") or "Worked out from the notice") + f"; the day's purchase {what} (Updated Manually, update {entry_id})", day_total["rid"]))
        elif f["target"] == "total":
            if f["field"] == "set_aside":
                con.execute("delete from snapshots where rowid=?", (row["rid"],))
                continue
            read = _read_snap(con, row)
            rv = read.get(f["field"]) if read else row[f["field"]]
            if rebuilt and read:
                if _same_value(rv, f["value"]):
                    flag("UPDATE_NOW_READ", f"the filing now reads {_show(kind, rv, cur_shown)}, the same as your update. You can undo the update.")
                elif not _same_value(rv, f["was"]):
                    flag("UPDATE_READ_CHANGED", f"when you made the update the filing read {_show(kind, f['was'], cur_shown)}; it now reads {_show(kind, rv, cur_shown)}. Your value stays in force until you look.")
            said = f"{UPDATED} (update {entry_id}): {label.lower()} as read {_show(kind, f['was'], cur_shown)}. Source: {r['source']}. Reason: {r['note']}"
            working = row["working"] if row["origin"] == "updated" else None
            working = said if not working else working if said in working else f"{working}; {said}"
            con.execute(f"update snapshots set {f['field']}=?, origin='updated', working=? where rowid=?", (f["value"], working, row["rid"]))
        else:
            if rebuilt:
                rv = row[f["field"]]
                if _same_value(rv, f["value"]) and (f["field"] != "max_value" or not f.get("value_currency") or f["value_currency"] == row["max_currency"]):
                    flag("UPDATE_NOW_READ", f"the filings now give {_show(kind, rv, row['max_currency'] if kind == 'money' else None)}, the same as your update. You can undo the update.")
                elif not _same_value(rv, f["was"]):
                    flag("UPDATE_READ_CHANGED", f"when you made the update the filings gave {_show(kind, f['was'], f.get('currency_shown'))}; they now give {_show(kind, rv, row['max_currency'] if kind == 'money' else None)}. Your value stays in force until you look.")
            con.execute(f"update programmes set {f['field']}=? where prog_id=?", (f["value"], row["prog_id"]))
            if f["field"] == "max_value" and f.get("value_currency"):
                con.execute("update programmes set max_currency=? where prog_id=?", (f["value_currency"], row["prog_id"]))


def marks(con, country=None):
    """Where each update shows: {"tx": {(prog_id, trade_date, venue, price_unit): {field: text}}, "snap": {(prog_id, as_of): {field: text}},
    "prog": {prog_id: {field: text}}, "aside": [...], "count": {prog_id: n}}. A figure worked out again from an updated one is listed under the
    field "derived" with its own text."""
    out = {"tx": {}, "snap": {}, "prog": {}, "count": {}}
    args = [] if country in (None, "", "ALL") else [country]
    for r in con.execute("select * from hand_entries where status='ACTIVE' and kind='update'" + (" and country=?" if args else "") + " order by entry_id", args):
        f = json.loads(r["fields"])
        prog = _prog_row(con, r["country"], r["ticker"], f.get("programme"))
        if not prog:
            continue
        label, kind = UPD_FIELDS.get(f["target"], {}).get(f["field"], (f["field"], "text"))
        cur = f.get("value_currency") or f.get("currency_shown") if kind in ("num", "money") else None
        text = (f"{UPDATED} on {str(r['updated_at'] or r['created_at'])[:10]} (update {r['entry_id']}). As read: {_show(kind, f.get('was'), cur)}. "
                f"Source: {r['source']}. Reason: {r['note']}")
        pid = prog["prog_id"]
        out["count"][pid] = out["count"].get(pid, 0) + 1
        if f["target"] == "programme":
            out["prog"].setdefault(pid, {})[f["field"]] = text
            if f["field"] == "max_value" and f.get("value_currency"):
                out["prog"][pid]["max_currency"] = text
        elif f["target"] == "total":
            out["snap"].setdefault((pid, f["as_of"]), {})[f["field"]] = text
        elif f["field"] != "set_aside":
            key = (pid, f["trade_date"], f.get("venue") or "", f.get("price_unit") or "")
            out["tx"].setdefault(key, {})[f["field"]] = text
            if f["field"] in ("shares", "value", "price_avg"):
                out["tx"][key]["derived"] = f"Worked out again from a figure {UPDATED} (update {r['entry_id']}): an amount or average that is shares x average or amount / shares"
                out["snap"].setdefault((pid, f["trade_date"]), {}).setdefault("derived", f"The day's closing total worked out again from a purchase {UPDATED} (update {r['entry_id']})")
        else:
            out["snap"].setdefault((pid, f["trade_date"]), {}).setdefault("derived", f"The day's closing total worked out again: a purchase was set aside (update {r['entry_id']})")
    return out


def update_choices(con, country, ticker, programme, target, row_key, field):
    """For the Update form: the company's programmes, the purchases and running totals of the one chosen, the figures that can be updated,
    and the figure as it is held now, with the filing, page and words it was read from."""
    out = {"targets": [[k, v] for k, v in UPD_TARGETS.items()], "fields": {t: [[k, v[0]] for k, v in d.items()] for t, d in UPD_FIELDS.items()}, "statuses": STATUSES,
           "purchases": [], "totals": [], "asread": None}
    prog = _prog_row(con, country, ticker, programme) if country and ticker and programme else None
    if not prog:
        return out
    out["purchases"] = [{"key": f"{t['trade_date']}|{t['venue'] or ''}|{t['price_unit'] or ''}", "label": f"{t['trade_date']}" + (f" · {t['venue']}" if t["venue"] else "") + f" · {t['shares']:,.0f} shares"
                         + (f" · {t['currency']} {t['value']:,.2f}" if t["value"] is not None else "")} for t in con.execute("select * from transactions where prog_id=? order by trade_date desc, venue", (prog["prog_id"],))]
    out["totals"] = [{"key": s["as_of"], "label": f"{s['as_of']} · {s['cum_shares']:,.0f} shares" + (f" · {s['currency']} {s['cum_value']:,.2f}" if s["cum_value"] is not None else "")
                      + (" · Calculated" if s["origin"] not in ("reported", "rounded", "hand") else "")} for s in con.execute("select * from snapshots where prog_id=? order by as_of desc", (prog["prog_id"],))]
    if target not in UPD_FIELDS or field not in UPD_FIELDS[target]:
        return out
    f = {"target": target, "programme": programme}
    if target == "purchase":
        parts = (row_key or "").split("|")
        if len(parts) != 3:
            return out
        f.update(trade_date=parts[0], venue=parts[1], price_unit=parts[2])
    elif target == "total":
        if not row_key:
            return out
        f["as_of"] = row_key
    row = _target_row(con, prog["prog_id"], f)
    if not row:
        return out
    label, kind = UPD_FIELDS[target][field]
    doc_id = row["doc_id"] if target != "programme" else (row["terms_doc"] or row["source_doc"])
    ev_key = {"purchase": f"tx|{f.get('trade_date')}|{f.get('venue') or ''}", "total": f"snap|{f.get('as_of')}", "programme": "prog"}[target]
    ev_field = {"cum_shares": "cum_shares", "cum_value": "cum_value", "value": "value", "shares": "shares", "price_avg": "price_avg", "price_high": "price_high", "price_low": "price_low"}.get(field, field)
    ev = con.execute("select page, text, context from evidence where doc_id=? and key=? and field=? limit 1", (doc_id, ev_key, ev_field)).fetchone() if doc_id else None
    d = con.execute("select doc_id, file_name, heading, doc_date, form, source_url from documents where doc_id=?", (doc_id,)).fetchone() if doc_id else None
    basis = None
    if target == "purchase" and field == "value":
        basis = "Reported" if row["value_origin"] == "reported" else "Entered by hand" if row["value_origin"] == "hand" else UPDATED if row["value_origin"] == "updated" else "Calculated"
    elif target == "total":
        basis = "Reported" if row["origin"] in ("reported", "rounded") else "Entered by hand" if row["origin"] == "hand" else UPDATED if row["origin"] == "updated" else "Calculated"
    held = con.execute("""select entry_id from hand_entries where status='ACTIVE' and kind='update' and country=? and ticker=? and json_extract(fields,'$.target')=? and json_extract(fields,'$.programme')=?
        and coalesce(json_extract(fields,'$.trade_date'),'')=? and coalesce(json_extract(fields,'$.venue'),'')=? and coalesce(json_extract(fields,'$.price_unit'),'')=? and coalesce(json_extract(fields,'$.as_of'),'')=?
        and json_extract(fields,'$.field')=?""", (country, ticker, target, programme, f.get("trade_date") or "", f.get("venue") or "", f.get("price_unit") or "", f.get("as_of") or "", field)).fetchone()
    value = None if kind == "aside" else row[field]
    cur = (row["currency"] if target != "programme" else row["max_currency"]) if kind in ("num", "money") else None
    out["asread"] = {"value": value, "shown": _show(kind, value, cur), "kind": kind, "currency": cur, "basis": basis, "doc_id": doc_id, "ev_key": ev_key,
                     "file_name": d["heading"] or d["file_name"] if d else None, "doc_date": d["doc_date"] if d else None, "manual": bool(d and d["form"] == "manual"),
                     "page": ev["page"] if ev else None, "text": ev["text"] if ev else None, "context": ev["context"] if ev else None, "already": held["entry_id"] if held else None,
                     "trade_date": f.get("trade_date"), "venue": f.get("venue"), "price_unit": f.get("price_unit"), "as_of": f.get("as_of")}
    return out


def patch_reading(con_updates, doc_id, p):
    """For the Tracker: the reading of one filing with the updates that concern it applied. Returns the patched reading and the texts of the
    updates used, or (p, []) when none concern it. con_updates is the list from tracker_updates(con)."""
    if not p or not con_updates:
        return p, []
    used, p2 = [], None
    for u in con_updates:
        f = u["fields"]
        if f["target"] == "programme":
            g = (p.get("programme") or {})
            if g.get("announced_date") != f["programme"] or u["ticker"] != (p.get("ticker") or u["doc_ticker"].get(doc_id)):
                continue
        elif f.get("doc_id") != doc_id:
            continue
        p2 = p2 or json.loads(json.dumps(p))
        if f["target"] == "programme":  # every notice of the programme carries the term, so the plan uses it; only the notice it came from is marked
            p2.setdefault("programme", {})[f["field"]] = f["value"]
            if f["field"] == "max_value" and f.get("value_currency"):
                p2["programme"]["max_currency"] = f["value_currency"]
            if f.get("doc_id") == doc_id:
                used.append(u["text"])
        elif f["target"] == "purchase":
            for t in list(p2.get("transactions") or []):
                if t.get("trade_date") == f["trade_date"] and (t.get("venue") or "") == (f.get("venue") or "") and (t.get("price_unit") or "") == (f.get("price_unit") or ""):
                    if f["field"] == "set_aside":
                        p2["transactions"].remove(t)
                    else:
                        t[f["field"]] = f["value"]
                        if f["field"] == "value":
                            t["value_origin"] = "updated"
                    used.append(u["text"])
        else:
            snaps = p2.get("snapshots") or []
            rr = f.get("row_read") or {}
            hit = next((s for s in snaps if s.get("as_of") == f["as_of"]), None) or next((s for s in snaps if s.get("cum_shares") == rr.get("cum_shares") and _same_value(s.get("cum_value"), rr.get("cum_value"))), None)
            if hit:
                if f["field"] == "set_aside":
                    snaps.remove(hit)
                else:
                    hit[f["field"]] = f["value"]
                    hit["origin"] = "updated"
                used.append(u["text"])
    return (p2, used) if p2 is not None else (p, [])


def tracker_updates(con):
    """Every update in force, in the shape patch_reading uses."""
    out = []
    tickers = {r["doc_id"]: r["ticker"] for r in con.execute("select doc_id, ticker from documents")}
    for r in con.execute("select * from hand_entries where status='ACTIVE' and kind='update' order by entry_id"):
        f = json.loads(r["fields"])
        out.append({"fields": f, "ticker": r["ticker"], "doc_ticker": tickers, "text": f"{UPDATED} (update {r['entry_id']}): {update_summary(f)}. Source: {r['source']}. Reason: {r['note']}"})
    return out
