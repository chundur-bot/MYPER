"""Turns stored notices into period figures. Currencies are never added together.

A programme's purchases come from one of two places. Running totals in notices are preferred, because one notice can
cover many days. Daily rows are the fallback. Totals held before the period are an opening balance, not period buying.
"""
import json
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

import threading

from . import countries, db, periods

_ONLY = threading.local()  # the one company the page asked for, if any; set for a request by the server


def only_ticker(ticker=""):
    _ONLY.ticker = str(ticker or "").strip().upper()


ALL_FROM, ALL_TO = "1900-01-01", "2999-12-31"  # no date limit: each programme's whole buying


def amounts_text(amounts):
    """Amounts as reported, for Excel and CSV: 'USD 998,000,000.00'."""
    return "; ".join(f"{c} {v:,.2f}" for c, v in sorted((amounts or {}).items()))


def _market(country, alias=""):
    return ("", ()) if country in (None, "", "ALL") else (f" and {alias}country=?", (country,))


def _where(country, alias=""):
    """The market chosen, and the one company chosen if there is one."""
    w, a = _market(country, alias)
    ticker = getattr(_ONLY, "ticker", "")
    return (w + f" and {alias}ticker=?", (*a, ticker)) if ticker else (w, a)


def hand_sources(con):
    """{doc_id: source} for every entry made by hand, so each of its figures can carry the mark "Entered by hand" and say where it came from."""
    return {r["doc_id"]: r["source"] for r in con.execute("select doc_id, source from hand_entries where status='ACTIVE' and doc_id is not null")}


HAND = "Entered by hand"
UPDATED = "Updated Manually"  # a figure read from a filing and changed by you on Add by hand (version 27)


def _combine(items):
    """Label for a total of several figures. One figure keeps its own label; several are added, so they are calculated."""
    items = [i for i in items if i]
    if not items:
        return None, ""
    if len(items) == 1:
        return items[0]
    return "Calculated", " + ".join(f"({w})" if " " in w else w for _, w in items)


def _provenance(p, events, start, end, cur):
    """(basis, working) for one programme's amount in one currency. Reported only if a notice states that very figure."""
    mine = [e for e in events if (e["currency"] or cur) == cur and e["value"] is not None]
    if not mine:
        return None
    if str(mine[-1]["key"]).startswith("snap|"):
        snaps = [s for s in p["snaps"] if s["cum_value"] is not None and s["as_of"] <= end and (s["currency"] or cur) == cur]
        last = snaps[-1]
        base = next((s for s in reversed(snaps) if s["as_of"] < start), None)
        if base:
            return "Calculated", f"{cur} {last['cum_value']:,.2f} total at {last['as_of']} - {cur} {base['cum_value']:,.2f} total at {base['as_of']}"
        if last.get("origin") == "reported":
            return "Reported", f"{cur} {last['cum_value']:,.2f}, the running total in the notice of {last['as_of']}"
        if last.get("origin") == "rounded":
            return "Reported", f"{last.get('working')}; latest notice {last['as_of']}"
        if last.get("origin") == "hand":
            return HAND, f"{cur} {last['cum_value']:,.2f}, the final total entered by hand at {last['as_of']}"
        if last.get("origin") == "updated":
            return UPDATED, f"{cur} {last['cum_value']:,.2f} at {last['as_of']}. {last.get('working') or ''}"
        return "Calculated", last.get("working") or "Worked out from the notice"
    txs = [e for e in mine]
    if len(txs) == 1 and txs[0].get("origin") == "reported":
        return "Reported", f"{cur} {txs[0]['value']:,.2f}, the amount in the notice of {txs[0]['date']}"
    if len(txs) == 1 and txs[0].get("origin") == "hand":
        return HAND, f"{cur} {txs[0]['value']:,.2f}, the amount entered by hand for {txs[0]['date']}"
    if len(txs) == 1 and txs[0].get("origin") == "updated":
        return UPDATED, f"{cur} {txs[0]['value']:,.2f}, the amount for {txs[0]['date']}, Updated Manually"
    how = "shares x average price" if all(e.get("origin") == "product" for e in txs) else "amounts in the notices"
    return "Calculated", (f"{how} on {txs[0]['date']}" if len(txs) == 1 else f"Sum of {len(txs)} purchase rows, using {how}")


def programme_events(con, country=None):
    """Per programme: the dated purchases and how they were derived."""
    w, a = _where(country, "p.")
    progs = db.rows(con.execute(f"""select p.*, c.company, c.sector, c.in_index from programmes p left join companies c on c.country=p.country and c.ticker=p.ticker where 1=1 {w}""", a))
    if not progs:
        return []
    snaps, txs = defaultdict(list), defaultdict(list)
    # purchases waiting for a programme document count nowhere until linked; a running total of shares with no amount is listed but can't give the amounts
    for s in con.execute("select * from snapshots where coalesce(waiting,0)=0 and cum_value is not null order by as_of"):
        snaps[s["prog_id"]].append(dict(s))
    for t in con.execute("select * from transactions where coalesce(waiting,0)=0 order by trade_date"):
        txs[t["prog_id"]].append(dict(t))
    for p in progs:
        pid = p["prog_id"]
        from_tx = [{"date": t["trade_date"], "shares": t["shares"] or 0, "value": t["value"], "currency": t["currency"], "doc_id": t["doc_id"], "key": f"tx|{t['trade_date']}|{t['venue']}", "origin": t["value_origin"]} for t in txs[pid]]
        from_snap, opening = [], None
        prior = None
        for s in snaps[pid]:
            if prior is None:
                opening = s
            else:
                value = None if s["cum_value"] is None or prior["cum_value"] is None else s["cum_value"] - prior["cum_value"]
                if (s["cum_shares"] or 0) - (prior["cum_shares"] or 0) > 0:
                    from_snap.append({"date": s["as_of"], "shares": s["cum_shares"] - prior["cum_shares"], "value": value, "currency": s["currency"], "doc_id": s["doc_id"], "key": f"snap|{s['as_of']}"})
            prior = s
        started = p["start_date"] or p["announced_date"]
        # The first total held counts as buying only if the programme began inside the year being tracked; it is dated when the notice says, so the split by month is approximate.
        p["opening"] = opening
        p["opening_as_of"] = opening["as_of"] if opening else None
        p["first_total_buying"] = None
        if opening and opening["cum_shares"]:
            p["first_total_buying"] = {"date": opening["as_of"], "shares": opening["cum_shares"], "value": opening["cum_value"], "currency": opening["currency"], "doc_id": opening["doc_id"], "key": f"snap|{opening['as_of']}", "from_opening": True, "started": started}
        use_snap = bool(snaps[pid]) and (sum(e["shares"] for e in from_snap) + (opening["cum_shares"] or 0 if opening else 0)) >= sum(e["shares"] for e in from_tx)
        p["events"] = from_snap if use_snap else from_tx
        p["tx_events"] = from_tx
        p["snaps"] = snaps[pid]
        p["method"] = "Running totals" if use_snap else ("Daily notices" if from_tx else "Terms only")
        p["last_total"] = snaps[pid][-1] if snaps[pid] else None
    return progs


def _in_period(p, start, end):
    """Rows bought in the period for one programme, and whether the period is fully covered."""
    events = [e for e in p["events"] if start <= e["date"] <= end]
    started = p["start_date"] or p["announced_date"] or ""
    complete = p["method"] != "Daily notices"
    note = ""
    first = p["first_total_buying"]
    if p["method"] == "Running totals" and first and start <= first["date"] <= end:
        if start == ALL_FROM or (started and started >= start):  # with no date limit, a running total since the programme began is the whole of it
            events = [first] + events
        elif started:
            complete = False
            note = f"The earliest notice held is {first['date']}. Add one from just before {start} to count buying before that date."
        else:
            complete = False
            note = "The programme's start date is unknown, so the first running total was left out."
    elif p["method"] == "Daily notices":
        note = "Built from daily notices only, so days without a saved notice are missing."
    if not complete and p["method"] == "Running totals":  # with no usable opening balance, the daily rows held are the better partial figure
        daily = [e for e in p["tx_events"] if start <= e["date"] <= end]
        if sum(e["shares"] for e in daily) > sum(e["shares"] for e in events):
            events = daily
    return events, complete, note


def _cancelled(filed):
    """Shares cancelled, added up from counts filings state. filed is [(form, date, shares, doc_id)]."""
    if not filed:
        return {"cancelled_shares": None, "cancelled_basis": None, "cancelled_working": "", "cancelled_docs": []}
    return {"cancelled_shares": sum(x[2] for x in filed), "cancelled_basis": "Calculated", "cancelled_working": f"Sum of counts from {filed[0][0]}: " + " + ".join(f"{x[2]:,.0f} on {x[1]}" for x in filed),
            "cancelled_docs": sorted({x[3] for x in filed})}


def _average(ev, home):
    """Total paid / total shares for one currency. Blank if any buying lacks its amount or shares, or amounts are in more than one currency."""
    bought = [e for e in ev if e["shares"] or e["value"] is not None]
    currencies = {e["currency"] or home for e in bought}
    if not bought or len(currencies) != 1 or any(e["value"] is None or not e["shares"] for e in bought):
        return {"avg_price": None, "avg_currency": None, "avg_basis": None, "avg_working": ""}
    paid, shares, cur = sum(e["value"] for e in bought), sum(e["shares"] for e in bought), currencies.pop()
    return {"avg_price": paid / shares, "avg_currency": cur, "avg_basis": "Calculated", "avg_working": f"{cur} {paid:,.2f} paid / {shares:,.0f} shares"}


def programme_rows(con, country, start, end):
    out = []
    links = {r["doc_id"]: r["source_url"] for r in con.execute("select doc_id, source_url from documents where source_url is not null")}
    cessed, counted = defaultdict(list), defaultdict(list)
    for e in con.execute("select prog_id, ceased_on, shares, doc_id from cessations where is_buyback=1 and prog_id is not null and shares is not null and ceased_on between ? and ? order by ceased_on", (start, end)):
        cessed[e["prog_id"]].append(("Appendix 3H", e["ceased_on"], e["shares"], e["doc_id"]))
    for e in con.execute("select prog_id, as_of, shares, doc_id from cancellations where kind='Cancelled' and basis='Reported count' and shares is not null and as_of between ? and ? order by as_of", (start, end)):
        counted[e["prog_id"]].append(("the notices", e["as_of"], e["shares"], e["doc_id"]))
    hand = hand_sources(con)
    from . import hand as hand_mod
    upd = hand_mod.marks(con, country)
    for p in programme_events(con, country):
        ev, complete, note = _in_period(p, start, end)
        by_cur = defaultdict(lambda: {"shares": 0, "value": None})
        for e in ev:
            b = by_cur[e["currency"] or countries.get(p["country"])["currency"]]
            b["shares"] += e["shares"] or 0
            if e["value"] is not None:
                b["value"] = (b["value"] or 0) + e["value"]
        row = {k: p[k] for k in ("prog_id", "country", "ticker", "company", "sector", "in_index", "announced_date", "buyback_type", "start_date", "end_date", "max_shares", "max_value", "max_currency", "shares_on_issue", "status", "method", "source_doc", "treatment", "treatment_text", "treatment_doc", "end_note", "size_note", "broker", "max_pct", "intended_shares", "terms_doc", "status_doc")}
        # what was entered by hand: the announcement, the terms in force, or the completion, each with its source
        row["hand_announced"], row["hand_terms"], row["hand_status"] = hand.get(p["source_doc"]), hand.get(p["terms_doc"]), hand.get(p["status_doc"])
        row["hand_treatment"] = hand.get(p["treatment_doc"])
        row["hand_purchases"] = sum(1 for e in p["tx_events"] if e["doc_id"] in hand)
        row["updated"], row["updated_count"] = upd["prog"].get(p["prog_id"], {}), upd["count"].get(p["prog_id"], 0)
        row["hand_text"] = "; ".join(x for x in (f"Announcement (source: {row['hand_announced']})" if row["hand_announced"] else "", f"Terms in force (source: {row['hand_terms']})" if row["hand_terms"] else "",
                                                 f"Completion (source: {row['hand_status']})" if row["hand_status"] else "", f"{row['hand_purchases']} purchase(s)" if row["hand_purchases"] else "",
                                                 f"{row['updated_count']} figure(s) Updated Manually" if row["updated_count"] else "") if x)
        row["status_date"] = (con.execute("select doc_date from documents where doc_id=?", (p["status_doc"],)).fetchone() or [None])[0] if p["status_doc"] and p["status"] == "COMPLETED" else None
        home = countries.get(p["country"])["currency"]
        row["shares"] = sum(b["shares"] for b in by_cur.values())
        row["by_currency"] = {c: b["value"] for c, b in by_cur.items() if b["value"] is not None}
        row["value"] = (by_cur[home]["value"] if home in by_cur else None)
        row["amounts"] = row["by_currency"]
        row["amounts_text"] = amounts_text(row["amounts"])
        row["order_value"] = max(row["amounts"].values(), default=None)  # only to put larger buyers first; never added across currencies
        row["provenance"] = {c: _provenance(p, ev, start, end, c) for c in row["amounts"]}
        row["amount_basis"], row["amount_working"] = _combine(list(row["provenance"].values())) if row["provenance"] else (None, "")
        row["other_currency"] = {c: v for c, v in row["by_currency"].items() if c != home}
        row["currency"] = home
        row.update(_cancelled(cessed.get(p["prog_id"]) or counted.get(p["prog_id"])))  # one or the other, so the same shares are never counted twice
        row.update(_average(ev, home))
        row["complete"], row["note"] = complete, note
        row["last_date"] = max((e["date"] for e in p["events"]), default=None)
        row["last_doc"] = ev[-1]["doc_id"] if ev else (p["last_total"]["doc_id"] if p["last_total"] else p["source_doc"])
        row["last_key"] = ev[-1]["key"] if ev else "prog"
        row["source_url"] = links.get(row["last_doc"], "")
        if p["last_total"] and p["last_total"]["cum_value"] is not None:
            row["programme_spent"], row["programme_spent_currency"] = p["last_total"]["cum_value"], p["last_total"]["currency"]
        else:
            row["programme_spent"], row["programme_spent_currency"] = (sum(e["value"] or 0 for e in p["events"]) or None), home
        same = row["max_value"] and row["programme_spent"] is not None and row["max_currency"] == row["programme_spent_currency"]
        row["used_pct"] = 100 * row["programme_spent"] / row["max_value"] if same else None
        # read from daily notices only: the announcement that gives the type, dates and size hasn't been read
        row["document_needed"] = bool(row["announced_date"]) and not any(row.get(k) for k in ("buyback_type", "start_date", "end_date", "max_value", "max_shares", "max_pct"))
        row["first_date"] = min((e["date"] for e in p["events"]), default=None)
        out.append(row)
    _settle_status(out)
    return out


def _settle_status(rows):
    """A programme still marked ACTIVE is shown COMPLETED, marked Calculated with the reason, when it has used its whole target
    or a later programme of the same company has started buying after its last purchase. A completion a notice states is Reported."""
    for r in rows:
        r["status_basis"], r["status_working"] = ("Reported", "The notice says the programme has completed") if r["status"] == "COMPLETED" else (None, "")
        if r["status"] == "COMPLETED" and r.get("hand_status"):
            r["status_basis"], r["status_working"] = HAND, "Completion entered by hand" + (f" on {r['status_date']}" if r.get("status_date") else "") + f". Source: {r['hand_status']}"
        if (r.get("updated") or {}).get("status"):
            r["status_basis"], r["status_working"] = UPDATED, r["updated"]["status"]
            continue
        if r["status"] == "COMPLETED":
            continue
        later = [o for o in rows if o["country"] == r["country"] and o["ticker"] == r["ticker"] and (o["announced_date"] or "") > (r["announced_date"] or "")
                 and o["first_date"] and r["last_date"] and o["first_date"] > r["last_date"]]
        if r["used_pct"] is not None and r["used_pct"] >= 99.95:
            r["status"], r["status_basis"], r["status_working"] = "COMPLETED", "Calculated", f"{r['used_pct']:.1f}% of its target used"
        elif later:
            o = min(later, key=lambda o: o["first_date"])
            r["status"], r["status_basis"], r["status_working"] = "COMPLETED", "Calculated", f"The programme announced {o['announced_date']} began buying on {o['first_date']}, after this one's last purchase on {r['last_date']}"


def summary(con, country, start, end):
    cs = [c for c in countries.load() if country in (None, "", "ALL", c["code"])]
    rows = programme_rows(con, country, start, end)
    markets = []
    for c in cs:
        mine = [r for r in rows if r["country"] == c["code"]]
        active = [r for r in mine if r["shares"]]
        members = con.execute("select count(*) n from companies where country=? and in_index=1", (c["code"],)).fetchone()["n"]
        others, amounts = defaultdict(float), defaultdict(float)
        for r in mine:
            for k, v in r["other_currency"].items():
                others[k] += v
            for k, v in r["amounts"].items():
                amounts[k] += v
        per_currency = defaultdict(list)
        for r in mine:
            for k, v in r["provenance"].items():
                per_currency[k].append(v)
        provenance = {k: _combine(v) for k, v in per_currency.items()}
        monthly = defaultdict(lambda: {"value": 0, "shares": 0})
        by_currency_month = defaultdict(lambda: defaultdict(float))
        undated = defaultdict(float)  # a first running total covers the programme so far, so its buying can't be placed in any month
        prog_by_id = {p["prog_id"]: p for p in programme_events(con, c["code"])}
        for r in mine:
            for e in _in_period(prog_by_id[r["prog_id"]], start, end)[0]:
                if e.get("from_opening"):
                    if e["value"] is not None:
                        undated[e["currency"] or c["currency"]] += e["value"]
                    continue
                if e["currency"] == c["currency"] and e["value"] is not None:
                    monthly[e["date"][:7]]["value"] += e["value"]
                if e["value"] is not None:
                    by_currency_month[e["currency"] or c["currency"]][e["date"][:7]] += e["value"]
                monthly[e["date"][:7]]["shares"] += e["shares"] or 0
        markets.append({**{k: c[k] for k in ("code", "name", "flag", "exchange", "currency") if k in c},
                        "value": sum(r["value"] or 0 for r in mine), "shares": sum(r["shares"] for r in mine), "other_currency": dict(others), "amounts": dict(amounts), "provenance": provenance,
                        "monthly_by_currency": {k: [{"month": m, "value": v} for m, v in sorted(ms.items())] for k, ms in by_currency_month.items()}, "undated": dict(undated),
                        "active_companies": len({r["ticker"] for r in active}), "programmes": len(mine), "members": members,
                        "partial": sum(1 for r in active if not r["complete"]), "monthly": [{"month": m, **v} for m, v in sorted(monthly.items())],
                        "documents": con.execute("select count(*) n from documents where country=?", (c["code"],)).fetchone()["n"],
                        "open_reviews": con.execute("select count(*) n from review where country=? and status='OPEN' and kind<>'NO_PROGRAMME'", (c["code"],)).fetchone()["n"]})
    top = {}  # a company with two programmes in the period is one buyer; each reported currency is ranked on its own
    for r in rows:
        for cur, val in r["amounts"].items():
            t = top.setdefault((r["country"], r["ticker"], cur), {"country": r["country"], "ticker": r["ticker"], "company": r["company"], "currency": cur, "value": 0})
            t["value"] += val
    return {"markets": markets, "top": sorted(top.values(), key=lambda r: -r["value"])}


def companies(con, country, start, end):
    """One row per company in the study."""
    w, a = _where(country, "c.")
    rows = {(r["country"], r["ticker"]): {**r, "programmes": 0, "value": None, "shares": 0, "max_value": None, "used_pct": None, "currency": None, "state": "No notices saved", "note": "", "other_currency": {}, "amounts": {}, "parts": defaultdict(list)}
            for r in db.rows(con.execute(f"select c.*, (select count(*) from documents d where d.country=c.country and d.ticker=c.ticker) documents, (select max(doc_date) from documents d where d.country=c.country and d.ticker=c.ticker) last_notice from companies c where c.in_index=1 {w}", a))}
    for p in programme_rows(con, country, start, end):
        r = rows.get((p["country"], p["ticker"]))
        if not r:
            continue
        r["programmes"] += 1
        r["shares"] += p["shares"]
        r["currency"] = p["currency"]
        if p["value"] is not None:
            r["value"] = (r["value"] or 0) + p["value"]
        for c, v in p["other_currency"].items():
            r["other_currency"][c] = r["other_currency"].get(c, 0) + v
        for c, v in p["amounts"].items():
            r["amounts"][c] = r["amounts"].get(c, 0) + v
            r["parts"][c].append(p["provenance"][c])
        if p["max_value"] is not None and p["status"] != "COMPLETED":
            r["max_value"], r["used_pct"], r["max_currency"] = p["max_value"], p["used_pct"], p["max_currency"]
        if p["shares"] and p["status"] != "COMPLETED":
            r["state"] = "Buying"
        elif r["state"] != "Buying":
            r["state"] = "Finished" if p["status"] == "COMPLETED" else "No buying saved"
        if p["note"]:
            r["note"] = p["note"]
    for r in rows.values():
        if r["documents"] and r["programmes"] == 0:
            r["state"] = "Notices saved, no figures"
        r["amounts_text"] = amounts_text(r["amounts"])
        r["order_value"] = max(r["amounts"].values(), default=None)
        r["amount_basis"], r["amount_working"] = _combine([_combine(v) for v in r.pop("parts").values()])
    return sorted(rows.values(), key=lambda r: (-(r["order_value"] or 0), r["ticker"]))


def date_workings(con):
    """{doc_id: working} for the filings whose purchase date is worked out, not stated: the old ASX daily notice (Appendix 3E) gives only 'previous day'."""
    return {r["doc_id"]: f"Calculated: the form gives no date for the previous day; this is the trading day before the notice dated {r['doc_date']} (a public holiday is not known). It can be Updated Manually."
            for r in con.execute("select doc_id, doc_date from documents where form='appendix_3e'")}


def issues(con, country, start, end):
    """Appendix 3G: securities issued, transferred or converted, as filed. Kept apart from purchases and never netted against them."""
    rows = db.rows(con.execute(f"""select e.*, c.company, d.doc_date filing_date, d.source_url, d.heading from issues e
        left join companies c on c.country=e.country and c.ticker=e.ticker left join documents d on d.doc_id=e.doc_id
        where coalesce(e.issued_on, d.doc_date) between ? and ? {_where(country, 'e.')[0]} order by e.issued_on desc, e.ticker, e.n""", (start, end, *_where(country)[1])))
    return {"rows": rows}


def company(con, country, ticker, start, end):
    c = con.execute("select * from companies where country=? and ticker=?", (country, ticker)).fetchone()
    if not c:
        return None
    spans = periods.for_company(con, country, ticker)  # only programmes whose terms changed: renewed, extended or resized
    hand = hand_sources(con)
    from . import hand as hand_mod
    upd = hand_mod.marks(con, country)
    worked = date_workings(con)
    return {**dict(c), "programmes": [{**p, "periods": spans.get(p["prog_id"])} for p in programme_rows(con, country, start, end) if p["ticker"] == ticker],
            "transactions": [{**t, "hand_source": hand.get(t["doc_id"]), "updated": upd["tx"].get((t["prog_id"], t["trade_date"], t["venue"] or "", t["price_unit"] or ""), {}), "date_working": worked.get(t["doc_id"])}
                             for t in db.rows(con.execute("select * from transactions where country=? and ticker=? order by trade_date desc", (country, ticker)))],
            "updates": sum(1 for x in con.execute("select 1 from hand_entries where status='ACTIVE' and kind='update' and country=? and ticker=?", (country, ticker))),
            "venues": [v for v in venues(con, country, start, end) if v["ticker"] == ticker],
            "cancellation": (lambda x: {"programmes": [v for v in x["programmes"] if v["ticker"] == ticker], "events": [v for v in x["events"] if v["country"] == country and v["ticker"] == ticker], "counts": [v for v in x["counts"] if v["country"] == country and v["ticker"] == ticker]})(cancellations(con, country, start, end)),
            "documents": [_public(d) for d in db.rows(con.execute("select * from documents where country=? and ticker=? order by doc_date desc", (country, ticker)))],
            "cessations": [r for r in cessations(con, country, start, end)["rows"] if r["ticker"] == ticker],
            "issues": [r for r in issues(con, country, start, end)["rows"] if r["ticker"] == ticker],
            "waiting": con.execute("select count(*) from transactions where country=? and ticker=? and waiting=1", (country, ticker)).fetchone()[0],
            "currency": countries.get(country)["currency"]}


def venues(con, country, start, end):
    """Each programme's buying by venue. A closing notice's venue totals are complete; otherwise only saved days can be split, and the rest shows as not split."""
    out = []
    for r in programme_rows(con, country, start, end):
        if not r["shares"]:
            continue
        base = {k: r[k] for k in ("country", "ticker", "company", "prog_id", "announced_date", "in_index")}
        closing = db.rows(con.execute("select * from venue_totals where prog_id=? and as_of between ? and ? order by as_of desc", (r["prog_id"], start, end)))
        closing = [v for v in closing if v["as_of"] == closing[0]["as_of"]]
        started = r["start_date"] or r["announced_date"] or ""
        rows = []
        if closing and started >= start:
            for v in closing:
                rows.append({**base, "venue": v["venue"], "shares": v["shares"], "price_avg": v["price_avg"], "price_unit": v["price_unit"], "value": v["value"], "currency": v["currency"],
                             "basis": "Closing notice", "days": None, "doc_id": v["doc_id"], "key": f"venue|{v['venue']}", "value_basis": "Calculated", "value_working": "Shares x average price, both from the closing notice"})
        else:
            grouped = defaultdict(list)
            for x in db.rows(con.execute("select * from transactions where prog_id=? and coalesce(waiting,0)=0 and trade_date between ? and ? order by trade_date", (r["prog_id"], start, end))):
                grouped[(x["venue"], x["price_unit"], x["currency"])].append(x)
            for (venue, unit, cur), xs in grouped.items():
                shares = sum(x["shares"] or 0 for x in xs)
                priced = [x for x in xs if x["price_avg"] is not None and x["shares"]]
                held = sum(x["shares"] for x in priced)
                value = [x["value"] for x in xs if x["value"] is not None]
                rows.append({**base, "venue": venue or "Not stated", "shares": shares, "price_avg": sum(x["shares"] * x["price_avg"] for x in priced) / held if held else None, "price_unit": unit, "value": sum(value) if value else None, "currency": cur,
                             "basis": "Saved days only", "days": len({x["trade_date"] for x in xs}), "doc_id": xs[-1]["doc_id"], "key": f"tx|{xs[-1]['trade_date']}|{venue}",
                             "value_basis": "Reported" if len(xs) == 1 and xs[0]["value_origin"] == "reported" else HAND if len(xs) == 1 and xs[0]["value_origin"] == "hand" else UPDATED if len(xs) == 1 and xs[0]["value_origin"] == "updated" else "Calculated", "value_working": "The amount in the notice" if len(xs) == 1 and xs[0]["value_origin"] == "reported" else ("Shares x average price" if len(xs) == 1 else f"Sum of {len(xs)} saved days; average is weighted by shares")})
            rest = r["shares"] - sum(x["shares"] for x in rows)
            if rows and rest <= 0.5 and r["method"] == "Running totals":  # the saved days add up to the running total, so nothing is missing
                for x in rows:
                    x["basis"] = "All days saved"
            if rest > 0.5:
                rows.append({**base, "venue": "Not split", "shares": rest, "price_avg": None, "price_unit": "", "value": None, "currency": "", "basis": "No saved notice for these days", "days": None, "doc_id": None, "key": "", "value_basis": None, "value_working": ""})
        for x in rows:
            x["share_pct"] = 100 * x["shares"] / r["shares"]
        out += rows
    return out


def cancellations(con, country, start, end):
    """What happens to the shares. Only what saved notices state: counts aren't netted, because a later notice may cancel shares reported earlier as awaiting."""
    w, a = _where(country)
    events = db.rows(con.execute(f"""select e.*, c.company from cancellations e left join companies c on c.country=e.country and c.ticker=e.ticker
        where e.as_of between ? and ? {_where(country, 'e.')[0]} order by e.as_of desc, e.ticker""", (start, end, *a)))
    counts = db.rows(con.execute(f"""select s.*, c.company from share_counts s left join companies c on c.country=s.country and c.ticker=s.ticker where s.as_of between ? and ? {_where(country, 's.')[0]} order by s.ticker, s.as_of desc""", (start, end, *a)))
    latest = {}
    for s in counts:
        latest.setdefault((s["country"], s["ticker"]), s)
    programmes = []
    for r in programme_rows(con, country, start, end):
        announced_in_period = r["treatment"] and start <= (r["announced_date"] or "") <= end
        if not r["shares"] and not announced_in_period:  # a programme with no purchases saved still shows what it says it will do
            continue
        mine = [e for e in events if e["prog_id"] == r["prog_id"]]
        balances = sorted((e for e in mine if e["kind"] == "Awaiting cancellation (balance)"), key=lambda e: (e["as_of"] or "", e["doc_id"]))
        held = latest.get((r["country"], r["ticker"]))
        programmes.append({**{k: r[k] for k in ("country", "ticker", "company", "prog_id", "announced_date", "status", "shares", "treatment_doc")}, "treatment": r["treatment"] or "Not stated", "treatment_text": r["treatment_text"],
                           "cancelled_wording": sum(e["shares"] for e in mine if e["kind"] == "Cancelled" and e["basis"] != "Reported count"), "cancelled_reported": sum(e["shares"] for e in mine if e["kind"] == "Cancelled" and e["basis"] == "Reported count"),
                           "awaiting_wording": sum(e["shares"] for e in mine if e["kind"] == "Awaiting cancellation") + (balances[-1]["shares"] if balances else 0),
                           "latest_count": held["shares"] if held else None, "latest_count_date": held["as_of"] if held else None})
    return {"programmes": programmes, "events": events, "counts": counts}


def cessations(con, country, start, end):
    """Appendix 3H entries, as filed. Kept apart from purchases and never netted against them."""
    rows = db.rows(con.execute(f"""select e.*, c.company, d.doc_date filing_date, d.source_url, d.heading, p.announced_date programme from cessations e
        left join companies c on c.country=e.country and c.ticker=e.ticker left join documents d on d.doc_id=e.doc_id left join programmes p on p.prog_id=e.prog_id
        where e.ceased_on between ? and ? {_where(country, 'e.')[0]} order by e.ceased_on desc, e.ticker""", (start, end, *_where(country)[1])))
    for r in rows:
        r["kind"] = "Buy-back" if r["is_buyback"] else "Other"
        r["programme_label"] = (r["programme"] or "No programme read") if r["is_buyback"] else "Not a buy-back"
    return {"rows": rows}


def waiting(con, country):
    """Purchases waiting for a programme document, one group per company: what was bought, and the programme date the notices cite."""
    w, a = _where(country, "r.")
    groups = {}
    for r in db.rows(con.execute(f"""select r.country, r.ticker, r.doc_id, r.detail, d.parsed_json, d.source_url, c.company from review r join documents d on d.doc_id=r.doc_id
            left join companies c on c.country=r.country and c.ticker=r.ticker where r.kind='NO_PROGRAMME' and r.status='OPEN' {w} order by r.ticker""", a)):
        g = groups.setdefault((r["country"], r["ticker"]), {"country": r["country"], "ticker": r["ticker"], "company": r["company"] or r["ticker"], "doc_ids": [], "cited": set(), "detail": r["detail"]})
        if r["doc_id"] not in g["doc_ids"]:
            g["doc_ids"].append(r["doc_id"])
        cited = (json.loads(r["parsed_json"])["p"].get("programme") or {}).get("announced_date") if r["parsed_json"] else None
        if cited:
            g["cited"].add(cited)
    out = []
    for g in groups.values():
        ids = ",".join(str(i) for i in g["doc_ids"])
        s = con.execute(f"select count(*) n, sum(shares) shares, min(trade_date) first, max(trade_date) last from transactions where doc_id in ({ids})").fetchone()
        c = con.execute(f"select count(*) n, min(ceased_on) first, max(ceased_on) last from cessations where doc_id in ({ids}) and is_buyback=1").fetchone()
        out.append({**g, "cited": ", ".join(sorted(g["cited"])) or "Not stated in the notices", "filings": len(g["doc_ids"]), "purchases": s["n"], "cessations": c["n"], "shares": s["shares"],
                    "first": min(x for x in (s["first"], c["first"]) if x) if (s["first"] or c["first"]) else None, "last": max(x for x in (s["last"], c["last"]) if x) if (s["last"] or c["last"]) else None})
    return out


def daily_rows(con, prog_id=None, country=None, start=ALL_FROM, end=ALL_TO):
    """Date-wise buying, one row per purchase date and venue. Running totals sit on a date's first row, and each figure is marked Reported or Calculated."""
    where, args = ("t.prog_id=?", [prog_id]) if prog_id is not None else ("t.trade_date between ? and ?", [start, end])
    if country and country != "ALL":
        where += " and t.country=?"
        args.append(country)
    if prog_id is None and getattr(_ONLY, "ticker", ""):
        where += " and t.ticker=?"
        args.append(_ONLY.ticker)
    rows = db.rows(con.execute(f"""select t.*, c.company, d.doc_date filing_date, d.source_url, d.file_name from transactions t left join documents d on d.doc_id=t.doc_id
        left join companies c on c.country=t.country and c.ticker=t.ticker where {where} order by t.trade_date, t.ticker, t.venue""", args))
    snaps = {(s["prog_id"], s["as_of"]): s for s in con.execute("select * from snapshots where coalesce(waiting,0)=0")}
    treatment = {s["prog_id"]: (s["treatment"], s["treatment_text"]) for s in con.execute("select prog_id, treatment, treatment_text from programmes")}
    from . import hand  # imported here: hand uses ingest, which this module does not need
    upd = hand.marks(con)
    worked = date_workings(con)
    hand = hand_sources(con)
    done = set()
    for r in rows:
        how, said = treatment.get(r["prog_id"], (None, None))
        if how == "Cancelled" and r["shares"] is not None:  # no notice states a count for each purchase, so it is worked out from what happens to this programme's shares
            rule = str(said or "").startswith("Rule")
            r["cancelled"], r["cancelled_basis"] = r["shares"], "Rule" if rule else "Calculated"
            r["cancelled_working"] = ("Not stated in the notice. " if rule else "") + f"The programme's shares are cancelled ({said}), so all {r['shares']:,.0f} shares bought are counted as cancelled. The date of cancellation is not stated."
        else:
            r["cancelled"], r["cancelled_basis"], r["cancelled_working"] = None, None, None
        reported, added = r["value_origin"] == "reported", r["value_origin"] == "sum"
        r["value_basis"] = "Reported" if reported else None if r["value"] is None else "Calculated"
        r["value_working"] = "As the notice states" if reported else None if r["value"] is None else "Sum of the amounts the filing reports for that day in several rows" if added else "Shares x average price"
        r["avg_basis"] = None if r["price_avg"] is None else "Calculated" if reported or added else "Reported"
        r["hand_source"] = hand.get(r["doc_id"])
        if r["value_origin"] in ("hand", "hand_product"):  # typed from an announcement: marked so, with its source
            r["value_basis"] = None if r["value"] is None else HAND if r["value_origin"] == "hand" else "Calculated"
            r["value_working"] = None if r["value"] is None else f"Entered by hand. Source: {r['hand_source']}" if r["value_origin"] == "hand" else "Shares x average price, both entered by hand"
            r["avg_basis"] = None if r["price_avg"] is None else HAND
        r["venue_label"] = r["venue"] or "Not stated"
        s = snaps.get((r["prog_id"], r["trade_date"]))
        first = (r["prog_id"], r["trade_date"]) not in done
        done.add((r["prog_id"], r["trade_date"]))
        r["cum_shares"], r["cum_value"], r["cum_currency"], r["cum_basis"] = (s["cum_shares"], s["cum_value"], s["currency"], HAND if s["origin"] == "hand" else UPDATED if s["origin"] == "updated" else "Reported" if s["origin"] in ("reported", "rounded") else "Calculated") if s and first else (None, None, "", None)
        r["cum_working"] = s["working"] if s and first else None
        r["date_working"] = worked.get(r["doc_id"])
        r["updated"] = upd["tx"].get((r["prog_id"], r["trade_date"], r["venue"] or "", r["price_unit"] or ""), {})
        if r["value_origin"] == "updated" and r["value"] is not None:
            r["value_basis"], r["value_working"] = UPDATED, r["updated"].get("value")
    return rows


def activity(con, prog_id):
    """One programme's charts and daily table, from start to latest notice."""
    p = con.execute("select country, ticker from programmes where prog_id=?", (prog_id,)).fetchone()
    if not p:
        return None
    prog = next(r for r in programme_rows(con, p["country"], ALL_FROM, ALL_TO) if r["prog_id"] == prog_id)
    snaps = db.rows(con.execute("select * from snapshots where prog_id=? and coalesce(waiting,0)=0 order by as_of", (prog_id,)))
    basis = lambda s: HAND if s["origin"] == "hand" else UPDATED if s["origin"] == "updated" else "Reported" if s["origin"] in ("reported", "rounded") else "Calculated"
    paid = [{"date": s["as_of"], "value": s["cum_value"], "currency": s["currency"], "basis": basis(s)} for s in snaps if s["cum_value"] is not None]
    shares = [{"date": s["as_of"], "value": s["cum_shares"], "basis": basis(s)} for s in snaps if s["cum_shares"] is not None]
    daily = daily_rows(con, prog_id)
    if not paid:  # no running totals: add up what the daily rows hold, which is only the days saved
        total_v, total_s, cur = 0, 0, None
        for r in daily:
            total_s += r["shares"] or 0
            if r["value"] is not None:
                total_v += r["value"]
                cur = cur or r["currency"]
            paid.append({"date": r["trade_date"], "value": total_v, "currency": r["currency"], "basis": "Calculated"})
            shares.append({"date": r["trade_date"], "value": total_s, "basis": "Calculated"})
    currency = paid[-1]["currency"] if paid else prog["max_currency"]
    target = None
    if prog["max_value"]:
        target = {"kind": "money", "value": prog["max_value"], "currency": prog["max_currency"], "comparable": prog["max_currency"] == currency}
    elif prog["max_shares"]:
        target = {"kind": "shares", "value": prog["max_shares"], "comparable": True}
    return {"programme": prog, "paid": paid, "shares": shares, "currency": currency, "target": target, "daily": daily}


def transactions(con, country, start, end):
    w, a = _where(country, "t.")
    hand = hand_sources(con)
    rows = db.rows(con.execute(f"""select t.*, c.company, c.sector, c.in_index, p.announced_date programme_announced from transactions t left join companies c on c.country=t.country and c.ticker=t.ticker
        left join programmes p on p.prog_id=t.prog_id
        where t.trade_date between ? and ? {w} order by t.trade_date desc, t.ticker""", (start, end, *a)))
    from . import hand as hand_mod
    upd = hand_mod.marks(con, country)
    worked = date_workings(con)
    for r in rows:
        r["hand_source"] = hand.get(r["doc_id"])
        r["updated"] = upd["tx"].get((r["prog_id"], r["trade_date"], r["venue"] or "", r["price_unit"] or ""), {})
        r["date_working"] = worked.get(r["doc_id"])
    return rows


def _public(d):
    d = dict(d)
    d.pop("parsed_json", None)
    return d


def documents(con, country):
    w, a = _where(country, "d.")
    return [_public(r) for r in db.rows(con.execute(f"""select d.*, c.company, (select count(*) from doc_pages p where p.doc_id=d.doc_id) pages, (select count(*) from evidence e where e.doc_id=d.doc_id) figures
        from documents d left join companies c on c.country=d.country and c.ticker=d.ticker where 1=1 {w} order by coalesce(d.doc_date,d.imported_at) desc, d.doc_id desc""", a))]


def search_documents(con, country, text):
    w, a = _where(country, "d.")
    return [r["doc_id"] for r in con.execute(f"select distinct d.doc_id from doc_pages p join documents d on d.doc_id=p.doc_id where p.text like ? {w}", (f"%{text}%", *a))]


def document(con, doc_id, key=None):
    d = con.execute("select * from documents where doc_id=?", (doc_id,)).fetchone()
    if not d:
        return None
    ev = db.rows(con.execute("select * from evidence where doc_id=? order by page, ev_id", (doc_id,)))
    chosen = [e for e in ev if e["key"] == key] if key else []
    pages = db.rows(con.execute("select page, text from doc_pages where doc_id=? order by page", (doc_id,)))
    entry = None
    if d["form"] == "manual":  # an entry made by hand has no pages: its panel shows what was typed and where it came from
        from . import hand
        held = con.execute("select entry_id from hand_entries where doc_id=?", (doc_id,)).fetchone()
        entry = hand.entry(con, held["entry_id"]) if held else None
    return {**_public(d), "hand": entry, "evidence": ev, "focus": chosen, "focus_key": key if chosen else None, "pages": pages,
            "open_page": (chosen or ev or [{"page": 1}])[0]["page"], "is_pdf": (d["file_name"] or "").lower().endswith(".pdf"),
            "reviews": db.rows(con.execute("select * from review where doc_id=?", (doc_id,)))}


# ---------- analysis ----------
def analysis(con, country, start, end):
    rows = programme_rows(con, country, start, end)
    out = {"pace": [], "concentration": [], "sectors": [], "price": [], "capital": [], "reaction": [], "participation": []}
    for c in countries.load():
        if country not in (None, "", "ALL", c["code"]):
            continue
        mine = [r for r in rows if r["country"] == c["code"]]
        per_cur = defaultdict(lambda: defaultdict(float))  # a company with two programmes is one buyer; currencies stay apart
        for r in mine:
            for cur, val in r["amounts"].items():
                per_cur[cur][r["ticker"]] += val
        members = con.execute("select count(*) n from companies where country=? and in_index=1", (c["code"],)).fetchone()["n"]
        buying = len({r["ticker"] for r in mine if r["shares"]})
        out["participation"].append({"country": c["code"], "name": c["name"], "exchange": c["exchange"], "currency": c["currency"], "members": members, "buying": buying,
                                     "amounts": {k: sum(v.values()) for k, v in per_cur.items()}, "averages": {k: sum(v.values()) / len(v) for k, v in per_cur.items()}})
        if not per_cur:
            out["concentration"].append({"country": c["code"], "name": c["name"], "currency": c["currency"], "buyers": 0, "top1": None, "top5": None, "top10": None})
        for cur, comps in per_cur.items():
            vals = sorted(comps.values(), reverse=True)
            tot = sum(vals)
            out["concentration"].append({"country": c["code"], "name": c["name"], "currency": cur, "buyers": len(vals), "top1": 100 * vals[0] / tot if tot else None, "top5": 100 * sum(vals[:5]) / tot if tot else None, "top10": 100 * sum(vals[:10]) / tot if tot else None})
        sec = defaultdict(lambda: {"value": 0, "companies": set()})
        for r in mine:
            for cur, val in r["amounts"].items():
                sec[(r["sector"] or "Unknown", cur)]["value"] += val
                sec[(r["sector"] or "Unknown", cur)]["companies"].add(r["ticker"])
        out["sectors"] += [{"country": c["code"], "currency": cur, "sector": s, "value": v["value"], "companies": len(v["companies"]), "share": 100 * v["value"] / sum(per_cur[cur].values()) if per_cur[cur] else None} for (s, cur), v in sorted(sec.items(), key=lambda kv: -kv[1]["value"])]
    today = date.today().isoformat()
    capital = {}
    for r in rows:
        if r["max_value"] and r["used_pct"] is not None:
            s, e = r["start_date"] or r["announced_date"], r["end_date"]
            elapsed = None
            if s and e and e > s:
                span = (date.fromisoformat(e) - date.fromisoformat(s)).days
                elapsed = max(0, min(100, 100 * (date.fromisoformat(min(today, e)) - date.fromisoformat(s)).days / span))
            out["pace"].append({"country": r["country"], "ticker": r["ticker"], "company": r["company"], "max_value": r["max_value"], "max_currency": r["max_currency"], "spent": r["programme_spent"], "used_pct": r["used_pct"], "time_used_pct": elapsed, "status": r["status"], "start": s, "end": e, "doc_id": r["source_doc"]})
        if r["shares_on_issue"] and r["shares"]:  # one entry per company, however many programmes it ran, measured against its latest share count
            c = capital.setdefault((r["country"], r["ticker"]), {"country": r["country"], "ticker": r["ticker"], "company": r["company"], "shares": 0, "complete": True, "programmes": 0, "latest": ""})
            c["shares"] += r["shares"]
            c["programmes"] += 1
            c["complete"] = c["complete"] and r["complete"]
            if (r["last_date"] or "") >= c["latest"]:
                c["latest"], c["shares_on_issue"] = r["last_date"] or "", r["shares_on_issue"]
    for c in capital.values():
        c["pct"] = 100 * c["shares"] / c["shares_on_issue"]
        out["capital"].append(c)
    w, a = _where(country, "t.")
    grouped = defaultdict(list)
    for t in con.execute(f"select t.* from transactions t where t.price_avg is not null and coalesce(t.waiting,0)=0 and t.trade_date between ? and ? {w} order by t.trade_date", (start, end, *a)):
        grouped[(t["country"], t["ticker"], t["price_unit"])].append(t)
    names = {(c["country"], c["ticker"]): c["company"] for c in con.execute("select country,ticker,company from companies where in_index=1")}
    for (cc, tk, unit), ts in grouped.items():
        if (cc, tk) in names:
            out["price"].append({"country": cc, "ticker": tk, "company": names[(cc, tk)], "unit": unit, "first_date": ts[0]["trade_date"], "first_price": ts[0]["price_avg"], "last_date": ts[-1]["trade_date"], "last_price": ts[-1]["price_avg"], "change_pct": 100 * (ts[-1]["price_avg"] / ts[0]["price_avg"] - 1), "days": len({t["trade_date"] for t in ts})})
    out["reaction"] = price_reaction(con, country, start, end)
    out["pace"].sort(key=lambda r: -r["used_pct"])
    out["capital"].sort(key=lambda r: -r["pct"])
    out["price"].sort(key=lambda r: -r["change_pct"])
    return out


def price_reaction(con, country, start, end, horizons=(1, 5, 20)):
    """Close-to-close change after each announcement, from the optional inbox/prices.csv. Not adjusted for the market, so it describes rather than explains."""
    w, a = _where(country, "p.")
    prog = db.rows(con.execute(f"select p.country, p.ticker, p.announced_date from programmes p where p.announced_date between ? and ? {w}", (start, end, *a)))
    results = []
    for p in prog:
        closes = db.rows(con.execute("select date, close from prices where country=? and ticker=? order by date", (p["country"], p["ticker"])))
        before = [c for c in closes if c["date"] <= p["announced_date"]]
        after = [c for c in closes if c["date"] > p["announced_date"]]
        if before and after:
            base = before[-1]["close"]
            results.append({"country": p["country"], "ticker": p["ticker"], "announced": p["announced_date"], **{f"d{h}": (100 * (after[h - 1]["close"] / base - 1) if len(after) >= h else None) for h in horizons}})
    summary_rows = []
    for h in horizons:
        vals = [r[f"d{h}"] for r in results if r[f"d{h}"] is not None]
        summary_rows.append({"horizon": h, "n": len(vals), "median": median(vals) if vals else None, "up_pct": 100 * sum(v > 0 for v in vals) / len(vals) if vals else None})
    return {"rows": results, "summary": summary_rows}


# ---------- quality ----------
def total_gaps(con, p):
    """Where two filings state a running total of shares, the rise between them should equal the purchases read for the dates between.
    A shortfall means a filing is missing from what was read; an excess means a purchase was misread or counted twice. Nothing is changed."""
    out = []
    held = db.rows(con.execute("select as_of, cum_shares, doc_id from snapshots where prog_id=? and cum_shares is not null and coalesce(waiting,0)=0 order by as_of", (p["prog_id"],)))
    days = db.rows(con.execute("select trade_date, sum(shares) shares from transactions where prog_id=? and coalesce(waiting,0)=0 group by trade_date", (p["prog_id"],)))
    for x, y in zip(held, held[1:]):
        rise = y["cum_shares"] - x["cum_shares"]
        if rise < 0:  # reported separately, as Running total fell
            continue
        read = sum(d["shares"] or 0 for d in days if x["as_of"] < d["trade_date"] <= y["as_of"])
        gap = rise - read
        base = {"country": p["country"], "ticker": p["ticker"], "doc_id": y["doc_id"]}
        between = f"The running total rose by {rise:,.0f} shares from {x['as_of']} ({x['cum_shares']:,.0f}) to {y['as_of']} ({y['cum_shares']:,.0f}), but the purchases read for those dates add up to {read:,.0f}."
        if gap > 0.5:
            out.append({**base, "severity": "bad", "check": "Purchases missing between filings", "detail": f"{between} {gap:,.0f} shares aren't covered by any filing read: a filing may be missing from your list, or a day's shares were misread."})
        elif gap < -0.5:
            out.append({**base, "severity": "bad", "check": "Purchases exceed the running total", "detail": f"{between} That is {-gap:,.0f} more than the totals allow: a purchase may be misread or counted twice, or a total may be wrong."})
    return out


def quality(con, country, start, end):
    w, a = _where(country)
    checks = []
    rows = programme_rows(con, country, start, end)
    for r in rows:
        if not r["complete"] and r["note"] and (r["shares"] or r["method"] == "Running totals"):
            checks.append({"severity": "warn", "country": r["country"], "ticker": r["ticker"], "check": "Partial coverage", "detail": r["note"], "doc_id": r["last_doc"]})
        if r["used_pct"] is not None and r["used_pct"] > 101:
            checks.append({"severity": "bad", "country": r["country"], "ticker": r["ticker"], "check": "Over the announced size", "detail": f"{r['used_pct']:.1f}% of the announced amount. The programme may have been raised: check the latest notice.", "doc_id": r["last_doc"]})
        if r["other_currency"]:
            checks.append({"severity": "info", "country": r["country"], "ticker": r["ticker"], "check": "Other currency", "detail": "Reported in " + ", ".join(r["other_currency"]) + "; shown in that currency and not converted.", "doc_id": r["last_doc"]})
        if r["status"] != "COMPLETED" and r["end_date"] and r["end_date"] < date.today().isoformat():
            checks.append({"severity": "warn", "country": r["country"], "ticker": r["ticker"], "check": "Past its end date", "detail": f"Planned to end {r['end_date']} with no final notice saved.", "doc_id": r["last_doc"]})
        if r["last_date"] and r["status"] != "COMPLETED" and r["last_date"] < (date.today() - timedelta(days=30)).isoformat():
            checks.append({"severity": "info", "country": r["country"], "ticker": r["ticker"], "check": "Older figures", "detail": f"Newest figure is {r['last_date']}. A newer notice may exist.", "doc_id": r["last_doc"]})
    for t in con.execute(f"select * from transactions where 1=1 {w}", a):
        if t["price_avg"] and t["price_high"] and t["price_low"] and not (t["price_low"] * 0.999 <= t["price_avg"] <= t["price_high"] * 1.001):
            checks.append({"severity": "bad", "country": t["country"], "ticker": t["ticker"], "check": "Price out of range", "detail": f"{t['trade_date']}: average {t['price_avg']} is outside {t['price_low']} to {t['price_high']}.", "doc_id": t["doc_id"]})
    for p in programme_events(con, country):
        closing = db.rows(con.execute("select as_of, sum(shares) shares, min(doc_id) doc_id from venue_totals where prog_id=? group by as_of", (p["prog_id"],)))
        totals = {s["as_of"]: s["cum_shares"] for s in con.execute("select as_of, cum_shares from snapshots where prog_id=?", (p["prog_id"],))}
        for v in closing:
            if v["as_of"] in totals and abs((totals[v["as_of"]] or 0) - v["shares"]) > 0.5:
                checks.append({"severity": "bad", "country": p["country"], "ticker": p["ticker"], "check": "Venue totals differ", "detail": f"{v['as_of']}: venues add up to {v['shares']:,.0f}, but the running total is {totals[v['as_of']]:,.0f}.", "doc_id": v["doc_id"]})
        snaps = db.rows(con.execute("select * from snapshots where prog_id=? order by as_of", (p["prog_id"],)))
        for x, y in zip(snaps, snaps[1:]):
            if (y["cum_shares"] or 0) < (x["cum_shares"] or 0):
                checks.append({"severity": "bad", "country": p["country"], "ticker": p["ticker"], "check": "Running total fell", "detail": f"{x['as_of']}: {x['cum_shares']:,.0f}, then {y['as_of']}: {y['cum_shares']:,.0f}. Two programmes may be mixed.", "doc_id": y["doc_id"]})
        checks += total_gaps(con, p)
    for d in con.execute(f"""select country, ticker, doc_type, doc_date, count(*) n, max(doc_id) doc_id from documents where ticker is not null and doc_date is not null
        and doc_type not in ('unknown','transactions csv','programmes csv','announcement list') {w} group by country, ticker, doc_type, doc_date having n>1""", a).fetchall():
        same = db.rows(con.execute("select reason, parsed_json from documents where country=? and ticker=? and doc_type=? and doc_date=?", (d["country"], d["ticker"], d["doc_type"], d["doc_date"])))
        reasons = sorted({s["reason"] for s in same if s["reason"]})
        linked = sorted({json.loads(s["parsed_json"])["p"]["programme"].get("announced_date") or "" for s in same if s["parsed_json"]} - {""})
        checks.append({"severity": "warn", "country": d["country"], "ticker": d["ticker"], "check": "Possible duplicate",
                       "detail": f"{d['n']} {d['doc_type']} filings dated {d['doc_date']}. " + (f"Reason for update: {'; '.join(reasons)}. " if reasons else "No reason for update stated. ")
                                 + (f"Programme announced {', '.join(linked)}. " if linked else "") + "Where they report the same purchase date, the latest filing overwrites.", "doc_id": d["doc_id"]})
    series = defaultdict(list)
    for s in con.execute(f"select * from share_counts where 1=1 {w} order by as_of", a):
        series[(s["country"], s["ticker"])].append(s)
    for (cc, tk), xs in series.items():
        for x, y in zip(xs, xs[1:]):
            if x["shares"] and abs(y["shares"] / x["shares"] - 1) > 0.10:
                checks.append({"severity": "warn", "country": cc, "ticker": tk, "check": "Share count jump", "detail": f"Shares on issue went from {x['shares']:,.0f} ({x['as_of']}) to {y['shares']:,.0f} ({y['as_of']}). One notice may be wrong, or the company's capital changed.", "doc_id": y["doc_id"]})
    return {"review": db.rows(con.execute(f"select r.*, d.file_name, d.heading, d.source_url from review r left join documents d on d.doc_id=r.doc_id where r.status='OPEN' and r.kind<>'NO_PROGRAMME' {_where(country, 'r.')[0]} order by r.review_id desc", a)),
            "checks": checks, "tickers": db.rows(con.execute(f"select country, ticker, company from companies where 1=1 {_market(country)[0]} order by ticker", _market(country)[1]))}


def collect_status(con):
    out = []
    for c in countries.load():
        folder = countries.INBOX / c["code"]
        out.append({**c, "folder": str(folder), "documents": con.execute("select count(*) n from documents where country=?", (c["code"],)).fetchone()["n"],
                    "members": con.execute("select count(*) n from companies where country=? and in_index=1", (c["code"],)).fetchone()["n"],
                    "with_docs": con.execute("select count(distinct d.ticker) n from documents d join companies m on m.country=d.country and m.ticker=d.ticker and m.in_index=1 where d.country=?", (c["code"],)).fetchone()["n"],
                    "listed": db.rows(con.execute("select * from announcement_list where country=? order by date desc limit 200", (c["code"],)))})
    runs = db.rows(con.execute("select * from runs order by run_id desc limit 10"))
    return {"countries": out, "runs": runs}
