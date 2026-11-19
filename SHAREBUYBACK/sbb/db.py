"""One SQLite file (buyback.db) holds everything. Tables are created when missing."""
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

VERSION = "2026-11-20 v28 1"  # shown on Add data, so it's clear which copy is running
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "buyback.db"

SCHEMA = """
create table if not exists companies (
  country text not null, ticker text not null, company text, sector text, index_name text, as_of text, source text,
  in_index integer not null default 1, primary key (country, ticker));
create table if not exists documents (
  doc_id integer primary key, sha256 text unique, country text not null, file_name text, rel_path text, ticker text, company_raw text,
  doc_type text, doc_date text, status text, message text, imported_at text);
create table if not exists programmes (
  prog_id integer primary key, country text not null, ticker text not null, announced_date text not null default '', buyback_type text,
  start_date text, end_date text, max_shares real, max_value real, max_currency text, shares_on_issue real, status text default 'ACTIVE',
  source_doc integer, terms_date text, treatment text, treatment_text text, treatment_doc integer, unique (country, ticker, announced_date));
create table if not exists transactions (
  tx_id integer primary key, prog_id integer not null, country text not null, ticker text not null, trade_date text not null, venue text not null default '',
  shares real, value real, currency text, price_avg real, price_high real, price_low real, price_unit text, doc_id integer,
  unique (prog_id, trade_date, venue, price_unit));
create table if not exists snapshots (
  snap_id integer primary key, prog_id integer not null, as_of text not null, cum_shares real, cum_value real, currency text, doc_id integer,
  unique (prog_id, as_of));
create table if not exists venue_totals (
  prog_id integer not null, venue text not null, as_of text not null, shares real, price_avg real, price_unit text, value real, currency text, doc_id integer,
  primary key (prog_id, venue, as_of));
create table if not exists cancellations (
  doc_id integer not null, prog_id integer not null, country text, ticker text, as_of text, venue text not null default '', shares real, kind text not null, note text,
  primary key (doc_id, venue, kind, note));
create table if not exists share_counts (
  country text not null, ticker text not null, as_of text not null, shares real, doc_id integer, primary key (country, ticker, as_of));
create table if not exists cessations (
  doc_id integer not null, n integer not null, country text, ticker text, security_code text, security text, quoted text, shares real, reason text, is_buyback integer,
  ceased_on text, consideration real, currency text, other_info text, issued_after real, prog_id integer, primary key (doc_id, n));
create table if not exists issues (
  doc_id integer not null, n integer not null, country text, ticker text, security_code text, security text, shares real, issued_on text, from_security text,
  provided_by text, other_info text, primary key (doc_id, n));
create table if not exists skipped_links (
  link text primary key, reason text, skipped_at text);
create table if not exists review (
  review_id integer primary key, doc_id integer, country text, ticker text, kind text, detail text, status text default 'OPEN', created_at text);
create table if not exists prices (
  country text not null, ticker text not null, date text not null, close real, primary key (country, ticker, date));
create table if not exists doc_pages (
  doc_id integer not null, page integer not null, text text, primary key (doc_id, page));
create table if not exists evidence (
  ev_id integer primary key, doc_id integer not null, key text not null, field text not null, page integer, text text, context text);
create table if not exists announcement_list (
  country text not null, company text, date text, title text, url text, source_file text, unique (country, company, date, title));
create table if not exists runs (
  run_id integer primary key, started_at text, seen integer, imported integer, review integer, failed integer, note text);
create table if not exists app_state (
  key text primary key, value text);
create table if not exists hand_entries (
  entry_id integer primary key, kind text not null, country text not null, ticker text not null, fields text not null, source text not null, note text,
  status text not null default 'ACTIVE', doc_id integer, created_at text, updated_at text, deleted_at text, delete_reason text);
create table if not exists hand_log (
  log_id integer primary key, entry_id integer not null, action text not null, at text not null, old_fields text, new_fields text, reason text);
create index if not exists ix_tx on transactions(country, trade_date);
create index if not exists ix_snap on snapshots(prog_id, as_of);
create index if not exists ix_ev on evidence(doc_id, key);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path=None):
    con = sqlite3.connect(path or DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    additions = {"programmes": {"broker": "text", "terms_date": "text", "treatment": "text", "treatment_text": "text", "treatment_doc": "integer", "end_note": "text", "size_note": "text", "max_pct": "real", "intended_shares": "real", "terms_doc": "integer", "status_doc": "integer"},  # databases made before these columns existed
                 "skipped_links": {"ticker": "text", "country": "text", "heading": "text"}, "documents": {"source_url": "text", "parsed_json": "text", "heading": "text", "reason": "text", "form": "text", "appendix": "text", "filing_type": "text"}, "snapshots": {"origin": "text", "working": "text", "waiting": "integer"}, "transactions": {"value_origin": "text", "broker": "text", "broker_role": "text", "broker_text": "text", "waiting": "integer", "also_in": "text", "security": "text"}, "cancellations": {"basis": "text"}}
    for table, columns in additions.items():
        have = {r["name"] for r in con.execute(f"pragma table_info({table})")}
        for column, kind in columns.items():
            if column not in have:
                con.execute(f"alter table {table} add column {column} {kind}")
    fill_labels(con)
    con.commit()
    return con


def fill_labels(con):
    """The Appendix and type shown for each filing, from data/filing_forms.csv. A form that isn't listed stays Not identified, and is looked at again in case the list has grown."""
    f = ROOT / "data" / "filing_forms.csv"
    labels = {}
    if f.exists():
        with f.open(encoding="utf-8-sig", newline="") as fh:
            labels = {(r["form"], r["doc_type"]): (r["appendix"], r["filing_type"]) for r in csv.DictReader(fh)}
    for d in con.execute("select doc_id, form, doc_type, parsed_json, appendix, filing_type from documents where appendix is null or appendix='Not identified'").fetchall():
        p = json.loads(d["parsed_json"])["p"] if d["parsed_json"] else {}
        form = d["form"] or p.get("form") or ""
        appendix, kind = labels.get((form, d["doc_type"] or p.get("doc_type") or ""), ("Not identified", "Not identified"))
        if (d["form"] or "", d["appendix"], d["filing_type"]) != (form, appendix, kind):
            con.execute("update documents set form=?, appendix=?, filing_type=? where doc_id=?", (form or None, appendix, kind, d["doc_id"]))


def state(con, key, value=None):
    """A value the app keeps about this database file itself (when it was last settled, when it was published). With a value, stores it."""
    if value is None:
        r = con.execute("select value from app_state where key=?", (key,)).fetchone()
        return r[0] if r else None
    con.execute("insert into app_state(key, value) values(?, ?) on conflict(key) do update set value=excluded.value", (key, str(value)))
    return str(value)


def rows(cur):
    return [dict(r) for r in cur]
