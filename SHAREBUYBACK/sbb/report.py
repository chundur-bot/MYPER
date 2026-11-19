"""Excel workbook for the selected country and period. Saved under reports/ for private use."""
import re
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import db, queries as q

REPORTS = db.ROOT / "reports"
HEAD = PatternFill("solid", fgColor="1F3A5F")


def _date_cell(v):
    """A YYYY-MM-DD text becomes a real Excel date shown as MM/DD/YYYY; anything else is left as it is."""
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?", v):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return v
    return v


def _sheet(wb, title, cols, rows):
    ws = wb.create_sheet(title)
    ws.append([c[1] for c in cols])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append([_date_cell(r.get(c[0])) for c in cols])
        for cell in ws[ws.max_row]:
            if isinstance(cell.value, datetime):
                cell.number_format = "mm/dd/yyyy hh:mm" if (cell.value.hour or cell.value.minute) else "mm/dd/yyyy"
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = c[2] if len(c) > 2 else 16
        if len(c) > 3:
            for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                row[0].number_format = c[3]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def write(con, country, start, end):
    REPORTS.mkdir(exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "About"
    s = q.summary(con, country, start, end)
    everything = start == q.ALL_FROM and end == q.ALL_TO
    ws.append(["Share buybacks", f"{country}, all programmes" if everything else f"{country}, {start} to {end}"])
    ws.append(["Generated", db.now()])
    ws.append(["Basis", "Only saved notices are counted. Each amount is marked Reported (a notice states it), Calculated (worked out from notices), Entered by hand (typed from the source named) or Updated Manually (a figure read from a notice and changed by you, with the source and reason; see the sheet Entered by hand). Currencies are not added together. Sectors come from Wikipedia lists. For private use."])
    ws.append([])
    ws.append(["Market", "Exchange", "Currency", "Amounts as reported", "Shares", "Companies buying", "Companies studied", "Partial coverage", "Notices saved"])
    for cell in ws[5]:
        cell.font = Font(bold=True)
    for m in s["markets"]:
        ws.append([m["name"], m["exchange"], m["currency"], q.amounts_text(m["amounts"]), m["shares"], m["active_companies"], m["members"], m["partial"], m["documents"]])
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 16
    money, whole, pct = "#,##0.00", "#,##0", "0.0"
    _sheet(wb, "Companies", [("country", "Market", 8), ("ticker", "Ticker", 9), ("company", "Company", 34), ("sector", "Sector", 30), ("state", "State", 20), ("amounts_text", "Bought back", 28), ("amount_basis", "Basis", 11), ("amount_working", "Working", 60), ("shares", "Shares", 16, whole),
                               ("max_value", "Announced size", 18, money), ("max_currency", "Size currency", 9), ("used_pct", "Used %", 9, pct), ("documents", "Notices", 8), ("last_notice", "Latest notice", 12), ("note", "Note", 70)], q.companies(con, country, start, end))
    _sheet(wb, "Programmes", [("country", "Market", 8), ("ticker", "Ticker", 9), ("company", "Company", 34), ("announced_date", "Announced", 12), ("buyback_type", "Type", 20), ("start_date", "Start", 12), ("end_date", "End", 12), ("max_value", "Announced size", 18, money), ("max_currency", "Currency", 9), ("max_shares", "Max shares", 16, whole),
                                ("max_pct", "Max % of shares", 10, "0.00##"), ("intended_shares", "Intended shares (approximate, not a limit)", 16, whole), ("hand_text", "Entered by hand", 50),
                                ("amounts_text", "Bought in period", 28), ("amount_basis", "Basis", 11), ("amount_working", "Working", 60), ("shares", "Shares in period", 16, whole), ("programme_spent", "Spent since start", 18, money), ("programme_spent_currency", "Spent currency", 9), ("used_pct", "Used %", 9, pct), ("treatment", "Treatment", 12), ("method", "Figures from", 16), ("cancelled_shares", "Shares cancelled (Calculated)", 16, whole), ("cancelled_working", "Shares cancelled: working", 40), ("avg_price", "Average price paid (Calculated)", 14), ("avg_currency", "Average price currency", 9), ("avg_working", "Average price: working", 40), ("status", "Status", 12), ("complete", "Period fully covered", 10), ("source_url", "Link to latest filing", 60), ("note", "Note", 70)], q.programme_rows(con, country, start, end))
    _sheet(wb, "Purchases", [("country", "Market", 8), ("ticker", "Ticker", 9), ("company", "Company", 34), ("trade_date", "Date", 12), ("venue", "Venue", 12), ("shares", "Shares", 16, whole), ("price_avg", "Average price", 14, "#,##0.0000"), ("price_high", "High", 14, "#,##0.0000"), ("price_low", "Low", 14, "#,##0.0000"), ("price_unit", "Price unit", 9), ("value", "Value", 18, money), ("currency", "Currency", 9), ("value_basis", "Value basis", 11), ("updated_text", "Updated Manually", 50), ("doc_id", "Notice id", 9)], [{**r, "value_basis": "Reported" if r["value_origin"] == "reported" else "Entered by hand" if r["value_origin"] == "hand" else "Updated Manually" if r["value_origin"] == "updated" else "Calculated",
       "updated_text": "; ".join(f"{k}: {v}" for k, v in (r.get("updated") or {}).items() if k != "derived")} for r in q.transactions(con, country, start, end)])
    _sheet(wb, "Daily activity", [("country", "Market", 8), ("ticker", "Ticker", 9), ("company", "Company", 34), ("trade_date", "Purchase date", 12), ("filing_date", "Filing date", 12), ("venue_label", "Venue", 26), ("shares", "Shares", 16, whole), ("price_high", "High", 14, "#,##0.0000"), ("price_low", "Low", 14, "#,##0.0000"), ("price_avg", "Average", 14, "#,##0.0000"), ("avg_basis", "Average basis", 11), ("price_unit", "Price unit", 9), ("value", "Amount paid", 18, money), ("currency", "Currency", 9), ("value_basis", "Amount basis", 11), ("cum_shares", "Total shares so far", 16, whole), ("cum_value", "Total paid so far", 18, money), ("cum_currency", "Total currency", 9), ("cum_basis", "Total basis", 11), ("source_url", "Link", 60)], q.daily_rows(con, None, country, start, end))
    _sheet(wb, "By venue", [("country", "Market", 8), ("ticker", "Ticker", 9), ("company", "Company", 34), ("announced_date", "Programme announced", 12), ("venue", "Venue", 28), ("shares", "Shares", 16, whole), ("share_pct", "Share of programme %", 10, pct), ("price_avg", "Average price", 14, "#,##0.0000"), ("price_unit", "Price unit", 9), ("value", "Value", 18, money), ("currency", "Currency", 9), ("value_basis", "Value basis", 11), ("value_working", "Working", 44), ("basis", "Split from", 28), ("days", "Saved days", 8), ("doc_id", "Notice id", 9)], q.venues(con, country, start, end))
    cancel = q.cancellations(con, country, start, end)
    _sheet(wb, "Cancellations", [("country", "Market", 8), ("ticker", "Ticker", 9), ("company", "Company", 34), ("announced_date", "Programme announced", 12), ("treatment", "Treatment", 12), ("treatment_text", "Words in the notice", 44), ("shares", "Bought in period", 16, whole), ("cancelled_reported", "Cancelled, reported count", 16, whole), ("cancelled_wording", "Cancelled per notice wording", 16, whole), ("awaiting_wording", "Awaiting per notice wording", 16, whole), ("latest_count", "Latest shares on issue", 18, whole), ("latest_count_date", "As of", 12)], cancel["programmes"])
    _sheet(wb, "Cancellation notices", [("as_of", "Notice date", 12), ("country", "Market", 8), ("ticker", "Ticker", 9), ("venue", "Venue", 28), ("kind", "Kind", 22), ("shares", "Shares", 16, whole), ("basis", "Basis", 20), ("note", "Detail", 40), ("doc_id", "Notice id", 9)], cancel["events"])
    _sheet(wb, "Shares on issue", [("country", "Market", 8), ("ticker", "Ticker", 9), ("as_of", "Notice date", 12), ("shares", "Shares on issue", 20, whole), ("doc_id", "Notice id", 9)], cancel["counts"])
    _sheet(wb, "Cessations", [("ceased_on", "Ceased on", 12), ("country", "Market", 8), ("ticker", "Ticker", 9), ("company", "Company", 34), ("security", "Security", 28), ("shares", "Number ceased", 16, whole), ("reason", "Reason", 50), ("kind", "Kind", 10), ("consideration", "Consideration", 18, money), ("currency", "Currency", 9), ("programme_label", "Programme announced", 18), ("issued_after", "On issue after", 18, whole), ("other_info", "Other information", 50), ("filing_date", "Filing date", 12), ("source_url", "Link", 60)], q.cessations(con, country, start, end)["rows"])
    _sheet(wb, "Notices", [("doc_id", "Notice id", 9), ("country", "Market", 8), ("ticker", "Ticker", 9), ("doc_date", "Date", 12), ("heading", "Heading", 50), ("reason", "Reason for update", 30), ("appendix", "Appendix", 20), ("filing_type", "Type", 28), ("status", "Status", 14), ("file_name", "File", 50), ("message", "Result", 40), ("source_url", "Link", 60)], q.documents(con, country))
    _sheet(wb, "Issues (3G)", [("country", "Market", 8), ("ticker", "Ticker", 9), ("company", "Company", 30), ("issued_on", "Issued on", 12), ("security_code", "Code", 9), ("security", "Security", 26),
                                ("shares", "Number", 14, whole), ("from_security", "From (converted)", 26), ("provided_by", "Provided by", 28), ("other_info", "What the company says", 60), ("filing_date", "Notice date", 12), ("doc_id", "Notice id", 9)],
           q.issues(con, country, start, end)["rows"])
    from . import hand
    _sheet(wb, "Entered by hand", [("entry_id", "Entry", 8), ("country", "Market", 8), ("ticker", "Ticker", 9), ("kind_label", "Kind", 22), ("date", "Date", 12), ("what", "What", 70), ("source", "Source", 50), ("note", "Note", 40), ("updated_at", "Last changed", 18)],
           hand.listing(con, country)["entries"])
    qual = q.quality(con, country, start, end)
    _sheet(wb, "Checks", [("severity", "Level", 8), ("country", "Market", 8), ("ticker", "Ticker", 9), ("check", "Check", 24), ("detail", "Detail", 90)], qual["checks"])
    path = REPORTS / (f"buybacks_{country}_all_programmes.xlsx" if everything else f"buybacks_{country}_{start}_to_{end}.xlsx")
    wb.save(path)
    return path
