"""Filing layouts described as data, so a new exchange form needs a definition file and no new code.

Each file in data/forms/ describes one layout: the phrases that identify it, where each figure sits, the checks to run, and how the
figures map to a purchase, a running total, cancellations and the programme. read() picks the definition matching the filing's
market and text, and returns the same record the other parsers return. A filing no definition matches is left to those parsers.

Only a definition whose status is "approved" is used. Nothing here guesses: a field that isn't found stays empty, a required one
missing is reported, and a failed check drops the figures it covers.

A field:   label  regular expression for the field's label, matched at the start of a line, ignoring case
           take   "line" (the rest of the label's line), "next" (the next line that isn't empty) or "block" (everything up to `until`)
           type   "number", "date", "money" (currency and amount, which may sit on separate lines) or "text"
           column which value to take when a line holds several, counting from 0
           after  only look below this line, for a label that appears more than once
           not    a value matching this is not the field's value (the label had none)
"""
import json
import re
from pathlib import Path

from . import parsers

FORMS_DIR = Path(__file__).resolve().parent.parent / "data" / "forms"
_CACHE = {"stamp": None, "rows": []}
CODES = set(parsers.CURRENCY.values()) | {"ILS", "IDR", "PHP", "VND", "AED", "SAR", "BRL", "MXN", "PLN", "TRY", "CZK", "HUF"}
# The whole run of digits, commas and points is taken, so 177.138,06 is never read as 177.138: parsers.num then leaves it unread
_NUMBER = r"(?<![\w.,/:])(?:\d[\d,.]*\d|\d)(?![\w/:])"
_MONEY = r"(HK\$|US\$|NZ\$|CA\$|NT\$|(?<![A-Za-z])[SAC]\$|£|€|\b[A-Z]{3})[ \t]*\n?[ \t]*(\d[\d,.]*\d|\d)(?![\w/])"


def definitions():
    """Every definition in data/forms, read again when a file there changes."""
    files = sorted(FORMS_DIR.glob("*.json")) if FORMS_DIR.exists() else []
    stamp = [(f.name, f.stat().st_mtime_ns) for f in files]
    if stamp != _CACHE["stamp"]:
        rows = []
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            missing = [k for k in ("id", "market", "status", "form", "identify", "fields", "map") if k not in d]
            if missing:
                raise ValueError(f"{f.name} is missing {', '.join(missing)}")
            d["file"] = f.name
            rows.append(d)
        _CACHE["stamp"], _CACHE["rows"] = stamp, rows
    return _CACHE["rows"]


def for_market(market):
    """Approved definitions for a market. With no market given, all of them."""
    return [d for d in definitions() if d["status"] == "approved" and (not market or d["market"] in (market, "ALL"))]


def match(text, market=None):
    """The definition whose identifying phrases are all in the text. The one with the most phrases wins."""
    found = [d for d in for_market(market) if all(re.search(p, _mend(text, d), re.I | re.M) for p in d["identify"])]
    return max(found, key=lambda d: len(d["identify"]), default=None)


def _words(d):
    """The words the definition's labels and identifying phrases are made of (four letters or more)."""
    if "_vocab" not in d:
        specs = list(d["identify"]) + [f["label"] for f in d["fields"].values()]
        d["_vocab"] = sorted({w for s in specs for w in re.findall(r"[A-Za-z]{4,}", re.sub(r"\\.", " ", s))}, key=len, reverse=True)
    return d["_vocab"]


def _mend(text, d):
    """Some PDFs print a word with its first letter apart ("T otal"). Mend the words the definition looks for, and only those, and only that split: a space
    before a word's last letter would join two real words ("share S$" must not become "shares$")."""
    squeezed = re.sub(r"[ \t]", "", text).lower()
    for w in _words(d):
        if w.lower() not in squeezed:
            continue
        # a capital first letter only, as headings and labels are printed: "a mount of" and "a round sum" are left alone
        text = re.sub(rf"(?<![A-Za-z]){re.escape(w[0].upper())}[ \t](?i:{re.escape(w[1:])})(?![A-Za-z])", lambda m: m.group(0)[0] + m.group(0)[2:], text)
    return text


def _clean(text, d):
    """The text without repeated page headers, which can fall between a label and its value."""
    text = _mend(text, d)
    for pattern in d.get("ignore", []):
        text = re.sub(pattern, "", text, flags=re.M)
    return text.replace("\f", "\n")


def _found(region, kind):
    """Every value of one kind in a stretch of text, each with where it starts and ends there."""
    if kind == "number":
        return [(parsers.num(m.group(0)), m.start(), m.end()) for m in re.finditer(_NUMBER, region)]
    if kind == "date":
        return [(parsers.to_date(m.group(0)), m.start(), m.end()) for m in re.finditer(parsers.DATE_RE, region)]
    if kind == "money":
        out = []
        for m in re.finditer(_MONEY, region):
            code = parsers.CURRENCY.get(m.group(1), m.group(1))
            if code in CODES:
                out.append(((code, parsers.num(m.group(2))), m.start(), m.end()))
        return out
    flat = re.sub(r"\s+", " ", region).strip()
    return [(flat, len(region) - len(region.lstrip()), len(region.rstrip()))] if flat else []


def _values(region, kind):
    return [v for v, _, _ in _found(region, kind)]


def _locate(text, spec):
    """(value, the words it was read from, where the value starts and ends in the text). All None when the label or its value isn't there."""
    nothing = (None, None, None)
    start = 0
    if spec.get("after"):
        a = re.search(spec["after"], text, re.I | re.M)
        if not a:
            return nothing
        start = a.end()
    m = re.search(spec["label"], text[start:], re.I | re.M)
    if not m:
        return nothing
    at = start + m.end()
    line_end = text.find("\n", at)
    line_end = len(text) if line_end < 0 else line_end
    take = spec.get("take", "line")
    if take == "line":
        begin, region = at, text[at:line_end]
    elif take == "next":
        begin, region = line_end, ""
        for line in text[line_end:].split("\n"):
            if line.strip():
                region = line
                break
            begin += len(line) + 1
    else:
        stop = re.search(spec["until"], text[at:], re.I | re.M) if spec.get("until") else None
        begin, region = at, (text[at:at + stop.start()] if stop else text[at:at + 400])
    if spec.get("not") and re.search(spec["not"], region.strip(), re.I):
        return nothing
    found = _found(region, spec.get("type", "text"))
    column = spec.get("column", 0)
    if column >= len(found) or found[column][0] is None:
        return nothing
    value, s, e = found[column]
    return value, re.sub(r"\s+", " ", text[start + m.start():at] + " " + region).strip(), (begin + s, begin + e)


def _field(text, spec):
    """(value, the words it was read from). (None, None) when the label or its value isn't there."""
    return _locate(text, spec)[:2]


def try_out(d, text, home, date_order="DMY"):
    """What a definition reads from a text, whatever its status: (the text as read, values, words, places, record).
    Used to check a definition against a sample; nothing is stored."""
    before = getattr(parsers._CTX, "market", None), getattr(parsers._CTX, "date_order", "DMY")
    parsers._CTX.market, parsers._CTX.date_order = d["market"], date_order or "DMY"
    try:
        clean = _clean(text, d)
        values, words, places = {}, {}, {}
        for name, spec in d["fields"].items():
            values[name], words[name], places[name] = _locate(clean, spec)
        return clean, values, words, places, build(d, dict(values), words, home)
    finally:
        parsers._CTX.market, parsers._CTX.date_order = before


def extract(text, d):
    """Every field of the definition: {name: value} and {name: words read}."""
    clean = _clean(text, d)
    values, words = {}, {}
    for name, spec in d["fields"].items():
        values[name], words[name] = _field(clean, spec)
    return values, words


def _amount(pair):
    return pair[1] if pair else None


def build(d, f, words, home):
    """The record the rest of the app stores, from one definition's fields."""
    m = d["map"]
    p = parsers._blank(form=d["form"], doc_type=d.get("doc_type", "transaction"))
    p.update(definition=d["id"], date_stated=True, venue_totals=[], cancellations=[])
    issues = p["issues"]
    for name in d.get("required", []):
        if f.get(name) is None:
            issues.append(("FIELD_MISSING", f"The {d['name']} field '{name}' could not be read from this filing. Please check it."))
    for c in d.get("checks", []):
        parts, target = [f.get(k) for k in c["sum"]], f.get(c["equals"])
        if None in parts or target is None:
            continue
        if abs(sum(parts) - target) > 0.5:
            issues.append((c["kind"], c["say"].format(sum=sum(parts), target=target)))
            for k in c.get("drop", []):
                f[k] = None
    for flag in d.get("flags", []):
        if f.get(flag["field"]) and re.search(flag["matches"], str(f[flag["field"]]), re.I):
            issues.append((flag["kind"], flag["say"]))

    who = m.get("company", {})
    p["company"] = f.get(who.get("name"))
    named = re.search(who["pattern"], f.get(who.get("security")) or "") if who.get("pattern") else None
    if named:
        p["ticker"] = named.group("ticker").upper()
        if "isin" in named.groupdict():
            p["isin"] = named.group("isin")
    p["doc_date"] = f.get(m.get("filing_date"))
    as_of = f.get(m.get("as_of")) or p["doc_date"]

    def venue_of(spec):
        return spec.get("venue", "") if "venue_from" not in spec else f.get(spec["venue_from"])

    for spec in m.get("purchases", []):
        shares = f.get(spec["shares"])
        if not shares:
            continue
        venue, day = venue_of(spec), f.get(spec["date"])
        paid, high, low = f.get(spec.get("paid")), f.get(spec.get("high")), f.get(spec.get("low"))
        units = {x[0] for x in (paid, high, low) if x}
        if venue is None or not day or len(units) != 1:  # never placed on the main exchange, dated or priced by assumption
            what = "its exchange" if venue is None else "its date" if not day else "one currency for its prices and amount"
            issues.append(("PURCHASE_UNCLEAR", f"A purchase of {shares:,.0f} shares was found, but not {what}. It was not added. Please enter it by hand."))
            continue
        unit = units.pop()
        x = parsers._tx(day, shares, None, _amount(high), _amount(low), unit, venue)
        if _amount(paid):  # the amount the form states; the average is worked out from it
            x.update(value=_amount(paid), price_avg=_amount(paid) / shares, value_origin="reported")
        else:
            issues.append(("NO_AVG_PRICE", "No amount paid found, so no value was kept for this purchase."))
        p["transactions"].append(x)

    counts = {"Cancelled": 0, "Treasury": 0}
    for kind, key, note in (("Cancelled", "cancelled", "Bought and cancelled, as the form states"), ("Treasury", "treasury", "Bought and held as treasury shares, as the form states")):
        for spec in m.get(key, []):
            shares, venue = f.get(spec["shares"]), venue_of(spec)
            if shares and venue is not None:
                counts[kind] += shares
                if kind == "Cancelled":
                    p["cancellations"].append({"as_of": as_of, "venue": venue, "shares": shares, "kind": "Cancelled", "note": note, "basis": "Reported count"})
                p.setdefault("treatment_words", {})[kind] = words.get(spec["shares"])
    held = f.get(m.get("treasury_held"))
    if held is not None and p["transactions"]:
        p["cancellations"].append({"as_of": as_of, "venue": "", "shares": held, "kind": "Held in treasury", "note": "Total held after this purchase", "basis": "Reported count"})

    prog, terms = {"announced_date": ""}, m.get("programme", {})
    for name in terms.get("size_from", []):  # a programme the company names, such as "S$2Bn ... Share Buy-back Programme"
        value, currency, written = parsers._money_match(f.get(name) or "", home)
        if value:
            prog.update(max_value=value, max_currency=currency, max_text=written)
            break
    mandate = terms.get("mandate", {})
    total = m.get("running_total", {})
    p["mandate"] = {"start": f.get(mandate.get("start")), "max_shares": f.get(mandate.get("max_shares")), "cum_shares": f.get(total.get("shares")), "cum_percent": f.get(total.get("percent"))}
    if not prog.get("max_value") and mandate:  # no named programme, so the buying belongs to the shareholder mandate, which begins on its start date
        start = p["mandate"]["start"]
        prog.update(announced_date=start or "", start_date=start, max_shares=p["mandate"]["max_shares"], buyback_type=mandate.get("type"))
    by_mandate = total.get("counted_from") == "mandate"
    if p["mandate"]["cum_shares"] is not None and as_of and not (by_mandate and prog.get("max_value")):  # a total counted from the mandate isn't a named programme's total
        p["snapshots"].append({"as_of": as_of, "cum_shares": p["mandate"]["cum_shares"], "cum_value": None, "currency": None, "origin": "reported",
                               "working": "Shares only: the form states no amount" + (". Counted from the start of the mandate" if by_mandate else "")})
    if f.get(m.get("shares_on_issue")) is not None:
        prog["shares_on_issue"] = f[m["shares_on_issue"]]
    only = [k for k, n in counts.items() if n]
    if len(only) == 1:
        prog["treatment"], prog["treatment_text"] = only[0], p["treatment_words"][only[0]]
    p.pop("treatment_words", None)
    p["programme"] = {k: v for k, v in prog.items() if v is not None}
    first = (m.get("purchases") or [{}])[0]
    under = {"trade_date": first.get("date"), "shares": first.get("shares"), "price_high": first.get("high"), "price_low": first.get("low"), "value": first.get("paid"), "cum_shares": total.get("shares"),
             "shares_on_issue": m.get("shares_on_issue"), "start_date": mandate.get("start"), "announced_date": mandate.get("start"), "max_shares": mandate.get("max_shares")}
    p["anchors"] = {k: "(?im)" + d["fields"][v]["label"] for k, v in under.items() if v in d["fields"] and not d["fields"][v].get("after")}  # where the evidence for each figure is looked for
    return p


def read(text, market, home):
    """The filing's record if a definition matches it, otherwise None."""
    d = match(text, market)
    if not d:
        return None
    values, words = extract(text, d)
    return build(d, values, words, home)
