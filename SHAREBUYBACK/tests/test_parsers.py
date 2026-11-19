"""Run:  python -P tests/test_parsers.py [folder of real sample PDFs]"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sbb import parsers

FX = ROOT / "tests" / "fixtures"


def load(name, home):
    text = parsers.read_text(FX / name)
    return text, parsers.parse(text, home)


# Real Appendix 3H forms, as the app's reader sees them
t, p = load("au_3h_mixed.txt", "AUD")
assert p["form"] == "appendix_3h" and p["ticker"] == "IPH" and p["doc_date"] == "2025-01-15" and not p["issues"], p["issues"]
lapse, bought = p["cessations"]
assert (lapse["security_code"], lapse["shares"], lapse["is_buyback"], lapse["ceased_on"], lapse["quoted"]) == ("IPHAA", 116236, 0, "2024-12-31", "Unquoted"), lapse
assert lapse["reason"].startswith("Lapse of conditional right") and lapse["reason"].endswith("satisfied"), lapse
assert (bought["security_code"], bought["shares"], bought["is_buyback"], bought["ceased_on"], bought["consideration"], bought["issued_after"]) == ("IPH", 2070144, 1, "2024-12-24", None, 273541468), bought
assert bought["reason"] == "Cancellation pursuant to an on-market buy-back" and "ongoing on-market buy-back" in bought["other_info"], bought
assert "Yes" not in bought["other_info"].split() and "No" not in bought["other_info"].split(), bought
assert any(e["key"] == "cess|1" and e["text"] == "2,070,144" for e in parsers.evidence(t, p))
t, p = load("au_3h_daily.txt", "AUD")
assert len(p["cessations"]) == 4 and sum(c["shares"] for c in p["cessations"]) == 78535, p["cessations"]
assert (p["cessations"][0]["consideration"], p["cessations"][0]["currency"], p["cessations"][0]["ceased_on"]) == (24036.41, "AUD", "2026-01-06"), p["cessations"][0]
assert [c["ceased_on"] for c in p["cessations"]] == ["2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
t, p = load("au_3h_lapse.txt", "AUD")
assert parsers.is_buyback_filing(t) and p["cessations"][0]["is_buyback"] == 0 and p["cessations"][0]["shares"] == 6106, p["cessations"]  # a 3H is kept even with no mention of a buy-back
assert parsers.heading(t) == "Appendix 3H - Notification of cessation of securities"

# A notice that only says "announces today", with an AGM date in its first sentence, buying into treasury
t, p = load("uk_treasury_today.txt", "GBP")
x = p["transactions"][0]
assert (x["trade_date"], x["shares"], x["price_avg"], x["price_high"], x["price_low"], x["price_unit"], x["currency"]) == ("2026-01-07", 49570, 6050.17, 6098, 6008, "GBp", "GBP"), x
assert abs(x["value"] - 49570 * 60.5017) < 0.01, x
assert p["doc_date"] == "2026-01-07" and p["date_basis"] == "purchase date", p["doc_date"]
assert p["programme"]["announced_date"] == "2025-09-26" and p["programme"]["shares_on_issue"] == 672215726, p["programme"]
assert p["programme"]["treatment"] == "Treasury" and p["programme"]["treatment_text"] == "will be held in treasury", p["programme"]
assert p["company"] == "Reckitt Benckiser Group plc" and p["ticker"] is None, p["company"]
assert [(c["kind"], c["shares"], c["as_of"]) for c in p["cancellations"]] == [("Held in treasury", 29873613, "2026-01-07")], p["cancellations"]
assert parsers.heading(t) == "Transaction in own shares" and not p["issues"]
d = parsers.parse("Example plc\nAnnual General Meeting on 8 May 2025.\nShare buyback programme\n12 June 2025\nThe board announces a share buyback.\n", "GBP")
assert d["doc_date"] == "2025-06-12", d["doc_date"]  # a meeting's date isn't the notice's date
d = parsers.parse("Example plc\n8 January 2026\nTransaction in own shares\nDate of purchase: 7 January 2026\nNumber of ordinary shares purchased: 100\nVolume weighted average price paid per share (pence): 50.00\n", "GBP")
assert d["doc_date"] == "2026-01-08" and "date_basis" not in d, d["doc_date"]  # a stated date stays

# The same notice with its RNS header: the header's date is the filing date, wherever the header sits
base = parsers.read_text(FX / "uk_treasury_today.txt").replace("\r\n", "\n")
assert "Transaction in own shares\n" in base
header = "RNS Number : 0588O\nReckitt Benckiser Group PLC\n08 January 2026\n"
on_top = header + "\n" + base
for full in (on_top, on_top.replace("\n", "\r\n"), "Printed 5 November 2026\n" + on_top, base.replace("Transaction in own shares\n", "Transaction in own shares\n\n" + header, 1)):
    p = parsers.parse(full, "GBP")
    assert p["doc_date"] == "2026-01-08" and "date_basis" not in p, (p["doc_date"], p.get("date_basis"))
    assert p["company"] == "Reckitt Benckiser Group PLC" and p["transactions"][0]["trade_date"] == "2026-01-07" and p["transactions"][0]["shares"] == 49570, p["company"]
    assert p["programme"]["announced_date"] == "2025-09-26" and p["cancellations"][0]["as_of"] == "2026-01-08", p["cancellations"]
    assert parsers.heading(full) == "Transaction in own shares", parsers.heading(full)

# A real RNS page from the company's system: each table cell's text sits in its own paragraph
t, p = load("uk_rns_cells.html", "GBP")
x = p["transactions"][0]
assert (x["trade_date"], x["shares"], x["price_avg"], x["price_high"], x["price_low"], x["price_unit"]) == ("2026-01-07", 49570, 6050.17, 6098, 6008, "GBp"), p["transactions"]
assert p["doc_date"] == "2026-01-08" and p["company"] == "Reckitt Benckiser Group PLC" and not p["issues"], (p["doc_date"], p["issues"])
assert p["programme"]["announced_date"] == "2025-09-26" and p["programme"]["treatment"] == "Treasury" and p["programme"]["shares_on_issue"] == 672215726, p["programme"]
assert re.search(r"Date of purchase:\s*\|\s*7 January 2026\s*\|", t), "a label and its value stay on one line"

# Prices written with their unit, and the phrases in data/keywords.csv
assert parsers.num("641.43p") == 641.43 and parsers.num("641.43 pence") == 641.43 and parsers.num("\u00a39.82") == 9.82 and parsers.num("3,162") == 3162
assert parsers.num("Aviva plc") is None and parsers.num("13:31") is None and parsers.num("") is None
assert parsers.compile_phrase("announced {...} on {DATE}").search("as announced on 05 March 2026").group(1) == "05 March 2026"
assert parsers.compile_phrase("announced {...} on {DATE}").search("buy-back announced by the Company on 28 October 2026").group(1) == "28 October 2026"

# Real Aviva page: prices with "p", a venue table, the broker, and "intends to cancel" beside "purchased for cancellation"
t, p = load("uk_rns_aviva.html", "GBP")
assert len(p["transactions"]) == 1, p["transactions"]
x = p["transactions"][0]
assert (x["trade_date"], x["shares"], x["price_avg"], x["price_high"], x["price_low"], x["price_unit"], x["venue"]) == ("2026-07-07", 100436, 678.0, 680.8, 674.2, "GBp", "London Stock Exchange (XLON)"), x
assert abs(x["value"] - 680956.08) < 0.01, x["value"]
assert (x["broker"], x["broker_role"]) == ("Citigroup Global Markets Limited", "Through"), (x.get("broker"), x.get("broker_role"))
assert p["programme"]["treatment"] == "Cancelled" and p["programme"]["announced_date"] == "2026-03-05" and p["doc_date"] == "2026-07-08", p["programme"]
assert p["programme"]["shares_on_issue"] == 3001450683 and not p["issues"], p["issues"]

# Real Macfarlane page: "announcement on", a list of individual trades, a broker "through", and phone numbers that aren't figures
t, p = load("uk_rns_macfarlane.html", "GBP")
assert len(p["transactions"]) == 1, p["transactions"]
x = p["transactions"][0]
assert (x["trade_date"], x["shares"], x["price_avg"], x["price_high"], x["price_low"], x["venue"]) == ("2026-05-22", 75000, 64.73, 64.73, 64.73, "XLON"), x
assert (x["broker"], x["broker_role"]) == ("Shore Capital Stockbrokers Limited", "Through"), x.get("broker")
assert p["programme"]["announced_date"] == "2025-05-15" and p["programme"]["treatment"] == "Cancelled" and p["programme"]["shares_on_issue"] == 156025491, p["programme"]
assert p["doc_date"] == "2026-05-26" and p["company"] == "Macfarlane Group PLC" and not p["issues"], p["issues"]

# Lloyds' wording, as supplied: a broker "from", and "intends to cancel" on its own
lloyds = ("RNS Number : 1234A\nLloyds Banking Group PLC\n03 February 2026\n\nTransaction in own shares\n"
          'Lloyds Banking Group plc (the "Company") announces today that it has purchased the following number of its ordinary shares, from Goldman Sachs International (the "Broker").\n'
          "Date of purchase: 02 February 2026\nNumber of ordinary shares purchased: 9,126,119\nVolume weighted average price paid per share (pence): 108.9401\n"
          "Highest price paid per share (pence): 110.00\nLowest price paid per share (pence): 107.65\n"
          "Such purchases form part of the Company's existing share buyback programme and were effected pursuant to the instructions issued to the Broker by the Company on 29 January 2026, as announced on 30 January 2026.\n"
          "The Company intends to cancel these shares.\n")
p = parsers.parse(lloyds, "GBP")
assert p["programme"]["treatment"] == "Cancelled" and p["programme"]["treatment_text"] == "intends to cancel", p["programme"]
assert p["broker"] == {"name": "Goldman Sachs International", "role": "From", "text": p["broker"]["text"]} and p["programme"]["announced_date"] == "2026-01-30", p.get("broker")
assert p["transactions"][0]["shares"] == 9126119 and p["transactions"][0]["broker"] == "Goldman Sachs International"
assert parsers.cancel_treatment("The shares will be held in treasury. Shares acquired will be cancelled.")[0] == "Conflict"

# Headings, and what is ignored
y = "Rule 3.19A.2\nAppendix 3Y\nChange of Director\u2019s Interest Notice\nName of entity ABC Ltd\nNature of change Example: on-market trade, participation in buy-back\n"
assert parsers.heading(y) == "Appendix 3Y - Change of Director\u2019s Interest Notice", parsers.heading(y)
assert not parsers.is_buyback_filing(y)
r = "Example Ltd\n1Q FY27 results update\nRevenue rose. The share buy-back continued during the quarter.\n"
assert parsers.heading(r) == "1Q FY27 results update" and not parsers.is_buyback_filing(r), parsers.heading(r)
assert not parsers.is_buyback_filing("Update", "1Q FY27 results update")
assert parsers.is_buyback_filing("Example Ltd\nFY26 results and share buy-back\nThe board announces a buy-back.\n")
assert parsers.is_buyback_filing("Appendix 3C - Notification of buy-back\n")
assert parsers.heading("Appendix 3C - Notification of buy-back\nAppendix 3C - Notification of buy-back 1 / 6\n") == "Appendix 3C - Notification of buy-back"
assert parsers.heading("Skip to main content\nSearch\nMeridian Completes FY24 LTI Buyback\n01 December 2023\n") == "Meridian Completes FY24 LTI Buyback"
assert parsers.heading("x", "Title from the list") == "Title from the list"
assert parsers.heading("Example plc\n2 January 2026\nChange of registered office address.\n") == "Change of registered office address.", "a date is not a heading"

t, p = load("rr_style.html", "GBP")
assert [x["trade_date"] for x in p["transactions"]] == ["2026-07-21", "2026-07-22"], p["transactions"]
x = p["transactions"][0]
assert x["shares"] == 846107 and x["price_avg"] == 1371.92 and x["price_high"] == 1385.2 and x["price_unit"] == "GBp", x
assert abs(x["value"] - 846107 * 13.7192) < 0.01 and x["currency"] == "GBP"
assert p["snapshots"][0]["cum_shares"] == 91942742 and abs(p["snapshots"][0]["cum_value"] - 91942742 * 12.5078) < 1, p["snapshots"]
assert p["programme"]["max_value"] == 2.3e9 and p["programme"]["announced_date"] == "2026-02-26", p["programme"]
assert p["programme"]["shares_on_issue"] == 8335893879, p["programme"]
ev = {(e["key"], e["field"]): e["text"] for e in parsers.evidence(t, p)}
assert ev[("tx|2026-07-21|", "shares")] == "846,107" and ev[("tx|2026-07-22|", "price_avg")] == "1,394.5700", ev

t, p = load("uk_labels.txt", "GBP")
x = p["transactions"][0]
assert (x["trade_date"], x["shares"], x["price_low"]) == ("2026-03-04", 120000, 2790), x
assert abs(x["value"] - 120000 * 28.0125) < 0.01

t, p = load("uk_venues.html", "GBP")
assert len(p["transactions"]) == 2 and {x["venue"] for x in p["transactions"]} == {"LSE", "CBOE"}, p["transactions"]
assert p["transactions"][0]["trade_date"] == "2026-05-05", p["transactions"]

t, p = load("nz_narrative.txt", "NZD")
x = p["snapshots"][0]
assert x["cum_shares"] == 500000 and x["avg"] == 5.6073 and x["currency"] == "NZD", x

# Weekly notice, allowed in the UK since February 2026: one row per date.
html = "<p>Tesco PLC</p><p>9 March 2026</p><p>Transaction in Own Shares</p><table><tr><th>Date of purchase</th><th>Number of shares purchased</th><th>Highest price (pence)</th><th>Lowest price (pence)</th><th>Volume weighted average price (pence)</th></tr><tr><td>2 March 2026</td><td>1,000</td><td>410.5</td><td>400.5</td><td>405.5</td></tr><tr><td>3 March 2026</td><td>2,000</td><td>411.0</td><td>401.0</td><td>406.0</td></tr></table>"
h = parsers._Html(); h.feed(html); p = parsers.parse("".join(h.out), "GBP")
assert [(x["trade_date"], x["shares"]) for x in p["transactions"]] == [("2026-03-02", 1000), ("2026-03-03", 2000)], p["transactions"]
assert abs(p["transactions"][1]["value"] - 2000 * 4.06) < 0.001

# No stated unit: no value is guessed.
p = parsers.parse("Example plc\n5 March 2026\nTransaction in Own Shares\nDate of purchase: 4 March 2026\nNumber of ordinary shares purchased: 100\nVolume weighted average price: 50.5\n", "GBP")
assert p["transactions"][0]["value"] is None and any(k == "NO_PRICE_UNIT" for k, _ in p["issues"]), p
# Share counts are never read as programme money.
assert parsers.max_value_in("a total of $369,260,287.44 shares", "AUD") == (None, None)
assert parsers.max_value_in("up to A$750 million (a total of $369,260,287.44", "AUD") == (750e6, "AUD")
assert parsers.max_value_in("buy back up to USD$750 million of its shares", "AUD") == (750e6, "USD")  # seen in a real CSL notice
assert parsers.max_value_in("up to AUD$1.15 billion", "AUD") == (1.15e9, "AUD")
c = [{"ticker": "BP", "company": "BP"}, {"ticker": "SSE", "company": "SSE plc"}]
assert parsers.match_company("x.txt", "BP p.l.c. notice", c) == "BP" and parsers.match_company("SSE_1.txt", "", c) == "SSE"
# Real Meridian wording, behind a long site menu: a completion is a final total, and a cap is not shares on issue.
menu = "Help For home For business " * 200
p = parsers.parse(menu + """Meridian Completes FY26 Equity Plans Buyback
11 December 2025
Meridian Energy Limited (Meridian) announced on 1 December 2025 that it would undertake an on-market share buyback in connection with FY26 equity plans.
Meridian has now completed that share buyback. Meridian acquired 500,000 ordinary shares on the NZX Main Board at an average price of NZ$5.6073 per share.""", "NZD")
assert p["doc_type"] == "transaction" and p["transactions"] == [] and not p["issues"], p
assert p["doc_date"] == "2025-12-11" and p["programme"]["announced_date"] == "2025-12-01" and p["programme"]["status"] == "COMPLETED", p
s = p["snapshots"][0]
assert s["cum_shares"] == 500000 and abs(s["cum_value"] - 2803650) < 0.01 and s["currency"] == "NZD", s
p = parsers.parse(menu + """Share Buyback in connection with the FY25 LTI Plan
25 October 2024
Meridian Energy Limited announces that it will begin an on-market share buyback to purchase a maximum of 1,000,000 ordinary shares (Buyback). The Buyback may occur from 1 November 2024 until 29 November 2024.""", "NZD")
g = p["programme"]
assert p["doc_type"] == "programme" and not p["issues"] and g["max_shares"] == 1000000 and g.get("shares_on_issue") is None, p
assert (g["announced_date"], g["start_date"], g["end_date"]) == ("2024-10-25", "2024-11-01", "2024-11-29"), g

# NZX capital change notice, with real Oceania Healthcare wording. The same form for a share issue must not count as a buyback.
cc = """Capital Change Notice
Notice of repurchase of ordinary shares by Oceania Healthcare Limited
This notice relates to a limited on-market share buyback programme originally announced on 31 July 2026.
Name of issuer Oceania Healthcare Limited
NZX ticker code OCA
Currency NZD
Number acquired 120,740 ordinary shares
Issue/acquisition/redemption price per security $0.7925 (average)
0.0166687%
issue/acquisition/redemption.
724,231,030 ordinary shares
Nil held as Treasury Stock
Date of issue/acquisition/redemption 5 August 2026
Date of release through MAP 6 August 2026
"""
p = parsers.parse(cc, "NZD")
x = p["transactions"][0]
assert p["form"] == "capital_change" and p["ticker"] == "OCA" and not p["issues"], p
assert (x["trade_date"], x["shares"], x["price_avg"], x["currency"]) == ("2026-08-05", 120740, 0.7925, "NZD"), x
assert abs(x["value"] - 95686.45) < 0.001 and p["doc_date"] == "2026-08-06" and p["programme"]["announced_date"] == "2026-07-31"
assert p["programme"]["shares_on_issue"] == 724231030, p["programme"]
assert parsers.parse("Capital Change Notice\nNumber issued 5,000 share rights\nName of issuer Example\n6 August 2026\n", "NZD")["form"] != "capital_change"

# Real Oceania announcement wording: a cap in words, a start date, and an end date tied to the announcement.
text = """31 July 2026
Limited share buyback in connection with Oceania employee equity vesting
Oceania Healthcare Limited has approved a limited on-market share buyback programme of up to 3.5 million shares in the
next twelve months (Buyback).
- shares will be bought back on or from 5 August 2026 and may occur from time to
time up until the 12-month anniversary of the date of this announcement.
"""
p = parsers.parse(text, "NZD")
g = p["programme"]
assert p["doc_type"] == "programme" and not p["issues"] and g["max_shares"] == 3500000, p
assert (g["announced_date"], g["start_date"], g["end_date"]) == ("2026-07-31", "2026-08-05", "2027-07-31"), g
assert any(e["field"] == "max_shares" and e["text"] == "up to 3.5 million shares" for e in parsers.evidence(text, p))

# Real HSBC layout: a section per venue, each in its own currency, and a running total in US$ millions.
text = """HSBC HOLDINGS PLC
Transaction in own shares
HSBC Holdings plc announces that it has purchased for cancellation the following number of its ordinary shares of US$ 0.50
as part of its buy-back announced on 5 August 2026.

Date of announcement: 23 September 2026

UK Venues
Date of purchase: 23 September 2026
Number of ordinary shares of US$0.50 each purchased: 3,350,605
Highest price paid per share: \u00a315.2720
Lowest price paid per share: \u00a315.1140
Volume weighted average price paid per share: \u00a315.1877

Hong Kong Stock Exchange
Date of purchase: 23 September 2026
Number of ordinary shares of US$0.50 each purchased: 525,600
Highest price paid per share: HK$159.5000
Lowest price paid per share: HK$157.8000
Volume weighted average price paid per share: HK$158.4112

Additional information
Shares repurchased and approximate total consideration
(in US$m) since the commencement of the buy-back
announced on 5 August 2026:
46,023,902
US$945.0
Company's issued ordinary share capital and total voting
rights* 17,141,942,291
"""
p = parsers.parse(text, "GBP")
uk, hk = p["transactions"]
assert p["doc_date"] == "2026-09-23" and p["programme"]["announced_date"] == "2026-08-05" and p["programme"]["shares_on_issue"] == 17141942291, p
assert (uk["venue"], uk["shares"], uk["price_avg"], uk["price_unit"], uk["currency"]) == ("UK Venues", 3350605, 15.1877, "GBP", "GBP"), uk
assert abs(uk["value"] - 3350605 * 15.1877) < 0.01, uk
assert (hk["venue"], hk["shares"], hk["price_high"], hk["currency"]) == ("Hong Kong Stock Exchange", 525600, 159.5, "HKD"), hk
s = p["snapshots"][0]
assert (s["as_of"], s["cum_shares"], s["cum_value"], s["currency"]) == ("2026-09-23", 46023902, 945e6, "USD"), s
assert not p["issues"], p["issues"]
assert {e["text"] for e in parsers.evidence(text, p) if e["key"] == "snap|2026-09-23"} == {"46,023,902", "US$945.0"}

# Real HSBC programme announcement: boilerplate must not become a programme size or a purchase.
text = """28 October 2026
HSBC HOLDINGS PLC SHARE BUY-BACK
HSBC Holdings plc announces that, as outlined in its announcement on 27 October 2026, it will commence a share buy-back for
up to a maximum consideration of US$ 1,000,000,000 (one billion United States dollars) (the Buy-back).
during the period running from 29 October 2026 and ending no later than 19 February 2027.
The maximum number of Ordinary Shares that may be repurchased under the Buy -back is
1,669,697,533, being the number of Ordinary Shares able to be repurchased under the 2026 Authority
as reduced by the number of Shares repurchased by HSBC since the 2026 Authority was granted.
HSBC Holdings plc is headquartered in London. With assets of US$3,445bn at 30 September 2026, HSBC is one of the largest.
"""
p = parsers.parse(text, "GBP")
g = p["programme"]
assert p["doc_type"] == "programme" and p["transactions"] == [] and not p["issues"], p
assert (g["max_value"], g["max_currency"], g["max_shares"], g["start_date"], g["end_date"]) == (1e9, "USD", 1669697533, "2026-10-29", "2027-02-19"), g
assert parsers.max_value_in("With assets of US$3,445bn at 30 September 2026", "GBP") == (None, None)
assert parsers.max_value_in("the \u00a32.3 billion buyback programme announced", "GBP") == (2.3e9, "GBP")
p = parsers.parse("Example plc\n5 March 2026\nThe buy-back has concluded.\n", "GBP")
assert p["programme"].get("status") == "COMPLETED"

# Real HSBC closing notice: one venue section still gets its venue, and programme totals are read per venue.
text = """HSBC HOLDINGS PLC
Transaction in own shares and conclusion of buy-back
as part of its buy-back announced on 5 August 2026.
Date of announcement: 28 September 2026
Hong Kong Stock Exchange
Date of purchase: 28 September 2026
Number of ordinary shares of US$0.50 each purchased: 911,200
Highest price paid per share: HK$160.7000
Lowest price paid per share: HK$158.0000
Volume weighted average price paid per share: HK$159.5951
The Company announces that, following the purchase of these shares, the buy -back has concluded.
Since the commencement of the buy-back, the Company has repurchased for cancellation 31,735,502
ordinary shares on the UK Venues at a volume weighted average price of \u00a315.1909 per ordinary share,
and 16,921,600 ordinary shares on the Hong Kong Stock Exchange at a volume weighted average
price of HK$161.2887 per ordinary share, for a total consideration of approximately US$1bn.
"""
p = parsers.parse(text, "GBP")
assert p["transactions"][0]["venue"] == "Hong Kong Stock Exchange", p["transactions"]
v = {x["venue"]: x for x in p["venue_totals"]}
assert v["UK Venues"]["shares"] == 31735502 and v["UK Venues"]["price_avg"] == 15.1909 and v["UK Venues"]["currency"] == "GBP", v
assert v["Hong Kong Stock Exchange"]["shares"] == 16921600 and v["Hong Kong Stock Exchange"]["price_unit"] == "HKD", v
assert abs(v["UK Venues"]["value"] - 31735502 * 15.1909) < 0.01
# A section's heading must look like a venue, or it stays blank.
p = parsers.parse("Example plc\nDate of announcement: 5 March 2026\nTransaction in Own Shares\nDate of purchase: 4 March 2026\nNumber of shares purchased: 100\nVolume weighted average price: 50.5 pence\n", "GBP")
assert p["transactions"][0]["venue"] == "", p["transactions"]

# Cancellation, in real wording from the saved notices.
assert parsers.cancel_treatment("The acquired shares will not be cancelled and will be held by Meridian as treasury stock as permitted")[0] == "Treasury"
assert parsers.cancel_treatment("Shares bought back will be cancelled on acquisition.") == ("Cancelled", "will be cancelled on acquisition")
assert parsers.cancel_treatment("announces that it has purchased for cancellation the following number")[0] == "Cancelled"
form = "the total number of Financial Products of the Class held as Treasury Stock after the issue. 724,231,030 ordinary shares Nil held as Treasury Stock Shares acquired will be cancelled."
assert parsers.cancel_treatment(form)[0] == "Cancelled", parsers.cancel_treatment(form)
assert parsers.cancel_treatment("Meridian has now completed that share buyback.") is None
assert parsers.cancel_treatment("of which $300 million has been purchased and cancelled as at 31 December 2025")[0] == "Cancelled"  # real CBA wording
# The real Oceania form: its question about treasury stock is not an answer.
form = "Nil held as Treasury Stock In the case of an acquisition of shares, whether those shares are to be held as treasury stock Shares acquired will be cancelled."
assert parsers.cancel_treatment(form) == ("Cancelled", "will be cancelled"), parsers.cancel_treatment(form)
assert parsers.cancel_treatment("the shares are being held as treasury stock")[0] == "Treasury"
assert parsers.cancel_treatment("Acquired shares will be held as treasury stock.")[0] == "Treasury"
text = """HSBC HOLDINGS PLC
Transaction in own shares
announces that it has purchased for cancellation the following number of its ordinary shares as part of its buy-back announced on 5 August 2026.
Date of announcement: 04 September 2026
UK Venues
Date of purchase: 04 September 2026
Number of ordinary shares of US$0.50 each purchased: 10,000
Volume weighted average price paid per share: \u00a315.7087
Hong Kong Stock Exchange
Date of purchase: 04 September 2026
Number of ordinary shares of US$0.50 each purchased: 409,200
Volume weighted average price paid per share: HK$166.7935
Shares cancelled which were awaiting cancellation having
been previously repurchased on the Hong Kong Stock
Exchange:
5,991,600
Company's issued ordinary share capital and total voting
rights* 17,160,000,000
*following the cancellation of the shares referred to above (i) which were awaiting cancellation having been repurchased previously on the Hong Kong Stock Exchange (ii) which were repurchased today on the UK Venues.
Cancellation of the shares repurchased today on the Hong Kong Stock Exchange takes longer than those repurchased on the UK Venues.
"""
p = parsers.parse(text, "GBP")
got = {(c["venue"], c["kind"], c["shares"]) for c in p["cancellations"]}
assert got == {("Hong Kong Stock Exchange", "Cancelled", 5991600), ("UK Venues", "Cancelled", 10000), ("Hong Kong Stock Exchange", "Awaiting cancellation", 409200)}, got
assert p["programme"]["treatment"] == "Cancelled"

# Each value records where it came from.
assert parsers.parse(text, "GBP")["cancellations"][0]["basis"] == "Reported count"
assert all(c["basis"] == "From notice wording" for c in parsers.parse(text, "GBP")["cancellations"][1:])
from sbb import queries
ex = [("Reported", "a"), ("Reported", "b")]
assert queries._combine(ex)[0] == "Calculated" and queries._combine(ex[:1]) == ("Reported", "a")

# Terms: the newest notice wins, whatever order files arrive in.
from sbb import db, ingest
con = db.connect(":memory:")
prog = lambda v, cur: {"announced_date": "2025-08-20", "max_value": v, "max_currency": cur}
new, old = {"programme": prog(750e6, "USD"), "transactions": [], "snapshots": [], "doc_date": "2026-02-16"}, {"programme": prog(750e6, "AUD"), "transactions": [], "snapshots": [], "doc_date": "2025-12-18"}
ingest.store(con, 2, "AU", "CSL", new)
ingest.store(con, 1, "AU", "CSL", old)
assert con.execute("select max_currency from programmes").fetchone()[0] == "USD"

# Real Frontier page: a venue table with its own Total row, "place ... into Treasury", a broker "through ... as part",
# a running total of shares with no amount, and shares in issue beside the treasury and voting rights figures
t, p = load("uk_rns_frontier.html", "GBP")
assert not p["issues"], p["issues"]
x, = p["transactions"]
assert (x["trade_date"], x["shares"], x["price_avg"], x["price_unit"], x["venue"], x["value"]) == ("2026-04-20", 50208, 400, "GBp", "London Stock Exchange (AIMX)", 200832), x
assert (x["broker"], x["broker_role"]) == ("Peel Hunt LLP", "Through"), x
assert p["programme"]["treatment"] == "Treasury" and p["programme"]["shares_on_issue"] == 39478535 and p["programme"]["announced_date"] == "2026-02-26", p["programme"]
assert [(s["cum_shares"], s["cum_value"], s["origin"]) for s in p["snapshots"]] == [(1000920, None, "reported")], p["snapshots"]
assert [(c["kind"], c["shares"]) for c in p["cancellations"]] == [("Held in treasury", 3519447)], p["cancellations"]

# Start and end dates from the programme_runs phrases in data/keywords.csv
runs = lambda s: {k: v for k, v in parsers.parse("Example plc\n2 March 2026\nShare buyback programme\nThe Company announces a buyback of up to £50 million. " + s, "GBP")["programme"].items() if k in ("start_date", "end_date", "end_note")}
assert runs("It will run from 2 March 2026 until 28 February 2027.") == {"start_date": "2026-03-02", "end_date": "2027-02-28"}
assert runs("commencing from 2 March 2026 and ending no later than 31 December 2026") == {"start_date": "2026-03-02", "end_date": "2026-12-31"}
assert runs("The programme will commence on 3 March 2026 and will end no later than 30 September 2026.") == {"start_date": "2026-03-03", "end_date": "2026-09-30"}
assert runs("It may start on or from 4 March 2026.") == {"start_date": "2026-03-04"}
assert runs("It will run up until the 12-month anniversary of the date of this announcement.")["end_date"] == "2027-03-02"
assert runs("No dates are given.") == {}
# The ASX form headed only "Notification of buy-back" (CBA, 28 June 2023): a final update to the programme notified on 9 Feb 2022, not a new programme
cba = parsers.parse((FX / "au_notification_cba_final.txt").read_text(encoding="utf-8"), "AUD", "AU", "DMY")
assert (cba["form"], cba["doc_type"], cba["ticker"], cba["doc_date"], cba["reason"]) == ("appendix_3c", "final", "CBA", "2023-06-28", "Final buy-back notification"), cba
assert (cba["programme"]["announced_date"], cba["programme"]["status"], cba["programme"]["max_value"], cba["programme"]["shares_on_issue"]) == ("2022-02-09", "COMPLETED", 3e9, 1688414169), cba["programme"]
assert cba["transactions"] == [] and [(s["as_of"], s["cum_shares"], s["cum_value"], s["currency"]) for s in cba["snapshots"]] == [("2023-06-28", 30222281, 2999999977.85, "AUD")], cba["snapshots"]
assert cba["broker"]["name"].startswith("Barrenjoey Markets Pty Limited") and cba["issues"] == [], (cba["broker"], cba["issues"])
# A notice that raises an existing programme's size (Aristocrat, 15 May 2023) is an update to that programme, with the new total, not a new programme of the increase
inc_text = (FX / "au_size_increase_aristocrat.txt").read_text(encoding="utf-8")
inc = parsers.parse(inc_text, "AUD", "AU", "DMY")
assert (inc["form"], inc["doc_type"], inc["doc_date"], inc["reason"], inc["issues"]) == ("notice", "update", "2023-05-15", "Programme size increased", []), inc
assert (inc["programme"]["announced_date"], inc["programme"]["max_value"], inc["programme"]["max_currency"], inc["programme"]["end_date"]) == ("", 1.5e9, "AUD", "2024-05-31") and "announced_assumed" not in inc["programme"], inc["programme"]
assert inc["programme"]["size_note"] == "Size raised to AUD 1,500,000,000 on 2023-05-15, an increase of AUD 500,000,000"
where = {e["field"]: (e["page"], e["text"]) for e in parsers.evidence(inc_text, inc)}
assert where["max_value"] == (4, "$1.5 billion") and where["end_date"] == (4, "31 May 2024"), where  # not the "$1.5 billion" on page 1, which values the acquisition
only = parsers.parse("Example Limited\n3 March 2026\nExample today announces an increase to its existing on-market share buy-back programme by up to a further $200 million.", "AUD", "AU", "DMY")
assert only["doc_type"] == "update" and only["programme"].get("max_value") is None and [k for k, _ in only["issues"]] == ["SIZE_INCREASE"] and "by AUD 200,000,000" in only["issues"][0][1], only  # no new total stated: nothing is added up
new = parsers.parse("Example Limited\n3 March 2026\nExample today announces an on-market share buy-back of up to $200 million.", "AUD", "AU", "DMY")
assert new["doc_type"] == "programme" and new["programme"]["max_value"] == 2e8 and new["programme"]["announced_date"] == "2026-03-03", new  # an ordinary announcement is unchanged
# A UK programme announcement (Aviva, 5 March 2026): the end date from "to be completed by", the broker from "agreement with",
# and the shareholders' general authority (267 million Shares) is not the programme's size
av = parsers.parse((FX / "uk_programme_aviva.txt").read_text(encoding="utf-8"), "GBP", "UK", "DMY")
assert (av["form"], av["doc_type"], av["doc_date"], av["issues"]) == ("notice", "programme", "2026-03-05", []), av
ap = av["programme"]
assert (ap["announced_date"], ap["start_date"], ap["end_date"], ap["max_value"], ap["max_currency"], ap.get("max_shares"), ap["treatment"]) == ("2026-03-05", "2026-03-06", "2026-08-06", 3.5e8, "GBP", None, "Cancelled"), ap
assert av["broker"]["name"] == "Citigroup Global Markets Limited" and ap["broker"] == "Citigroup Global Markets Limited", av["broker"]
own = parsers.parse("Example plc\n3 March 2026\nExample plc announces a share buyback programme to repurchase up to 10 million ordinary shares, under the authority granted by shareholders.", "GBP", "UK", "DMY")
assert own["programme"]["max_shares"] == 1e7, own["programme"]  # the programme's own limit is still read
print("fixtures OK")

if len(sys.argv) > 1:
    for f in sorted(Path(sys.argv[1]).glob("*.pdf")):
        text = parsers.read_text(f)
        p = parsers.parse(text, "AUD")
        print(f"\n{f.name}: {p['form']} {p['doc_type']} {p['ticker']} {p['doc_date']}\n  prog={p['programme']}\n  tx={p['transactions']}\n  snap={p['snapshots']}\n  issues={p['issues']}")
        for e in parsers.evidence(text, p):
            print(f"    p{e['page']} {e['key']} {e['field']}: {e['text']!r}")
