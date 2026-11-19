"""The Tracker section: every filing already read, given a type, a confidence and the programme it belongs to; each programme checked against
the running totals in its own filings.

It works from the readings the app already holds (documents.parsed_json) and writes only its own tables (tracker_*) in the same database.
It fetches nothing and keeps no filing text. Its tables are rebuilt in full whenever the filings held have changed, so they can't drift."""
import hashlib
import json
import re
import threading
from datetime import date

from . import countries, db

RULES_VERSION = "2026-11-20"
SCHEMA = """
create table if not exists tracker_notices (
  notice_id integer primary key, doc_id integer, link text, country text, ticker text, company text, title text, filed text, type text, type_basis text,
  in_scope integer, excluded_reason text, confidence text, low_reason text, reader text, plan_id integer, tie_method text, data text);
create table if not exists tracker_plans (plan_id integer primary key, country text, ticker text, data text);
create table if not exists tracker_checks (plan_id integer, name text, result text, detail text, expected real, found real);
create table if not exists tracker_runs (run_id integer primary key, started text, finished text, signature text, report text);
create index if not exists ix_tracker_notices on tracker_notices(country, ticker);
"""
OUT_OF_SCOPE = re.compile(r"off[- ]market|tender offer|employee share|employee incentive|minimum holding|unmarketable parcel|small holding|selective buy", re.I)
LOCK = threading.Lock()
STATUSES = ["In progress", "Completed", "Target reached", "Ended, no final notice"]


# ---------- each notice: type and confidence ----------
def classify(title, form, doc_type):
    """(type, basis) from the form type when the filing is a form, otherwise from its title."""
    by_form = {("appendix_3c", "daily"): "Daily transaction", ("appendix_3c", "update"): "Change to terms", ("appendix_3c", "final"): "Final notice",
               ("appendix_3c", "programme"): "Programme announcement", ("appendix_3h", "cessation"): "Cancellation of shares", ("capital_change", "transaction"): "Capital change notice",
               ("hkex_ndr", "transaction"): "Daily transaction", ("hkex_daily", "transaction"): "Daily transaction", ("hkex_monthly", "transaction"): "Monthly return",
               ("manual", "programme"): "Programme announcement", ("manual", "update"): "Change to terms", ("manual", "transaction"): "Daily transaction",
               ("manual", "final"): "Final notice", ("manual", "completion"): "Completion",
               ("appendix_3d", "update"): "Change to terms", ("appendix_3e", "daily"): "Daily transaction", ("appendix_3f", "final"): "Final notice", ("appendix_3g", "issue"): "Issue of securities"}  # entries made by hand say what they are
    if (form, doc_type) in by_form:
        return by_form[(form, doc_type)], "kind chosen when it was entered by hand" if form == "manual" else "form type"
    for pattern, kind in ((r"transactions? in own shares|purchases? pursuant|daily share buy-?\s?back notice|acquisition of (?:its )?own shares", "Daily transaction"),
                          (r"\bcomplet(?:es|ed|ion)\b|\bconclu", "Completion"),
                          (r"\bterminat", "Termination"),
                          (r"extension|\bextends?\b|increase|additional|upsiz|variation|change", "Change to terms"),
                          (r"cancellation of shares|cessation of securities|treasury", "Cancellation of shares")):
        if re.search(pattern, title or "", re.I):
            return kind, "title"
    by_reading = {"transaction": "Daily transaction", "daily": "Daily transaction", "programme": "Programme announcement", "update": "Change to terms", "final": "Final notice", "cessation": "Cancellation of shares"}
    if doc_type in by_reading:  # what the reader found in the filing outranks a general word in its title
        return by_reading[doc_type], "reading"
    if re.search(r"buy-?\s?back|repurchase", title or "", re.I):
        return "Programme announcement", "title"
    return "Not identified", "none"


def confidence(kind, p):
    """high: read from a fixed form or labelled template. medium: read from prose by pattern. low: a required figure is missing, and is left blank.
    n/a: no figures expected."""
    tx, snaps, prog = p.get("transactions") or [], p.get("snapshots") or [], p.get("programme") or {}
    if p.get("form") == "manual":
        return "entered by hand", None  # typed by you from the source you named: nothing was read, so no reading confidence applies
    missing = None
    if kind in ("Daily transaction", "Capital change notice"):
        if not tx:
            missing = "No purchase was read"
        elif any(not t.get("shares") for t in tx):
            missing = "A purchase has no number of shares"
        elif any(t.get("value") is None and t.get("price_avg") is None for t in tx):
            missing = "A purchase has neither an amount nor a price"
    elif kind == "Programme announcement":
        if not prog.get("announced_date"):
            missing = "No announcement date"
        elif not (prog.get("max_value") or prog.get("max_shares")):
            missing = "Neither a planned amount nor a maximum number of shares"
    elif kind == "Change to terms":
        if not (prog.get("max_value") or prog.get("max_shares") or prog.get("end_date") or p.get("reason")):
            missing = "The change itself was not read"
    elif kind == "Final notice":
        if not any(s.get("cum_shares") and s.get("cum_value") is not None for s in snaps):
            missing = "Final totals were not read"
    elif kind == "Cancellation of shares":
        if not any(c.get("shares") for c in p.get("cessations") or []):
            missing = "No number of shares cancelled"
    elif kind == "Not identified":
        missing = "The filing type was not identified"
    else:
        return "n/a", None  # completion and termination letters
    flagged = [d for k, d in (p.get("issues") or []) if k in ("CHECK_FAILED", "NO_AVG_PRICE", "VENUE_MISMATCH")]
    if missing or flagged:
        return "low", missing or flagged[0]
    return ("high" if p.get("form") in ("appendix_3c", "appendix_3d", "appendix_3e", "appendix_3f", "appendix_3h", "capital_change") or p.get("definition") else "medium"), None  # "definition": a fixed-form layout in data/forms


def _notices(con):
    """Every filing held, and every link set aside, as a notice with its type, scope and confidence. Each carries its reading as "p"."""
    known = {c["code"] for c in countries.load()}
    out = []
    from . import hand  # figures Updated Manually are used in place of the reading, and the notice says so
    updates = hand.tracker_updates(con)
    for d in con.execute("""select d.doc_id, d.source_url, d.country, d.ticker, coalesce(c.company, d.company_raw) company, coalesce(d.heading, d.file_name) heading, d.doc_date,
            d.form, d.doc_type, d.parsed_json from documents d left join companies c on c.country=d.country and c.ticker=d.ticker order by d.doc_id"""):
        p = json.loads(d["parsed_json"]).get("p") or {} if d["parsed_json"] else None
        p, used = hand.patch_reading(updates, d["doc_id"], p)
        kind, basis = classify(d["heading"], (p or {}).get("form"), (p or {}).get("doc_type"))
        if basis == "none":
            kind, basis = classify(d["heading"], d["form"], d["doc_type"])
        reason = None
        stated = ((p or {}).get("programme") or {}).get("buyback_type")
        if d["country"] not in known:
            reason = f"Market {d['country']} is not in data\\countries.json"
        elif OUT_OF_SCOPE.search(d["heading"] or ""):
            reason = "Out of scope: " + OUT_OF_SCOPE.search(d["heading"]).group(0).lower() + " (on-market buybacks only)"
        elif not d["ticker"]:
            reason = "No company chosen for this filing"
        elif stated and not re.search(r"on[- ]?market", stated, re.I):
            reason = f"Out of scope: {stated} (on-market buybacks only)"
        elif kind == "Cancellation of shares" and ((p or {}).get("cessations") or []) and not any(c.get("is_buyback") for c in p["cessations"]):
            reason = "Cessation not from a buyback"
        elif kind == "Issue of securities":
            reason = "Issue of securities (Appendix 3G): kept on the company panel, not part of a buyback"
        level, why = confidence(kind, p) if p is not None else ("not read", "Nothing has been read from this filing")
        if used:
            level, why = "updated manually", " | ".join(used)
        out.append({"doc_id": d["doc_id"], "link": d["source_url"] or "", "country": d["country"], "ticker": d["ticker"], "company": d["company"], "title": d["heading"],
                    "filed": d["doc_date"] or (p or {}).get("doc_date"), "type": kind, "type_basis": basis, "in_scope": 0 if reason else 1, "excluded_reason": reason,
                    "confidence": level, "low_reason": why, "reader": (p or {}).get("form"), "p": p})
    held = {n["link"] for n in out if n["link"]}
    for s in con.execute("select link, reason, ticker, country, heading from skipped_links"):
        if s["link"] not in held:
            out.append({"doc_id": None, "link": s["link"], "country": s["country"], "ticker": s["ticker"], "company": None, "title": s["heading"], "filed": None,
                        "type": classify(s["heading"], None, None)[0], "type_basis": "title", "in_scope": 0, "excluded_reason": "Removed by you" if s["reason"] == "Removed by you" else s["reason"],
                        "confidence": None, "low_reason": None, "reader": None, "p": None})
    return out


def _summary(p):
    """The few figures of a notice shown in the Notices table."""
    tx, g = p.get("transactions") or [], p.get("programme") or {}
    snap = (p.get("snapshots") or [{}])[-1]
    kinds = {t.get("currency") for t in tx if t.get("value") is not None and t.get("currency")}
    several = len(kinds) > 1  # one notice can report buying in more than one currency: amounts are then not added
    priced = [t["value"] for t in tx if t.get("value") is not None]
    return {"purchase_date": tx[0].get("trade_date") if tx else None, "shares": sum(t.get("shares") or 0 for t in tx) if tx else None, "amount": sum(priced) if priced and not several else None,
            "amount_basis": "Several currencies, not added" if several else None if not priced else "Reported" if all(t.get("value_origin") == "reported" for t in tx if t.get("value") is not None)
            else "Entered by hand" if all(t.get("value_origin") == "hand" for t in tx if t.get("value") is not None)
            else "Updated Manually" if any(t.get("value_origin") == "updated" for t in tx if t.get("value") is not None) else "Calculated",
            "currency": ("/".join(sorted(kinds)) if several else None) or (tx[0].get("currency") if tx else None) or snap.get("currency") or g.get("max_currency"),
            "total_shares": snap.get("cum_shares"), "total_amount": snap.get("cum_value"), "planned_amount": g.get("max_value")}


# ---------- programmes ----------
def _days(a, b):
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except (TypeError, ValueError):
        return 10 ** 6


def _plans(notices):
    """One programme per company per announcement. Returns the programmes; each notice gets "plan" (its index) and "tie" (how it was tied)."""
    companies = {}
    for n in sorted((n for n in notices if n["in_scope"] and n["ticker"] and n["p"] is not None), key=lambda n: (n["country"], n["ticker"], n["filed"] or "9999", n["doc_id"])):
        companies.setdefault((n["country"], n["ticker"]), []).append(n)
    currency = {c["code"]: c.get("currency") for c in countries.load()}
    today, made = date.today().isoformat(), []
    for (market, ticker), items in companies.items():
        plans = []

        def new_plan(announced, basis):
            plans.append({"announced": announced or "", "announced_basis": basis, "items": []})
            return plans[-1]

        def find(announced):
            return next((x for x in plans if announced and x["announced"] == announced), None)

        def unassigned():
            return next((x for x in plans if not x["announced"]), None)

        def latest_before(day):
            ok = [x for x in plans if x["announced"] and day and x["announced"] <= day]
            return max(ok, key=lambda x: x["announced"]) if ok else None

        def tie(it, plan, method):
            plan["items"].append(it)
            it["tie"] = method

        for it in items:  # 1. the form names its programme
            g = it["p"].get("programme") or {}
            if it["p"].get("form") == "appendix_3c":
                tie(it, find(g.get("announced_date")) or new_plan(g.get("announced_date"), "Notification form"), "Form field 1.4c: date of initial notification")
        for it in items:  # 2. company announcements of a programme
            p, g = it["p"], it["p"].get("programme") or {}
            if "tie" in it or p.get("doc_type") != "programme":
                continue
            day = g.get("announced_date") or it["filed"] or ""
            plan = find(g.get("announced_date")) if not g.get("announced_assumed") else None
            method = "Programme date stated in the announcement"
            if not plan:
                near = [x for x in plans if _days(x["announced"], day) <= 10]
                plan, method = (min(near, key=lambda x: _days(x["announced"], day)), "Company announcement within 10 days of the programme's notification") if near else (None, method)
            if not plan and g.get("max_value"):
                same = [x for x in plans if x["announced"] and x["announced"] <= day and any((i["p"].get("programme") or {}).get("max_value") == g["max_value"] for i in x["items"])
                        and not any(i["p"].get("doc_type") == "final" and (i["filed"] or "") < day for i in x["items"])]
                plan, method = (max(same, key=lambda x: x["announced"]), "Company announcement restating a running programme of the same size") if same else (None, method)
            if not plan:
                plan, method = new_plan(day, "Company announcement"), "New programme from the company's announcement"
            tie(it, plan, method)
        # 3. everything else. A filing that states no mandate date (the Hong Kong daily report) is placed after those that do, so it joins the mandate by purchase date whatever the filing dates
        for it in sorted(items, key=lambda i: bool((i["p"].get("programme") or {}).get("mandate_undated"))):
            if "tie" in it:
                continue
            p, g = it["p"], it["p"].get("programme") or {}
            tx, cess = p.get("transactions") or [], [c for c in p.get("cessations") or [] if c.get("is_buyback")]
            day = (min(t["trade_date"] for t in tx) if tx else cess[0].get("ceased_on") if cess else None) or it["filed"] or ""
            if p.get("doc_type") == "update" and p.get("form") == "manual" and find(g.get("announced_date")):  # a change entered by hand names its programme
                tie(it, find(g["announced_date"]), "Programme chosen when the change was entered by hand")
            elif p.get("doc_type") == "update":
                plan = latest_before(it["filed"] or day)
                tie(it, plan or (unassigned() or new_plan("", "Not identified")), "Change to terms applied to the latest programme announced before it" if plan else "No programme announcement found")
            elif g.get("announced_date"):
                plan = find(g["announced_date"])
                near = [x for x in plans if _days(x["announced"], g["announced_date"]) <= 3] if not plan else []
                if plan or near:
                    tie(it, plan or near[0], "Programme date cited in the notice" if plan else "Programme date cited in the notice, within 3 days of the announcement read")
                else:
                    tie(it, new_plan(g["announced_date"], "Cited in notices; announcement not read"), "Programme date cited in the notice")
            else:
                plan = latest_before(day)
                mandate = bool(g.get("mandate_undated"))
                tie(it, plan or (unassigned() or new_plan("", "Mandate, date not stated" if mandate else "Not identified")),
                    "Latest programme announced on or before the purchase date" if plan else "Bought under the shareholder mandate; the filing doesn't state its date" if mandate else "No programme announcement found")

        ordered = sorted(plans, key=lambda x: x["announced"])
        for at, plan in enumerate(ordered):
            later_buying = any(x["announced"] and any(i["p"].get("transactions") for i in x["items"]) for x in ordered[at + 1:]) and bool(plan["announced"])
            d = {"country": market, "ticker": ticker, "company": items[0]["company"] or ticker, "announced": plan["announced"], "announced_basis": plan["announced_basis"], "type": None,
                 "start": None, "end": None, "currency": currency.get(market), "planned_amount": None, "planned_currency": None, "planned_shares": None, "planned_pct": None, "intended_shares": None, "shares_on_issue": None,
                 "brokers": [], "treatment": None, "changes": [], "final_shares": None, "final_value": None, "completed_on": None, "cum_shares": None, "cum_value": None, "cum_as_of": None, "totals": {}}
            buys, low = {}, 0
            for it in sorted(plan["items"], key=lambda i: (i["filed"] or "9999", i["doc_id"])):
                p, g = it["p"], it["p"].get("programme") or {}
                low += it["confidence"] == "low"
                d["type"] = g.get("buyback_type") or d["type"]
                if g.get("start_date"):
                    d["start"] = min(d["start"], g["start_date"]) if d["start"] else g["start_date"]  # a later update never moves the start later
                d["end"] = g.get("end_date") or d["end"]
                if g.get("max_value") and (g["max_value"], g.get("max_currency")) != (d["planned_amount"], d["planned_currency"]):
                    if d["planned_amount"]:
                        d["changes"].append(f"{it['filed']}: planned amount {d['planned_currency']} {d['planned_amount']:,.0f} to {g.get('max_currency')} {g['max_value']:,.0f}")
                    d["planned_amount"], d["planned_currency"] = g["max_value"], g.get("max_currency")
                d["planned_shares"] = g.get("max_shares") or d["planned_shares"]
                d["planned_pct"] = g.get("max_pct") or d["planned_pct"]  # stated only as a percentage of the shares: kept as a percentage
                d["intended_shares"] = g.get("intended_shares") or d["intended_shares"]  # what the company expects to buy: never the limit
                d["shares_on_issue"] = g.get("shares_on_issue") or d["shares_on_issue"]
                d["treatment"] = g.get("treatment") or d["treatment"]
                name = (p.get("broker") or {}).get("name") or g.get("broker")
                if name and name not in d["brokers"]:
                    d["brokers"].append(name)
                if p.get("reason") and p.get("doc_type") == "update" and it["filed"]:
                    d["changes"].append(f"{it['filed']}: {p['reason']}")
                for t in p.get("transactions") or []:
                    buys[(t["trade_date"], t.get("venue") or "")] = t  # a later filing for the same day and venue replaces the earlier one
                for s in p.get("snapshots") or []:
                    if s.get("cum_shares") is not None and s.get("as_of"):
                        d["totals"][s["as_of"]] = [s["as_of"], s["cum_shares"], s.get("cum_value")]  # every running total, for the cross-check
                    if p.get("doc_type") == "final":
                        d["final_shares"], d["final_value"], d["completed_on"] = s.get("cum_shares"), s.get("cum_value"), it["filed"]
                    elif s.get("cum_shares") is not None and s.get("as_of") and (not d["cum_as_of"] or s["as_of"] >= d["cum_as_of"]):
                        d["cum_shares"], d["cum_value"], d["cum_as_of"] = s["cum_shares"], s.get("cum_value"), s["as_of"]
                if it["type"] == "Completion":
                    d["completed_on"] = d["completed_on"] or it["filed"]
            kinds = [t.get("security") for t in buys.values() if t.get("security")]
            if len(set(kinds)) > 1:  # two classes of share (A and H): the class bought on the home exchange is the programme's; the other is listed beside it, not added
                home = next((t["security"] for t in buys.values() if t.get("security") and t.get("currency") == d["currency"]), kinds[0])
                d["security"] = home
                d["other_securities"] = "; ".join(f"{s} {sum(t.get('shares') or 0 for t in buys.values() if t.get('security') == s):,.0f} shares" for s in sorted(set(kinds)) if s != home)
                counted = {k: t for k, t in buys.items() if t.get("security") in (home, None)}
            else:
                d["security"], d["other_securities"], counted = (kinds[0] if kinds else None), None, buys
            d["purchases"] = len({k[0] for k in buys})
            d["first_purchase"], d["last_purchase"] = (min(k[0] for k in buys), max(k[0] for k in buys)) if buys else (None, None)
            d["sum_shares"] = sum(t.get("shares") or 0 for t in counted.values())
            seen = [t.get("currency") for t in buys.values() if t.get("currency")]
            d["buy_currency"] = (d["currency"] if d["currency"] in seen else seen[0] if seen else None) or d["currency"]
            priced = [t for t in buys.values() if t.get("value") is not None and (t.get("currency") or d["buy_currency"]) == d["buy_currency"]]
            d["sum_value"] = sum(t["value"] for t in priced) if priced else None
            others = {}
            for t in buys.values():
                if t.get("value") is not None and t.get("currency") and t["currency"] != d["buy_currency"]:
                    others[t["currency"]] = others.get(t["currency"], 0) + t["value"]
            d["other_currencies"] = "; ".join(f"{c} {v:,.2f}" for c, v in sorted(others.items())) or None  # never added to the amount above
            d["unpriced"] = len([t for t in buys.values() if t.get("value") is None])
            d["calculated_values"] = sum(1 for t in priced if t.get("value_origin") not in ("reported", "hand", "updated"))
            d["hand_notices"] = sum(1 for i in plan["items"] if i["p"].get("form") == "manual")  # entries made by hand among its notices
            d["totals"] = [d["totals"][k] for k in sorted(d["totals"])]
            d["daily"] = sorted(([k[0], k[1], t.get("shares"), t.get("value"), t.get("price_avg"), t.get("price_unit")] for k, t in buys.items()), key=lambda x: x[:2])
            if d["final_shares"] is not None:
                d["shares_bought"], d["spent"], d["spent_basis"], d["spent_origin"] = d["final_shares"], d["final_value"], "Final notice", "Reported"
            elif d["cum_shares"] is not None and d["cum_shares"] >= d["sum_shares"]:
                d["shares_bought"], d["spent"], d["spent_basis"], d["spent_origin"] = d["cum_shares"], d["cum_value"], f"Running total in the notice of {d['cum_as_of']}", "Reported"
                if d["cum_value"] is None and d["sum_value"] is not None:  # the running total states shares only; say so where Spent is empty
                    d["spent_basis"] = f"The running total in the notice of {d['cum_as_of']} states shares only, so no amount spent is known. The purchases read add up to {d['buy_currency'] or ''} {d['sum_value']:,.2f}, which may not be every purchase"
            else:
                d["shares_bought"], d["spent"] = d["sum_shares"], d["sum_value"]
                d["spent_basis"] = "Sum of the purchases read" + (" (some amounts calculated as shares x average price)" if d["calculated_values"] else "")
                d["spent_origin"] = "Calculated"
            same = d["planned_amount"] and d["spent"] is not None and (d["planned_currency"] or d["buy_currency"]) == d["buy_currency"]
            d["pct_used"] = round(100 * d["spent"] / d["planned_amount"], 2) if same else None  # never worked out across two currencies
            d["status"] = ("Completed" if d["completed_on"] else "Target reached" if d["pct_used"] is not None and d["pct_used"] >= 99.5
                           else "Ended, no final notice" if (d["end"] and d["end"] < today) or later_buying else "In progress")  # a later programme of the company is buying, so this one has ended
            d["notices"], d["low"] = len(plan["items"]), low
            d["brokers"], d["changes"] = "; ".join(d["brokers"]), " | ".join(d["changes"])
            for it in plan["items"]:
                it["plan"] = len(made)
            made.append(d)
    return made


def _checks(d):
    """One programme against the running totals in its own filings. Differences are listed and never applied."""
    out = []
    upto = lambda day, i: sum((x[i] or 0) for x in d["daily"] if x[0] <= day)
    between = lambda a, b, i: sum((x[i] or 0) for x in d["daily"] if a < x[0] <= b)

    def compare(name, expected, found, what, ok_gap):
        if expected is None or found is None:
            return out.append((name, "Not checkable", f"No {what} to compare", None, None))
        gap = expected - found
        out.append((name, "Match" if abs(gap) <= ok_gap else "Difference",
                    f"Filing states {expected:,.2f}; purchases read add to {found:,.2f}" + ("" if abs(gap) <= ok_gap else f"; {abs(gap):,.2f} {'not covered by' if gap > 0 else 'more than'} the purchases read"), expected, found))

    totals, money = d["totals"], d["sum_value"] is not None and not d["unpriced"]
    if totals and d["daily"]:  # history before the first notice held
        compare("Purchases before the first running total", totals[0][1], upto(totals[0][0], 2), "running total", 0.5)
    else:
        out.append(("Purchases before the first running total", "Not checkable", "No running total, or no purchases, in the notices read", None, None))
    for name, i, on, gap_ok in (("Shares between running totals", 1, True, lambda v: 0.5), ("Amount between running totals", 2, money, lambda v: max(1.0, 0.00001 * abs(v)))):
        pairs = [(a, b) for a, b in zip(totals, totals[1:]) if a[i] is not None and b[i] is not None] if on and d["daily"] else []
        if not pairs:
            out.append((name, "Not checkable", "Fewer than two running totals, or purchases without amounts", None, None))
            continue
        bad = [(a, b, b[i] - a[i], between(a[0], b[0], i + 1)) for a, b in pairs]
        bad = [x for x in bad if abs(x[2] - x[3]) > gap_ok(x[2])]
        if not bad:
            out.append((name, "Match", f"{len(pairs)} steps between running totals agree with the purchases read", None, None))
        else:
            a, b, rise, read = bad[0]
            out.append((name, "Difference", f"{len(bad)} of {len(pairs)} steps differ. First: {a[0]} to {b[0]} the running total rises {rise:,.2f}; purchases read add to {read:,.2f}", rise, read))
    if d["planned_amount"] and d["pct_used"] is not None:
        over, slack = d["spent"] - d["planned_amount"], max(1000.0, 0.001 * d["planned_amount"])
        out.append(("Spent against planned amount", "Match" if over <= slack else "Difference", f"Planned {d['planned_amount']:,.2f}; spent {d['spent']:,.2f}" + (f"; {over:,.2f} over" if over > slack else ""), d["planned_amount"], d["spent"]))
    else:
        out.append(("Spent against planned amount", "Not checkable", "No planned amount in the same currency", None, None))
    return out


# ---------- building and keeping current ----------
def ensure(con):
    con.executescript(SCHEMA)


def signature(con):
    """Changes whenever a filing is added, read again, moved, removed or set aside, and once a day (a programme's end date may have passed)."""
    h = hashlib.sha1(f"{RULES_VERSION}|{date.today().isoformat()}".encode())
    for r in con.execute("select doc_id, country, ticker, doc_date, heading, length(parsed_json), imported_at from documents order by doc_id"):
        h.update(repr(tuple(r)).encode())
    for r in con.execute("select link, reason from skipped_links order by link"):
        h.update(repr(tuple(r)).encode())
    for r in con.execute("select country, ticker, company from companies order by country, ticker"):
        h.update(repr(tuple(r)).encode())
    for r in con.execute("select entry_id, status, updated_at, fields from hand_entries where kind='update' order by entry_id"):  # an update made or undone runs the Tracker again
        h.update(repr(tuple(r)).encode())
    return h.hexdigest()


def run(con):
    """Rebuild the tracker's tables from the filings held. Nothing else in the database is written."""
    with LOCK:
        ensure(con)
        con.commit()
        started, mark = db.now(), signature(con)
        notices = _notices(con)
        plans = _plans(notices)
        try:
            for table in ("tracker_notices", "tracker_plans", "tracker_checks"):
                con.execute(f"delete from {table}")
            ids, results = [], {}
            for d in plans:
                ids.append(con.execute("insert into tracker_plans(country,ticker,data) values(?,?,?)", (d["country"], d["ticker"], json.dumps(d))).lastrowid)
                rows = _checks(d)
                con.executemany("insert into tracker_checks(plan_id,name,result,detail,expected,found) values(?,?,?,?,?,?)", [(ids[-1], *x) for x in rows])
                for x in rows:
                    results[x[1]] = results.get(x[1], 0) + 1
            con.executemany("insert into tracker_notices(doc_id,link,country,ticker,company,title,filed,type,type_basis,in_scope,excluded_reason,confidence,low_reason,reader,plan_id,tie_method,data) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [(n["doc_id"], n["link"], n["country"], n["ticker"], n["company"], n["title"], n["filed"], n["type"], n["type_basis"], n["in_scope"], n["excluded_reason"], n["confidence"], n["low_reason"],
                              n["reader"], ids[n["plan"]] if "plan" in n else None, n.get("tie"), json.dumps(_summary(n["p"])) if n["p"] is not None else None) for n in notices])
            scope = [n for n in notices if n["in_scope"]]
            report = {"notices": len(notices), "in scope": len(scope), "excluded": len(notices) - len(scope), "programmes": len(plans),
                      "by confidence": {k: sum(1 for n in scope if n["confidence"] == k) for k in ("high", "medium", "low", "n/a", "not read")}, "cross-check": results}
            con.execute("insert into tracker_runs(started,finished,signature,report) values(?,?,?,?)", (started, db.now(), mark, json.dumps(report)))
            con.execute("delete from tracker_runs where run_id not in (select run_id from tracker_runs order by run_id desc limit 50)")
            con.commit()
        except Exception:
            con.rollback()
            raise
        return report


def current(con, busy=False):
    """Bring the tracker up to date when the filings held have changed since it was last built. While a list is being read it is left as it is.
    Returns the last build: when, and whether it is behind."""
    ensure(con)
    last = con.execute("select finished, signature from tracker_runs order by run_id desc limit 1").fetchone()
    behind = not last or last["signature"] != signature(con)
    if behind and not busy:
        run(con)
        last, behind = con.execute("select finished, signature from tracker_runs order by run_id desc limit 1").fetchone(), False
    return {"built": last["finished"] if last else None, "behind": behind}


# ---------- what the screens show ----------
def _market(country):
    c = countries.get(str(country or "").upper())
    if not c:
        raise ValueError("Choose an exchange at the top of the page. The tracker shows one exchange at a time.")
    return c


def _where(country, ticker):
    ticker = str(ticker or "").strip().upper()
    return ("country=? and ticker=?", (country, ticker)) if ticker else ("country=?", (country,))


def _plan_rows(con, country, ticker):
    where, args = _where(country, ticker)
    checks = {}
    for c in con.execute(f"select plan_id, result, count(*) n from tracker_checks where plan_id in (select plan_id from tracker_plans where {where}) group by plan_id, result", args):
        checks.setdefault(c["plan_id"], {"Match": 0, "Difference": 0, "Not checkable": 0})[c["result"]] = c["n"]
    out = []
    for r in con.execute(f"select plan_id, data from tracker_plans where {where} order by ticker, plan_id", args):
        d = json.loads(r["data"])
        d.pop("totals"), d.pop("daily")
        t = checks.get(r["plan_id"], {"Match": 0, "Difference": 0, "Not checkable": 0})
        out.append({"plan_id": r["plan_id"], **d, "matches": t["Match"], "differences": t["Difference"], "check": "Difference" if t["Difference"] else "Match" if t["Match"] else "Not checkable"})
    return out


def overview(con, country, ticker="", busy=False):
    """One exchange, programme by programme."""
    c, state = _market(country), current(con, busy)
    plans = _plan_rows(con, c["code"], ticker)
    where, args = _where(c["code"], ticker)
    n = {r["k"]: r["n"] for r in con.execute(f"select case when in_scope=0 then 'excluded' else coalesce(confidence,'not read') end k, count(*) n from tracker_notices where {where} group by 1", args)}
    scope = sum(v for k, v in n.items() if k != "excluded")
    span = con.execute(f"select min(filed), max(filed) from tracker_notices where in_scope=1 and {where}", args).fetchone()
    gaps = []
    if plans:
        no_plan = sum(1 for p in plans if p["planned_amount"] is None and p["planned_shares"] is None)
        cited = sum(1 for p in plans if "not read" in (p["announced_basis"] or ""))
        loose = sum(1 for p in plans if not p["announced"] and not str(p["announced_basis"] or "").startswith("Mandate"))
        undated = sum(1 for p in plans if not p["announced"] and str(p["announced_basis"] or "").startswith("Mandate"))
        diff = sum(p["differences"] for p in plans)
        if no_plan:
            gaps.append(f"{no_plan} of {len(plans)} programmes have no planned amount or share limit read.")
        if cited:
            gaps.append(f"{cited} programme{'s are' if cited != 1 else ' is'} known only from the date cited in purchase notices; the announcement itself has not been read.")
        if loose:
            gaps.append(f"{loose} group{'s' if loose != 1 else ''} of notices could not be tied to a programme announcement (shown as Programme not identified).")
        if undated:
            gaps.append(f"{undated} mandate{'s have' if undated != 1 else ' has'} no date: the filings read say the buying was under a repurchase mandate but not when it was granted, or its size.")
        if n.get("low"):
            gaps.append(f"{n['low']} notice{'s are' if n['low'] != 1 else ' is'} low confidence: a required figure was not found, and it is left blank.")
        if n.get("not read"):
            gaps.append(f"{n['not read']} filing{'s have' if n['not read'] != 1 else ' has'} nothing read from {'them' if n['not read'] != 1 else 'it'} yet.")
        if diff:
            gaps.append(f"{diff} cross-check difference{'s' if diff != 1 else ''}, mostly a purchase notice missing between two running totals.")
        if n.get("excluded"):
            gaps.append(f"{n['excluded']} filing{'s are' if n['excluded'] != 1 else ' is'} excluded as out of scope (see the Excluded tab).")
        gaps += ["On-market buybacks only.", "Only the filings held in this app. Nothing is listed from an exchange feed."]
    return {"country": c["code"], "name": c["name"], "exchange": c.get("exchange", ""), "ticker": str(ticker or "").upper(), **state, "from": span[0], "to": span[1], "plans": plans,
            "counts": {"notices": scope, "low": n.get("low", 0), "excluded": n.get("excluded", 0), "differences": sum(p["differences"] for p in plans)}, "not_covered": gaps}


def _notice_row(r):
    return {**{k: r[k] for k in ("notice_id", "doc_id", "link", "country", "ticker", "company", "title", "filed", "type", "type_basis", "confidence", "low_reason", "reader", "plan_id", "tie_method")},
            **(json.loads(r["data"]) if r["data"] else {})}


def _plan_label(con, country):
    return {r["plan_id"]: f"{r['ticker']} · announced {json.loads(r['data'])['announced'] or 'not identified'}" for r in con.execute("select plan_id, ticker, data from tracker_plans where country=?", (country,))}


def notices(con, country, ticker="", busy=False):
    c, state = _market(country), current(con, busy)
    where, args = _where(c["code"], ticker)
    label = _plan_label(con, c["code"])
    rows = [_notice_row(r) for r in con.execute(f"select * from tracker_notices where in_scope=1 and {where} order by coalesce(filed,'') desc, notice_id desc", args)]
    for r in rows:
        r["plan_label"] = label.get(r["plan_id"], "")
    return {**state, "rows": rows}


def checks(con, country, ticker="", busy=False):
    c, state = _market(country), current(con, busy)
    where, args = _where(c["code"], ticker)
    label = _plan_label(con, c["code"])
    rows = db.rows(con.execute(f"select k.plan_id, p.ticker, k.name, k.result, k.detail, k.expected, k.found from tracker_checks k join tracker_plans p on p.plan_id=k.plan_id where {where.replace('country', 'p.country').replace('ticker=', 'p.ticker=')} order by p.ticker, k.plan_id, k.rowid", args))
    for r in rows:
        r["plan_label"] = label.get(r["plan_id"], "")
    return {**state, "rows": rows}


def excluded(con, country, ticker="", busy=False):
    c, state = _market(country), current(con, busy)
    where, args = _where(c["code"], ticker)
    return {**state, "rows": db.rows(con.execute(f"select notice_id, doc_id, ticker, filed, type, title, excluded_reason reason, link from tracker_notices where in_scope=0 and {where} order by coalesce(filed,'') desc, notice_id desc", args))}


def plan(con, plan_id):
    """One programme in full: every field, its checks, and its notices in date order."""
    ensure(con)
    r = con.execute("select plan_id, data from tracker_plans where plan_id=?", (int(plan_id or 0),)).fetchone()
    if not r:
        raise ValueError("That programme isn't in the tracker any more. Open the Tracker again.")
    d = json.loads(r["data"])
    d.pop("daily")
    found = db.rows(con.execute("select name, result, detail from tracker_checks where plan_id=? order by rowid", (r["plan_id"],)))
    d["check"] = "Difference" if any(c["result"] == "Difference" for c in found) else "Match" if any(c["result"] == "Match" for c in found) else "Not checkable"
    named = d["announced_basis"] == "Notification form"  # the form's own field names are given only where the programme comes from the ASX form
    money = {"planned_amount": d["planned_currency"], "spent": d["buy_currency"], "sum_value": d["buy_currency"], "cum_value": d["buy_currency"], "final_value": d["buy_currency"]}
    fields = [{"key": k, "name": name, "form_name": PLAN_FORM_NAMES.get(k, "") if named else "", "value": d.get(k), "currency": money.get(k)}
              for k, name in PLAN_COLUMNS if k != "spent_origin" and d.get(k) not in (None, "")]
    from . import periods
    held = con.execute("select prog_id from programmes where country=? and ticker=? and announced_date=?", (d["country"], d["ticker"], d["announced"] or "")).fetchone()
    return {"plan_id": r["plan_id"], **d, "fields": fields, "checks": found, "periods": periods.for_company(con, d["country"], d["ticker"]).get(held["prog_id"]) if held else None,
            "timeline": [_notice_row(n) for n in con.execute("select * from tracker_notices where plan_id=? order by coalesce(filed,'9999'), notice_id", (r["plan_id"],))]}


PLAN_FORM_NAMES = {"announced": "1.4c Date of initial notification of buy-back", "type": "2.1 The type of buy-back is", "start": "3C.2 Proposed buy-back start date", "end": "3C.3 Proposed buy-back end date",
                   "planned_shares": "3A.5a Maximum number of +securities", "shares_on_issue": "3A.1 Total number of +securities on issue", "brokers": "3A.6 Name of broker or brokers",
                   "planned_amount": "3D.1 Any other information", "final_shares": "5.1 Total number of +securities bought back", "final_value": "5.2 Total consideration paid or payable",
                   "cum_shares": "4.3 Total number of +securities bought back", "cum_value": "4.4 Total consideration paid or payable"}
NAMES = {  # key: (name on the ASX form, plain English)
    "doc_date": ("1.5 Date of this announcement", "Filing date"), "announced_date": ("1.4c Date of initial notification of buy-back", "Programme first announced"),
    "previous_date": ("1.4d Date of previous announcement to this update", "Previous notice"), "reason": ("1.4a/1.4b Type of and reason for update", "What this notice is"),
    "buyback_type": ("2.1 The type of buy-back is", "Buyback type"), "shares_on_issue": ("3A.1 Total number of +securities on issue in the class", "Shares on issue"),
    "max_shares": ("3A.5a Maximum number of +securities", "Maximum shares to buy"), "broker": ("3A.6 Name of broker or brokers", "Broker"),
    "start_date": ("3C.2 Proposed buy-back start date", "Programme start"), "end_date": ("3C.3 Proposed buy-back end date", "Programme end"),
    "hand_source": ("", "Entered by hand. Source"), "hand_note": ("", "Note entered with it"), "max_pct": ("", "Maximum as % of shares"), "intended_shares": ("", "Intended number of shares (approximate, not a limit)"),
    "max_value": ("3D.1 Any other information", "Planned amount"), "max_currency": ("", "Currency of the planned amount"), "treatment": ("", "What happens to the shares"),
    "size_note": ("", "Change of size"), "trade_date": ("4.2 Previous day on which +securities were bought back", "Purchase date"), "venue": ("", "Trading venue"), "also_in": ("", "Also reported in another market's notices"), "security": ("", "Class of share"),
    "shares": ("4.3 Total number of +securities bought back on previous day", "Shares bought on the day"), "value": ("4.4 Total consideration paid or payable on previous day", "Amount paid on the day"),
    "price_avg": ("", "Average price paid"), "price_high": ("4.5 Highest price paid", "Highest price paid"), "price_low": ("4.6 Lowest price paid", "Lowest price paid"),
    "price_unit": ("", "Price unit"), "currency": ("", "Currency"), "value_origin": ("", "Amount is reported, a sum of the filing's rows, or calculated as shares x average price"),
    "as_of": ("", "Total as of"), "cum_shares": ("4.3 / 5.1 Total number of +securities bought back", "Total shares bought to date"), "cum_value": ("4.4 / 5.2 Total consideration paid or payable", "Total paid to date"),
    "ceased_on": ("Date of cessation", "Date cancelled"), "security": ("ASX +security code and description", "Security"), "consideration": ("Total consideration paid or payable", "Amount for the cancellation"),
    "issued_after": ("3.1 Quoted +equity securities (total number)", "Shares on issue afterwards"), "is_buyback": ("", "Cancelled because of a buyback"), "other_info": ("Any other information", "Other information"),
}


def notice(con, notice_id):
    """One notice: its type, confidence, programme, and every field read from it. Form names are given only for the ASX form, where they are known."""
    ensure(con)
    r = con.execute("select * from tracker_notices where notice_id=?", (int(notice_id or 0),)).fetchone()
    if not r:
        raise ValueError("That notice isn't in the tracker any more. Open the Tracker again.")
    d = con.execute("select parsed_json from documents where doc_id=?", (r["doc_id"],)).fetchone() if r["doc_id"] else None
    p = (json.loads(d["parsed_json"]).get("p") or {}) if d and d["parsed_json"] else {}
    named, out = p.get("form") in ("appendix_3c", "appendix_3h"), []

    def add(key, value, prefix=""):
        if value in (None, "", [], {}):
            return
        name = NAMES.get(key, ("", key.replace("_", " ").capitalize()))
        out.append({"form_name": name[0] if named else "", "name": prefix + name[1], "value": value})

    add("doc_date", p.get("doc_date"))
    add("reason", p.get("reason"))
    add("previous_date", p.get("previous_date"))
    if p.get("form") == "manual":
        add("hand_source", (p.get("manual") or {}).get("source"))
        add("hand_note", (p.get("manual") or {}).get("note"))
    for k, v in (p.get("programme") or {}).items():
        if k not in ("max_text", "treatment_text", "announced_assumed", "status"):
            add(k, v)
    many = len(p.get("transactions") or []) > 1
    for i, t in enumerate(p.get("transactions") or [], 1):
        for k in ("trade_date", "venue", "security", "also_in", "shares", "value", "currency", "price_avg", "price_high", "price_low", "price_unit", "value_origin"):
            add(k, t.get(k), f"Purchase {i}: " if many else "")
    for s in p.get("snapshots") or []:
        for k in ("as_of", "cum_shares", "cum_value"):
            add(k, s.get(k))
    for i, c in enumerate(p.get("cessations") or [], 1):
        for k in ("ceased_on", "security", "shares", "reason", "consideration", "currency", "issued_after", "is_buyback", "other_info"):
            add(k, c.get(k), f"Cancellation {i}: ")
    label = con.execute("select ticker, data from tracker_plans where plan_id=?", (r["plan_id"],)).fetchone() if r["plan_id"] else None
    return {**_notice_row(r), "in_scope": r["in_scope"], "excluded_reason": r["excluded_reason"], "fields": out,
            "plan_label": f"{label['ticker']} · announced {json.loads(label['data'])['announced'] or 'not identified'}" if label else ""}


# ---------- Excel ----------
PLAN_COLUMNS = [("company", "Company"), ("ticker", "Code"), ("status", "Status"), ("announced", "Programme first announced"), ("announced_basis", "How the announcement date is known"),
                ("type", "Buyback type"), ("start", "Programme start"), ("end", "Programme end"), ("planned_amount", "Planned amount"), ("planned_currency", "Currency of the planned amount"),
                ("planned_shares", "Maximum shares to buy"), ("planned_pct", "Maximum as % of shares"), ("intended_shares", "Intended number of shares (approximate, not a limit)"), ("shares_on_issue", "Shares on issue"), ("brokers", "Broker or brokers"), ("treatment", "What happens to the shares"),
                ("shares_bought", "Shares bought so far"), ("spent", "Amount spent so far"), ("buy_currency", "Currency of the purchases"), ("other_currencies", "Spent in other currencies (not added)"), ("security", "Class of share"), ("other_securities", "Other classes bought (not added)"), ("spent_origin", "Reported or Calculated"), ("spent_basis", "Where the amount spent comes from"),
                ("pct_used", "Percent of planned amount used (Calculated)"), ("purchases", "Purchase days read"), ("first_purchase", "First purchase"), ("last_purchase", "Latest purchase"),
                ("sum_shares", "Shares in the purchases read"), ("sum_value", "Amount in the purchases read"), ("cum_shares", "Latest running total of shares"), ("cum_value", "Latest running total of amount"),
                ("cum_as_of", "Running total as of"), ("final_shares", "Final notice: shares"), ("final_value", "Final notice: amount"), ("completed_on", "Completed on"), ("changes", "Changes to terms"),
                ("notices", "Notices tied to it"), ("hand_notices", "Of which entered by hand"), ("low", "Low-confidence notices"), ("check", "Cross-check result")]


def workbook(con, country, busy=False):
    """The tracker for one exchange as an Excel file under reports/. Returns the file."""
    from datetime import datetime
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    from .report import REPORTS, _date_cell
    o = overview(con, country, "", busy)
    held, checked, left = notices(con, country)["rows"], checks(con, country)["rows"], excluded(con, country)["rows"]
    wb = Workbook()

    def sheet(title, headers, rows, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.append(headers)
        for cell in ws[1]:
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3A5F")
        for r in rows:
            ws.append(["" if v is None else _date_cell(v) for v in r])
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, datetime):
                    cell.number_format = "mm/dd/yyyy"
        ws.freeze_panes = "B2"
        if rows:
            ws.auto_filter.ref = ws.dimensions
        for i, h in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(i)].width = min(60, max([12, len(str(h)) + 2] + [len(str(r[i - 1])) + 2 for r in rows[:200] if r[i - 1] is not None]))
        return ws

    by = {s: sum(1 for p in o["plans"] if p["status"] == s) for s in STATUSES}
    planned, spent = {}, {}
    for p in o["plans"]:
        if p["planned_amount"]:
            planned[p["planned_currency"]] = planned.get(p["planned_currency"], 0) + p["planned_amount"]
        if p["spent"]:
            spent[p["buy_currency"]] = spent.get(p["buy_currency"], 0) + p["spent"]
    money = lambda m: "; ".join(f"{k} {v:,.2f}" for k, v in sorted(m.items()) if k)  # per currency, never added across currencies
    n = o["counts"]
    ws = sheet("Summary", ["Item", "Value"], [], first=True)
    for row in ([["Exchange", f"{o['name']} ({o['exchange']})"], ["Built", o["built"]], ["Filings from", o["from"]], ["Filings to", o["to"]], ["Programmes", len(o["plans"])]] + [[s, by[s]] for s in STATUSES]
                + [["Notices in scope", n["notices"]], ["Low-confidence notices", n["low"]], ["Low-confidence share", f"{100 * n['low'] / n['notices']:.1f}%" if n["notices"] else ""], ["Excluded", n["excluded"]],
                   ["Cross-check differences", n["differences"]], ["Planned amount, per currency", money(planned)], ["Amount spent so far, per currency", money(spent)], [], ["Not covered"]] + [[x] for x in o["not_covered"]]):
        ws.append(["" if v is None else _date_cell(v) for v in row])
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 36, 60
    sheet("Programmes", [h for _, h in PLAN_COLUMNS], [[p.get(k) for k, _ in PLAN_COLUMNS] for p in o["plans"]])
    cols = [("ticker", "Code"), ("company", "Company"), ("filed", "Filed"), ("type", "Type"), ("title", "Title"), ("confidence", "Confidence"), ("low_reason", "Why low"), ("purchase_date", "Purchase date"),
            ("shares", "Shares"), ("amount", "Amount"), ("amount_basis", "Reported or Calculated"), ("currency", "Currency"), ("total_shares", "Total shares to date"), ("total_amount", "Total amount to date"),
            ("planned_amount", "Planned amount"), ("plan_label", "Programme"), ("tie_method", "How it was tied"), ("link", "Link")]
    sheet("Notices", [h for _, h in cols], [[r.get(k) for k, _ in cols] for r in held])
    sheet("Cross-check", ["Code", "Programme", "Check", "Result", "Detail", "Filing states", "Purchases read"], [[r["ticker"], r["plan_label"], r["name"], r["result"], r["detail"], r["expected"], r["found"]] for r in checked])
    sheet("Excluded", ["Code", "Filed", "Type", "Title", "Reason", "Link"], [[r["ticker"], r["filed"], r["type"], r["title"], r["reason"], r["link"]] for r in left])
    REPORTS.mkdir(exist_ok=True)
    f = REPORTS / f"buyback_tracker_{o['country']}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    wb.save(f)
    return f
