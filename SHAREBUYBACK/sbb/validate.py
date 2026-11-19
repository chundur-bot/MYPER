"""Checks run on the figures read from every filing, whichever reader read it.

Nothing here changes a figure. A figure that fails a check is reported as CHECK_FAILED, so the filing goes to Quality for a
person to look at.
"""
import re
from datetime import date, timedelta

EARLIEST = "1990-01-01"


def _day(value):
    try:
        return date.fromisoformat(str(value)) if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)) else None
    except ValueError:
        return None


def _n(value):
    return f"{value:,.0f}" if float(value) == int(value) else f"{value:,.4f}".rstrip("0")


def check(p, today=None):
    """Every failed check on one filing's record, as (kind, what is wrong in plain words)."""
    found = []
    say = lambda text: found.append(("CHECK_FAILED", text + " Please check it against the filing."))
    latest = (today or date.today()) + timedelta(days=1)
    filed = _day(p.get("doc_date"))
    if p.get("doc_date") and not filed:
        say(f"The filing date read ({p['doc_date']}) isn't a real date.")
    elif filed and filed > latest:
        say(f"The filing date read ({p['doc_date']}) is in the future.")
    bought = 0
    for x in p.get("transactions", []):
        when, day = x.get("trade_date"), _day(x.get("trade_date"))
        name = f"The purchase dated {when}" if when else "A purchase"
        if not day:
            say(f"{name} has no real date.")
        elif day > latest:
            say(f"{name} is dated in the future.")
        elif str(when) < EARLIEST:
            say(f"{name} is dated before 1990.")
        elif filed and filed <= latest and day > filed:
            say(f"{name} is dated after the filing's own date ({p['doc_date']}).")
        shares = x.get("shares")
        if shares is None or shares <= 0:
            say(f"{name} has no positive number of shares.")
        else:
            bought += shares
            if abs(shares - round(shares)) > 1e-6:
                say(f"{name} has {_n(shares)} shares, which isn't a whole number.")
        high, low, avg, value = x.get("price_high"), x.get("price_low"), x.get("price_avg"), x.get("value")
        for label, v in (("highest price", high), ("lowest price", low), ("average price", avg), ("amount paid", value)):
            if v is not None and v <= 0:
                say(f"{name} has a {label} of {_n(v)}, which isn't above zero.")
        if high and low and high > 0 and low > 0 and low > high:
            say(f"{name} has a lowest price ({_n(low)}) above its highest price ({_n(high)}).")
        elif avg and avg > 0:
            if high and high > 0 and avg > high * 1.02:  # an amount paid can include duties and fees, so a little above is allowed
                say(f"{name} has an average price ({_n(avg)}) above its highest price ({_n(high)}), so the amount paid, the shares or a price was misread.")
            if low and low > 0 and avg < low * 0.98:
                say(f"{name} has an average price ({_n(avg)}) below its lowest price ({_n(low)}), so the amount paid, the shares or a price was misread.")
        if value is not None and not re.fullmatch(r"[A-Z]{3}", str(x.get("currency") or "")):
            say(f"{name} has an amount with no recognised currency.")
    prog = p.get("programme") or {}
    issued = prog.get("shares_on_issue")
    if issued is not None and issued <= 0:
        say(f"The shares in issue read ({_n(issued)}) aren't above zero.")
    elif issued and bought > issued:
        say(f"The shares bought ({_n(bought)}) are more than the shares in issue ({_n(issued)}).")
    last = max((x["trade_date"] for x in p.get("transactions", []) if _day(x.get("trade_date"))), default=None)
    for s in p.get("snapshots", []):
        total = s.get("cum_shares")
        if total is None:
            continue
        if total < 0:
            say(f"The running total of shares ({_n(total)}) is below zero.")
        elif bought and last and s.get("as_of") and s["as_of"] >= last and total < bought:
            say(f"The running total of shares ({_n(total)}) is smaller than the {_n(bought)} shares this filing reports buying.")
        if prog.get("max_shares") and total > prog["max_shares"]:
            say(f"The running total of shares ({_n(total)}) is above the maximum the filing states ({_n(prog['max_shares'])}).")
        if s.get("cum_value") is not None and s["cum_value"] < 0:
            say("The running total of money is below zero.")
    start, end = _day(prog.get("start_date")), _day(prog.get("end_date"))
    if start and end and end < start:
        say(f"The programme's end date ({prog['end_date']}) is before its start date ({prog['start_date']}).")
    for label, v in (("maximum number of shares", prog.get("max_shares")), ("programme size", prog.get("max_value"))):
        if v is not None and v <= 0:
            say(f"The {label} read ({_n(v)}) isn't above zero.")
    return found
