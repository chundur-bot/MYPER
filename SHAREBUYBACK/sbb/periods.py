"""The periods of a programme whose terms changed: a buy-back renewed for another year, an end date moved, a size raised.

The programmes table keeps one set of terms, the newest. Each filing's own reading is kept too (documents.parsed_json), so the terms every filing
stated can be set out again from what is already stored. Nothing is fetched, nothing is stored, and no filing is read again.

A period is one start date. A filing that keeps the start and changes the end or the size is a change within that period; a filing with a new
start begins a new period. Dates and sizes are as each filing states them (Reported). Shares bought in a period are the purchases read whose
dates fall inside it, added up, and the share of the target used is worked out from them (both Calculated). A maximum in shares is a limit for that period, so it is
measured against the period's own purchases; a size in money is the programme's whole size, so it is measured against everything paid up to the end of the period.
"""
import json
from datetime import date, timedelta

TERMS = ("start_date", "end_date", "max_shares", "max_value", "max_currency", "max_pct")  # a size can be stated as a percentage of the shares (entered by hand)


def _size(t):
    money = f"{t.get('max_currency') or ''} {t['max_value']:,.0f}".strip() if t.get("max_value") else ""
    shares = f"{t['max_shares']:,.0f} shares" if t.get("max_shares") else ""
    pct = f"{t['max_pct']:g}% of shares" if t.get("max_pct") else ""
    return " and ".join(x for x in (money, shares, pct) if x) or "no size stated"


def _day_before(iso):
    try:
        return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()
    except (TypeError, ValueError):
        return None


def for_company(con, country, ticker):
    """{prog_id: periods} for each of the company's programmes whose terms changed at least once; other programmes are left out."""
    progs = [dict(r) for r in con.execute("select prog_id, announced_date, source_doc from programmes where country=? and ticker=?", (country, ticker))]
    if not progs:
        return {}
    by_date = {p["announced_date"]: p["prog_id"] for p in progs if p["announced_date"]}
    by_doc = {}
    for table, day in (("transactions", "trade_date"), ("snapshots", "as_of")):
        for r in con.execute(f"select distinct x.doc_id, x.prog_id from {table} x join programmes p on p.prog_id=x.prog_id where p.country=? and p.ticker=? and x.doc_id is not null", (country, ticker)):
            by_doc.setdefault(r["doc_id"], r["prog_id"])
    for p in progs:
        if p["source_doc"]:
            by_doc.setdefault(p["source_doc"], p["prog_id"])
    stated = {p["prog_id"]: [] for p in progs}
    for d in con.execute("select doc_id, doc_date, doc_type, parsed_json from documents where country=? and ticker=? and parsed_json is not null order by coalesce(doc_date,'9999'), doc_id", (country, ticker)):
        try:
            p = json.loads(d["parsed_json"])["p"]
        except (ValueError, KeyError, TypeError):
            continue
        g = p.get("programme") or {}
        if not any(g.get(k) for k in TERMS[:4] + ("max_pct",)):
            continue
        # terms are taken from a form (which has fields for them) and from a company's announcement or change of terms. A purchase notice in prose is left out:
        # the dates it gives are the days it covers, such as one week of buying, not the programme's
        if not (p.get("form") == "appendix_3c" or p.get("definition") or d["doc_type"] in ("programme", "update", "final")):
            continue
        pid = by_date.get(g.get("announced_date")) if g.get("announced_date") else None
        pid = pid or by_doc.get(d["doc_id"])
        if pid in stated:
            stated[pid].append({"doc_id": d["doc_id"], "filed": d["doc_date"], "doc_type": d["doc_type"], "reason": (p.get("reason") or "").strip(), "hand": p.get("form") == "manual", **{k: g.get(k) for k in TERMS}})
    out = {}
    for p in progs:
        made = _periods(con, p["prog_id"], stated[p["prog_id"]])
        if made:
            out[p["prog_id"]] = made
    return out


def _periods(con, prog_id, stated):
    # each change of terms, in filing order: a filing that restates the terms in force changes nothing
    current, changes, seen = {}, [], []
    for s in stated:
        merged = {**current, **{k: s[k] for k in TERMS if s.get(k) is not None}}
        if not merged.get("max_value"):
            merged.pop("max_currency", None)
        if merged == current:
            continue
        if s["doc_type"] not in ("programme", "update", "final") and merged in seen:
            continue  # a daily form filed around a change can still carry the terms it replaced: not a change back
        changes.append({**s, **{k: merged.get(k) for k in TERMS}, "was": dict(current)})
        seen.append(dict(merged))
        current = merged
    if len(changes) < 2:
        return None
    rows = []
    for c in changes:
        if rows and rows[-1]["start"] in (c["start_date"], None):  # the same period: its end moved or its size changed, or its dates were first stated after its size
            r, was = rows[-1], c["was"]
            said = []
            first_dates = r["start"] is None or (was.get("end_date") is None and not r["changes"])
            r["start"] = c["start_date"]
            if c["end_date"] != was.get("end_date") and not first_dates:
                said.append(f"end date {was.get('end_date') or 'not stated'} changed to {c['end_date'] or 'not stated'}")
            if (c["max_shares"], c["max_value"], c.get("max_currency"), c.get("max_pct")) != (was.get("max_shares"), was.get("max_value"), was.get("max_currency"), was.get("max_pct")):
                said.append(f"size {_size(was)} changed to {_size(c)}")
            if said:
                r["changes"].append(f"{c['filed'] or 'Undated filing'}: " + "; ".join(said))
            r.update(end=c["end_date"], max_shares=c["max_shares"], max_value=c["max_value"], max_currency=c.get("max_currency"), max_pct=c.get("max_pct"))
            r["hand"] = r["hand"] or c["hand"]
        else:
            rows.append({"start": c["start_date"], "end": c["end_date"], "max_shares": c["max_shares"], "max_value": c["max_value"], "max_currency": c.get("max_currency"), "max_pct": c.get("max_pct"),
                         "filed": c["filed"], "doc_id": c["doc_id"], "doc_type": c["doc_type"], "reason": c["reason"], "changes": [], "hand": c["hand"]})
    if len(rows) < 2 and not rows[0]["changes"]:  # one period whose terms never changed once stated: nothing to set out
        return None
    buys = [dict(r) for r in con.execute("select trade_date, shares, value, currency from transactions where prog_id=? and coalesce(waiting,0)=0 order by trade_date", (prog_id,))]
    # each purchase belongs to one period: the latest one that had started by its date and had not ended. Periods can overlap when a renewal is filed early
    spans = []
    for i, r in enumerate(rows):
        nxt = rows[i + 1]["start"] if i + 1 < len(rows) else None
        spans.append((r["start"], r["end"] or (_day_before(nxt) if nxt else None)))  # no end stated: up to the day before the next period, or open
    home, placed = {}, set()
    for n, b in enumerate(buys):
        for i in range(len(rows) - 1, -1, -1):
            first, last = spans[i]
            if (not first or b["trade_date"] >= first) and (not last or b["trade_date"] <= last):
                home[n] = i
                placed.add(n)
                break
    for i, r in enumerate(rows):
        inside = [(n, b) for n, b in enumerate(buys) if home.get(n) == i]
        amounts = {}
        for _, b in inside:
            if b["value"] is not None and b["currency"]:
                amounts[b["currency"]] = amounts.get(b["currency"], 0) + b["value"]
        r["days"] = len({b["trade_date"] for _, b in inside})
        r["bought_shares"] = sum(b["shares"] or 0 for _, b in inside)
        r["amounts"] = amounts  # each currency apart; never added together
        r["used_pct"], r["used_working"] = None, ""
        if r["max_shares"] and not r["max_value"]:
            r["used_pct"] = 100 * r["bought_shares"] / r["max_shares"]
            r["used_working"] = f"{r['bought_shares']:,.0f} shares bought in the period / {r['max_shares']:,.0f} shares, the period's maximum"
        elif r["max_value"] and r["max_currency"]:
            # a money size is the programme's whole size, raised or carried into later periods, so it is measured against everything paid since the programme began
            so_far = [b for n, b in enumerate(buys) if n in home and home[n] <= i]
            if so_far and all(b["value"] is not None and b["currency"] == r["max_currency"] for b in so_far):
                paid = sum(b["value"] for b in so_far)
                r["used_pct"] = 100 * paid / r["max_value"]
                r["used_working"] = f"{r['max_currency']} {paid:,.2f} paid from the programme's first purchase to the end of this period / {r['max_currency']} {r['max_value']:,.0f}, the size stated for this period"
        r["current"] = i == len(rows) - 1
    rest = [b for n, b in enumerate(buys) if n not in placed]
    starts, ends = [r["start"] for r in rows if r["start"]], [r["end"] for r in rows if r["end"]]
    out = {"count": len(rows), "from": min(starts) if starts else None, "to": max(ends) if ends and all(r["end"] for r in rows) else None, "rows": rows,
           "outside": {"shares": sum(b["shares"] or 0 for b in rest), "days": len({b["trade_date"] for b in rest}), "first": rest[0]["trade_date"], "last": rest[-1]["trade_date"]} if rest else None, "gap": None}
    total = con.execute("select as_of, cum_shares from snapshots where prog_id=? and cum_shares is not null and coalesce(waiting,0)=0 order by as_of desc, cum_shares desc limit 1", (prog_id,)).fetchone()
    read = sum(b["shares"] or 0 for b in buys)
    if total and total["cum_shares"] - read > 0.5:  # the filings' own running total is more than the purchases read add up to
        out["gap"] = {"as_of": total["as_of"], "stated": total["cum_shares"], "read": read, "missing": total["cum_shares"] - read}
    return out
