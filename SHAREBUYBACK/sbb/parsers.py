"""Read one saved announcement and pull out the buyback facts.

Formats: the Appendix 3C form used on ASX (and by some NZX issuers), UK "Transaction in Own Shares" style notices, and
narrative notices. Anything uncertain goes on the review list; a value is never guessed. Prices with no stated unit stay
without a value until reviewed.
"""
import re
import threading
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

MON = "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
DATE_RE = rf"\d{{1,2}}(?:st|nd|rd|th)?[ \-]+(?:{MON})[ ,\-]+\d{{4}}|(?:{MON}) \d{{1,2}},? \d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}"
NUM_RE = r"\d[\d,]*(?:\.\d+)?"
MONEY_RE = r"(HK\$|HKD|(?<![A-Za-z])S\$|SGD|CA\$|(?<![A-Za-z])C\$|CAD|NT\$|TWD|JPY|CNY|RMB|CHF|SEK|NOK|DKK|INR|KRW|ZAR|MYR|THB|USD\$|AUD\$|NZD\$|A\$|AU\$|AUD|NZ\$|NZD|US\$|USD|£|GBP|EUR|€|\$)\s?(\d[\d,]*(?:\.\d+)?)\s*(billion|bn|million|mn|m)\b"
CURRENCY = {"HK$": "HKD", "HKD": "HKD", "S$": "SGD", "SGD": "SGD", "CA$": "CAD", "C$": "CAD", "CAD": "CAD", "NT$": "TWD", "TWD": "TWD", "JPY": "JPY", "CNY": "CNY", "RMB": "CNY", "CHF": "CHF", "SEK": "SEK", "NOK": "NOK", "DKK": "DKK",
            "INR": "INR", "KRW": "KRW", "ZAR": "ZAR", "MYR": "MYR", "THB": "THB", "USD$": "USD", "AUD$": "AUD", "NZD$": "NZD", "A$": "AUD", "AU$": "AUD", "AUD": "AUD", "NZ$": "NZD", "NZD": "NZD", "US$": "USD", "USD": "USD", "£": "GBP", "GBP": "GBP", "EUR": "EUR", "€": "EUR"}
SCALE = {"billion": 1e9, "bn": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6}
# price units beyond the home markets, looked for after those: (pattern, code)
OTHER_UNITS = [(r"(?<![A-Za-z])S\$|\bSGD\b", "SGD"), (r"CA\$|(?<![A-Za-z])C\$|\bCAD\b", "CAD"), (r"NT\$|\bTWD\b", "TWD"), (r"\bJPY\b", "JPY"), (r"\bCNY\b|\bRMB\b", "CNY"), (r"\bCHF\b", "CHF"),
               (r"\bSEK\b", "SEK"), (r"\bNOK\b", "NOK"), (r"\bDKK\b", "DKK"), (r"\bINR\b", "INR"), (r"\bKRW\b", "KRW"), (r"\bZAR\b", "ZAR"), (r"\bMYR\b", "MYR"), (r"\bTHB\b", "THB")]
PERIOD_WORDS = r"during\s+the\s+(?:quarter|month|week|half[- ]year|year|three\s+months|six\s+months|period)\b|(?:quarter|months?|year)\s+ended"
_CTX = threading.local()  # the market and date order of the filing being read, set by parse()


def num(s):
    """A number, allowing a price written with its unit, such as 641.43p, 641.43 pence or \u00a39.82. The unit itself comes from the label."""
    if s is None:
        return None
    digits = re.search(r"\d[\d,.]*\d", str(s))
    # commas are thousands separators only, as in 1,234,567.89. Another convention, such as 1.234,56 or 12,5, isn't guessed
    if digits and "," in digits.group(0) and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", digits.group(0)):
        return None
    text = str(s).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        m = re.fullmatch(r"(?:[A-Z]{1,3}\$?|[\u00a3$\u20ac])?\s*(-?\d+(?:\.\d+)?)\s*(?:p|pence|GBp|GBX)?\.?", text, re.I)
        return float(m.group(1)) if m else None


def to_date(s):
    """Return YYYY-MM-DD, or None. Slash dates are day first, as on the exchanges in scope."""
    if not s:
        return None
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", str(s).strip()).replace(",", " ").replace("-", " ") if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s).strip()) else str(s).strip()
    s = re.sub(r"\s+", " ", s)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y" if getattr(_CTX, "date_order", "DMY") == "MDY" else "%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(s.replace("Sept ", "Sep "), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


class _Html(HTMLParser):
    """Keeps table rows as 'a | b | c' lines so columns survive. Paragraphs inside a cell stay on the cell's line:
    RNS pages wrap each cell's text in its own paragraph, and a label must stay on the same line as its value."""
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.cell = [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in ("td", "th"):
            self.cell += 1
        elif tag in self.BLOCK:
            self.out.append(" " if self.cell else "\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th"):
            self.cell = max(0, self.cell - 1)
            self.out.append(" | ")
        elif tag == "tr":
            self.cell = 0  # a cell left open by the page still ends with its row
            self.out.append("\n")
        elif tag in self.BLOCK:
            self.out.append(" " if self.cell else "\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))


def _sheet_text(path, suffix):
    """A workbook as text, one line per row with the cells joined by ' | '. A row holding a single cell (a note) keeps its own lines."""
    def show(v):
        if v is None:
            return ""
        return str(int(v)) if isinstance(v, float) and v == int(v) else str(v)
    lines = []
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        sheets = [[[show(c) for c in row] for row in ws.iter_rows(values_only=True)] for ws in wb.worksheets]
        wb.close()
    else:
        try:
            import xlrd
        except ImportError:
            raise ValueError("This is an old .xls workbook. Open it in Excel and save it as .xlsx, or install xlrd, then try again")
        book = xlrd.open_workbook(str(path))
        sheets = [[[show(ws.cell_value(r, c)) for c in range(ws.ncols)] for r in range(ws.nrows)] for ws in book.sheets()]
    for rows in sheets:
        for cells in rows:
            filled = [c.strip() for c in cells if c and c.strip()]
            if not filled:
                continue
            if len(filled) == 1:
                lines += [x.strip() for x in filled[0].split("\n") if x.strip()]
            else:
                lines.append(" | ".join(re.sub(r"\s+", " ", c).strip() for c in cells))
    return "\n".join(lines)


def read_pages(path):
    """The file's text, one string per page. Web and text files count as one page."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return [_sheet_text(p, suffix)]
    if suffix == ".pdf":
        from pypdf import PdfReader
        return [(pg.extract_text() or "").replace("\xa0", " ") for pg in PdfReader(str(p)).pages]
    raw = p.read_bytes()
    text = raw.decode("utf-8", errors="replace") if raw[:2] not in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-16", errors="replace")
    if suffix in (".html", ".htm"):
        h = _Html()
        h.feed(text)
        text = "".join(h.out)
    return [text.replace("\xa0", " ")]


PAGE_BREAK = "\n\f\n"


def read_text(path):
    return PAGE_BREAK.join(read_pages(path))


def _blank(**kw):
    d = {"form": "unknown", "ticker": None, "company": None, "doc_type": "unknown", "doc_date": None, "programme": {}, "transactions": [], "snapshots": [], "issues": []}
    d.update(kw)
    return d


def _money_match(text, home):
    """The programme size: (value, currency, text as written). The sentence must be about the buyback, so 'assets of US$3,445bn' never counts."""
    exact = re.search(r"(?:maximum consideration|aggregate purchase price|up to|maximum of)[^.\n]{0,40}?(HK\$|HKD|JPY|CAD|SGD|CHF|INR|CNY|RMB|US\s?\$|USD\$?|A\$|AUD\$?|NZ\$|NZD\$?|£|GBP|€|EUR)\s?(\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?)", text or "", re.I)
    if exact:
        sym = re.sub(r"\s", "", exact.group(1))
        return num(exact.group(2)), CURRENCY.get(sym.upper() if sym not in ("£", "€") else sym, home), text[exact.start(1):exact.end(2)]
    for m in re.finditer(MONEY_RE, text or "", re.I):
        before = text[max(0, m.start() - 160):m.start()]
        before = before[before.rfind(". ") + 1:]
        after = text[m.end():m.end() + 80]
        after = after[:after.find(". ")] if ". " in after else after
        about = before + " " + after
        if re.search(r"\bassets\b|revenue|profit|net debt|market cap", before, re.I) or not re.search(r"buy-?\s?back|repurchase|up\s+to|maximum", about, re.I):
            continue
        # an amount already spent isn't the programme's size: "for a total of $126.6 million under its $2.0 billion program"
        if re.search(r"(?:for\s+a\s+total\s+of|total\s+(?:consideration|cost)\s+of|at\s+a\s+(?:total\s+)?cost\s+of|for\s+approximately|for\s+an\s+aggregate\s+of)\s*$", before, re.I):
            continue
        sym = m.group(1).upper() if m.group(1) not in ("£", "€") else m.group(1)
        return num(m.group(2)) * SCALE[m.group(3).lower()], CURRENCY.get(sym, home), m.group(0)
    return None, None, None


def max_value_in(text, home):
    return _money_match(text, home)[:2]


# ---------- Appendix 3C ----------
def parse_3c(t, home):
    d = _blank(form="appendix_3c")
    after = lambda label: (re.search(label + r"[^\n]*\n\s*([^\n]+)", t) or [None, None])[1]
    d["ticker"] = (after(r"1\.3 ASX issuer code") or "").strip().upper() or None
    d["company"] = (after(r"1\.1 Name of entity") or "").strip() or None
    d["doc_date"] = to_date(after(r"1\.5 Date of this announcement"))
    d["reason"] = (after(r"1\.4b Reason for update") or "").strip() or None
    broker = re.search(r"Broker name:\s*\n\s*([^\n]+)", t)
    if broker and not re.match(r"to be confirmed", broker.group(1).strip(), re.I):
        d["broker"] = {"name": broker.group(1).strip(), "role": "Programme broker", "text": "3A.6 " + broker.group(0).replace("\n", " ").strip()}
    d["previous_date"] = to_date(after(r"1\.4d Date of previous announcement"))
    on_issue = re.search(r"3A\.1 Total number.*?bought back\s+([\d,]+)", t, re.S)
    max_sh = re.search(r"3A\.5a Maximum number.*?bought back\s+([\d,]+)", t, re.S)
    other = re.search(r"3D\.1 Any other information[^\n]*\n(.*?)(?:Appendix 3C - Notification|Part 4|Part 5|$)", t, re.S)
    max_val, max_cur, max_text = _money_match(other.group(1) if other else "", home)
    btype = re.search(r"2\.1 The type of buy-back is:?\s*\n\s*([^\n]+)", t)
    initial = to_date(after(r"1\.4c Date of initial notification"))
    d["programme"] = {"announced_date": initial or d["doc_date"], "buyback_type": btype.group(1).strip() if btype else None,
                      "start_date": to_date(after(r"3C\.2 Proposed buy-back start date")), "end_date": to_date(after(r"3C\.3 Proposed buy-back end date")),
                      "max_shares": num(max_sh.group(1)) if max_sh else None, "max_value": max_val, "max_currency": max_cur, "max_text": max_text,
                      "shares_on_issue": num(on_issue.group(1)) if on_issue else None}
    day = re.search(r"4\.3 Total number.*?(?:received\s+)?([\d,]+)\s+([\d,]+)\s*\n", t, re.S)
    fin = re.search(r"5\.1 Total number[^\n]*\n\s*([\d,]+)", t)
    if day:
        d["doc_type"] = "daily"
        trade = to_date(after(r"4\.2 Previous day"))
        if not trade:
            trade = d["doc_date"]
            d["issues"].append(("DATE_ASSUMED", "Field 4.2 (previous day) could not be read, so the notice date was used as the purchase date."))
        val = re.search(r"4\.4 Total consideration.*?([A-Z]{3})\s+([\d,.]+)\s+([A-Z]{3})\s+([\d,.]+)", t, re.S)
        high = re.search(r"4\.5 Highest price paid\s+[A-Z]{3}\s+[\d,.]+\s+[A-Z]{3}\s+([\d,.]+)", t)
        low = re.search(r"4\.6 Lowest price paid\s+[A-Z]{3}\s+[\d,.]+\s+[A-Z]{3}\s+([\d,.]+)", t)
        before, today = num(day.group(1)), num(day.group(2))
        if not val:
            d["issues"].append(("VALUE_MISSING", "Field 4.4 (total consideration) could not be read."))
        cur = val.group(3) if val else home
        v_before, v_today = (num(val.group(2)), num(val.group(4))) if val else (None, None)
        if v_before is not None and val.group(1) != val.group(3):
            d["issues"].append(("CURRENCY_MIX", f"Field 4.4 shows {val.group(1)} before and {val.group(3)} on the day."))
        d["transactions"].append({"trade_date": trade, "venue": "", "shares": today, "value": v_today, "currency": cur, "price_unit": cur,
                                  "price_avg": (v_today / today) if v_today and today else None, "price_high": num(high.group(1)) if high else None, "price_low": num(low.group(1)) if low else None, "value_origin": "reported"})
        prev = (date.fromisoformat(trade) - timedelta(days=1)).isoformat()
        d["snapshots"] += [{"as_of": prev, "cum_shares": before, "cum_value": v_before, "currency": cur, "origin": "reported"},
                           {"as_of": trade, "cum_shares": before + today, "cum_value": (v_before + v_today) if v_today is not None and v_before is not None else None, "currency": cur, "origin": "sum",
                            "working": f"{cur} {v_before:,.2f} before that day + {cur} {v_today:,.2f} on the day" if v_today is not None and v_before is not None else None}]
    elif fin:
        d["doc_type"] = "final"
        val = re.search(r"5\.2 Total consideration[^\n]*\n\s*([A-Z]{3})\s+([\d,.]+)", t)
        if not val:
            d["issues"].append(("VALUE_MISSING", "Field 5.2 (total consideration) could not be read."))
        d["programme"]["status"] = "COMPLETED"
        d["snapshots"].append({"as_of": d["doc_date"], "cum_shares": num(fin.group(1)), "cum_value": num(val.group(2)) if val else None, "currency": val.group(1) if val else home, "origin": "reported"})
    else:
        d["doc_type"] = "programme" if re.search(r"New announcement", t) else "update"
    if not d["ticker"]:
        d["issues"].append(("NO_TICKER", "Field 1.3 (ASX issuer code) could not be read."))
    return d


# ---------- Appendix 3H ----------
def parse_3h(t, home):
    """Securities that have ceased, one entry per security and date. Kept apart from purchases, and never netted against them."""
    d = _blank(form="appendix_3h", doc_type="cessation")
    flat = re.sub(r"^Appendix 3H - Notification of cessation of securities(?: \d+ / \d+)?\s*$", "", t, flags=re.M).replace("\f", "")
    after = lambda label, text=flat: (re.search(label + r"[^\n]*\n\s*([^\n]+)", text) or [None, None])[1]
    d["ticker"] = (after(r"1\.3 ASX issuer code") or "").strip().upper() or None
    d["company"] = (after(r"1\.1 Name of \+?Entity") or "").strip() or None
    d["doc_date"] = to_date(after(r"1\.5 Date of this announcement"))
    start, end = flat.find("Part 2 -"), flat.find("Part 3 -")
    part = flat[start:end if end > start else len(flat)] if start >= 0 else ""
    issued = flat[end:] if end >= 0 else ""
    d["cessations"] = []
    for block in re.split(r"ASX \+Security Code and Description\s*\n", part)[1:]:
        code, _, name = (block.split("\n", 1)[0]).partition(":")
        code = code.strip().upper()
        shares = re.search(r"Number of securities that have ceased\s*\n\s*([\d,]+)", block)
        reason = re.search(r"Reason for cessation\s*\n(.*?)\n\s*Date of cessation", block, re.S)
        ceased = to_date(after(r"Date of cessation", block))
        if not shares or not reason or not ceased:
            d["issues"].append(("CESSATION_UNCLEAR", f"An entry for {code or 'a security'} could not be read in full, so it was not added. Please check the filing."))
            continue
        words = re.sub(r"\s+", " ", reason.group(1)).strip()
        paid = re.search(r"Total consideration paid or payable\s+for the securities\s*\n\s*([A-Z]{3})\s+([\d,.]+)", block)
        other = re.search(r"Any other information[^\n]*\?\s*\n(.*)", block, re.S)
        note = re.sub(r"\s+", " ", re.sub(r"(?:^\s*(?:Yes|No)\s*$\n?)+", "", other.group(1), flags=re.M)).strip() if other else ""
        kind = re.search(r"^(?:Quoted|Unquoted)[^\n]*", block, re.M)
        after_change = re.search(rf"^{re.escape(code)} : .*?([\d,]+)\s*$", issued, re.M) if code else None
        d["cessations"].append({"security_code": code, "security": name.strip(), "quoted": kind.group(0).split()[0] if kind else None, "shares": num(shares.group(1)), "reason": words,
                                "is_buyback": 1 if re.search(r"buy[\s-]*back", words, re.I) else 0, "ceased_on": ceased, "consideration": num(paid.group(2)) if paid else None,
                                "currency": paid.group(1) if paid else None, "other_info": note, "issued_after": num(after_change.group(1)) if after_change else None})
    if not d["cessations"] and not d["issues"]:
        d["issues"].append(("CESSATION_UNCLEAR", "No securities that have ceased could be found in this form."))
    if not d["ticker"]:
        d["issues"].append(("NO_TICKER", "Field 1.3 (ASX issuer code) could not be read."))
    return d


# ---------- notices in words or tables ----------
def unit_of(text, home):
    """The price unit stated in the text, or None if it states none."""
    if re.search(r"pence|\bGBp\b|\(p\)|\d\s?p\b(?!\.m)", text):  # not the p of "5 p.m."
        return "GBp"
    if re.search(r"HK\$|\bHKD\b", text):
        return "HKD"
    if re.search(r"£|\bGBP\b", text):
        return "GBP"
    if re.search(r"€|\bEUR\b", text):
        return "EUR"
    if re.search(r"US\$|\bUSD\b", text):
        return "USD"
    if re.search(r"NZ\$|\bNZD\b", text):
        return "NZD"
    if re.search(r"(?<![A-Za-z])A\$|AU\$|\bAUD\b", text):
        return "AUD"
    for pattern, code in OTHER_UNITS:
        if re.search(pattern, text):
            return code
    if "$" in text and home in ("AUD", "NZD", "USD", "CAD", "SGD", "HKD", "TWD"):
        return home
    return None


def _tx(trade, shares, avg, high, low, unit, venue=""):
    cur = "GBP" if unit == "GBp" else unit
    value = None
    if shares is not None and avg is not None and unit:
        value = shares * avg / 100 if unit == "GBp" else shares * avg
    return {"trade_date": trade, "venue": venue, "shares": shares, "value": value, "currency": cur, "price_unit": unit, "price_avg": avg, "price_high": high, "price_low": low, "value_origin": "product"}


# ---------- phrases from data/keywords.csv ----------
KEYWORDS_FILE = Path(__file__).resolve().parent.parent / "data" / "keywords.csv"
KEYWORDS_DIR = KEYWORDS_FILE.with_suffix("")  # data/keywords/: more phrase files, copied in beside the main one
_KW = {"stamp": None, "rows": []}
_NAME = r"((?-i:[A-Z])[\w&.,'\u2019\- ]{1,80}?)"
_GAP = r"(?:[^.\n]|\.(?=\d)){1,160}?"


def compile_phrase(phrase):
    """A keywords-file phrase as a pattern: {DATE} and {NAME} are captured, {...} stands for a few words, spaces match any spacing and quotes match curly ones."""
    out = []
    for piece in re.split(r"(\{DATE\}|\{NAME\}|\s*\{\.\.\.\}\s*|\s+)", phrase.strip()):
        if not piece:
            continue
        if piece == "{DATE}":
            out.append(f"({DATE_RE})")
        elif piece == "{NAME}":
            out.append(_NAME)
        elif piece.strip() == "{...}":
            out.append(r"\s+(?:" + _GAP + r"\s+)?" if piece != piece.strip() else _GAP)
        elif piece.isspace():
            out.append(r"\s+")
        else:
            out.append("".join('["\u201c\u201d]' if ch == '"' else re.escape(ch) for ch in piece))
    return re.compile("".join(out), re.I)


def keywords(field, market=None):
    """[(pattern, means, phrase)] for one field. The file is re-read when it changes, so edits need no restart."""
    files = ([KEYWORDS_FILE] if KEYWORDS_FILE.exists() else []) + (sorted(KEYWORDS_DIR.glob("*.csv")) if KEYWORDS_DIR.is_dir() else [])
    if not files:
        return []
    stamp = [(f.name, f.stat().st_mtime_ns) for f in files]
    if _KW["stamp"] != stamp:
        import csv
        _KW["rows"] = []
        for f in files:  # a file that can't be read is left out and the others still count
            try:
                with f.open(encoding="utf-8-sig", newline="") as fh:
                    _KW["rows"] += [r for r in csv.DictReader(fh) if (r.get("phrase") or "").strip() and (r.get("field") or "").strip()]
            except (OSError, UnicodeDecodeError, csv.Error):
                continue
        for r in _KW["rows"]:
            r["pattern"] = compile_phrase(r["phrase"])
        # a programme date or broker phrase must say where the date or name is; one that doesn't is skipped rather than misread
        _KW["rows"] = [r for r in _KW["rows"] if r.get("field") not in ("programme_date", "broker", "programme_runs") or r["pattern"].groups >= 1]
        _KW["stamp"] = stamp
    return [(r["pattern"], (r.get("means") or "").strip(), r["phrase"]) for r in _KW["rows"]
            if r.get("field") == field and (r.get("market") or "ALL").upper() in ("ALL", (market or "ALL").upper())]


def first_phrase(text, field):
    """The earliest match in the text for a keywords-file field: (match, means, phrase), or None."""
    found = [(m, means, phrase) for pattern, means, phrase in keywords(field, getattr(_CTX, "market", None)) for m in [pattern.search(text)] if m]
    return min(found, key=lambda x: x[0].start()) if found else None


def programme_runs(text):
    """The programme's start and end dates from the 'programme_runs' phrases in data/keywords.csv. A phrase with two dates gives both;
    a phrase with one says in 'means' whether it is the Start or the End. The earliest wording in the notice wins."""
    found = sorted(((m, means) for pattern, means, _ in keywords("programme_runs", getattr(_CTX, "market", None)) for m in [pattern.search(text)] if m), key=lambda x: x[0].start())
    out = {}
    for m, means in found:
        dates = [to_date(g) for g in m.groups() if g]
        if len(dates) >= 2 and re.search(r"\b(?:purchased|repurchased|acquired|bought|transactions)\b[^.]{0,80}$", text[max(0, m.start() - 100):m.start()], re.I):
            continue  # the days a notice's purchases cover, not how long the programme runs
        if len(dates) >= 2:
            out.setdefault("start_date", dates[0])
            out.setdefault("end_date", dates[1])
        elif dates and means.lower().startswith("start"):
            out.setdefault("start_date", dates[0])
        elif dates and means.lower().startswith("end"):
            out.setdefault("end_date", dates[0])
    return out


def _cells(line):
    return [c.strip() for c in (line.split("|") if "|" in line else re.split(r"\s{2,}|\t", line)) if c.strip()]


def _colmap(cells):
    m = {}
    for i, c in enumerate(cells):
        lc = c.lower()
        if "venue" in lc or "exchange" in lc or "market" in lc:
            m["venue"] = i
        elif "date" in lc:
            m["date"] = i
        elif "high" in lc:
            m["high"] = i
        elif "low" in lc:
            m["low"] = i
        elif "average" in lc or "vwap" in lc:
            m["avg"] = i
        elif ("number" in lc or "shares" in lc or "volume" in lc or "aggregate" in lc) and "price" not in lc:
            m.setdefault("shares", i)
    return m if "shares" in m and ("avg" in m or "high" in m) else None


ROW_LABELS = [("avg", r"(average|vwap)"), ("high", r"high"), ("low", r"low"), ("shares", r"(number|aggregate|shares purchased|volume)")]  # price labels first: 'volume weighted average'


def _tables(lines, trade_default, home, doc_unit):
    """Rows-per-date or rows-per-venue tables, and transposed tables with one column per date."""
    out = []
    for i, line in enumerate(lines):
        cells = _cells(line)
        if not cells:
            continue
        cols = _colmap(cells) if len(cells) >= 3 else None
        if cols:
            unit_header = unit_of(line, home)
            for row in lines[i + 1:i + 40]:
                c = _cells(row)
                if len(c) <= cols["shares"]:
                    break
                shares = num(c[cols["shares"]])
                if shares is None:
                    break
                get = lambda k: num(c[cols[k]]) if k in cols and cols[k] < len(c) else None
                trade = to_date(c[cols["date"]]) if "date" in cols and cols["date"] < len(c) else None
                venue = c[cols["venue"]] if "venue" in cols and cols["venue"] < len(c) else ""
                if not venue and "date" not in cols and num(c[0]) is None:
                    venue = c[0]
                out.append(_tx(trade or trade_default, shares, get("avg"), get("high"), get("low"), unit_of(row, home) or unit_header or doc_unit, venue))
            if out:
                return out
        dated = [to_date(re.search(DATE_RE, c).group(0)) for c in cells if re.search(DATE_RE, c)]
        if dated and "|" in line:
            found = {}
            for row in lines[i + 1:i + 12]:
                c = _cells(row)
                if not c:
                    continue
                key = next((k for k, pat in ROW_LABELS if re.search(pat, c[0], re.I)), None)
                if key and key not in found:
                    found[key] = (c, unit_of(row, home))
            if "shares" in found and ("avg" in found or "high" in found):
                for j, trade in enumerate(dated):  # the last cells of a row line up with the date columns
                    val = lambda k: num(found[k][0][j - len(dated)]) if k in found and len(found[k][0]) > len(dated) else None
                    unit = (found.get("avg") or found.get("high") or (None, None))[1] or unit_of(line, home) or doc_unit
                    if val("shares") is not None:
                        out.append(_tx(trade, val("shares"), val("avg"), val("high"), val("low"), unit))
                if out:
                    return out
    return out


def _venue_blocks(body, home, doc_unit):
    """Separate labelled sections, one per venue, each with its own date and prices in its own currency (seen in HSBC's notices)."""
    starts = list(re.finditer(rf"date of purchase\s*:?\s*({DATE_RE})", body, re.I))
    out = []
    for i, m in enumerate(starts):
        block = body[m.start():starts[i + 1].start() if i + 1 < len(starts) else m.start() + 700]
        sh = re.search(rf"number of [^:\n]*?(?:purchased|repurchased|acquired)[^:\n]*:\s*({NUM_RE})", block, re.I)
        if not sh:
            continue
        price = lambda word: re.search(rf"{word}[^\n:]*:\s*([^\d\n]*?)\s*({NUM_RE})\s*(pence|p\b)?", block, re.I)
        avg, high, low = price("weighted average price"), price("highest price"), price("lowest price")
        unit_text = (avg.group(1) + (avg.group(3) or "")) if avg else ""
        before = [ln.strip() for ln in body[:m.start()].splitlines() if ln.strip()]
        # With one section, the line above is a venue only if it reads like one (HSBC's closing notice has Hong Kong alone).
        looks_like_venue = before and re.search(r"exchange|venue|market|\bLSE\b|cboe|turquoise|aquis|chi-x|bats", before[-1], re.I) and ":" not in before[-1]
        venue = before[-1][:40] if before and (len(starts) > 1 or looks_like_venue) else ""
        out.append(_tx(to_date(m.group(1)), num(sh.group(1)), num(avg.group(2)) if avg else None, num(high.group(2)) if high else None, num(low.group(2)) if low else None, unit_of(unit_text, home) or doc_unit, venue))
    return out


def _venue_split(lines, day, home):
    """The day's purchase split by venue, from a venue table ('Aggregate information') or a list of individual trades.
    Used only when the venue rows add up to the day's total; otherwise 'MISMATCH'. None when there is no such table."""
    for i, line in enumerate(lines):
        cells = [c.lower() for c in _cells(line)]
        if len(cells) < 3 or not any("venue" in c for c in cells):
            continue
        col = {}
        for j, c in enumerate(cells):
            if "venue" in c:
                col["venue"] = j
            elif "high" in c:
                col["high"] = j
            elif "low" in c:
                col["low"] = j
            elif "average" in c or "vwap" in c or ("price" in c and "price" not in col):
                col["price"] = j
            elif ("volume" in c or "number" in c or "shares" in c) and "price" not in c:
                col.setdefault("shares", j)
        if "venue" not in col or "shares" not in col or "price" not in col:
            continue
        unit = unit_of(line, home) or day["price_unit"]
        venues = {}
        for row in lines[i + 1:i + 400]:
            c = _cells(row)
            if len(c) <= max(col.values()):
                break
            shares, price = num(c[col["shares"]]), num(c[col["price"]])
            if shares is None or price is None:
                break
            if re.fullmatch(r"(total|aggregated?|all venues)", c[col["venue"]].strip(), re.I):  # the table's own total row, not another venue
                continue
            v = venues.setdefault(c[col["venue"]], {"shares": 0, "paid": 0, "high": None, "low": None})
            v["shares"] += shares
            v["paid"] += shares * price
            hi = num(c[col["high"]]) if "high" in col else price
            lo = num(c[col["low"]]) if "low" in col else price
            v["high"] = hi if v["high"] is None else max(v["high"], hi)
            v["low"] = lo if v["low"] is None else min(v["low"], lo)
        if not venues:
            continue
        if day["shares"] is None or abs(sum(v["shares"] for v in venues.values()) - day["shares"]) > 0.5:
            return "MISMATCH"
        out = []
        for name, v in venues.items():
            avg = round(v["paid"] / v["shares"], 6) if v["shares"] else None
            if len(venues) == 1 and day["price_avg"] is not None:  # one venue: the notice's own stated figures stay exact
                avg, v["high"], v["low"] = day["price_avg"], day["price_high"] if day["price_high"] is not None else v["high"], day["price_low"] if day["price_low"] is not None else v["low"]
            out.append(_tx(day["trade_date"], v["shares"], avg, v["high"], v["low"], unit, name))
        return out
    return None


def _venue_totals(body, as_of, home):
    """Programme totals per venue: 'repurchased ... 31,735,502 ordinary shares on the UK Venues at a volume weighted average price of £15.1909'."""
    if not re.search(r"since\s+the\s+commencement", body, re.I):
        return []
    out = []
    for m in re.finditer(rf"({NUM_RE})\s+ordinary\s+shares\s+on\s+the\s+([A-Z][^.\n]{{2,40}}?)\s+at\s+a\s+(?:volume\s+)?weighted\s+average\s+price\s+of\s+([^\d\s]*)\s*({NUM_RE})\s*(pence|p\b)?", body):
        x = _tx(as_of, num(m.group(1)), num(m.group(4)), None, None, unit_of(m.group(3) + (m.group(5) or ""), home), m.group(2).strip())
        out.append(x)
    return out


CUM_PATTERNS = [
    rf"(?:in aggregate|since|to date|in total|cumulative|total of)[^.\n]{{0,160}}?(?:purchased|repurchased|acquired|bought(?: back)?)\s+(?:a total of\s+)?({NUM_RE})\s+(?:ordinary\s+)?shares[^.\n]{{0,80}}?(?:weighted average price|average price)[^\d.\n]{{0,40}}({NUM_RE})\s*(pence|p\b)?",
    rf"(?:purchased|repurchased|acquired|bought(?: back)?)\s+(?:a total of\s+)?({NUM_RE})\s+(?:ordinary\s+)?shares\s+in aggregate[^.\n]{{0,80}}?(?:weighted average price|average price)[^\d.\n]{{0,40}}({NUM_RE})\s*(pence|p\b)?",
]


def parse_notice(t, home):
    d = _blank(form="notice", doc_type="unknown")
    # An RNS header gives the company and the filing date: "RNS Number : 0588O / Reckitt Benckiser Group PLC / 08 January 2026".
    rns = re.search(rf"RNS\s+Number\s*:?[^\n]*\n\s*([^\n]+?)\s*\n\s*({DATE_RE})", t, re.I)
    stated = re.search(rf"date of announcement\s*:?\s*({DATE_RE})", t, re.I)
    # Saved web pages carry a long site menu before the notice starts. A meeting's date, in the wording about the authority to buy, isn't the notice's date.
    first = next((m for m in re.finditer(DATE_RE, t[:8000]) if not re.search(r"(?:general\s+meeting|\bagm\b|authority)[^.\n]{0,50}$", t[max(m.start() - 80, 0):m.start()], re.I)), None)
    d["doc_date"] = to_date(rns.group(2)) if rns else to_date(stated.group(1)) if stated else (to_date(first.group(0)) if first else None)
    d["date_stated"] = bool(rns or stated)
    named = re.search(r"([A-Z][^\n(.]{1,70}?\b(?:plc|PLC|Limited|Ltd))\s*\(\s*(?:the\s+)?[\"\u201c]Company", t)
    if rns or named:
        d["company"] = (rns.group(1) if rns else named.group(1)).strip()
    doc_unit = unit_of(t, home)

    max_val, max_cur, max_text = _money_match(t, home)
    announced = first_phrase(re.sub(r"[ \t]+", " ", t), "programme_date")
    d["programme"] = {"announced_date": to_date(announced[0].group(1)) if announced else "", "max_value": max_val, "max_currency": max_cur, "max_text": max_text, "buyback_type": "On market buy-back" if re.search(r"on[- ]market|market purchase", t, re.I) else None}
    # "has 39,478,535 Ordinary Shares in issue" first: a label search could run on into the next sentence's treasury or voting rights figure
    issued = re.search(r"([\d,]{7,})\s+ordinary shares(?:[^.\n]{0,40})in issue", t, re.I) or re.search(r"(?:shares\s+in\s+issue|voting\s+rights|issued\s+share\s+capital)[^\d\n.]{0,90}([\d,]{7,})", t, re.I) or re.search(r"will\s+have\s+([\d,]{7,})\s+issued\s+ordinary\s+shares", t, re.I) or re.search(r"([\d,]{11,})\s+ordinary shares", t, re.I)  # billions only: a smaller number here is usually the programme's cap
    if issued:
        d["programme"]["shares_on_issue"] = num(issued.group(1))

    # the shareholders' general authority ("authority to repurchase up to 267 million Shares granted by its shareholders") is not this programme's limit
    cap = next((m for m in re.finditer(rf"(?:up to|maximum of|no more than)\s+(?:a maximum of\s+)?({NUM_RE})(?:\s*(million|billion))?\s+(?:of its\s+)?(?:ordinary\s+|fully paid\s+)*shares", t, re.I) if not _is_authority(t, m)), None)
    if cap:
        d["programme"]["max_shares"] = num(cap.group(1)) * SCALE.get((cap.group(2) or "").lower(), 1)
        d["cap_text"] = re.sub(r"\s+", " ", cap.group(0))
    else:
        cap = re.search(rf"maximum\s+number\s+of\s+[^.]{{0,90}}?\bis\s+({NUM_RE})", t, re.I)
        if cap:
            d["programme"]["max_shares"] = num(cap.group(1))
    d["programme"].update(programme_runs(re.sub(r"\s+", " ", t)))
    # "up until the 12-month anniversary of the date of this announcement": worked out from the notice's date.
    if not d["programme"].get("end_date") and d["doc_date"] and re.search(r"(?:12|twelve)[- ]month\s+anniversary\s+of\s+the\s+date\s+of\s+this\s+announcement", t, re.I):
        day = date.fromisoformat(d["doc_date"])
        d["programme"]["end_date"] = day.replace(year=day.year + 1, day=28 if (day.month, day.day) == (2, 29) else day.day).isoformat()
        d["programme"]["end_note"] = "Worked out from '12-month anniversary' of the announcement"

    body = t
    for pat in CUM_PATTERNS:
        m = re.search(pat, body, re.I | re.S)
        if m:
            sh, avg = num(m.group(1)), num(m.group(2))
            unit = "GBp" if m.group(3) else doc_unit
            tx = _tx(d["doc_date"], sh, avg, None, None, unit)
            d["cum"] = {"cum_shares": sh, "cum_value": tx["value"], "currency": tx["currency"], "avg": avg, "origin": "product", "working": f"{sh:,.0f} shares x {avg:,.4f} {unit or ''} average"}
            body = body[:m.start()] + body[m.end():]
            break

    # a running total of shares with no amount: "has purchased a total of 1,000,920 Ordinary Shares since the commencement"
    if "cum" not in d:
        count_only = re.search(rf"(?:purchased|repurchased|acquired|bought(?: back)?)\s+a\s+total\s+of\s+({NUM_RE})\s+(?:ordinary\s+)?shares\s+since\s+the\s+(?:commencement|start|launch)", body, re.I)
        if count_only:
            d["cum"] = {"cum_shares": num(count_only.group(1)), "cum_value": None, "currency": None, "origin": "reported", "working": "Shares only: the notice states no amount"}
            body = body[:count_only.start()] + body[count_only.end():]

    date_m = re.search(rf"date of (?:purchase|transaction|buy-?back)[^\n\d]{{0,30}}({DATE_RE})", body, re.I)
    on_m = re.search(rf"(?:on|dated?)\s+({DATE_RE})[^.\n]{{0,120}}(?:purchas(?:ed|es)|acquired|bought)|(?:purchas(?:ed|es)|acquired|bought)[^.\n]{{0,160}}?\bon\s+({DATE_RE})", body, re.I)
    trade = to_date(date_m.group(1)) if date_m else (to_date(on_m.group(1) or on_m.group(2)) if on_m else None)

    # "Shares repurchased and approximate total consideration (in US$m) since the commencement...: 46,023,902  US$945.0"
    total = re.search(rf"(?:shares\s+repurchased|shares\s+purchased)[^:]{{0,40}}consideration\s*\(in\s+(US\$|£|GBP|USD|€)\s*m\)[^:]*?since[^:]*:\s*({NUM_RE})\s+((?:US\$|£|€)?\s*({NUM_RE}))", body, re.I)
    if total and "cum" not in d:
        d["cum"] = {"cum_shares": num(total.group(2)), "cum_value": num(total.group(4)) * 1e6, "currency": CURRENCY.get(total.group(1).upper() if total.group(1) not in ("£", "€") else total.group(1), home), "value_text": total.group(3).strip(), "origin": "rounded", "working": f"{total.group(3).strip()} million as the notice states it, described there as approximate"}

    txs = _venue_blocks(body, home, doc_unit) or _tables(body.splitlines(), trade or d["doc_date"], home, doc_unit)
    if not txs:
        sh = re.search(r"(?:aggregate )?number of (?:ordinary |fully paid )*shares (?:purchased|repurchased|bought(?: back)?|acquired)\s*(?:\([^)\n]*\))?\s*[:|\-\u2013]?\s*(\d[\d,]*)", body, re.I)  # the number follows the label directly: 'repurchased by HSBC since the 2026 Authority' is not a count
        avg = re.search(r"(?:volume[- ])?weighted average price[^\d\n]{0,70}(\d[\d,.]*)", body, re.I)
        high = re.search(r"highest price[^\d\n]{0,60}(\d[\d,.]*)", body, re.I)
        low = re.search(r"lowest price[^\d\n]{0,60}(\d[\d,.]*)", body, re.I)
        if sh:
            txs = [_tx(trade or d["doc_date"], num(sh.group(1)), num(avg.group(1).rstrip(".")) if avg else None, num(high.group(1).rstrip(".")) if high else None, num(low.group(1).rstrip(".")) if low else None, doc_unit)]
            # an amount the notice states, under a label such as "Aggregate price paid": the average is then worked out from it
            paid = re.search(rf"(?:aggregate|total)\s+(?:price|consideration|amount)\s+paid[^\d\n]{{0,40}}({NUM_RE})", body, re.I)
            if paid and txs[0]["price_avg"] is None and txs[0]["shares"] and doc_unit and doc_unit != "GBp" and num(paid.group(1)):
                txs[0].update(value=num(paid.group(1)), currency=doc_unit, price_unit=doc_unit, price_avg=num(paid.group(1)) / txs[0]["shares"], value_origin="reported")
    if not txs:
        s = re.search(rf"(?:purchased|repurchased|acquired|bought(?: back)?)\s+(?:a total of\s+)?({NUM_RE})\s+(?:of its\s+)?(?:ordinary\s+|fully paid\s+)*shares[^.\n]{{0,140}}?(?:price|average)[^\d\n]{{0,30}}(\d[\d,]*(?:\.\d+)?)\s*(pence|p\b)?", body, re.I)
        if s:
            txs = [_tx(trade or d["doc_date"], num(s.group(1)), num(s.group(2)), None, None, "GBp" if s.group(3) else doc_unit)]

    if re.search(r"buy\s*-?\s*back\s+has\s+(?:now\s+)?(?:concluded|completed|ended)", body, re.I):  # PDFs can split it as "buy -back"
        d["programme"]["status"] = "COMPLETED"

    # "Has now completed that buyback... acquired N": a programme total with no purchase dates, so it is a final total rather than a dated purchase.
    if len(txs) == 1 and not trade and re.search(r"completed\s+(?:that|the|its)[^.\n]{0,40}buy-?\s?back", body, re.I):
        x = txs[0]
        d["snapshots"].append({"as_of": d["doc_date"], "cum_shares": x["shares"], "cum_value": x["value"], "currency": x["currency"], "avg": x["price_avg"], "origin": "product", "working": f"{x['shares']:,.0f} shares x {x['price_avg']:,.4f} {x['price_unit'] or ''} average"})
        d["programme"]["status"] = "COMPLETED"
        txs = []

    if txs and all(not x["venue"] for x in txs) and len({x["trade_date"] for x in txs}) == 1 and len(txs) == 1:
        split = _venue_split(body.splitlines(), txs[0], home)
        if split == "MISMATCH":
            d["issues"].append(("VENUE_MISMATCH", "The venue table doesn't add up to the day's total, so the day is kept as one figure. Please check it."))
        elif split:
            txs = split

    # Venue rows and a total row for the same day: keep the total only, so nothing counts twice.
    totals = {x["trade_date"] for x in txs if re.fullmatch(r"(total|aggregated?|all venues)", x["venue"], re.I)}
    txs = [x for x in txs if x["trade_date"] not in totals or re.fullmatch(r"(total|aggregated?|all venues)", x["venue"], re.I)]
    for x in txs:
        if re.fullmatch(r"(total|aggregated?|all venues)", x["venue"], re.I):
            x["venue"] = ""
    d["transactions"] = txs
    d["venue_totals"] = _venue_totals(body, d["doc_date"], home) if d["doc_date"] else []
    d["cancellations"] = _cancellations(body, txs, d["doc_date"]) if d["doc_date"] else []

    last = max((x["trade_date"] for x in txs if x["trade_date"]), default=None)
    if "cum" in d:
        d["snapshots"].append({"as_of": last or d["doc_date"], **d.pop("cum")})
    if txs:
        d["doc_type"] = "transaction"
        if not trade and not date_m and any(x["trade_date"] == d["doc_date"] for x in txs):
            if re.search(PERIOD_WORDS, body, re.I):
                d["issues"].append(("PERIOD_PURCHASE", "The notice reports buying over a period, not on a day, so it was not added as a purchase. Enter it by hand."))
                d["transactions"] = txs = []
            else:
                d["issues"].append(("DATE_ASSUMED", "No purchase date found, so the notice date was used."))
        if any(not x["price_unit"] for x in txs):
            d["issues"].append(("NO_PRICE_UNIT", "The notice states no price unit, so no value was calculated. Please check it."))
        if any(x["price_avg"] is None for x in txs):
            d["issues"].append(("NO_AVG_PRICE", "No average price found, so no value was calculated."))
    elif d["snapshots"]:
        d["doc_type"] = "transaction"
    elif (max_val or cap) and re.search(r"buy-?\s?back|repurchase", t, re.I):
        d["doc_type"] = "programme"
        raised = _size_increase(t, home) if max_val else None
        if raised:  # an increase to a programme already running: it updates that programme, and is never a new one
            d["doc_type"], d["reason"] = "update", "Programme size increased"
            d["programme"].update(max_value=raised["total"], max_currency=raised["currency"] if raised["total"] else None, max_text=raised["text"] if raised["total"] else None)
            when = d["doc_date"] or "this filing's date"
            if raised["total"]:
                d["anchors"] = {"max_value": raised["lead"]}
                d["programme"]["size_note"] = f"Size raised to {raised['currency']} {raised['total']:,.0f} on {when}" + (f", an increase of {max_cur} {max_val:,.0f}" if max_val != raised["total"] else "")
            else:
                d["programme"]["size_note"] = f"Size raised by {max_cur} {max_val:,.0f} on {when}; the new total isn't stated in that filing"
                d["issues"].append(("SIZE_INCREASE", f"This filing raises the programme's size by {max_cur} {max_val:,.0f} but doesn't state the new total, so the size was left as it was. Please check it."))
        else:
            d["programme"]["announced_assumed"] = not d["programme"]["announced_date"]  # dated by the notice, not by wording that names an announcement
            d["programme"]["announced_date"] = d["programme"]["announced_date"] or d["doc_date"] or ""
    else:
        d["issues"].append(("NOT_RECOGNISED", "Could not find buyback figures in this file. Enter them by hand or set it aside."))
    if not d["doc_date"]:
        d["issues"].append(("NO_DATE", "No notice date found near the top of the file."))
    if any(x["trade_date"] is None for x in txs):
        d["issues"].append(("NO_TRADE_DATE", "A purchase without a date was left out."))
        d["transactions"] = [x for x in txs if x["trade_date"]]
    return d


def _is_authority(t, m):
    """Whether a number of shares is the general authority shareholders gave to buy back shares, and so not the programme's own limit."""
    before, after = re.sub(r"\s+", " ", t[max(0, m.start() - 90):m.start()]), re.sub(r"\s+", " ", t[m.end():m.end() + 90])
    return bool(re.search(r"(?:authority|authorisation|authorization|authorised|authorized)\s+(?:granted\s+)?to\s+(?:(?:re)?purchase|buy\s?-?\s?back|make\s+market\s+purchases\s+of)\s*$", before, re.I)
                or re.match(r"\s*,?\s*(?:as\s+)?(?:granted|approved|authorised|authorized)\s+by\s+(?:its\s+|the\s+)?shareholders", after, re.I))


def _size_increase(t, home):
    """For a notice whose wording raises an existing programme's size (the 'programme_increase' phrases in data/keywords.csv):
    the new total it states, as {"total", "currency", "text"}; total is None when only the increase is given. None when it isn't an increase."""
    flat = re.sub(r"\s+", " ", t)
    if not first_phrase(flat, "programme_increase"):
        return None
    total = re.search(rf"(?:brings?|bringing|takes?|taking|increas\w+)\s+the\s+total(?:\s+(?:program(?:me)?|buy-?\s?back))?(?:\s+size)?\s+to\s+(?:up\s+to\s+)?(?:approximately\s+)?{MONEY_RE}", flat, re.I) \
        or re.search(rf"total\s+(?:program(?:me)?|buy-?\s?back)(?:\s+program(?:me)?)?\s+size\s+(?:of|to|is\s+now)\s+(?:up\s+to\s+)?(?:approximately\s+)?{MONEY_RE}", flat, re.I)
    if not total:
        return {"total": None, "currency": None, "text": None}
    sym = total.group(1).upper() if total.group(1) not in ("£", "€") else total.group(1)
    lead = r"\s+".join(re.escape(w) for w in flat[total.start():total.start(1)].split()[:4])  # the words that introduce the total, so its source isn't mistaken for the same amount elsewhere
    return {"total": num(total.group(2)) * SCALE[total.group(3).lower()], "currency": CURRENCY.get(sym, home), "text": flat[total.start(1):total.end(3)], "lead": "(?i)" + lead}


# ---------- NZX capital change notice ----------
def parse_capital_change(t, home):
    """The labelled NZX form. The same form also reports share issues, so parse() sends only buyback acquisitions here."""
    d = _blank(form="capital_change", doc_type="transaction")
    field = lambda pat: (re.search(pat, t, re.I) or [None, None])[1]
    d["ticker"] = (field(r"NZX ticker code\s+([A-Z0-9]{2,6})") or "").upper() or None
    d["company"] = (field(r"Name of issuer\s+([^\n]+)") or "").strip() or None
    d["doc_date"] = to_date(field(rf"Date of release through MAP\s+({DATE_RE})"))
    announced = to_date(field(rf"announced on\s+({DATE_RE})"))
    trade = to_date(field(rf"Date of issue/acquisition/redemption\s+({DATE_RE})"))
    shares = num(field(rf"Number (?:acquired|repurchased|redeemed)[^\d\n]*({NUM_RE})"))
    price_line = field(r"price per security\s+([^\n]+)") or ""
    price = re.search(NUM_RE, price_line)
    cur = (field(r"\bCurrency\s+([A-Z]{3})\b") or "").upper() or unit_of(price_line, home)
    on_issue = field(r"([\d,]{7,})\s+ordinary shares\s+(?:Nil|[\d,]+)[^\n]*Treasury")
    d["programme"] = {"announced_date": announced or "", "buyback_type": "On market buy-back" if re.search(r"on-market", t, re.I) else None, "shares_on_issue": num(on_issue)}
    if shares is None or not trade:
        d["issues"].append(("NOT_RECOGNISED", "This capital change notice is missing the number acquired or the date. Please check it."))
        return d
    d["transactions"].append(_tx(trade, shares, num(price.group(0)) if price else None, None, None, cur))
    if not price:
        d["issues"].append(("NO_AVG_PRICE", "No price per security found, so no value was calculated."))
    if not d["ticker"]:
        d["issues"].append(("NO_TICKER", "No NZX ticker code found."))
    return d


BUYBACK_WORDS = r"buy\s*-?\s*back|own\s+shares|share\s+repurchase"
IGNORED_WORDS = r"appendix\s*3[xyz]\b|director.{0,25}(?:interest|dealing|shareholding)|\bpdmr\b|\bresults?\b|[1-4]q\s*fy|quarterly\s+(?:report|update|activities|cash)|annual\s+report|investor\s+presentation"


def _top_lines(text, count):
    return [x.strip() for x in re.split(r"[\n\f]|\s{3,}", text) if x.strip()][:count]  # a web page can run its heading and menu together on one line


def heading(text, title=""):
    """The filing's heading, as written, to show beside it. A title from the list comes first."""
    if str(title or "").strip():
        return str(title).strip()[:160]
    form = re.search(r"Appendix\s*(\d+[A-Z])\b[ \t]*[-\u2013:]?[ \t]*([^\n]*)\n?\s*([^\n]*)", text[:1500])
    if form:
        return f"Appendix {form.group(1)} - {(form.group(2).strip() or form.group(3).strip())}"[:160]
    lines = _top_lines(text[:6000], 400)
    short = [x for x in lines if len(x.split()) >= 2 and len(x) <= 160]
    titles = [x for x in short if not x.endswith(".") and ". " not in x]  # a heading, not a sentence from the body
    for pattern, among in ((r"^capital change notice", titles), (IGNORED_WORDS, [x for x in titles if x in lines[:8]]), (BUYBACK_WORDS, titles), (BUYBACK_WORDS, short)):
        for line in among:
            if re.search(pattern, line, re.I):
                return line
    for line in lines:
        if len(line.split()) >= 3 and not re.match(r"skip to", line, re.I) and not to_date(line):
            return line[:160]
    return lines[0][:160] if lines else ""


def is_buyback_filing(text, title=""):
    """For unfiltered lists: the form, or the words near the top. A director's notice or a results update must not read as a company buyback, even if it mentions one.
    The window allows for a site menu or long header above the wording; anything still skipped is listed on Add data, with its heading and link."""
    start = f"{title}\n{text[:600]}"
    from . import hkex
    if hkex.is_return(text):  # a return is a buyback filing only if it reports a repurchase
        return hkex.has_buyback(text)
    if hkex.is_daily(text):
        return True
    if re.search(r"appendix\s*3[xyz]\b|change\s+of\s+director", start, re.I):
        return False
    if re.search(r"appendix\s*3[ch]\b", start, re.I):
        return True
    if re.search(r"Appendix 3[CH]", text) and re.search(r"1\.3 ASX issuer code", text):  # the form's title can sit below a long summary page
        return True
    for line in [str(title or "")] + _top_lines(text, 8):  # the heading line decides: "results and share buy-back" stays, a results update mentioning one doesn't
        if re.search(IGNORED_WORDS, line, re.I) and not re.search(BUYBACK_WORDS, line, re.I):
            return False
    return bool(re.search(BUYBACK_WORDS, f"{title}\n{text[:6000]}", re.I))


# ---------- what happens to the shares ----------
def cancel_treatment(text):
    """('Cancelled' or 'Treasury', the words used), only when the notice says so. The phrases are in data/keywords.csv.
    If the notice uses phrases for both, ('Conflict', the two phrases), so it goes to review rather than one being picked."""
    flat = re.sub(r"\s+", " ", text)
    hits = {}
    for pattern, means, _ in keywords("treatment", getattr(_CTX, "market", None)):
        m = pattern.search(flat)
        if m and len(m.group(0)) > len(hits.get(means, "")):  # the fullest wording found is the one shown
            hits[means] = m.group(0)
    if len(hits) > 1:
        return "Conflict", "; ".join(f"{k}: '{v}'" for k, v in sorted(hits.items()))
    return next(iter(hits.items()), None)

def _cancellations(body, txs, as_of):
    """Counts the notice itself states: earlier purchases now cancelled, today's purchases cancelled, and today's still awaiting cancellation."""
    out = []
    flat = re.sub(r"\s+", " ", body)
    earlier = re.search(rf"shares cancelled which were awaiting cancellation[^:]*?repurchased on the ([A-Z][^:]{{2,40}}?):\s*({NUM_RE})", flat, re.I)
    if earlier:
        out.append({"as_of": as_of, "venue": earlier.group(1).strip(), "shares": num(earlier.group(2)), "kind": "Cancelled", "note": "Bought earlier, cancelled now", "basis": "Reported count"})
    for x in txs:
        venue = x.get("venue") or ""
        if not venue:
            continue
        if re.search(rf"cancellation of the shares repurchased today on the {re.escape(venue)} takes longer", flat, re.I):
            out.append({"as_of": as_of, "venue": venue, "shares": x["shares"], "kind": "Awaiting cancellation", "note": "Bought that day, cancellation to follow", "basis": "From notice wording"})
        elif re.search(rf"following the\s+cancellation", flat, re.I) and re.search(rf"repurchased today on the {re.escape(venue)}", flat, re.I):
            out.append({"as_of": as_of, "venue": venue, "shares": x["shares"], "kind": "Cancelled", "note": "Bought and cancelled the same day", "basis": "From notice wording"})
    return out


def set_filing_date(p, value, basis):
    """Use this as the filing's date, moving what was dated by the date it replaces."""
    old = p["doc_date"]
    p["doc_date"], p["date_basis"] = value, basis
    for row in p["snapshots"] + p.get("cancellations", []):
        if row.get("as_of") == old or not row.get("as_of"):
            row["as_of"] = value


def covering_dates(p):
    """Whether a purchase notice's start and end are only the days its purchases cover (a weekly notice says "from 14 September to 18 September"),
    not the dates the programme runs. True only for a notice in prose that reports purchases, when every purchase lies inside the two dates and they are at most a month apart."""
    g = p.get("programme") or {}
    a, b = g.get("start_date"), g.get("end_date")
    days = [x.get("trade_date") for x in p.get("transactions") or [] if x.get("trade_date")]
    if p.get("form") != "notice" or p.get("doc_type") != "transaction" or not (a and b and days):
        return False
    try:
        apart = (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return False
    return 0 <= apart <= 31 and a <= min(days) and max(days) <= b


def _settle_notice_date(p):
    """A filing can't be dated before the purchases it reports. A notice saying only 'announces today' has no date of its own, so its latest purchase date stands in, and the filing says so."""
    latest = max((x["trade_date"] for x in p["transactions"] if x.get("trade_date")), default=None)
    if latest and not p.get("date_stated") and (not p["doc_date"] or p["doc_date"] < latest):
        set_filing_date(p, latest, "purchase date")


def parse(text, home, market=None, date_order=None):
    """Read with the market's own phrases and date order (DMY unless its settings say MDY)."""
    _CTX.market, _CTX.date_order = market, date_order or "DMY"
    try:
        p = _parse(text, home)
        from . import validate
        p["issues"] += validate.check(p)  # the same checks on every filing, whichever reader read it
        return p
    finally:
        _CTX.market, _CTX.date_order = None, "DMY"


def _parse(text, home):
    """The facts in a notice, plus what it says happens to the shares."""
    p = _parse_form(text, home)
    if p["form"] == "notice":
        _settle_notice_date(p)
        if covering_dates(p):  # the week the notice covers, not how long the programme runs
            p["programme"].pop("start_date", None)
            p["programme"].pop("end_date", None)
        held = re.search(rf"\b(?:holds?|there\s+are)\s+({NUM_RE})\s+(?:of\s+its\s+)?(?:ordinary\s+)?shares\s+(?:held\s+)?in\s+treasury", re.sub(r"\s+", " ", text), re.I)
        if held and p["doc_date"] and p["transactions"]:
            p.setdefault("cancellations", []).append({"as_of": p["doc_date"], "venue": "", "shares": num(held.group(1)), "kind": "Held in treasury", "note": "Total held after this purchase", "basis": "Reported count"})
    from . import forms
    market = getattr(_CTX, "market", None)
    if not p.get("definition") and market and forms.for_market(market) and not (p["transactions"] or p["snapshots"] or p["doc_type"] == "programme"):
        p["issues"] = [x for x in p["issues"] if x[0] != "NOT_RECOGNISED"]  # one message, saying what the filing needs
        p["issues"].append(("UNKNOWN_LAYOUT","No figures were read: this filing matches none of the layouts described for this market in data/forms. It needs a layout definition, or its figures entered by hand."))
    treatment = None if p.get("definition") else cancel_treatment(text)  # a described form states what happened to the shares in its own fields
    if treatment and treatment[0] == "Conflict":
        p["issues"].append(("TREATMENT_CONFLICT", f"The notice uses wording for both cancelling and holding in treasury ({treatment[1]}). Please check which applies."))
    elif treatment:
        p["programme"]["treatment"], p["programme"]["treatment_text"] = treatment
    if p["form"] == "notice":
        found = first_phrase(re.sub(r"\s+", " ", text), "broker")
        if found:
            p["broker"] = {"name": found[0].group(1).strip(" ,"), "role": found[1], "text": found[0].group(0)}
    if p.get("broker"):
        p["programme"]["broker"] = p["broker"]["name"]
        for x in p["transactions"]:
            x["broker"], x["broker_role"], x["broker_text"] = p["broker"]["name"], p["broker"]["role"], p["broker"]["text"]
    return p


def _parse_form(text, home):
    """Choose the format from the content, so a new country can use the existing parsers. A layout described in data/forms is tried first."""
    from . import forms, hkex
    if hkex.is_return(text):  # the Hong Kong forms have rows that repeat, so they are read in their own module
        return hkex.read_return(text, home)
    described = forms.read(text, getattr(_CTX, "market", None), home)
    if described:
        return described
    if re.search(r"Capital Change Notice", text, re.I) and re.search(r"Number (?:acquired|repurchased|redeemed)", text, re.I) and re.search(r"buy-?\s?back|repurchase", text, re.I):
        return parse_capital_change(text, home)
    if re.search(r"Appendix 3H", text[:600]) and re.search(r"1\.3 ASX issuer code", text):
        return parse_3h(text, home)
    if re.search(r"Appendix 3G", text[:600]) and re.search(r"1\.3 ASX issuer code", text):
        return parse_3g(text, home)
    # the ASX forms for buy-backs announced before 5 June 2021 (version 28)
    if re.search(r"Appendix 3E", text[:600]) and re.search(r"Daily share buy-?back notice", text[:600], re.I):
        return parse_3e(text, home)
    if re.search(r"Appendix 3F", text[:600]) and re.search(r"Final share buy-?back notice", text[:600], re.I):
        return parse_3f(text, home)
    if re.search(r"Appendix 3D", text[:600]) and re.search(r"Changes relating to buy-?back", text[:600], re.I):
        return parse_3d(text, home)
    # The same ASX form is sometimes headed only "Notification of buy-back", with no "Appendix 3C" on any page
    if re.search(r"Appendix 3C|^Notification of buy-back\s*$", text, re.M) and re.search(r"1\.3 ASX issuer code", text):
        return parse_3c(text, home)
    return parse_notice(text, home)


# ---------- where each figure came from ----------
def _number_pattern(v):
    """Matches a number as a notice may write it: 1371.92 finds 1,371.92 and 1,371.9200."""
    whole, _, frac = f"{v:.5f}".rstrip("0").partition(".")
    pat = "".join(ch + ",?" for ch in whole[:-1]) + whole[-1]
    return rf"(?<![\d.,]){pat}" + (rf"\.{frac}0*" if frac else r"(?:\.0+)?") + r"(?![\d])"


def _locate(text, pattern, anchor=None):
    """(start, written text) of the pattern, looking after the anchor first so a form's summary page is the last resort."""
    start = 0
    if anchor:
        a = re.search(anchor, text)
        if a:
            start = a.start()
    m = re.search(pattern, text[start:]) if start else None
    if m:
        return start + m.start(), m.group(0)
    m = re.search(pattern, text)
    return (m.start(), m.group(0)) if m else (None, None)


def _date_pattern(iso, text):
    for m in re.finditer(DATE_RE, text):
        if to_date(m.group(0)) == iso:
            return r"(?<!\d)" + re.escape(m.group(0))
    return None


ANCHORS_3C = {"trade_date": r"4\.2 Previous", "shares": r"4\.3 Total", "value": r"4\.4 Total", "price_high": r"4\.5 Highest", "price_low": r"4\.6 Lowest",
              "shares_on_issue": r"3A\.1 Total", "max_shares": r"3A\.5a", "start_date": r"3C\.2", "end_date": r"3C\.3", "announced_date": r"1\.4c", "max_value": r"3D\.1",
              "cum_shares": r"5\.1 Total", "cum_value": r"5\.2 Total", "before_shares": r"4\.3 Total", "before_value": r"4\.4 Total"}


def evidence(text, p):
    """One record per figure: key (which row it belongs to), field, page, the text as written, and the words before it."""
    out = []
    anchors = ANCHORS_3C if p["form"] == "appendix_3c" else p.get("anchors", {})  # a described form names the label each figure sits under

    def add(key, field, value):
        if value in (None, ""):
            return
        is_date = isinstance(value, str)
        if is_date:  # look after the field's label first, as the same date can also appear earlier in other words
            label = re.search(anchors[field], text) if field in anchors else None
            pattern = (_date_pattern(value, text[label.start():]) if label else None) or _date_pattern(value, text)
        else:
            pattern = _number_pattern(float(value))
        if not pattern:
            return
        pos, written = _locate(text, pattern, anchors.get(field))
        if pos is None:
            return
        line_start = text.rfind("\n", 0, pos) + 1
        context = re.sub(r"\s+", " ", text[max(line_start - 90, 0):pos]).strip()[-90:]
        out.append({"key": key, "field": field, "page": text.count("\f", 0, pos) + 1, "text": written, "context": context})

    for x in p["transactions"]:
        key = f"tx|{x['trade_date']}|{x.get('venue') or ''}"
        add(key, "trade_date", x["trade_date"])
        for field in ("shares", "price_avg", "price_high", "price_low"):
            add(key, field, x.get(field))
        if p["form"] == "appendix_3c" or (p.get("definition") and x.get("value_origin") == "reported"):
            add(key, "value", x.get("value"))
    daily_3c = p["form"] in ("appendix_3c", "appendix_3e") and len(p["snapshots"]) == 2
    for s in p["snapshots"][-1:] if daily_3c else p["snapshots"]:
        key = f"snap|{s['as_of']}"
        if daily_3c:  # the running total is 'before' plus 'on the day', so point at both
            before, day = p["snapshots"][0], p["transactions"][0] if p["transactions"] else {}
            add(key, "before_shares", before.get("cum_shares"))
            add(key, "before_value", before.get("cum_value"))
            add(key, "shares", day.get("shares"))
            add(key, "value", day.get("value"))
        else:
            add(key, "cum_shares", s.get("cum_shares"))
            add(key, "cum_value", s.get("cum_value"))
            add(key, "price_avg", s.get("avg"))
            if s.get("value_text"):  # a rounded total as written, such as "US$945.0", in millions
                m = re.search(re.escape(s["value_text"]), text)
                if m:
                    out.append({"key": key, "field": "cum_value", "page": text.count("\f", 0, m.start()) + 1, "text": m.group(0), "context": ""})
    for v in p.get("venue_totals", []):
        add(f"venue|{v['venue']}", "venue_shares", v["shares"])
        add(f"venue|{v['venue']}", "venue_price", v["price_avg"])
    for c in p.get("cancellations", []):
        add(f"cancel|{c['as_of']}|{c['venue']}|{c['kind']}", "cancel_shares", c["shares"])
    prog = p["programme"]
    if prog.get("treatment_text"):
        m = re.search(r"\s+".join(re.escape(w) for w in prog["treatment_text"].split()), text)
        if m:
            out.append({"key": "prog", "field": "treatment", "page": text.count("\f", 0, m.start()) + 1, "text": m.group(0), "context": ""})
    for field in ("announced_date", "start_date", "end_date", "max_shares", "shares_on_issue"):
        add("prog", field, prog.get(field))
    if p.get("cap_text"):  # the cap as written, such as "up to 3.5 million shares"
        m = re.search(r"\s+".join(re.escape(w) for w in p["cap_text"].split()), text)
        if m:
            out.append({"key": "prog", "field": "max_shares", "page": text.count("\f", 0, m.start()) + 1, "text": m.group(0), "context": ""})
    if prog.get("max_text"):
        lead = re.search(anchors["max_value"], text) if "max_value" in anchors else None  # the words that introduce the size, when the same amount appears elsewhere
        at = text.find(prog["max_text"], lead.start() if lead else 0)
        if at >= 0:
            out.append({"key": "prog", "field": "max_value", "page": text.count("\f", 0, at) + 1, "text": prog["max_text"], "context": ""})
    for i, c in enumerate(p.get("cessations", [])):
        key = f"cess|{i}"
        add(key, "ceased_on", c["ceased_on"])
        add(key, "shares", c["shares"])
        add(key, "consideration", c["consideration"])
    return out


def match_company(name_hint, text, companies):
    """Find the ticker: the file name's first word, then a company name near the top of the text. Longest name first."""
    tickers = {c["ticker"] for c in companies}
    first = re.split(r"[ _\-]", Path(name_hint).stem, maxsplit=1)[0].upper() if name_hint else ""
    if first in tickers:
        return first
    head = text[:1200]
    strip = lambda n: re.sub(r"\b(plc|limited|ltd|corporation|inc\.?|the)\b", "", n, flags=re.I).strip(" .,")
    for c in sorted(companies, key=lambda c: -len(c["company"] or "")):
        n = strip(c["company"] or "")
        if len(n) < 2:
            continue
        flags = re.I if len(n) >= 4 else 0  # short names such as BP or IMI must match exactly, or ordinary words would count
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", head, flags):
            return c["ticker"]
    return None


# ---------- ASX Appendix 3D, 3E and 3F (forms for buy-backs announced before 5 June 2021) and Appendix 3G (version 28) ----------
# Each is a fixed form with numbered items. A figure that cannot be told apart is never guessed: it goes to review.
_OLD_MONEY = r"(NZ\$|A\$|AU\$|US\$|AUD|NZD|USD|\$)\s?(\d[\d,]*\.?\d*)"
_NO_CHANGE = re.compile(r"^(?:no change\.?|n/?a\.?|not applicable\.?|none\.?)$", re.I)


def _item(t, n, nxt):
    """The text of item n of an old ASX form: from its number to the next item's number (or the end)."""
    m = re.search(rf"(?m)^\s*{n}\s+(?=\S)", t)
    if not m:
        return ""
    end = re.search(rf"(?m)^\s*{nxt}\s+(?=\S)", t[m.end():]) if nxt else None
    return t[m.end(): m.end() + end.start()] if end else t[m.end():]


def _signed_date(t):
    m = re.search(r"Date:\s*([0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", t)
    return to_date(m.group(1)) if m else None


def _old_money(s, home):
    """(value, currency) of the amounts in s, in order. "$" alone is the market's own currency, as on the forms of that market."""
    out = []
    for m in re.finditer(_OLD_MONEY, s or ""):
        v = num(m.group(2).rstrip("."))
        if v is not None:
            out.append((v, CURRENCY.get(m.group(1).upper().replace(" ", ""), home) if m.group(1) != "$" else home))
    return out


def _weekday_before(iso):
    d = datetime.strptime(iso, "%Y-%m-%d").date() - timedelta(days=1)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d.isoformat()


def _old_entity(t):
    m = re.search(r"Name of entity\s+ABN/ARSN\s*\n\s*([^\n]+?)\s*\n", t)
    return m.group(1).strip() if m else None


_OLD_HEAD = [r"Appendix 3[DEF]", r"Changes relating to buy-back", r"Daily share buy-back notice", r"Final share buy-back notice", r"\+ See chapter 19 for defined terms\.?",
             r".*Appendix 3[DEF]\s+Page \d+.*"]
_3D_HEAD = [r"All buy-backs", r"On-market buy-back", r"Column [12]", r"\(Details announced to", r"market in Appendix 3C", r"or\s+last Appendix 3D\)", r"\(Details of change to", r"buy-back proposals\)"]


def _strip_old(t, form):
    """The page headings and column headings that repeat on every page of the old forms, taken out so an item's text ends where the item ends."""
    heads = _OLD_HEAD + (_3D_HEAD if form == "3D" else [])
    return re.sub(r"(?m)^\s*(?:" + "|".join(heads) + r")\s*$\n?", "", t.replace("\f", ""))


def parse_3e(t, home):
    """Appendix 3E, the daily notice: the shares and amount before the previous day, and on the previous day. The form gives no date for the
    previous day, only the date it was signed, so the purchase is dated the trading day before that date, marked Calculated with the working.
    A public holiday is not known, so that date can be a day out; it can be Updated Manually."""
    t = _strip_old(t, "3E")
    d = _blank(form="appendix_3e", doc_type="daily", company=_old_entity(t))
    d["doc_date"] = _signed_date(t)
    btype = next((x.strip() for x in re.sub(r"^\s*Type of buy-?back", "", _item(t, 1, 2), flags=re.I).split("\n") if x.strip()), None)
    given = re.search(r"Date Appendix 3C was given to\s+ASX\s+(.+?)\s*\n", _item(t, 2, 3) + "\n", re.S)
    announced = to_date(re.sub(r"\s+", " ", given.group(1)).strip()) if given else None
    shares = [num(x) for x in re.findall(r"(?m)^\s*(\d{1,3}(?:,\d{3})+|\d+)\s*$", _item(t, 3, 4))]
    paid = _old_money(_item(t, 4, 5), home)
    prices = [v for v, _ in _old_money(re.split(r"highest price allowed", _item(t, 5, 6), flags=re.I)[0], home)]
    remaining = re.sub(r"\s+", " ", _item(t, 7, None).split("Compliance statement")[0]).strip()
    remaining = re.sub(r"^If the company/trust has\s+disclosed.*?bought back\s*", "", remaining, flags=re.I).strip()
    d["programme"] = {"announced_date": announced, "buyback_type": btype}
    if remaining and not _NO_CHANGE.match(remaining):
        d["programme"]["size_note"] = f"Remaining to be bought back, as the notice states: {remaining}"
    if not announced:
        d["issues"].append(("DATE_MISSING", "Item 2 (date Appendix 3C was given to ASX) could not be read, so the programme is chosen by date."))
    if len(shares) != 2 or len(paid) != 2:
        d["issues"].append(("CHECK_FAILED", "Items 3 and 4 (shares and amount, before the previous day and on it) could not be read as two columns. Nothing was added; please check the filing."))
        return d
    if not d["doc_date"]:
        d["issues"].append(("DATE_MISSING", "The notice states no date, so the previous day cannot be worked out. Nothing was added; enter the purchase on Add by hand or update it."))
        return d
    (before, today), ((v_before, cur), (v_today, cur2)) = shares, paid
    if cur != cur2:
        d["issues"].append(("CURRENCY_MIX", f"Item 4 shows {cur} before and {cur2} on the previous day."))
    trade = _weekday_before(d["doc_date"])
    hi, lo = (prices[2], prices[3]) if len(prices) == 4 else (prices[0], prices[1]) if len(prices) == 2 and before == 0 else (None, None)
    d["date_working"] = f"The form gives no date for the previous day; it is the trading day before the notice dated {d['doc_date']} (a public holiday is not known)"
    d["transactions"].append({"trade_date": trade, "venue": "", "shares": today, "value": v_today, "currency": cur2, "price_unit": cur2,
                              "price_avg": v_today / today if today else None, "price_high": hi, "price_low": lo, "value_origin": "reported", "date_working": d["date_working"]})
    d["snapshots"] += [{"as_of": _weekday_before(trade), "cum_shares": before, "cum_value": v_before, "currency": cur, "origin": "reported"},
                       {"as_of": trade, "cum_shares": before + today, "cum_value": v_before + v_today if cur == cur2 else None, "currency": cur2, "origin": "sum",
                        "working": f"{cur} {v_before:,.2f} before that day + {cur2} {v_today:,.2f} on the day" if cur == cur2 else None}]
    d["previous_date"] = trade
    return d


def parse_3f(t, home):
    """Appendix 3F, the final notice: the total shares and amount of the whole buy-back. The programme is marked Completed on the notice's date."""
    t = _strip_old(t, "3F")
    d = _blank(form="appendix_3f", doc_type="final", company=_old_entity(t))
    d["doc_date"] = _signed_date(t)
    btype = next((x.strip() for x in re.sub(r"^\s*Type of buy-?back", "", _item(t, 1, 2), flags=re.I).split("\n") if x.strip()), None)
    shares = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)", re.sub(r"^\s*Number of shares/units bought\s+back", "", _item(t, 2, 3), flags=re.I))
    paid = _old_money(_item(t, 3, 4), home)
    d["programme"] = {"buyback_type": btype, "status": "COMPLETED"}
    if not shares or not paid or not d["doc_date"]:
        d["issues"].append(("CHECK_FAILED", "Items 2 and 3 (shares bought back and total consideration) or the notice's date could not be read. Nothing was added; please check the filing."))
        return d
    d["snapshots"].append({"as_of": d["doc_date"], "cum_shares": num(shares.group(1)), "cum_value": paid[0][0], "currency": paid[0][1], "origin": "reported"})
    return d


def parse_3d(t, home):
    """Appendix 3D, changes to a buy-back. Each item has Column 1 (as announced) and Column 2 (the change). The PDF text runs the two columns
    together, so a change is only taken where it can be told apart: "No change" or "N/A" in Column 2, or two dated periods or two figures
    of which the second is the change. Anything else goes to review with its wording; it is never guessed."""
    t = _strip_old(t, "3D")
    d = _blank(form="appendix_3d", doc_type="update", company=_old_entity(t))
    d["doc_date"] = _signed_date(t)
    if not d["doc_date"]:
        d["date_basis"] = "not stated in the form"
    given = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", re.sub(r"(?s)^.*?given to\s+ASX", "", _item(t, 1, 2)))
    given = to_date(given.group(1)) if given else None
    d["previous_date"] = given
    d["programme"] = {}
    unclear = []
    clean = lambda s: re.sub(r"\s+", " ", s or "").strip()
    for n, nxt, label in ((2, 3, "broker"), (4, 5, "maximum number"), (5, 6, "number remaining"), (6, 7, "period"), (7, 8, "conditions"), (8, 9, "other change")):
        body = _item(t, n, nxt)
        body = re.split(r"\n\s*\n\s*(?:Appendix 3D\s*\n|$)", body)[0] if n == 8 else body
        lines = [x.strip() for x in body.split("\n") if x.strip()]
        tail = lines[-1] if lines else ""
        if not lines or _NO_CHANGE.match(tail) or re.fullmatch(r"(?:N/?A\s*){2}", tail, re.I) or re.match(r"Deleted", lines[0]):
            continue
        words = clean(body)
        if label == "period":
            spans = re.findall(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+to\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", words)
            if len(spans) == 2:
                d["programme"]["start_date"], d["programme"]["end_date"] = to_date(spans[1][0]), to_date(spans[1][1])
                continue
        if label == "maximum number":
            counts = re.findall(r"(\d{1,3}(?:,\d{3}){2,})\s+(?:shares|units)", words, re.I)
            if len(counts) == 2:
                d["programme"]["max_shares"] = num(counts[1])
                continue
        unclear.append(f"Item {n} ({label}): {words[:400]}")
    reason = clean(re.sub(r"^\s*Reason for change", "", _item(t, 9, 10)))
    d["reason"] = reason or None
    if unclear:
        d["issues"].append(("CHANGE_UNCLEAR", "This Appendix 3D changes an item whose two columns (as announced, and the change) run together in the filing's text, so the change was not taken: "
                            + " | ".join(x.rstrip(". ") for x in unclear) + (f". Reason given: {reason.rstrip('. ')}" if reason else "") + ". Check the filing; if a term changed, update it on Add by hand."))
    return d


def parse_3g(t, home):
    """Appendix 3G, securities issued, transferred or converted. One entry per issue: the class it went into, the number, the date, the class it
    came from, how it was provided (new securities issued, or existing ones transferred) and the company's own words. Part 4 gives the
    securities on issue afterwards. Kept apart from purchases, and never netted against them."""
    d = _blank(form="appendix_3g", doc_type="issue")
    flat = re.sub(r"(?m)^Appendix 3G - Notification of issue[^\n]*$", "", t).replace("\f", "")
    after = lambda label, text=flat: (re.search(label + r"[^\n]*\n\s*([^\n]+)", text) or [None, None])[1]
    d["ticker"] = (after(r"1\.3 ASX issuer code") or "").strip().upper() or None
    d["company"] = (after(r"1\.1 Name of entity") or "").strip() or None
    d["doc_date"] = to_date(after(r"1\.5 Date of this announcement"))
    d["issued"] = []
    blocks = re.split(r"(?m)^Issue details\s*$", flat)
    nums = [num(m) for m in re.findall(r"(?m)^Issue details\s*\nNumber of \+securities\s*\n\s*([\d,]+)", flat)]
    dates = [to_date(x) for x in re.findall(r"Date the \+securities the subject of this notification were issued/transferred\s*\n\s*([^\n]+)", flat)]
    froms = re.findall(r"FROM \(Existing Class\)\s*\nASX \+Security code and description\s*\n\s*([^\n]+)", flat)
    tos = re.findall(r"TO \(Existing Class\)\s*\nASX \+Security code and description\s*\n\s*([^\n]+)", flat)
    others = [re.sub(r"\s+", " ", x).strip() for x in re.findall(r"Any other information the entity wishes to provide about the \+securities the subject of this notification\s*\n(.*?)\n(?:Issue details|Name of KMP)", flat, re.S)]
    how = set(re.findall(r"(?m)^(A transfer of existing \+securities|An issue of new \+securities)\s*$", flat))
    provided = None if len(how) != 1 else ("Transfer of existing securities" if "transfer" in next(iter(how)) else "Issue of new securities")
    summary = [(c, desc.strip(), num(n), to_date(dt)) for c, desc, n, dt in re.findall(r"(?m)^([A-Z0-9]{3,6})\s+(.+?)\s+([\d,]+)\s+(\d{1,2}/\d{1,2}/\d{4})\s*$", flat.split("Part 1 -")[0])]
    if nums and len(nums) == len(dates) == len(tos):
        for i, n in enumerate(nums):
            code, _, desc = tos[i].partition(":")
            d["issued"].append({"security_code": code.strip().upper(), "security": desc.strip(), "shares": n, "issued_on": dates[i], "from_security": froms[i].strip() if i < len(froms) else None,
                                "provided_by": provided, "other_info": others[i] if i < len(others) else None})
        by_day = {}
        for x in d["issued"]:
            by_day[(x["security_code"], x["issued_on"])] = by_day.get((x["security_code"], x["issued_on"]), 0) + x["shares"]
        if summary and by_day != {(c, dt): n for c, _, n, dt in summary}:
            d["issues"].append(("CHECK_FAILED", "The issues in the form's detail do not add up to its summary on page 1. Please check the filing."))
    elif summary:  # the detail could not be read in order: the summary on page 1 states each class, number and date
        d["issued"] = [{"security_code": c, "security": desc, "shares": n, "issued_on": dt, "from_security": None, "provided_by": provided, "other_info": None} for c, desc, n, dt in summary]
        d["issues"].append(("ISSUE_DETAIL_UNCLEAR", "The detail of each issue could not be read in order, so the summary on page 1 was used (class, number and date only)."))
    else:
        d["issues"].append(("ISSUE_UNCLEAR", "No securities issued or transferred could be read in this form. Please check the filing."))
    if provided is None and d["issued"]:
        d["issues"].append(("ISSUE_DETAIL_UNCLEAR", "The form does not say in one way how the securities were provided (new securities issued, or existing ones transferred), so that is left blank."))
    part4 = flat.split("4.1 Quoted", 1)[1].split("4.2 Unquoted", 1)[0] if "4.1 Quoted" in flat else ""
    on_issue = re.search(rf"(?m)^{re.escape(d['ticker'] or '#')}\s*:\s*[^\n]*?\s([\d,]+)\s*$", part4)
    d["on_issue"] = {"security_code": d["ticker"], "shares": num(on_issue.group(1))} if on_issue else None
    if not d["ticker"]:
        d["issues"].append(("NO_TICKER", "Field 1.3 (ASX issuer code) could not be read."))
    return d
