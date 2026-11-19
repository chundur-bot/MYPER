"""Hong Kong: the HKEX Next Day Disclosure Return (form FF305), the Monthly Return (FF301) and the daily Share Repurchase Report.

The returns have rows that repeat (events, repurchases, several exchanges, several mandates), which a layout file in data/forms
can't describe, so they are read here. The result is the same record the other readers return, so everything after it is shared.

Rules kept throughout: a figure that isn't stated is left empty and goes to review ("Not stated"), never assumed; a value the form
states is Reported, a value worked out from others is Calculated and says how; amounts in different currencies are never added.
"""
import re
from collections import OrderedDict

from . import parsers

VENUE = "HKEX"  # "On the Exchange" in a return; "Exchange" in the daily report
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
D = rf"\d{{1,2}} (?:{MONTHS}) \d{{4}}"
CUR = r"(?:HKD|RMB|CNY|USD|GBP|EUR|SGD|AUD|NZD|JPY|CAD|CHF|TWD)"
CURRENCY = {"RMB": "CNY"}  # the code the rest of the app uses
NUM = r"[\d,]+(?:\.\d+)?"


def _cur(code):
    return CURRENCY.get(code, code)


def _n(text):
    return parsers.num(text) if text not in (None, "") else None


def _d(text):
    return parsers.to_date(text) if text else None


def _ticker(code):
    """The stock code without leading zeros (02429 and 2429 are the same company)."""
    digits = re.sub(r"\D", "", str(code or ""))
    return str(int(digits)) if digits else None


def _flat(text):
    """Page headers and footers removed, so a table can run across pages."""
    text = text.replace("\xa0", " ").replace("\f", "\n")
    return re.sub(r"^FF30\d\s*\n\s*vPage \d+ of \d+ [\d.]+\s*$", "", text, flags=re.M)


def _band(issues, who, day, cur, shares, paid, high, low):
    """The amount paid divided by the shares must sit between the lowest and highest price, allowing a little above the highest for stamp duty and fees."""
    if shares and paid and high and low:
        avg = paid / shares
        if avg < low * 0.999 or avg > high * 1.005:
            issues.append(("HK_PRICE_OUTSIDE", f"{who} on {day}: {paid:,.2f} {cur} for {shares:,.0f} shares is {avg:,.4f} a share, outside the stated range {low:g} to {high:g}. Please check it."))


ALIASES = {"nyse": "New York Stock Exchange", "lse": "London Stock Exchange", "sse": "Shanghai Stock Exchange", "szse": "Shenzhen Stock Exchange", "hkex": VENUE}


def _canon(name):
    """The same exchange is written differently in the returns and the daily report (NYSE, New York Stock Exchange): one name for each."""
    name = re.sub(r"\s+", " ", name or "").strip()
    return ALIASES.get(name.lower(), name) or "Another exchange (not named)"


OFF_MARKET = {"by private arrangement": "Private arrangement", "by general offer": "General offer"}
SECURITIES = {"ord": "Ordinary", "h shares": "H shares", "a shares": "A shares", "wvr ord": "WVR ordinary"}


def _venue(method, exchange):
    m = (method or "").strip().lower()
    return VENUE if m.startswith("on the exchange") else OFF_MARKET.get(m) or _canon(exchange)


def _security(cls="", kind=""):
    """The class of share as one label: the daily report writes ORD, H SHARES, A SHARES, WVR ORD; a return gives a class and a type (H, A or Not applicable)."""
    kind, cls = re.sub(r"\s+", " ", kind or "").strip(), re.sub(r"\s+", " ", cls or "").strip()
    if kind.lower() in SECURITIES:
        return SECURITIES[kind.lower()]
    if kind.upper() in ("H", "A"):
        return f"{kind.upper()} shares"
    if kind and kind.lower() != "not applicable":
        return kind
    return "Ordinary" if cls.lower() in ("ordinary shares", "ordinary") else (cls or None)


def is_return(text):
    return bool(re.search(r"\bFF30[15]\b", text[:400]))


def has_buyback(text):
    """A return that reports no repurchase (a share issue, a sale of treasury shares, a monthly return without buybacks) holds no buyback."""
    return bool(re.search(r"Repurchase of shares \(|A\. Repurchase report", text))


# ---------- Next Day Disclosure Return (FF305) and Monthly Return (FF301) ----------
def read_return(text, home):
    flat = _flat(text)
    monthly = bool(re.search(r"\bFF301\b", text[:400]))
    p = parsers._blank(form="hkex_monthly" if monthly else "hkex_ndr", doc_type="transaction")
    p.update(definition=p["form"], date_stated=True, venue_totals=[], cancellations=[])
    who = re.search(r"Name of Issuer:\s*(.+)", flat)
    if who:
        p["company"] = re.sub(r"\s*\(.*$", "", who.group(1)).strip()
    code = re.search(r"Stock code \(if listed\)\s*(\d+)", flat)
    p["ticker"] = _ticker(code.group(1)) if code else None
    sub = re.search(rf"Date Submitted:\s*({D})", flat)
    p["doc_date"] = _d(sub.group(1)) if sub else None
    if not p["ticker"]:
        p["issues"].append(("HK_NO_CODE", "No stock code was found on this return. Choose the company."))
    if monthly:
        _monthly(flat, p)
    else:
        _ndr(flat, p)
    return p


def _ndr(t, p):
    issues = p["issues"]
    i1 = re.search(r"\nSection I\n", t)
    i2 = re.search(r"\nSection II\n|Section II must also be completed", t)
    i3 = re.search(r"\nSection III\n|Section III must also be completed", t)
    sec1 = t[i1.start():i2.start()] if i1 and i2 else t
    sec2 = t[i2.start():i3.start()] if i2 and i3 else (t[i2.start():] if i2 else "")

    # Section I A: balances and events
    op = re.search(rf"Opening balance as at \(Note 1\)\s*({D})\s+({NUM})\s+({NUM})\s+({NUM})", sec1)
    cl = re.search(rf"Closing balance as at \(Notes 5 and 6\)\s*({D})\s+({NUM})\s+({NUM})\s+({NUM})", sec1)
    events, change_issued, change_treasury = [], 0.0, 0.0
    if op and cl:
        body = re.sub(r"[ \t]+", " ", sec1[op.end():cl.start()])
        for chunk in re.split(r"\n(?=\d+\)\.)", "\n" + body):
            head = re.match(r"\s*(\d+)\)\.\s*(.+?)(?=\n?\s*(?:Shares repurchased on|Date of changes|Please refer|See Part|Settlement|\Z))", chunk, re.S)
            if not head:
                continue
            flat = re.sub(r"\s+", " ", chunk)
            kind = re.sub(r"\s+", " ", head.group(2)).strip()
            day = re.search(rf"Date of changes\s*({D})", flat)
            nums = re.search(rf"(-?{NUM})\s+({NUM})\s*%\s*(?:(-?{NUM})\s*)?(?:({CUR})\s*({NUM}))?", flat[day.end():] if day else flat)
            ev = {"n": int(head.group(1)), "kind": kind, "date": _d(day.group(1)) if day else None, "issued": _n(nums.group(1)) if nums else None,
                  "treasury": _n(nums.group(3)) if nums and nums.group(3) else 0.0, "cur": _cur(nums.group(4)) if nums and nums.group(4) else None, "price": _n(nums.group(5)) if nums and nums.group(5) else None}
            bought = re.search(rf"Shares repurchased on ({D})(?: in the (U\.S\.|HK|US|Hong Kong))? and cancelled on ({D})", flat)
            ev["bought"] = _d(bought.group(1)) if bought else None
            ev["market"] = bought.group(2) if bought and bought.group(2) else ""
            events.append(ev)
            if ev["issued"] is not None:
                change_issued += ev["issued"]
                change_treasury += ev["treasury"] or 0.0
        o_i, o_t = _n(op.group(2)), _n(op.group(3))
        c_i, c_t = _n(cl.group(2)), _n(cl.group(3))
        if abs(o_i + change_issued - c_i) > 0.5 or abs(o_t + change_treasury - c_t) > 0.5:
            issues.append(("HK_BALANCE", f"The balances on this return don't add up: opening issued {o_i:,.0f} {change_issued:+,.0f} should be {c_i:,.0f}, and opening treasury {o_t:,.0f} {change_treasury:+,.0f} should be {c_t:,.0f}. Please check the events."))
        p["balances"] = {"open": _d(op.group(1)), "close": _d(cl.group(1)), "issued_close": c_i, "treasury_close": c_t, "total_close": _n(cl.group(4))}
        p["programme"]["shares_on_issue"] = c_i
        closing_day = _d(cl.group(1))
        for ev in events:
            if ev["kind"].startswith("Repurchase of shares") and ev["issued"] is not None and "cancelled" in ev["kind"] and ev["date"]:
                n = abs(ev["issued"])
                note = f"Event {ev['n']}: " + (f"bought {ev['bought']}, " if ev["bought"] else "") + f"cancelled {ev['date']}" + (f" ({ev['market']})" if ev["market"] else "")
                p["cancellations"].append({"as_of": ev["date"], "venue": "", "shares": n, "kind": "Cancelled", "note": note, "basis": "Reported count"})
        if c_t and closing_day:
            p["cancellations"].append({"as_of": closing_day, "venue": "", "shares": c_t, "kind": "Held in treasury", "note": "Total held at the closing balance", "basis": "Reported count"})

    # Section I B: repurchased for cancellation, not yet cancelled
    part_b = []
    b0 = re.search(r"B\. Shares redeemed or repurchased for cancellation but not yet cancelled", sec1)
    if b0:
        b_text = re.sub(r"\s+", " ", sec1[b0.end():])
        for m in re.finditer(rf"Shares repurchased[^.]*?not yet cancelled(?: in (\w+))? Date of changes ({D}) ({NUM}) ({NUM}) ?% ({CUR}) ({NUM})", b_text):
            part_b.append({"market": m.group(1) or "", "date": _d(m.group(2)), "shares": _n(m.group(3)), "currency": _cur(m.group(5)), "price": _n(m.group(6))})
    if part_b and cl:
        p["cancellations"].append({"as_of": _d(cl.group(1)), "venue": "", "shares": sum(r["shares"] for r in part_b), "kind": "Awaiting cancellation (balance)",
                                   "note": f"{len(part_b)} purchases not yet cancelled at the closing balance; a balance, so the latest return's figure stands and they are never added together", "basis": "Reported count"})

    # Section II: one block per exchange or per mandate, each with its rows, totals and mandate
    blocks = []
    for chunk in re.split(r"\n(?=\d+\. Class of shares )", sec2):
        flat = re.sub(r"\s+", " ", chunk)
        if "A. Repurchase report" not in flat:
            continue
        rows = []
        for m in re.finditer(rf"(\d+)\)\. ?({D}) ({NUM}) ?(On the Exchange|On another stock exchange ([A-Za-z][A-Za-z .&-]*?)(?= {CUR} )|By private arrangement|By general offer) ?({CUR}) ?({NUM}) ?({CUR}) ?({NUM}) ?({CUR}) ?({NUM})", flat):
            rows.append({"date": _d(m.group(2)), "shares": _n(m.group(3)), "method": m.group(4), "venue": _venue(m.group(4), m.group(5)), "currency": _cur(m.group(6)),
                         "high": _n(m.group(7)), "low": _n(m.group(9)), "paid": _n(m.group(11)), "paid_text": m.group(11), "cur_check": len({m.group(6), m.group(8), m.group(10)}) == 1,
                         "off": m.group(4).strip().lower() in OFF_MARKET})
        tot = re.search(rf"Total number of shares repurchased ({NUM}) Aggregate price paid \$ ?({CUR}) ?({NUM})", flat)
        can = re.search(rf"Number of shares repurchased for cancellation ({NUM})", flat)
        tre = re.search(rf"Number of shares repurchased for holding as treasury shares ({NUM})", flat)
        res = re.search(rf"Date of the resolution granting the repurchase mandate ({D})", flat)
        auth = re.search(rf"authorised to repurchase under the repurchase mandate ({NUM})", flat)
        used = re.search(rf"under the repurchase mandate \(a\) ({NUM})", flat)
        pct = re.search(rf"granting the repurchase mandate ({NUM}) ?%", flat)
        listed = re.search(r"Listed on the Exchange (Yes|No)", flat)
        share = re.search(r"Class of shares (.+?) Type of shares (.+?) Listed on the Exchange", flat)
        blocks.append({"rows": rows, "total": _n(tot.group(1)) if tot else None, "total_cur": _cur(tot.group(2)) if tot else None, "total_paid": _n(tot.group(3)) if tot else None,
                       "cancel": _n(can.group(1)) if can else None, "treasury": _n(tre.group(1)) if tre else None, "resolution": _d(res.group(1)) if res else None,
                       "authorised": _n(auth.group(1)) if auth else None, "used": _n(used.group(1)) if used else None, "percent": _n(pct.group(1)) if pct else None,
                       "listed": listed.group(1) if listed else None, "security": _security(share.group(1), share.group(2)) if share else None})
    p["blocks"] = blocks
    for b in blocks:
        if not b["rows"]:
            issues.append(("HK_NO_ROWS", "A repurchase report on this return has no readable rows. Please check it."))
            continue
        add = sum(r["shares"] for r in b["rows"])
        if b["total"] is not None and abs(add - b["total"]) > 0.5:
            issues.append(("HK_TOTAL_DIFFERS", f"The repurchase rows add up to {add:,.0f} shares but the return's total says {b['total']:,.0f}."))
        if b["cancel"] is not None and b["treasury"] is not None and b["total"] is not None and abs(b["cancel"] + b["treasury"] - b["total"]) > 0.5:
            issues.append(("HK_TREATMENT_DIFFERS", f"Shares for cancellation ({b['cancel']:,.0f}) and for treasury ({b['treasury']:,.0f}) don't add up to {b['total']:,.0f}."))
        if b["cancel"] is None or b["treasury"] is None:
            issues.append(("HK_TREATMENT_NOT_STATED", "This return doesn't state both the shares for cancellation and for treasury. Not stated."))
        for r in b["rows"]:
            if not r["cur_check"]:
                issues.append(("HK_CURRENCY_MIXED", f"A repurchase of {r['shares']:,.0f} shares on {r['date']} states its prices and amount in different currencies. It was not added. Please enter it by hand."))
            elif r["off"]:
                issues.append(("HK_OFF_MARKET", f"A repurchase of {r['shares']:,.0f} shares on {r['date']} was made {r['method'].lower()}, not on an exchange. It was not added: the app follows on-market buybacks."))
    _ndr_records(p, blocks, part_b)
    for kind, detail in _cross_check_part_b(p, part_b):
        issues.append((kind, detail))


def _ndr_records(p, blocks, part_b):
    """Purchases (one per day, exchange and currency; blocks for different mandates on the same day add up), the programme (the latest mandate) and the running total."""
    days = OrderedDict()
    for b in blocks:
        for r in b["rows"]:
            if r["off"] or not r["cur_check"]:  # said so above; never added
                continue
            k = (r["date"], r["venue"], r["currency"])
            d = days.setdefault(k, {"shares": 0.0, "paid": 0.0, "high": r["high"], "low": r["low"], "n": 0, "security": b.get("security")})
            d["shares"] += r["shares"]
            d["paid"] += r["paid"]
            d["high"], d["low"] = max(d["high"], r["high"]), min(d["low"], r["low"])
            d["n"] += 1
    for (day, venue, cur), d in days.items():
        x = parsers._tx(day, d["shares"], None, d["high"], d["low"], cur, venue)
        # the amount is stated; the average is worked out from it. A day reported in several rows (two mandates) is their sum, which the return itself doesn't state
        x.update(value=d["paid"], price_avg=d["paid"] / d["shares"], value_origin="reported" if d["n"] == 1 else "sum", security=d["security"])
        p["transactions"].append(x)
        _band(p["issues"], p.get("company") or "This company", day, cur, d["shares"], d["paid"], d["high"], d["low"])
    dated = [b for b in blocks if b["resolution"]]
    latest = max(dated, key=lambda b: b["resolution"]) if dated else None
    prog = {}
    if latest:
        prog.update(announced_date=latest["resolution"], start_date=latest["resolution"], max_shares=latest["authorised"], buyback_type="On-market, under shareholder mandate")
        several = len({b["resolution"] for b in dated}) > 1
        if several:
            prog["size_note"] = ("This return reports buying under two mandates: " + "; ".join(f"resolution of {b['resolution']}: {b['used']:,.0f} of {b['authorised']:,.0f} shares used" for b in sorted(dated, key=lambda b: b["resolution"]) if b["used"] and b["authorised"])
                                 + ". Its purchases are shown under the later mandate, and no running total is kept from it, because each total covers one mandate only")
        if latest["used"] is not None and p["transactions"] and not several:
            last_day = max(x["trade_date"] for x in p["transactions"])
            p["snapshots"].append({"as_of": last_day, "cum_shares": latest["used"], "cum_value": None, "currency": None, "origin": "reported",
                                   "working": "Shares only, counted from the mandate's resolution, on any exchange: the return states no amount"})
    elif p["transactions"]:  # no mandate date on the return: still bought under the mandate, so it is not left waiting for an announcement
        prog.update(buyback_type="On-market, under shareholder mandate", mandate_undated=True)
    cancel = sum(b["cancel"] or 0 for b in blocks)
    treasury = sum(b["treasury"] or 0 for b in blocks)
    if cancel and not treasury:
        prog["treatment"], prog["treatment_text"] = "Cancelled", f"Number of shares repurchased for cancellation {cancel:,.0f}"
    elif treasury and not cancel:
        prog["treatment"], prog["treatment_text"] = "Treasury", f"Number of shares repurchased for holding as treasury shares {treasury:,.0f}"
    prog.update({k: v for k, v in p["programme"].items() if k not in prog})
    p["programme"] = {k: v for k, v in prog.items() if v is not None}


def _cross_check_part_b(p, part_b):
    """Section I B lists the same purchases a day at a time; where it names a day this return also reports, the two must agree."""
    out = []
    if not part_b:
        return out
    by_day = {}
    for r in part_b:
        by_day[(r["date"], r["currency"])] = by_day.get((r["date"], r["currency"]), 0) + r["shares"]
    for x in p["transactions"]:
        day, cur = x["trade_date"], x["currency"]
        if (day, cur) in by_day and abs(by_day[(day, cur)] - x["shares"]) > 0.5:
            out.append(("HK_PARTB_DIFFERS", f"On {day}, the repurchase report gives {x['shares']:,.0f} shares ({cur}) but the list of shares not yet cancelled gives {by_day[(day, cur)]:,.0f}. Please check it."))
    return out


def _monthly(t, p):
    """The monthly return states each event's date and number, and the month's balances, but no price and no exchange.
    It is kept as counts only: never as purchases, so a day already reported by a Next Day Disclosure Return is not counted twice."""
    flat = re.sub(r"[ \t]+", " ", t)
    month = re.search(rf"For the month ended: ({D})", flat)
    closing_day = _d(month.group(1)) if month else p["doc_date"]
    bal = re.search(rf"Balance at close of the month ({NUM}) ({NUM}) ({NUM})", flat)
    if bal and closing_day:
        p["programme"]["shares_on_issue"] = _n(bal.group(1))
        if _n(bal.group(2)):
            p["cancellations"].append({"as_of": closing_day, "venue": "", "shares": _n(bal.group(2)), "kind": "Held in treasury", "note": "Total held at the close of the month", "basis": "Reported count"})
    e0 = re.search(r"\(E\)\. Other Movements in Issued Shares and/or Treasury Shares", flat)
    if not e0:
        return
    e_text = flat[e0.end():]
    e1 = re.search(r"Total increase/ decrease|\nRemarks:", e_text)
    e_text = e_text[:e1.start()] if e1 else e_text
    approvals = set()
    for m in re.finditer(rf"\n?(\d+)\)\. ?(Repurchase of shares \((shares held as treasury shares|shares repurchased and cancelled)\)) ({CUR}) (?:({NUM}) )?({D}) (?:({D}) )?(-?{NUM})(?: (-?{NUM}))?(?=\s|$)", e_text):
        n, treat, cur, day, approved, issued, treasury = m.group(1), m.group(3), m.group(4), _d(m.group(6)), _d(m.group(7)), _n(m.group(8)), _n(m.group(9))
        if treat == "shares held as treasury shares":
            p["cancellations"].append({"as_of": day, "venue": "", "shares": abs(issued) if issued is not None else None, "kind": "Treasury repurchase (monthly return)",
                                       "note": f"Event {n}, {cur}, date as stated: no price or exchange in a monthly return", "basis": "Reported count"})
        else:
            p["cancellations"].append({"as_of": day, "venue": "", "shares": abs(issued) if issued is not None else None, "kind": "Cancelled (monthly return)",
                                       "note": f"Event {n}, {cur}, the date is the cancellation date", "basis": "Reported count"})
        if approved:
            approvals.add(approved)
    if approvals:
        first = max(approvals)
        p["programme"].update(announced_date=first, start_date=first, buyback_type="On-market, under shareholder mandate")
    if p["cancellations"] and not any(c["kind"] in ("Treasury repurchase (monthly return)", "Cancelled (monthly return)") for c in p["cancellations"]):
        p["cancellations"] = []


# ---------- daily Share Repurchase Report ----------
HEADER = re.compile(r"^Company \| Stock\s*code \| Sec\.\s*type \| Trading date", re.M)


def is_daily(text):
    return bool(HEADER.search(text)) and "Method of repurchase" in text


def daily_groups(text):
    """[(stock code, company name, [row, ...])] in the order the report lists them, and the footnotes by number."""
    head = HEADER.search(text)
    lines = [x for x in text[head.start():].split("\n")]
    rows, notes = [], {}
    for line in lines[1:]:
        cells = [c.strip() for c in line.split(" | ")]
        if len(cells) >= 14 and re.fullmatch(r"\d{1,5}", cells[1] or ""):
            rows.append(cells)
        m = re.match(r"Note: \((\d)\)\s*(.*)", line)
        if m:
            notes[int(m.group(1))] = m.group(2)
    groups = OrderedDict()
    for c in rows:
        groups.setdefault(_ticker(c[1]), (c[0], []))[1].append(c)
    return [(code, name, rs) for code, (name, rs) in groups.items()], notes


def render_group(text, rows, notes):
    """The text kept for one company: the report's heading line and that company's rows, so each figure can be shown in its place."""
    head = HEADER.search(text)
    lines = [text[head.start():].split("\n")[0]] + [" | ".join(r) for r in rows]
    cited = sorted({int(n) for r in rows for n in re.findall(r"Note (\d)", " ".join(r[9:]))} | {int(n) for r in rows for n in re.findall(r"& (\d)", " ".join(r[9:]))})
    lines += [f"Note: ({n}) {notes[n]}" for n in cited if n in notes]
    return "\n".join(lines)


def read_daily_group(code, name, rows, notes, doc_date=None):
    p = parsers._blank(form="hkex_daily", doc_type="transaction")
    p.update(definition="hkex_daily", date_stated=True, venue_totals=[], cancellations=[], ticker=code, company=name)
    issues = p["issues"]
    parts = OrderedDict()
    for c in rows:
        day = re.fullmatch(r"(\d{4})/(\d{2})/(\d{2})", c[3] or "")
        hi, lo, paid = (re.fullmatch(rf"({CUR}) ({NUM})", c[i] or "") for i in (5, 6, 7))
        shares = _n(c[4])
        if not (day and hi and lo and paid and shares) or len({hi.group(1), lo.group(1), paid.group(1)}) != 1:
            issues.append(("HK_ROW_UNCLEAR", f"A row for {name} on {c[3]} could not be read in full ({c[4]} shares, {c[5]}, {c[6]}, {c[7]}). It was not added. Please enter it by hand."))
            continue
        iso = f"{day.group(1)}-{day.group(2)}-{day.group(3)}"
        parts.setdefault((iso, VENUE if c[8].strip().lower() == "exchange" else _canon(c[8]), _cur(hi.group(1))), []).append((c, shares, _n(hi.group(2)), _n(lo.group(2)), _n(paid.group(2))))
    for (iso, venue, cur), items in parts.items():
        shares, paid = sum(i[1] for i in items), sum(i[4] for i in items)
        high, low = max(i[2] for i in items), min(i[3] for i in items)
        x = parsers._tx(iso, shares, None, high, low, cur, venue)
        x.update(value=paid, price_avg=paid / shares, value_origin="reported" if len(items) == 1 else "sum", security=_security(kind=items[0][0][2]))
        p["transactions"].append(x)
        _band(issues, name, iso, cur, shares, paid, high, low)
        last = items[-1][0]
        # the report puts a company's totals for the day and currency on its last row
        total, can, tre = _n(last[9]), _n(last[10]), _n(last[11])
        same = [i for (d, v, cu), its in parts.items() if d == iso and cu == cur for i in its]
        if total is not None and abs(sum(i[1] for i in same) - total) > 0.5 and last is same[-1][0]:
            issues.append(("HK_TOTAL_DIFFERS", f"On {iso} the {cur} rows for {name} add up to {sum(i[1] for i in same):,.0f} shares, but the report's total says {total:,.0f}."))
        if total is not None and last is same[-1][0]:
            if can is None and tre is None:
                issues.append(("HK_TREATMENT_NOT_STATED", f"For {name} on {iso} ({cur}) the report doesn't say how many shares were cancelled or held as treasury. Not stated."))
            else:
                if can is None or tre is None:
                    issues.append(("HK_TREATMENT_NOT_STATED", f"For {name} on {iso} ({cur}) the report gives {'treasury' if can is None else 'cancellation'} shares only. The other count is not stated."))
                if can is not None and tre is not None and abs(can + tre - total) > 0.5:
                    issues.append(("HK_TREATMENT_DIFFERS", f"For {name} on {iso} ({cur}) shares for cancellation ({can:,.0f}) and for treasury ({tre:,.0f}) don't add up to the total {total:,.0f}. Please check the report."))
    # how the shares are treated: only where a count equal to the total is stated
    kinds = set()
    for c in rows:
        total, can, tre = _n(c[9]), _n(c[10]), _n(c[11])
        if total and can == total and not tre:
            kinds.add("Cancelled")
        elif total and tre == total and not can:
            kinds.add("Treasury")
        elif total and (can or tre):
            kinds.add("Mixed")
    if len(kinds) == 1 and "Mixed" not in kinds:
        k = next(iter(kinds))
        p["programme"].update(treatment=k, treatment_text=f"for {'cancellation' if k == 'Cancelled' else 'holding as treasury shares'}")
        for c in rows:
            if _n(c[10 if k == 'Cancelled' else 11]) == _n(c[9]) and _n(c[9]):
                p["programme"]["treatment_text"] = f"the report states a total of {c[9]}, for cancellation {c[10] or 'not stated'}, for treasury {c[11] or 'not stated'}"
                break
    # the mandate's running count: in the row, or in the footnote the row points to
    snaps = {}
    for c in rows:
        day = re.fullmatch(r"(\d{4})/(\d{2})/(\d{2})", c[3] or "")
        if not day:
            continue
        iso = f"{day.group(1)}-{day.group(2)}-{day.group(3)}"
        used = _n(c[12]) if re.fullmatch(NUM, c[12] or "") else None
        how = "Counted from the mandate's resolution, on any exchange, as the report states"
        if used is None and re.match(r"Note \d", c[12] or ""):
            first = int(re.match(r"Note (\d)", c[12]).group(1))
            m = re.search(rf"Number of such securities purchased on ([^.]*?) since special resolutions? is ({NUM})", notes.get(first, ""))
            if m:
                used, how = _n(m.group(2)), f"From footnote {first}: purchased on {m.group(1)} since the special resolution"
        if used is not None:
            snaps[iso] = (used, how)
    for iso, (used, how) in snaps.items():
        p["snapshots"].append({"as_of": iso, "cum_shares": used, "cum_value": None, "currency": None, "origin": "reported", "working": f"Shares only: {how}"})
    p["doc_date"] = max((x["trade_date"] for x in p["transactions"]), default=doc_date)
    # the report states the buying was under the repurchase mandate but not the mandate's date: a mandate, date not stated, and counted like any other
    p["programme"].update(buyback_type="On-market, under shareholder mandate", mandate_undated=True)
    return p
