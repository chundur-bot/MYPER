"use strict";
// Share Buyback Insight: one page for all markets. Layout and helpers follow China Bond Insight. Plain JavaScript; PDF.js is the only library, kept in static/vendor so the page works offline.

let goToken = 0;
const S = { from: null, to: null, country: "ALL", ticker: "", tickerCountry: "", tickers: [], sec: "home", sub: {}, mode: "dashboard", countries: [], periods: null };
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const view = () => $("#view");

// ---------- helpers ----------
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const amt = (v) => (v === null || v === undefined || v === "" || isNaN(v)) ? "" : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const amt0 = (v) => (v === null || v === undefined || v === "" || isNaN(v)) ? "" : Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
const int = (v) => (v === null || v === undefined || v === "") ? "" : Number(v).toLocaleString("en-US");
const lastDay = (ym) => { const [y, m] = ym.split("-").map(Number); return `${ym}-${String(new Date(y, m, 0).getDate()).padStart(2, "0")}`; };
const today = () => new Date().toISOString().slice(0, 10);
const addDays = (d, n) => { const x = new Date(d + "T00:00:00Z"); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); };
const qs = (o) => Object.entries(o).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
const monthName = (ym) => new Date(ym + "-01T00:00:00").toLocaleString("en-GB", { month: "long", year: "numeric" });
const monthShort = (ym) => new Date(ym + "-01T00:00:00").toLocaleString("en-GB", { month: "short", year: "2-digit" });
const periodLabel = (f, t) => (f.slice(8) === "01" && t === lastDay(f.slice(0, 7))) ? monthName(f.slice(0, 7)) : `${f} to ${t}`;
const icon = (id) => `<svg aria-hidden="true"><use href="#i-${id}"/></svg>`;

async function api(path, params = {}, opts = {}) {
  const asked = goToken;
  const r = await fetch(path + (Object.keys(params).length ? "?" + qs(params) : ""), opts);
  const j = await r.json();
  if (!opts.method && asked !== goToken) throw new Error("superseded");  // another page was chosen meanwhile: this one must not draw
  if (!r.ok || (j && j.error)) throw new Error(j.error || r.statusText);
  return j;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.style.display = "none"), 3500);
}
function download(name, text) {
  const b = new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function csvOf(rows, cols) {
  const line = (vals) => vals.map((v) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; }).join(",");
  const cell = (v) => (typeof v === "string" && /^\d{5,}$/.test(v)) ? `="${v}"` : typeof v === "string" ? usDate(v) : v;  // keep leading zeros in Excel; dates as MM/DD/YYYY
  return [line(cols), ...rows.map((r) => line(cols.map((k) => cell(r[k]))))].join("\n");
}

// ---------- tooltip (hover and keyboard focus) ----------
function tipOn(el, html) {
  const t = $("#tip");
  const show = (x, y) => { t.innerHTML = html; t.style.display = "block";
    const w = t.offsetWidth, h = t.offsetHeight;
    t.style.left = Math.min(innerWidth - w - 8, Math.max(8, x - w / 2)) + "px"; t.style.top = Math.max(8, y - h - 12) + "px"; };
  el.addEventListener("pointermove", (e) => show(e.clientX, e.clientY));
  el.addEventListener("focus", () => { const r = el.getBoundingClientRect(); show(r.left + r.width / 2, r.top); });
  const hide = () => (t.style.display = "none");
  el.addEventListener("pointerleave", hide); el.addEventListener("blur", hide);
}

// ---------- tables: sort, search, filters, paging, CSV ----------
function table(el, cfg) {
  const st = { sort: cfg.sort || null, dir: cfg.dir || 1, page: 0, q: "", f: {} };
  const size = cfg.pageSize || 50;
  (cfg.filters || []).forEach((f) => { if (f.auto) f.options = [...new Set(cfg.rows.map((r) => r[f.key]).filter((v) => v !== null && v !== undefined && v !== ""))].sort(); });
  const filtered = () => {
    let rs = cfg.rows;
    if (st.q) { const q = st.q.toLowerCase(); rs = rs.filter((r) => cfg.columns.some((c) => String(r[c.key] ?? "").toLowerCase().includes(q)) || (cfg.searchKeys || []).some((k) => String(r[k] ?? "").toLowerCase().includes(q))); }
    for (const f of cfg.filters || []) { const v = st.f[f.key]; if (v) rs = rs.filter((r) => String(r[f.key] ?? "") === v); }
    if (st.sort) {
      const k = st.sort, num = cfg.columns.find((c) => c.key === k)?.num;
      rs = [...rs].sort((a, b) => { let x = a[k], y = b[k];
        if (num) { x = x === null || x === "" ? -Infinity : Number(x); y = y === null || y === "" ? -Infinity : Number(y); } else { x = String(x ?? ""); y = String(y ?? ""); }
        return (x < y ? -1 : x > y ? 1 : 0) * st.dir; });
    }
    return rs;
  };
  const render = () => {
    const rs = filtered(), pages = Math.max(1, Math.ceil(rs.length / size));
    st.page = Math.min(st.page, pages - 1);
    const slice = rs.slice(st.page * size, st.page * size + size);
    const showBar = cfg.search !== false || (cfg.filters || []).length || cfg.csv;
    el.innerHTML = `${showBar ? `<div class="tbar">
        ${cfg.search !== false ? `<input type="search" placeholder="Search…" value="${esc(st.q)}" class="tq" aria-label="Search this table">` : ""}
        ${(cfg.filters || []).map((f) => `<select data-f="${f.key}" aria-label="${esc(f.label)}"><option value="">${esc(f.label)}: all</option>${f.options.map((o) => `<option ${st.f[f.key] === String(o) ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`).join("")}
        <span class="count">${int(rs.length)} row${rs.length === 1 ? "" : "s"}${cfg.totals ? cfg.totals(rs) : ""}</span>
        ${cfg.csv ? `<button class="btn sm tcsv">${icon("download")} CSV</button>` : ""}</div>` : ""}
      <div class="twrap ${cfg.short ? "short" : ""}"><table class="${S.mode === "analyst" || cfg.compact ? "compact" : ""}"><thead><tr>${cfg.columns.map((c) => `<th data-k="${c.key}" class="${c.num ? "n" : ""}">${esc(c.label)}${st.sort === c.key ? `<span class="ar">${st.dir > 0 ? "▲" : "▼"}</span>` : ""}</th>`).join("")}</tr></thead>
      <tbody>${slice.length ? slice.map((r, i) => `<tr data-i="${st.page * size + i}" class="${cfg.onRow ? "click" : ""}">${cfg.columns.map((c) => {
        const v = r[c.key], out = c.html ? c.html(v, r) : esc(c.fmt ? c.fmt(v, r) : v);
        const cls = c.num ? "n" : c.wrap ? "wrap" : c.clip ? "clip" : "";
        return `<td class="${cls}"${cls === "clip" ? ` title="${esc(v)}"` : ""}>${out}</td>`; }).join("")}</tr>`).join("") : `<tr><td colspan="${cfg.columns.length}" class="empty">Nothing to show for this selection.</td></tr>`}</tbody></table></div>
      ${pages > 1 ? `<div class="pager"><button class="btn sm pp" ${st.page === 0 ? "disabled" : ""}>‹ Prev</button>Page ${st.page + 1} of ${pages}<button class="btn sm pn" ${st.page >= pages - 1 ? "disabled" : ""}>Next ›</button></div>` : ""}`;
    const s = $(".tq", el);
    if (s) s.oninput = (e) => { st.q = e.target.value; st.page = 0; const pos = e.target.selectionStart; render(); const n = $(".tq", el); n.focus(); n.setSelectionRange(pos, pos); };
    $$("select[data-f]", el).forEach((sel) => (sel.onchange = () => { st.f[sel.dataset.f] = sel.value; st.page = 0; render(); }));
    $$("th", el).forEach((th) => (th.onclick = () => { const k = th.dataset.k; st.dir = st.sort === k ? -st.dir : 1; st.sort = k; render(); }));
    if (cfg.onRow) $$("tbody tr[data-i]", el).forEach((tr) => (tr.onclick = (e) => { if (!e.target.closest("a, [data-pick]")) cfg.onRow(rs[Number(tr.dataset.i)]); }));
    if ($(".pp", el)) $(".pp", el).onclick = () => { st.page--; render(); };
    if ($(".pn", el)) $(".pn", el).onclick = () => { st.page++; render(); };
    if ($(".tcsv", el)) $(".tcsv", el).onclick = () => download(cfg.csv, csvOf(filtered(), cfg.csvColumns || cfg.columns.map((c) => c.key)));
  };
  render();
}

// ---------- number and label formats ----------
const SYM = { GBP: "£", AUD: "A$", NZD: "NZ$", USD: "US$", EUR: "€", HKD: "HK$" };
function money(v, cur) {
  if (v === null || v === undefined || v === "" || isNaN(v)) return "–";
  const s = SYM[cur] ?? (cur ? cur + " " : ""), a = Math.abs(v);
  if (a >= 1e9) return s + (v / 1e9).toFixed(2) + "bn";
  if (a >= 1e6) return s + (v / 1e6).toFixed(1) + "m";
  if (a >= 1e3) return s + (v / 1e3).toFixed(0) + "k";
  return s + Number(v).toFixed(0);
}
const moneyFull = (v, cur) => (v === null || v === undefined) ? "" : (SYM[cur] ?? "") + amt(v);
const count = (v) => { if (!v) return v === 0 ? "0" : "–"; const a = Math.abs(v); return a >= 1e9 ? (v / 1e9).toFixed(2) + "bn" : a >= 1e6 ? (v / 1e6).toFixed(1) + "m" : a >= 1e4 ? (v / 1e3).toFixed(0) + "k" : int(Math.round(v)); };
const pc = (v) => (v === null || v === undefined) ? "–" : Number(v).toFixed(1) + "%";
// Amounts in the currency each notice reports them in. Never added or converted across currencies.
const amounts = (o, fallback) => { const e = Object.entries(o || {}); return e.length ? e.map(([c, v]) => money(v, c)).join(", ") : money(0, fallback); };
// Reported: a notice states this figure. Calculated: worked out from notices; the working shows on hover and in the side panel.
// Bought: shares first, then each currency's amount in full, e.g. "1,712,662,647 shares (GBP 1,750,000,020.87)".
// A programme whose terms changed (renewed for another year, its end moved, its size raised): the whole span, and one row for each period as its filing stated it.
const periodRuns = (p) => p.periods
  ? `${esc(p.periods.from || "?")} to ${esc(p.periods.to || p.end_date || "?")}<div class="muted small sans">${int(p.periods.count)} period${p.periods.count === 1 ? "" : "s"}. The newest runs ${esc(p.start_date || "?")} to ${esc(p.end_date || "?")}</div>`
  : `${esc(p.start_date || "?")} to ${esc(p.end_date || "?")}`;
const periodTarget = (r) => r.max_value ? money(r.max_value, r.max_currency) : r.max_shares ? `${int(r.max_shares)} shares` : r.max_pct ? `${r.max_pct}% of shares` : `<span class="muted">Not stated</span>`;
const periodsBlock = (p) => {
  const x = p.periods;
  if (!x) return "";
  const rows = x.rows.map((r) => `<tr class="${r.current ? "now" : ""}" data-pdoc="${r.doc_id}" title="Open the filing that stated this period">
      <td class="mono">${esc(r.start || "?")} to ${esc(r.end || "?")}${r.changes.map((c) => `<div class="muted small sans">${esc(c)}</div>`).join("")}</td>
      <td class="n">${periodTarget(r)}</td>
      <td class="n" title="${esc(Object.entries(r.amounts || {}).map(([c, v]) => `${c} ${amt(v)}`).join("; "))}">${int(Math.round(r.bought_shares || 0))}<div class="muted small">${int(r.days)} day${r.days === 1 ? "" : "s"}</div></td>
      <td class="n">${r.used_pct === null || r.used_pct === undefined ? `<span class="muted">–</span>` : `${pc(r.used_pct)} ${tag("Calculated", r.used_working)}`}</td>
      <td class="mono">${esc(r.filed || "")}${r.hand ? " " + tag("Entered by hand", "This period's terms were entered by hand") : ""}</td></tr>`).join("");
  return `<h3 class="periods-h">Periods</h3><div class="twrap short periods"><table class="compact"><thead><tr><th>Period</th><th class="n">Target</th><th class="n">Shares bought</th><th class="n">Used</th><th>Filed</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="small muted">Dates and target are as each filing states them ${tag("Reported", "As the filing states")}. Shares bought are the purchases read with a date inside the period, added up. The newest period is highlighted. Click a period to open its filing.</p>
    ${x.outside ? `<p class="small muted">${int(Math.round(x.outside.shares))} shares on ${int(x.outside.days)} day${x.outside.days === 1 ? "" : "s"} (${esc(x.outside.first)} to ${esc(x.outside.last)}) fall outside every stated period, so they are in no row above.</p>` : ""}
    ${x.gap ? `<div class="note">The filings' own total at ${esc(x.gap.as_of)} is ${int(x.gap.stated)} shares, but the purchases read add up to ${int(Math.round(x.gap.read))}. ${int(Math.round(x.gap.missing))} shares are in notices not read yet ${tag("Calculated", "Total stated in the filing - sum of the purchases read")}.</div>` : ""}`;
};
const bindPeriods = (root) => $$(`${root} [data-pdoc]`).forEach((tr) => (tr.onclick = () => openDoc(+tr.dataset.pdoc, "prog")));
const boughtText = (shares, amts) => { const e = Object.entries(amts || {}); return `${int(Math.round(shares || 0))} shares` + (e.length ? ` (${e.map(([c, v]) => `${esc(c)} ${amt(v)}`).join("; ")})` : ""); };
// ---------- entries made by hand ----------
const HAND_KINDS = [["programme", "Programme announcement"], ["change", "Change of terms"], ["purchase", "Purchase"], ["completion", "Completion"], ["update", "Update a reading"]];
const HAND_HELP = {
  programme: "Type the terms exactly as the announcement states them. Maximum shares, maximum amount and maximum % of shares are alternatives: fill in whichever it states. Intended number is what the company expects to buy (\"approximately 260,000\"); it is never used as the limit. The end date is typed by you: if the announcement gives a period, such as 12 months from its date, type the date and put the wording in Note.",
  change: "Choose the programme, then type only what changed: a new start or end date, or a new size. The terms before the change are kept, and the Periods table shows both.",
  purchase: "Choose the exchange the shares were bought on (for a company listed in two places this can differ from its home exchange). If you type the average price but not the amount, the amount is worked out as shares x average price and marked Calculated.",
  update: "Changes one figure read from a filing: a programme's terms, a purchase or a running total. Choose the programme, what, and the figure; the figure as held and the words it was read from are shown. The filing's reading is kept unchanged, and the figure is marked Updated Manually everywhere. Figures worked out from it (an average, an amount that is shares x average, the day's closing total) are worked out again and stay Calculated; totals a notice states are not changed. Set aside leaves a row read wrongly out of every figure.",
  completion: "Marks the programme Completed on the date you give. If the announcement states final totals, type them; if not, leave them blank and the totals stay as the purchases read.",
};
const HAND_NAMES = { announced_date: "Announced on", buyback_type: "Type", start_date: "Starts", end_date: "Ends", max_shares: "Maximum shares", max_value: "Maximum amount", max_currency: "Currency of the maximum",
  max_pct: "Maximum as % of shares", intended_shares: "Intended number (approximate, not a limit)", broker: "Broker", treatment: "Shares are", programme: "Programme announced", change_date: "Date of the change",
  trade_date: "Purchase date", venue: "Bought on", shares: "Shares", value: "Amount paid", currency: "Currency", price_avg: "Average price", price_high: "Highest price", price_low: "Lowest price",
  completed_on: "Completed on", final_shares: "Total shares bought", final_value: "Total amount paid", final_currency: "Currency of the total" };
function handForm(kind, ch, v, mkt) {
  const val = (id) => v[id] === null || v[id] === undefined ? "" : String(v[id]);
  const row = (id, label, input, req) => `<label for="h_${id}">${esc(label)}${req ? ` <span class="req">*</span>` : ""}</label>${input}`;
  const txt = (id, ph = "", mode = "") => `<input type="text" id="h_${id}" value="${esc(val(id))}" placeholder="${esc(ph)}"${mode ? ` inputmode="${mode}"` : ""}>`;
  const dt = (id) => `<input type="date" id="h_${id}" value="${esc(val(id))}">`;
  const sel = (id, opts, blank) => `<select id="h_${id}">${blank !== undefined ? `<option value="">${esc(blank)}</option>` : ""}${opts.map(([o, label]) => `<option value="${esc(o)}" ${val(id) === String(o) ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
  const cur = (id) => sel(id, ch.currencies.map((c) => [c, c]), "Currency");
  const withCur = (id, cid, ph) => `<div class="row"><input type="text" id="h_${id}" value="${esc(val(id))}" placeholder="${esc(ph)}" inputmode="decimal" style="flex:1 1 160px">${cur(cid)}</div>`;
  if (!val("max_currency") && mkt.currency) v.max_currency = mkt.currency;
  if (!val("currency") && mkt.currency) v.currency = mkt.currency;
  if (!val("final_currency") && mkt.currency) v.final_currency = mkt.currency;
  if (!val("venue") && mkt.exchange) v.venue = mkt.exchange;
  const progs = ch.programmes.map((p) => [p.announced_date, `Announced ${p.announced_date}${p.start_date || p.end_date ? ` · runs ${p.start_date || "?"} to ${p.end_date || "?"}` : ""}${p.status === "COMPLETED" ? " · completed" : ""}`]);
  const prog = (need) => row("programme", "Programme", progs.length ? sel("programme", progs, need ? "Choose the programme" : "Latest announced by the purchase date") : `<span class="small muted">${v.ticker ? `No programme is held for ${esc(v.ticker)} yet. Add its Programme announcement first.` : "Choose the company first."}</span>`, need);
  const top = row("country", "Exchange", `<select id="h_country">${ch.markets.map((m) => `<option value="${esc(m.code)}" ${m.code === v.country ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select>`, true)
    + row("ticker", "Company", `<input type="text" id="h_ticker" list="h_companies" value="${esc(val("ticker"))}" placeholder="Type the code or choose" autocomplete="off"><datalist id="h_companies">${ch.companies.map((c) => `<option value="${esc(c.ticker)}">${esc(c.ticker)} · ${esc(c.company || "")}</option>`).join("")}</datalist>`, true);
  const sizes = row("max_shares", "Maximum shares", txt("max_shares", "If stated", "numeric")) + row("max_value", "or maximum amount", withCur("max_value", "max_currency", "If stated"))
    + row("max_pct", "or maximum % of shares", `<div class="row"><input type="text" id="h_max_pct" value="${esc(val("max_pct"))}" placeholder="For example 0.5" inputmode="decimal" style="flex:1 1 120px"><span class="small muted">% of ordinary shares</span></div>`)
    + row("intended_shares", "Intended number", `<div class="row"><input type="text" id="h_intended_shares" value="${esc(val("intended_shares"))}" placeholder="If stated" inputmode="numeric" style="flex:1 1 120px"><span class="small muted">approximately; not a limit</span></div>`);
  const dates = row("start_date", "Starts", dt("start_date")) + row("end_date", "Ends", `<div class="row">${dt("end_date")}<span class="small muted">typed by you; never worked out</span></div>`);
  const body = {
    programme: row("announced_date", "Announced on", dt("announced_date"), true) + row("buyback_type", "Type", sel("buyback_type", ch.types.map((t) => [t, t]), "Not stated")) + dates + sizes
      + row("broker", "Broker", txt("broker", "If the announcement names one")) + row("treatment", "Shares are", sel("treatment", ch.treatments.map((t) => [t, t === "Treasury" ? "Held in treasury" : t]), "Not stated")),
    change: prog(true) + row("change_date", "Date of the change", dt("change_date"), true) + dates + sizes,
    purchase: prog(false) + row("trade_date", "Purchase date", dt("trade_date"), true)
      + row("venue", "Bought on", `<input type="text" id="h_venue" list="h_venues" value="${esc(val("venue"))}" placeholder="The exchange"><datalist id="h_venues">${ch.venues.map((x) => `<option value="${esc(x)}"></option>`).join("")}</datalist>`, true)
      + row("shares", "Shares", txt("shares", "", "numeric"), true) + row("value", "Amount paid", withCur("value", "currency", "If stated"))
      + row("price_avg", "Average price", txt("price_avg", "If stated", "decimal")) + row("price_high", "Highest price", txt("price_high", "If stated", "decimal")) + row("price_low", "Lowest price", txt("price_low", "If stated", "decimal"))
      + row("broker", "Broker", txt("broker", "If stated")),
    completion: prog(true) + row("completed_on", "Completed on", dt("completed_on"), true) + row("final_shares", "Total shares bought", txt("final_shares", "If the announcement states it", "numeric"))
      + row("final_value", "Total amount paid", withCur("final_value", "final_currency", "If stated")),
  }[kind];
  return top + body + row("source", "Source", txt("source", "A link, or where it came from, e.g. \"NZX announcement of 2 March 2026\""), true) + row("note", "Note", txt("note", "Optional, e.g. the wording of a period the announcement gives"));
}
function handDelete(r) {
  const m = $("#modal");
  m.hidden = false;
  const undo = r.kind === "update";
  m.innerHTML = `<div class="modal-box small-box"><div class="card-head"><h2>${undo ? "Undo this update?" : `Delete this ${esc(r.kind_label.toLowerCase())}?`}</h2><div class="right"><button class="icon-btn" id="closeModal" aria-label="Close">${icon("x")}</button></div></div>
    <p class="small">${esc(r.ticker)}, ${esc(r.date || "")}: ${esc(r.what)}. ${undo ? "The figure goes back to what the filing reads." : "It is taken out of every figure."} It stays in the history, with today's date and your reason.</p>
    <div class="form"><label for="hReason">Reason <span class="req">*</span></label><input type="text" id="hReason" placeholder="For example: Entered twice">
    <span></span><div class="row"><button class="btn danger" id="hDel">${undo ? "Undo" : "Delete"}</button><button class="btn" id="hKeep">Cancel</button></div></div></div>`;
  $("#closeModal").onclick = closeModal; $("#hKeep").onclick = closeModal; $("#hReason").focus();
  $("#hDel").onclick = async () => {
    try { await post("/api/hand/delete", { entry_id: r.entry_id, reason: $("#hReason").value }); closeModal(); toast(undo ? "Undone. The filing's figure is back, and the update is kept in the history." : "Deleted. It is out of the figures and kept in the history."); if (S.hand && S.hand.edit === r.entry_id) S.hand.edit = null; PAGES.hand(); }
    catch (e) { toast(e.message); }
  };
}
// The panel of an entry made by hand: what was typed and where it came from. There are no pages to show.
function openHandDoc(d) {
  const e = d.hand, f = (e && e.fields) || {};
  const show = (k, v) => v === null || v === undefined || v === "" ? "" : `<dt>${esc(HAND_NAMES[k] || k)}</dt><dd class="${/date|_on$/.test(k) ? "mono" : ""}">${typeof v === "number" ? (k === "max_pct" ? `${v}%` : Number.isInteger(v) ? int(v) : amt(v)) : esc(v)}</dd>`;
  openSheet(`<div class="sh-head"><div class="acts"><button class="btn sm hand-edit" id="hGoEdit">Edit on Add by hand</button><button class="icon-btn" id="closeSheet" aria-label="Close">${icon("x")}</button></div>
      <div class="kicker">${esc(d.country)} · ${esc(d.ticker || "")} · ${esc(d.doc_date || "")} · ${esc(d.filing_type || "")}</div><div class="title">${esc(d.file_name)}</div>${tag("Entered by hand", e ? "Source: " + e.source : "")}
      ${d.reviews.filter((r) => r.status === "OPEN").map((r) => `<div class="note">${esc(r.detail)}</div>`).join("")}</div>
    <div class="sh-body">${e ? `<dl class="kv">${Object.entries(f).map(([k, v]) => show(k, v)).join("")}<dt>Source</dt><dd>${/^https?:\/\//i.test(e.source) ? sourceLink(e.source) + " " : ""}${esc(e.source)}</dd>${e.note ? `<dt>Note</dt><dd>${esc(e.note)}</dd>` : ""}
      <dt>Entered</dt><dd class="mono">${esc(String(e.created_at || "").slice(0, 16))}${e.updated_at && e.updated_at !== e.created_at ? ` · last changed ${esc(String(e.updated_at).slice(0, 16))}` : ""}</dd></dl>
      <p class="small muted">Entered by hand, so there is no filing text to highlight. Every change to this entry is in the history on Add data > Add by hand.</p>` : `<p class="muted">This entry is no longer held.</p>`}</div>`, true);
  $("#hGoEdit").onclick = () => { if (!e) return; S.hand = { kind: e.kind, edit: e.entry_id, vals: { ...e.fields, country: e.country, ticker: e.ticker, source: e.source, note: e.note || "" } }; closeSheet(); go("collect", "hand"); };
}
const handTag = (source) => source ? " " + tag("Entered by hand", `Source: ${source}`) : "";
const sizeText = (p) => {
  const parts = [p.max_value ? money(p.max_value, p.max_currency) : "", p.max_shares ? int(p.max_shares) + " shares" : "", p.max_pct ? `up to ${p.max_pct}% of shares` : ""].filter(Boolean);
  return parts.length ? parts.join(" · ") : "–";
};

// A programme's status: COMPLETED in bold red, ACTIVE in bold green. A completion worked out by the app is tagged Calculated, with its reason.
const statusText = (p) => `<span class="st ${p.status === "COMPLETED" ? "done" : p.status === "ACTIVE" ? "live" : ""}">${esc(p.status || "–")}</span>${p.status_basis === "Calculated" || p.status_basis === "Entered by hand" || p.status_basis === "Updated Manually" ? ` ${tag(p.status_basis, p.status_working)}<div class="muted small">${esc(p.status_working)}</div>` : ""}`;
const tag = (basis, working) => basis ? `<span class="tag ${basis === "Reported" ? "rep" : basis === "Entered by hand" || basis === "Updated Manually" ? "hand" : "calc"}" title="${esc(working || "")}">${esc(basis)}</span>` : "";
// ---------- a figure read from a filing, Updated Manually (version 27) ----------
// The filing's reading is kept; the update is kept with its source and reason, can be edited or undone, and is applied again after every rebuild.
const UPD = "Updated Manually";
const updTag = (text) => text ? " " + tag(UPD, text) : "";
const updButton = (o, label = "update", cls = "linkbtn") => `<button class="${cls} hand-edit" data-upd="${esc(JSON.stringify(o))}" title="Change a figure read from the filing, with its source and reason">${esc(label)}</button>`;
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-upd]");
  if (!b) return;
  e.stopPropagation(); e.preventDefault();  // a row's own click (open the filing) does not run as well
  const o = JSON.parse(b.dataset.upd);
  S.hand = { kind: "update", edit: null, vals: { country: o.country, ticker: o.ticker, programme: o.programme || "", target: o.target || "", row: o.row || "", field: o.field || "" } };
  closeSheet();
  go("collect", "hand").then(() => window.scrollTo({ top: 0 }));
}, true);
function updForm(ch, uc, v, mkt, editing) {
  const val = (id) => v[id] === null || v[id] === undefined ? "" : String(v[id]);
  const row = (id, label, input, req) => `<label for="h_${id}">${esc(label)}${req ? ` <span class="req">*</span>` : ""}</label>${input}`;
  const sel = (id, opts, blank) => `<select id="h_${id}">${blank !== undefined ? `<option value="">${esc(blank)}</option>` : ""}${opts.map(([o, label]) => `<option value="${esc(o)}" ${val(id) === String(o) ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
  const txt = (id, ph = "", mode = "") => `<input type="text" id="h_${id}" value="${esc(val(id))}" placeholder="${esc(ph)}"${mode ? ` inputmode="${mode}"` : ""}>`;
  let h = row("country", "Exchange", `<select id="h_country">${ch.markets.map((m) => `<option value="${esc(m.code)}" ${m.code === v.country ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select>`, true)
    + row("ticker", "Company", `<input type="text" id="h_ticker" list="h_companies" value="${esc(val("ticker"))}" placeholder="Type the code or choose" autocomplete="off"><datalist id="h_companies">${ch.companies.map((c) => `<option value="${esc(c.ticker)}">${esc(c.ticker)} · ${esc(c.company || "")}</option>`).join("")}</datalist>`, true);
  const progs = ch.programmes.map((p) => [p.announced_date, `Announced ${p.announced_date}${p.start_date || p.end_date ? ` · runs ${p.start_date || "?"} to ${p.end_date || "?"}` : ""}${p.status === "COMPLETED" ? " · completed" : ""}`]);
  h += row("programme", "Programme", progs.length ? sel("programme", progs, "Choose the programme") : `<span class="small muted">${v.ticker ? `No programme is held for ${esc(v.ticker)}.` : "Choose the company first."}</span>`, true);
  const t = val("programme") ? val("target") : "";
  if (val("programme")) h += row("target", "What", sel("target", uc.targets, "Choose: programme terms, a purchase or a running total"), true);
  if (t === "purchase") h += row("row", "Purchase", uc.purchases.length ? sel("row", uc.purchases.map((x) => [x.key, x.label]), "Choose the purchase") : `<span class="small muted">No purchases are held for this programme.</span>`, true);
  if (t === "total") h += row("row", "Running total", uc.totals.length ? sel("row", uc.totals.map((x) => [x.key, x.label]), "Choose the running total") : `<span class="small muted">No running totals are held for this programme.</span>`, true);
  if (t && (t === "programme" || val("row"))) h += row("field", "Figure", sel("field", uc.fields[t] || [], "Choose the figure"), true);
  const a = uc.asread;
  if (a) {
    h += `<label>As held now</label><div><b class="mono">${esc(a.shown)}</b>${a.basis ? " " + tag(a.basis, "") : ""}${editing ? ` <span class="small muted">(with this update in force; as read: ${esc(String(v.was_shown || ""))})</span>` : ""}</div>`;
    h += `<label>From</label><div>${a.doc_id ? `<button class="linkbtn" data-doc="${a.doc_id}" data-key="${esc(a.ev_key || "")}">${esc(a.file_name || "the filing")}</button>${a.doc_date ? `, filed ${esc(a.doc_date)}` : ""}${a.page ? `, page ${int(a.page)}` : ""}${a.manual ? " (entered by hand: change it as an entry, not here)" : ""}` : `<span class="small muted">No single filing: the terms come from the notices read</span>`}</div>`;
    if (a.text) h += `<label>Source text</label><div class="quote">${esc(a.context || "")} <mark>${esc(a.text)}</mark></div>`;
    if (a.already && !editing) h += `<span></span><div class="note small">This figure already has update ${int(a.already)}. Edit or undo it in the list below.</div>`;
    const k = a.kind, cur = (id) => sel(id, ch.currencies.map((c) => [c, c]), "Currency");
    if (k === "money" && !val("value_currency")) v.value_currency = a.currency || mkt.currency || "";
    const input = k === "aside" ? `<span class="small">The row leaves every figure. It is kept, and comes back when the update is undone.</span>`
      : k === "date" ? `<input type="date" id="h_value" value="${esc(val("value"))}">`
      : k === "treatment" ? sel("value", ch.treatments.map((x) => [x, x === "Treasury" ? "Held in treasury" : x]), "Not stated")
      : k === "status" ? sel("value", uc.statuses.map((x) => [x, x]), "Choose")
      : k === "cur" ? cur("value")
      : k === "money" ? `<div class="row"><input type="text" id="h_value" value="${esc(val("value"))}" placeholder="Blank = not stated" inputmode="decimal" style="flex:1 1 160px">${cur("value_currency")}</div>`
      : k === "whole" ? txt("value", "A whole number of shares", "numeric")
      : k === "num" ? txt("value", "Blank = not stated", "decimal")
      : txt("value", "Blank = not stated");
    h += row("value", k === "aside" ? "Set aside" : "New value", input, k === "whole" || k === "cur" || k === "status");
  }
  return h + row("source", "Source", txt("source", "Where the right figure is: the filing and page, or a link"), true) + row("note", "Reason", txt("note", "For example: digits transposed in the reading"), true);
}

// A filing's link from your list. Web links open in the browser; browsers can't open a file share from a page, so those can be copied.
const sourceLink = (url) => !url ? "" : /^https?:\/\//i.test(url) ? `<a href="${esc(url)}" target="_blank" rel="noopener" title="${esc(url)}">Doc</a>` : `<button class="linkbtn" data-copy-link="${esc(url)}" title="${esc(url)}">Copy file path</button>`;
// Add one programme's announcement by pasting its link, from a programme card or the Waiting for programme list.
const programmeDocForm = (country, ticker) => `<span class="pdoc" data-country="${esc(country)}" data-ticker="${esc(ticker)}"><input type="text" placeholder="Paste the announcement's link" aria-label="Programme announcement link for ${esc(ticker)}" style="min-width:220px"> <button class="btn sm primary" type="button">Read</button></span>`;
function bindProgrammeDocForms() {
  $$(".pdoc").forEach((f) => {
    const go1 = async () => {
      const text = f.querySelector("input").value.trim();
      if (!text) return toast("Paste the programme announcement's link first.");
      try { await post("/api/filings/paste", { text, ticker: f.dataset.ticker, market: f.dataset.country }); toast(`Reading the programme document for ${f.dataset.ticker}. Progress is on Add data.`); closeSheet(); go("collect", "import"); }
      catch (x) { toast(x.message); }
    };
    f.querySelector("button").onclick = (e) => { e.stopPropagation(); go1(); };
    f.querySelector("input").onclick = (e) => e.stopPropagation();
    f.querySelector("input").onkeydown = (e) => { if (e.key === "Enter") go1(); };
  });
}

// Remove a filing: a first click asks, a second removes, and the page then shows the reconciled figures.
const removeButton = (docId, label = "Remove") => `<button class="btn sm danger" data-remove="${docId}">${esc(label)}</button>`;
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-remove]"); if (!b) return;
  e.stopPropagation(); e.preventDefault();
  if (!b.dataset.asked) {
    b.dataset.asked = "1"; const was = b.textContent; b.textContent = "Click again to remove";
    setTimeout(() => { if (b.isConnected) { delete b.dataset.asked; b.textContent = was; } }, 5000);
    return;
  }
  try { await post("/api/filings/remove", { doc_id: +b.dataset.remove }); closeSheet(); toast("Filing removed, and its company reconciled by filing date."); go(S.sec); }
  catch (x) { toast(x.message); }
}, true);
// Starts a read. If a code that came with the links isn't in the company list, the user confirms or stops to correct it; send(true) reads anyway.
async function readChecked(send) {
  let r = await send(false);
  if (r && r.unknown) {
    const lines = r.unknown.slice(0, 10).map((u) => `${u.code} is not in the ${u.country} company list.` + (u.suggestions.length ? ` Did you mean ${u.suggestions.map((s) => `${s.ticker} (${s.company})`).join(", ")}?` : ""));
    const more = r.unknown.length > 10 ? `\n...and ${r.unknown.length - 10} more.` : "";
    if (!confirm(`${lines.join("\n")}${more}\n\nOK: read anyway, and add ${r.unknown.length === 1 ? "it as a new company" : "them as new companies"}.\nCancel: stop, so you can correct the code.`)) return false;
    await send(true);
  }
  return true;
}
const moveButton = (docId, ticker) => `<button class="btn sm" data-move="${docId}" data-from="${esc(ticker || "")}" title="Put this filing under another code">Move</button>`;
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-move]"); if (!b) return;
  e.stopPropagation(); e.preventDefault();
  const to = (prompt(`Move this filing${b.dataset.from ? ` from ${b.dataset.from}` : ""} to which code?\nIts figures leave ${b.dataset.from || "where they are"} and are added to the code you type. Nothing is read again.`) || "").trim().toUpperCase();
  if (!to) return;
  try {
    const r = await post("/api/filings/move", { doc_id: +b.dataset.move, ticker: to });
    closeSheet(); toast(`Filing moved to ${r.to}.` + (r.old_code_removed ? ` ${r.from} had no other filings and was taken off the company list.` : "")); loadTickers && loadTickers(); go(S.sec);
  } catch (x) { toast(x.message); }
}, true);
document.addEventListener("click", async (e) => { const b = e.target.closest("[data-copy-link]"); if (!b) return; e.stopPropagation(); try { await navigator.clipboard.writeText(b.dataset.copyLink); toast("File path copied."); } catch { toast(b.dataset.copyLink); } });
const others = (o) => { const e = Object.entries(o || {}); return e.length ? "plus " + e.map(([c, v]) => money(v, c)).join(", ") + " (not converted)" : ""; };
function pill(v) {
  const s = String(v ?? "");
  const cls = /^(PARSED|Buying|ACTIVE|Running totals|OK|Cancelled)$/.test(s) ? "ok" : /^(FAILED|bad)$/.test(s) ? "bad"
    : /^(NEEDS_REVIEW|warn|Notices saved, no figures|Daily notices|No buying saved)$/.test(s) ? "warn" : /^(COMPLETED|Finished|info|Treasury)$/.test(s) ? "blue" : "";
  const nice = { PARSED: "Read", NEEDS_REVIEW: "Needs review", FAILED: "Failed", COMPLETED: "Completed", ACTIVE: "Active", warn: "Check", bad: "Problem", info: "Note" }[s] || s;
  return s ? `<span class="pill ${cls}">${esc(nice)}</span>` : "";
}
const T = () => (S.ticker ? { ticker: S.ticker } : {});  // the one company chosen at the top of the page, if any
const P = () => ({ country: S.country, from: S.from, to: S.to, ...T() });
// A published copy of someone else's database: say so, hide what would change it, and offer the newest copy when one is waiting.
function showReadOnly(ro) {
  if (!ro || !ro.on) return;
  document.body.classList.add("ro");
  const b = $("#roBanner");
  if (!b) return;
  b.hidden = false;
  b.title = `A copy of ${ro.source}. Nothing you do here changes it.`;
  b.innerHTML = `<b>Read-only copy</b>${ro.published ? ` · published ${esc(String(ro.published).slice(0, 16))}` : ""}${ro.version ? ` · ${esc(ro.version)}` : ""}
    <button class="btn sm${ro.newer ? " primary" : ""}" id="roLoad" type="button">${ro.newer ? "Load the newer copy" : "Check for a newer copy"}</button>`;
  $("#roLoad").onclick = async () => {
    try {
      const r = await post("/api/read_only/refresh");
      if (r.loaded) { toast("The newer copy is loaded."); location.reload(); } else toast("This is the newest published copy.");
    } catch (e) { toast(e.message); }
  };
}
const post = (path, body) => api(path, {}, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const fieldName = { trade_date: "Purchase date", shares: "Shares on the day", price_avg: "Average price", price_high: "Highest price", price_low: "Lowest price", value: "Paid on the day", cum_shares: "Total shares", cum_value: "Total paid",
  before_shares: "Shares before that day", before_value: "Paid before that day", announced_date: "First announced", start_date: "Start date", end_date: "End date", max_shares: "Maximum shares", max_value: "Announced size", shares_on_issue: "Shares on issue", venue_shares: "Programme shares", venue_price: "Programme average price", treatment: "What happens to the shares", cancel_shares: "Cancellation count" };

// ---------- charts ----------
function columnChart(el, data, cur) {
  const W = 640, H = 220, L = 58, R = 8, T = 18, B = 26;
  const max = Math.max(1, ...data.map((d) => d.value));
  const mag = Math.pow(10, Math.floor(Math.log10(max))), step = mag * (max / mag > 5 ? 2 : max / mag > 2 ? 1 : 0.5), top = Math.ceil(max / step) * step;
  const y = (v) => T + (H - T - B) * (1 - v / top), bw = (W - L - R) / Math.max(1, data.length), barW = Math.min(46, bw * 0.62);
  let g = "";
  for (let v = 0; v <= top + 1e-9; v += step) g += `<line class="gl" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${money(v, cur)}</text>`;
  data.forEach((d, i) => {
    const x = L + bw * i + (bw - barW) / 2, yy = y(d.value), h = Math.max(1, H - B - yy), r = Math.min(4, barW / 2, h);
    g += `<rect class="hit" data-i="${i}" tabindex="0" role="img" aria-label="${esc(d.label)}: ${money(d.value, cur)}" x="${L + bw * i}" y="${T}" width="${bw}" height="${H - T - B}"/>`;
    g += `<path class="bar" d="M${x},${H - B} V${yy + r} Q${x},${yy} ${x + r},${yy} H${x + barW - r} Q${x + barW},${yy} ${x + barW},${yy + r} V${H - B} Z"/>`;
    g += `<text class="ax" x="${x + barW / 2}" y="${H - 8}" text-anchor="middle">${esc(d.short)}</text>`;
  });
  g += `<line x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}" stroke="var(--border-strong)"/>`;
  el.innerHTML = `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="group" aria-label="Amount bought back by month">${g}</svg></div>`;
  $$(".hit", el).forEach((h) => { const d = data[+h.dataset.i]; tipOn(h, `<b>${moneyFull(d.value, cur)}</b><span>${esc(d.label)}</span>`); });
}
const dayLabel = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" });
const niceTop = (max) => { const m = Math.pow(10, Math.floor(Math.log10(max || 1))), r = max / m, n = r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10; return { top: n * m, step: (n * m) / (n === 2.5 ? 5 : n === 1 || n === 10 ? 5 : 4) }; };
// One measure over time. Dots mark what notices state; the straight lines between them join saved notices, and don't show the days between.
function trendChart(el, points, { fmt, target, label, zero = true }) {
  if (!points.length) { el.innerHTML = `<p class="muted small">Nothing saved for this yet.</p>`; return; }
  const W = 640, H = 230, L = 68, R = 16, T = 16, B = 26;
  const vals = points.map((p) => p.value).concat(target ? [target.value] : []);
  const hi = Math.max(...vals), lo = zero ? 0 : Math.min(...vals), pad = zero ? 0 : (hi - lo || hi || 1) * 0.15;
  const { top, step } = niceTop(zero ? hi : hi + pad - Math.max(lo - pad, 0));
  const y0 = zero ? 0 : Math.max(0, lo - pad), yTop = zero ? top : Math.max(y0 + top, hi + pad * 0.5);
  const ts = points.map((p) => +new Date(p.date)), t0 = Math.min(...ts), t1 = Math.max(...ts);
  const x = (d) => t1 === t0 ? (L + W - R) / 2 : L + (W - L - R) * ((+new Date(d) - t0) / (t1 - t0));
  const y = (v) => T + (H - T - B) * (1 - (v - y0) / (yTop - y0));
  let g = "";
  for (let i = 0, n = zero ? Math.round(top / step) : 4; i <= n; i++) { const v = y0 + (yTop - y0) * i / n; g += `<line class="gl" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${esc(fmt(v))}</text>`; }
  if (target) g += `<line x1="${L}" x2="${W - R}" y1="${y(target.value)}" y2="${y(target.value)}" stroke="var(--ink-2)" stroke-width="1.5" stroke-dasharray="6 4"/><text class="lbl" x="${W - R}" y="${y(target.value) - 6}" text-anchor="end">Target ${esc(fmt(target.value))}</text>`;
  if (points.length > 1) g += `<polyline fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" points="${points.map((p) => `${x(p.date)},${y(p.value)}`).join(" ")}"/>`;
  points.forEach((p, i) => { g += `<circle cx="${x(p.date)}" cy="${y(p.value)}" r="4" fill="var(--series-1)" stroke="var(--surface)" stroke-width="2"/><circle class="hit" data-i="${i}" tabindex="0" role="img" aria-label="${esc(dayLabel(p.date))}: ${esc(fmt(p.value))}" cx="${x(p.date)}" cy="${y(p.value)}" r="12"/>`; });
  const ticks = t1 === t0 ? [points[0].date] : [points[0].date, points[points.length - 1].date];
  ticks.forEach((d, i) => { g += `<text class="ax" x="${x(d)}" y="${H - 8}" text-anchor="${t1 === t0 ? "middle" : i ? "end" : "start"}">${esc(dayLabel(d))}</text>`; });
  el.innerHTML = `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="group" aria-label="${esc(label)}">${g}</svg></div>`;
  $$(".hit", el).forEach((h) => { const p = points[+h.dataset.i]; tipOn(h, `<b>${esc(fmt(p.value))}</b><span>${esc(dayLabel(p.date))}${p.basis ? " · " + esc(p.basis) : ""}${target ? ` · ${(100 * p.value / target.value).toFixed(1)}% of target` : ""}</span>`); });
}
// Shares per purchase date, stacked by venue. Only dates with a saved notice appear, so the axis is by notice, not by calendar.
function dailyBars(el, rows) {
  if (!rows.length) { el.innerHTML = `<p class="muted small">No daily purchases saved for this programme.</p>`; return; }
  const dates = [...new Set(rows.map((r) => r.trade_date))], venues = [...new Set(rows.map((r) => r.venue_label))].sort();
  const shown = venues.slice(0, 4), slot = (v) => Math.max(0, shown.indexOf(v)) + 1;
  const totals = dates.map((d) => rows.filter((r) => r.trade_date === d).reduce((a, r) => a + (r.shares || 0), 0));
  const W = 640, H = 230, L = 68, R = 16, T = 16, B = 26, { top, step } = niceTop(Math.max(...totals));
  const y = (v) => T + (H - T - B) * (1 - v / top), bw = (W - L - R) / dates.length, barW = Math.min(36, bw * 0.62);
  let g = "";
  for (let v = 0; v <= top + 1e-9; v += step) g += `<line class="gl" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${esc(count(v))}</text>`;
  const every = Math.ceil(dates.length / 6);
  dates.forEach((d, i) => {
    let base = 0; const x0 = L + bw * i + (bw - barW) / 2, day = rows.filter((r) => r.trade_date === d).sort((a, b) => a.venue_label.localeCompare(b.venue_label));
    day.forEach((r, k) => { const h = Math.max(1, y(base) - y(base + r.shares)), yy = y(base + r.shares) + (k ? 2 : 0), rr = k === day.length - 1 ? Math.min(4, h, barW / 2) : 0, hh = Math.max(1, h - (k ? 2 : 0));
      g += `<path fill="var(--series-${slot(r.venue_label)})" d="M${x0},${yy + hh} V${yy + rr} Q${x0},${yy} ${x0 + rr},${yy} H${x0 + barW - rr} Q${x0 + barW},${yy} ${x0 + barW},${yy + rr} V${yy + hh} Z"/>`; base += r.shares; });
    g += `<rect class="hit" data-i="${i}" tabindex="0" role="img" aria-label="${esc(dayLabel(d))}: ${int(totals[i])} shares" x="${L + bw * i}" y="${T}" width="${bw}" height="${H - T - B}"/>`;
    if (i % every === 0) g += `<text class="ax" x="${x0 + barW / 2}" y="${H - 8}" text-anchor="middle">${esc(dayLabel(d))}</text>`;
  });
  g += `<line x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}" stroke="var(--border-strong)"/>`;
  const legend = venues.length > 1 ? `<div class="legend">${shown.map((v) => `<span><i style="background:var(--series-${slot(v)})"></i>${esc(v)}</span>`).join("")}</div>` : "";
  el.innerHTML = `${legend}<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="group" aria-label="Daily shares bought back">${g}</svg></div>`;
  $$(".hit", el).forEach((h) => { const i = +h.dataset.i, day = rows.filter((r) => r.trade_date === dates[i]); tipOn(h, `<b>${int(totals[i])} shares</b><span>${esc(dayLabel(dates[i]))}${day.length > 1 ? " · " + day.map((r) => `${esc(r.venue_label)} ${int(r.shares)}`).join(", ") : ""}</span>`); });
}
function barList(el, rows, onPick) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  el.innerHTML = rows.length ? `<div class="hbars">${rows.map((r, i) => `<div class="hbar ${onPick ? "click" : ""}" data-i="${i}" ${onPick ? 'tabindex="0" role="button"' : ""}>
      <div class="l" title="${esc(r.label)}">${esc(r.label)}</div><div class="t"><i style="width:${(100 * r.value / max).toFixed(1)}%"></i></div><div class="v">${esc(r.text)}</div></div>`).join("")}</div>` : `<p class="muted">Nothing in this period yet.</p>`;
  if (onPick) $$(".hbar", el).forEach((h) => { const r = rows[+h.dataset.i]; h.onclick = () => onPick(r); h.onkeydown = (e) => { if (e.key === "Enter") onPick(r); }; });
}

// ---------- side panels ----------
function openSheet(html, wide) { const d = $("#sheet"); d.innerHTML = html; d.classList.toggle("wide", !!wide); d.classList.add("on"); $("#scrim").classList.add("on"); const c = $("#closeSheet"); if (c) { c.onclick = closeSheet; c.focus(); } }
function closeSheet() { $("#sheet").classList.remove("on"); $("#scrim").classList.remove("on"); }

function venueTable(rows, src) {
  return `<div class="twrap short"><table class="compact"><thead><tr><th>Programme</th><th>Venue</th><th class="n">Shares</th><th class="n">Share</th><th class="n">Average</th><th class="n">Value</th><th></th><th>Split from</th><th></th></tr></thead><tbody>${rows.map((v) => `<tr><td>${esc(v.announced_date)}</td><td>${esc(v.venue)}</td><td class="n">${int(v.shares)}</td><td class="n">${pc(v.share_pct)}</td><td class="n">${v.price_avg === null ? "" : Number(v.price_avg).toFixed(4) + " " + esc(v.price_unit)}</td><td class="n">${v.value === null ? "" : money(v.value, v.currency)}</td><td>${tag(v.value_basis, v.value_working)}</td><td>${esc(v.basis)}</td><td>${src(v.doc_id, v.key, "source")}</td></tr>`).join("")}</tbody></table></div>`;
}
function getNotices() {
  return `<div class="code-card get-notices"><b>Get new notices</b>
    <div class="small muted">Paste a hyperlink, or read an Excel list with Ticker and Hyperlink, on Add data.</div>
    <div class="row-c left"><button class="btn sm primary" id="goUpload">Add filings</button></div></div>`;
}
function openAddCompany() {
  const m = $("#modal"), chosen = S.country === "ALL" ? "AU" : S.country;
  m.hidden = false;
  m.innerHTML = `<div class="modal-box small-box"><div class="card-head"><h2>Add a company to your study</h2><div class="right"><button class="icon-btn" id="closeModal" aria-label="Close">${icon("x")}</button></div></div>
    <div class="form"><label for="sC">Country</label><select id="sC">${S.countries.map((c) => `<option value="${esc(c.code)}" ${c.code === chosen ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
    <label for="sT">Code</label><input type="text" id="sT" placeholder="For example BHP" maxlength="8">
    <label for="sN">Company (optional)</label><input type="text" id="sN" placeholder="For example BHP Group">
    <span></span><div class="row"><button class="btn primary" id="sGo">Add</button></div></div></div>`;
  $("#closeModal").onclick = closeModal;
  $("#sT").focus();
  $("#sGo").onclick = async () => {
    try { const e = await post("/api/study", { country: $("#sC").value, ticker: $("#sT").value, company: $("#sN").value }); toast(`${e.ticker} added.`); closeModal(); go("companies", "list"); }
    catch (x) { toast(x.message); }
  };
}
// A company's purchases by programme, then year, then month, then each date. Totals add up the rows below them, per currency,
// and leave out purchases waiting for a programme document, which are listed but marked.
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
// opt.full adds the day's high and low; opt.latest opens only the latest programme and its latest year; opt.companies puts each company above its programmes.
function purchaseGroups(txs, progs, src, opt = {}) {
  const announced = Object.fromEntries((progs || []).map((p) => [p.prog_id, p.announced_date]));
  const by = (rs, key, up) => { const m = new Map(); rs.forEach((r) => { const k = key(r); if (!m.has(k)) m.set(k, []); m.get(k).push(r); }); return [...m.entries()].sort((a, b) => (up ? 1 : -1) * String(a[0]).localeCompare(String(b[0]))); };
  const sumLine = (rs) => {
    const counted = rs.filter((r) => !r.waiting), money = {};
    counted.forEach((r) => { if (r.value !== null) money[r.currency] = (money[r.currency] || 0) + r.value; });
    const days = new Set(counted.map((r) => r.trade_date)).size, unpriced = counted.filter((r) => r.value === null).length, waiting = rs.length - counted.length;
    return `<span class="small muted"> · ${int(days)} day${days === 1 ? "" : "s"} · </span><b>${boughtText(counted.reduce((t, r) => t + (r.shares || 0), 0), money)}</b> ${tag("Calculated", "Sum of the purchases below")}`
      + (unpriced ? ` <span class="pill warn">${int(unpriced)} without a value</span>` : "") + (waiting ? ` <span class="pill warn">${int(waiting)} waiting, not counted</span>` : "");
  };
  const rowsTable = (rs) => `<div class="twrap short"><table class="compact"><thead><tr><th>Date</th><th>Venue</th><th class="n">Shares</th><th class="n">Average</th>${opt.full ? `<th class="n">High</th><th class="n">Low</th>` : ""}<th class="n">Value</th><th>Broker</th><th></th></tr></thead><tbody>${rs.map((t) => `<tr><td>${esc(t.trade_date)}${t.date_working ? " " + tag("Calculated", t.date_working) : ""}${t.waiting ? ` <span class="pill warn">Waiting</span>` : ""}${handTag(t.hand_source)}</td><td>${esc(t.venue)}</td><td class="n">${int(t.shares)}${updTag((t.updated || {}).shares)}</td><td class="n">${t.price_avg === null ? "" : Number(t.price_avg).toFixed(4)} ${esc(t.price_unit)}${updTag((t.updated || {}).price_avg)}${(t.updated || {}).derived && !(t.updated || {}).price_avg ? " " + tag("Calculated", t.updated.derived) : ""}</td>${opt.full ? `<td class="n">${t.price_high ?? ""}${updTag((t.updated || {}).price_high)}</td><td class="n">${t.price_low ?? ""}${updTag((t.updated || {}).price_low)}</td>` : ""}<td class="n">${t.value === null ? "" : `${esc(t.currency)} ${amt(t.value)}`}${updTag((t.updated || {}).value)}</td><td>${esc(t.broker || "")}</td><td>${src(t.doc_id, `tx|${t.trade_date}|${t.venue}`, "source")} ${t.doc_id ? updButton({ country: t.country, ticker: t.ticker, programme: t.programme_announced || announced[t.prog_id] || "", target: "purchase", row: `${t.trade_date}|${t.venue || ""}|${t.price_unit || ""}` }) : ""}</td></tr>`).join("")}</tbody></table></div>`;
  const programmes = (rs) => by(rs, (t) => t.programme_announced || announced[t.prog_id] || "").map(([prog, prs], i) => `<details class="grp"${!opt.latest || i === 0 ? " open" : ""}><summary><b>${prog ? `Programme announced ${esc(prog)}` : "Programme not identified"}</b>${sumLine(prs)}</summary><div class="grp-in">
    ${by(prs, (t) => (t.trade_date || "").slice(0, 4)).map(([year, yrs], j) => `<details class="grp"${!opt.latest || j === 0 ? " open" : ""}><summary><b>${esc(year)} total</b>${sumLine(yrs)}</summary><div class="grp-in">
      ${by(yrs, (t) => (t.trade_date || "").slice(0, 7)).map(([month, mrs]) => `<details class="grp"><summary><b>${MONTH_NAMES[+month.slice(5, 7) - 1] || ""} ${esc(month.slice(0, 4))}</b>${sumLine(mrs)}</summary><div class="grp-in">${rowsTable(mrs.sort((a, b) => b.trade_date.localeCompare(a.trade_date)))}</div></details>`).join("")}
    </div></details>`).join("")}</div></details>`).join("");
  if (!opt.companies) return programmes(txs);
  return by(txs, (t) => `${t.ticker}|${t.country}`, true).map(([, crs]) => `<details class="grp"><summary><b>${esc(crs[0].ticker)}</b> ${esc(crs[0].company || "")} <span class="small muted">${esc(crs[0].country)}</span>${sumLine(crs)}</summary><div class="grp-in">${programmes(crs)}</div></details>`).join("");
}
function closeModal() { const m = $("#modal"); m.hidden = true; m.innerHTML = ""; }
async function openCompany(country, ticker) {
  openSheet(`<div class="sh-body"><p class="muted">Loading…</p></div>`);
  const c = await api("/api/company", { country, ticker, from: S.from, to: S.to });
  if (!c) return openSheet(`<div class="sh-body"><p>Not found.</p></div>`);
  const src = (doc, key, label) => doc ? `<button class="linkbtn" data-doc="${doc}" data-key="${esc(key || "")}">${esc(label || "show source")}</button>` : "";
  openSheet(`<div class="sh-head"><div class="acts"><button class="icon-btn" id="closeSheet" aria-label="Close">${icon("x")}</button></div>
      <div class="kicker">${esc(country)} · ${esc(c.ticker)}</div><div class="title">${esc(c.company)}</div><div class="muted">${esc(c.sector || "")}</div></div>
    <div class="sh-body">
      ${getNotices()}
      <div class="row-c left"><button class="btn sm" id="rereadCo">Re-read this company</button><label class="small"><input type="checkbox" id="rereadGaps"> Only filings with gaps</label>
        <span class="small muted">Reads its filings again from their links with the latest reading rules. Removed filings stay out.</span></div>
      <h3>Programmes</h3>
      ${c.waiting ? `<div class="note">${int(c.waiting)} purchase${c.waiting === 1 ? " is" : "s are"} waiting for a programme document and left out of the totals. See Quality > Waiting for programme.</div>` : ""}
      ${c.programmes.length ? c.programmes.map((p) => `<div class="code-card" style="margin-bottom:10px"><dl class="kv">
        <dt>Announced</dt><dd class="mono">${esc(p.announced_date || "not stated")}${handTag(p.hand_announced)} ${src(p.source_doc, "prog")} ${c.documents.find((d) => d.doc_id === p.source_doc)?.source_url ? removeButton(p.source_doc, "Remove this filing") : ""}</dd>
        <dt>Type</dt><dd>${esc(p.buyback_type || "–")}${updTag((p.updated || {}).buyback_type)}</dd><dt>Status</dt><dd>${statusText(p)}</dd>
        <dt>Runs</dt><dd class="mono">${periodRuns(p)}${handTag(p.hand_terms)}${updTag((p.updated || {}).start_date || (p.updated || {}).end_date)}${p.end_note ? `<div class="muted small">${esc(p.end_note)}</div>` : ""}</dd>
        ${p.document_needed ? `<dt>Programme document</dt><dd><span class="pill warn">Needed</span> <span class="small muted">Type, dates and size come from the announcement${p.announced_date ? ` dated ${esc(p.announced_date)}` : ""}.</span><div class="mt-s">${programmeDocForm(p.country, p.ticker)}</div></dd>` : ""}
        <dt>Announced size</dt><dd>${sizeText(p)}${handTag(p.hand_terms)}${updTag((p.updated || {}).max_shares || (p.updated || {}).max_value)}${p.max_pct && !p.max_shares && !p.max_value ? `<div class="muted small">Stated as a percentage only; the share count isn't given, so no number of shares is shown</div>` : ""}${p.size_note ? `<div class="muted small">${esc(p.size_note)}</div>` : ""}</dd>
        ${p.intended_shares ? `<dt>Intended</dt><dd>About ${int(p.intended_shares)} shares${handTag(p.hand_terms)}<div class="muted small">What the company expects to buy; not a limit</div></dd>` : ""}
        <dt>${isAllPeriod() ? "Bought so far" : "Bought in period"}</dt><dd><b>${boughtText(p.shares, p.amounts)}</b> ${tag(p.amount_basis, p.amount_working)} ${src(p.last_doc, p.last_key, "show latest source")}${p.amount_working ? `<div class="muted small">${esc(p.amount_working)}</div>` : ""}${p.hand_purchases ? `<div class="muted small">${int(p.hand_purchases)} of the purchases ${p.hand_purchases === 1 ? "was" : "were"} entered by hand</div>` : ""}${p.updated_count ? `<div class="muted small">${int(p.updated_count)} figure${p.updated_count === 1 ? "" : "s"} of this programme Updated Manually; see Add data > Add by hand</div>` : ""}</dd>
        <dt>Since it began</dt><dd>${money(p.programme_spent, p.programme_spent_currency)} ${p.used_pct !== null ? "· " + pc(p.used_pct) + " of announced " + tag("Calculated", "Spent since it began / announced size") : ""}</dd>
        <dt>Shares cancelled</dt><dd>${p.cancelled_shares === null ? "–" : `${int(p.cancelled_shares)} ${tag(p.cancelled_basis, p.cancelled_working)} ${p.cancelled_docs.map((d) => src(d, "", "source")).join(" ")}<div class="muted small">${esc(p.cancelled_working)}</div>`}</dd>
        <dt>Average price paid</dt><dd>${p.avg_price === null ? "–" : `${esc(p.avg_currency)} ${Number(p.avg_price).toFixed(4)} ${tag(p.avg_basis, p.avg_working)}<div class="muted small">${esc(p.avg_working)}</div>`}</dd>
        <dt>Broker</dt><dd>${esc(p.broker || "Not disclosed")}${updTag((p.updated || {}).broker)}</dd>
        <dt>Shares</dt><dd>${pill(p.treatment || "Not stated")}${handTag(p.hand_treatment)}${updTag((p.updated || {}).treatment)} ${p.treatment_doc ? src(p.treatment_doc, "prog", "source") : ""}</dd>
        <dt>Figures from</dt><dd>${pill(p.method)}</dd></dl>${periodsBlock(p)}<div class="row-c left"><button class="btn sm" data-activity="${p.prog_id}">View charts and daily activity</button>${p.announced_date ? updButton({ country: p.country, ticker: p.ticker, programme: p.announced_date, target: "programme" }, "Update a figure", "btn sm") : ""}</div>${p.note ? `<div class="note">${esc(p.note)}</div>` : ""}</div>`).join("") : `<p class="muted">No programme figures saved for this company.</p>`}
      <h3>By venue</h3>
      ${c.venues.length ? venueTable(c.venues, src) : `<p class="muted">No buying in this period.</p>`}
      <h3>Cessations (Appendix 3H)</h3>
      ${c.cessations.length ? `<div class="twrap short"><table class="compact"><thead><tr><th>Ceased on</th><th>Security</th><th class="n">Number</th><th>Reason</th><th>Programme</th><th></th></tr></thead><tbody>${c.cessations.map((e) => `<tr><td>${esc(e.ceased_on)}</td><td>${esc(e.security || "")}</td><td class="n">${int(e.shares)}</td><td class="wrap">${esc(e.reason)}</td><td>${esc(e.programme_label)}</td><td>${src(e.doc_id, `cess|${e.n}`)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">None read in this period.</p>`}
      <h3>Issues and transfers (Appendix 3G)</h3>
      ${c.issues && c.issues.length ? `<div class="twrap short"><table class="compact"><thead><tr><th>Issued on</th><th>Security</th><th class="n">Number</th><th>From</th><th>Provided by</th><th>What the company says</th><th></th></tr></thead><tbody>${c.issues.map((e) => `<tr><td>${esc(e.issued_on || "")}</td><td>${esc(e.security_code || "")} ${esc(e.security || "")}</td><td class="n">${int(e.shares)}</td><td>${esc(e.from_security || "")}</td><td>${e.provided_by ? esc(e.provided_by) : `<span class="muted small">Not stated</span>`}</td><td class="wrap small">${esc(e.other_info || "")}</td><td>${src(e.doc_id, "", "source")}</td></tr>`).join("")}</tbody></table></div><p class="small muted">Shares issued or transferred, for example when employee rights vest. Kept apart from the buy-back and never netted against it. A transfer of existing shares does not add to the shares on issue.</p>` : `<p class="muted">None read in this period.</p>`}
      <h3>Cancellations from saved notices</h3>
      ${c.cancellation.events.length ? `<div class="twrap short"><table class="compact"><thead><tr><th>Notice</th><th>Venue</th><th>Kind</th><th class="n">Shares</th><th>Basis</th><th></th></tr></thead><tbody>${c.cancellation.events.map((e) => `<tr><td>${esc(e.as_of)}</td><td>${esc(e.venue)}</td><td>${esc(e.kind)}</td><td class="n">${int(e.shares)}</td><td>${esc(e.basis)}</td><td>${src(e.doc_id, `cancel|${e.as_of}|${e.venue}|${e.kind}`, "source")}</td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">No cancellation counts in the saved notices.</p>`}
      <h3>Purchases</h3>
      ${c.transactions.length ? purchaseGroups(c.transactions, c.programmes, src) : `<p class="muted">No daily purchases saved.</p>`}
      <h3>Notices</h3>
      ${c.documents.length ? c.documents.map((d) => `<div class="tl"><span class="when">${esc(d.doc_date || "no date")}</span><span>${src(d.doc_id, "", d.file_name)} <span class="muted small">${esc(d.appendix || "")} · ${esc(d.filing_type || d.doc_type || "")}</span> ${sourceLink(d.source_url, "link ↗")} ${d.source_url ? moveButton(d.doc_id, d.ticker) + " " + removeButton(d.doc_id) : ""}</span>${pill(d.status)}</div>`).join("") : `<p class="muted">None saved yet.</p>`}
    </div>`);
  $$("#sheet [data-doc]").forEach((b) => (b.onclick = () => openDoc(+b.dataset.doc, b.dataset.key)));
  $("#goUpload").onclick = () => { closeSheet(); go("collect", "import"); };
  $$("#sheet [data-activity]").forEach((b) => (b.onclick = () => { S.activityProg = +b.dataset.activity; closeSheet(); go("companies", "activity"); }));
  bindPeriods("#sheet");
  bindProgrammeDocForms();
  $("#rereadCo").onclick = async () => {
    try { const r = await post("/api/filings/reread", { country, ticker: c.ticker, only_gaps: $("#rereadGaps").checked }); toast(`Reading ${int(r.total)} filing${r.total === 1 ? "" : "s"} again. Progress is on Add data.`); closeSheet(); go("collect", "import"); }
    catch (x) { toast(x.message); }
  };
}

// ---------- announcement viewer: opens at the page of a figure, with its source text highlighted ----------
const strip = (s) => String(s || "").replace(/\s+/g, "");
// Find a figure in text, ignoring spacing. If it appears several times, prefer the place just after its label.
function findRange(full, ev) {
  const map = []; let s = "";
  for (let i = 0; i < full.length; i++) if (!/\s/.test(full[i])) { map.push(i); s += full[i]; }
  const t = strip(ev.text); if (!t) return null;
  // A whole value only: "1 December" must not match inside "11 December", nor "500,000" inside "1,500,000".
  const whole = (i) => { const a = full[map[i] - 1] ?? " ", b = full[map[i + t.length - 1] + 1] ?? " "; return !(/\d/.test(t[0]) && /[\d.,]/.test(a)) && !(/\d/.test(t[t.length - 1]) && /\d/.test(b)); };
  const hits = []; for (let i = s.indexOf(t); i >= 0; i = s.indexOf(t, i + 1)) if (whole(i)) hits.push(i);
  if (!hits.length) return null;
  const ctx = strip(ev.context).slice(-28);
  const anchor = ctx ? s.lastIndexOf(ctx, s.length) : -1;
  const best = anchor >= 0 ? (hits.find((h) => h >= anchor) ?? hits[hits.length - 1]) : hits[0];
  return [map[best], map[best + t.length - 1] + 1];
}
function markHtml(text, ranges) {
  // ranges: [start, end, strong]; overlapping ranges merge, and a strong one wins.
  const sorted = [...ranges].sort((a, b) => a[0] - b[0]);
  let out = "", at = 0;
  for (const [a, b, strong] of sorted) { if (a < at) continue; out += esc(text.slice(at, a)) + `<mark class="${strong ? "strong" : ""}">${esc(text.slice(a, b))}</mark>`; at = b; }
  return out + esc(text.slice(at));
}
async function openDoc(id, key) {
  openSheet(`<div class="sh-body"><p class="muted">Loading the notice…</p></div>`, true);
  const d = await api("/api/document", { id, ...(key ? { key } : {}) });
  if (!d) return openSheet(`<div class="sh-body"><p>Not found.</p></div>`);
  if (d.form === "manual") return openHandDoc(d);
  const V = { d, page: d.open_page || 1, focus: new Set((d.focus || []).map((e) => e.ev_id)), pdf: null, total: d.pages.length || 1 };
  const figureList = d.evidence.length ? `<div class="figs">${d.evidence.map((e) => `<button class="fig ${V.focus.has(e.ev_id) ? "on" : ""}" data-ev="${e.ev_id}"><span class="muted small">${esc(fieldName[e.field] || e.field)}${e.key.startsWith("tx|") ? " · " + esc(e.key.split("|")[1]) : ""}${e.key.startsWith("venue|") ? " · " + esc(e.key.split("|")[1]) : ""}${e.key.startsWith("cancel|") ? " · " + esc(e.key.split("|")[2]) + " · " + esc(e.key.split("|")[3]) : ""}</span><b class="mono">${esc(e.text)}</b><span class="muted small">page ${e.page}</span></button>`).join("")}</div>` : `<p class="muted small">No figures were read from this file.</p>`;
  openSheet(`<div class="sh-head"><div class="acts">${d.source_url ? moveButton(d.doc_id, d.ticker) + removeButton(d.doc_id, "Remove filing") : ""}${d.source_url ? `<span class="btn sm">${sourceLink(d.source_url)}</span>` : `<a class="btn sm" href="/api/doc_file?id=${d.doc_id}" target="_blank" rel="noopener">${icon("download")} Original</a>`}<button class="icon-btn" id="closeSheet" aria-label="Close">${icon("x")}</button></div>
      <div class="kicker">${esc(d.country)} · ${esc(d.ticker || "company not set")} · ${esc(d.doc_date || "no date")} · ${esc(d.appendix || "")} · ${esc(d.filing_type || d.doc_type || "")}</div><div class="title viewer-title">${esc(d.file_name)}</div>${pill(d.status)}
      ${d.reviews.filter((r) => r.status === "OPEN").map((r) => `<div class="note">${esc(r.detail)}</div>`).join("")}</div>
    <div class="viewer"><aside class="viewer-side"><h3>Figures read</h3>${figureList}</aside>
      <div class="viewer-main"><div class="pagebar"><button class="btn sm" id="pgPrev">‹ Prev</button><span id="pgLabel" class="mono small"></span><button class="btn sm" id="pgNext">Next ›</button><span id="hlNote" class="muted small"></span></div><div id="docPage"></div></div></div>`, true);
  const draw = async () => {
    $("#pgLabel").textContent = `Page ${V.page} of ${V.total}`;
    $("#pgPrev").disabled = V.page <= 1; $("#pgNext").disabled = V.page >= V.total;
    const here = d.evidence.filter((e) => e.page === V.page);
    const useFocus = V.focus.size > 0;
    const wanted = here.map((e) => ({ ...e, strong: useFocus ? V.focus.has(e.ev_id) : true }));
    let found = 0;
    if (d.is_pdf && window.pdfjsLib) {
      try { found = await drawPdf(V, wanted); } catch (e) { drawText(V, wanted); $("#hlNote").textContent = "The page image could not be drawn, so its text is shown instead."; return; }
    } else found = drawText(V, wanted);
    const missed = wanted.filter((w) => w.strong).length - found;
    $("#hlNote").textContent = missed > 0 ? `${missed} figure${missed === 1 ? "" : "s"} could not be highlighted here; see the list on the left.` : "";
    const m = $("#docPage mark.strong") || $("#docPage mark"); if (m) m.scrollIntoView({ block: "center" });
  };
  $("#pgPrev").onclick = () => { V.page--; draw(); };
  $("#pgNext").onclick = () => { V.page++; draw(); };
  $$("#sheet .fig").forEach((b) => (b.onclick = () => { const e = d.evidence.find((x) => x.ev_id === +b.dataset.ev); V.focus = new Set([e.ev_id]); V.page = e.page; $$("#sheet .fig").forEach((x) => x.classList.toggle("on", x === b)); draw(); }));
  if (d.is_pdf && window.pdfjsLib) {
    try { V.pdf = await pdfjsLib.getDocument(`/api/doc_file?id=${d.doc_id}`).promise; V.total = V.pdf.numPages; } catch (e) { V.pdf = null; d.is_pdf = false; if (!d.pages.length) $("#docPage").innerHTML = `<p class="muted">This PDF could not be opened here. Use Original above.</p>`; }
  }
  if (d.source_url) {
    d.is_pdf = false;
    $(".pagebar").hidden = true;
    $("#docPage").innerHTML = `<div class="note">This filing isn't stored here, so it can't be shown with highlights. The figures read from it are on the left, each with its page number. ${sourceLink(d.source_url)}</div>`;
    return;
  }
  if (d.is_pdf || d.pages.length) draw();
  else { $("#docPage").innerHTML = `<p class="muted">This file has no text to show here. Use Original above to open it.</p>`; $("#pgLabel").textContent = ""; }
}
function drawText(V, wanted) {
  const text = (V.d.pages.find((p) => p.page === V.page) || {}).text || "";
  const ranges = []; let found = 0;
  wanted.forEach((w) => { const r = findRange(text, w); if (r) { ranges.push([r[0], r[1], w.strong]); if (w.strong) found++; } });
  $("#docPage").innerHTML = text ? `<pre class="doctext">${markHtml(text, ranges)}</pre>` : `<p class="muted">This page has no readable text. It may be a scan, which needs text recognition (OCR) before it can be highlighted.</p>`;
  return found;
}
async function drawPdf(V, wanted) {
  const page = await V.pdf.getPage(V.page);
  const box = $("#docPage"), base = page.getViewport({ scale: 1 });
  const scale = Math.min(2, Math.max(0.6, (box.clientWidth - 4) / base.width)), vp = page.getViewport({ scale });
  box.innerHTML = `<div class="pdfpage" style="width:${vp.width}px;height:${vp.height}px;--scale-factor:${scale}"><canvas></canvas><div class="textLayer"></div></div>`;
  const cv = $("canvas", box), ratio = window.devicePixelRatio || 1;
  cv.width = vp.width * ratio; cv.height = vp.height * ratio; cv.style.width = vp.width + "px"; cv.style.height = vp.height + "px";
  await page.render({ canvasContext: cv.getContext("2d"), viewport: vp, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null }).promise;
  const layer = $(".textLayer", box), content = await page.getTextContent();
  const task = pdfjsLib.renderTextLayer({ textContentSource: content, container: layer, viewport: vp, textDivs: [] });
  await task.promise;
  const spans = $$("span", layer).filter((s) => !s.classList.contains("markedContent"));
  let full = ""; const starts = spans.map((s) => { const at = full.length; full += s.textContent + " "; return at; });
  const perSpan = new Map(); let found = 0;
  wanted.forEach((w) => {
    const r = findRange(full, w); if (!r) return;
    if (w.strong) found++;
    spans.forEach((s, i) => { const a = starts[i], b = a + s.textContent.length; const x = Math.max(a, r[0]), y = Math.min(b, r[1]);
      if (x < y) { if (!perSpan.has(i)) perSpan.set(i, []); perSpan.get(i).push([x - a, y - a, w.strong]); } });
  });
  perSpan.forEach((ranges, i) => { spans[i].innerHTML = markHtml(spans[i].textContent, ranges); });
  return found;
}

// ---------- period and country ----------
const isAllPeriod = () => S.from === S.periods.default.from && S.to === S.periods.default.to;
async function loadTop() {
  const [cs, p] = await Promise.all([api("/api/countries"), api("/api/periods")]);
  S.countries = cs; S.periods = p;
  $("#country").innerHTML = `<option value="ALL">All markets</option>` + cs.map((c) => `<option value="${esc(c.code)}">${esc(c.flag || "")} ${esc(c.name)} · ${esc(c.exchange)}</option>`).join("") + `<option value="__add">+ Add a country…</option>`;
  $("#country").value = S.country;
  $("#month").innerHTML = `<option value="all">All programmes</option>` + p.years.map((y) => `<option value="${y}">Calendar ${y}</option>`).join("") + `<option value="custom">Custom range…</option>`;
  if (!S.from) { S.from = p.default.from; S.to = p.default.to; }
  syncPeriod();
  await loadTickers();
  showReadOnly(p.read_only);
}
// The ticker selector: every company of the chosen market with a filing or programme saved, or All tickers.
async function loadTickers() {
  try { S.tickers = await (await fetch("/api/tickers?" + qs({ country: S.country }))).json(); } catch { S.tickers = []; }
  if (!Array.isArray(S.tickers)) S.tickers = [];
  if (S.ticker && !S.tickers.some((t) => t.ticker === S.ticker && t.country === S.tickerCountry)) { S.ticker = ""; S.tickerCountry = ""; }
  $("#ticker").innerHTML = `<option value="">All tickers</option>` + S.tickers.map((t) => `<option value="${esc(t.country)}|${esc(t.ticker)}">${esc(t.ticker)}${t.company && t.company !== t.ticker ? " · " + esc(t.company) : ""}${S.country === "ALL" ? ` (${esc(t.country)})` : ""}</option>`).join("");
  $("#ticker").value = S.ticker ? `${S.tickerCountry}|${S.ticker}` : "";
}
function syncPeriod() {
  const sel = $("#month"), y = S.from.slice(0, 4);
  const isAll = isAllPeriod();
  const isYear = S.from === `${y}-01-01` && S.to === `${y}-12-31` && [...sel.options].some((o) => o.value === y);
  sel.value = isAll ? "all" : isYear ? y : "custom";
  $("#customDates").hidden = isAll || isYear;
  $("#pFrom").value = isAll ? "" : S.from; $("#pTo").value = isAll ? "" : S.to;
}
const countryName = () => S.country === "ALL" ? "All markets" : (S.countries.find((c) => c.code === S.country) || {}).name;

// ---------- pages ----------
const SECTIONS = {
  home: {}, companies: { subs: [["programmes", "Programmes"], ["list", "Companies"], ["purchases", "Purchases"], ["activity", "Daily activity"], ["venues", "By venue"], ["cancellations", "Cancellations"], ["cessations", "Cessations"]] }, announcements: {},
  analysis: { subs: [["market", "Markets"], ["pace", "Pace"], ["sectors", "Sectors"], ["price", "Purchase prices"], ["reaction", "Announcement reaction"]] },
  quality: {}, tracker: { subs: [["tkOverview", "Overview"], ["tkProgrammes", "Programmes"], ["tkNotices", "Notices"], ["tkChecks", "Cross-check"], ["tkExcluded", "Excluded"]] }, collect: { subs: [["import", "Add filings"], ["hand", "Add by hand"], ["countries", "Countries"], ["reset", "Reset"]] }, library: { subs: [["Research_Report.md", "Research report"], ["Vendor_Study.md", "Vendor study"], ["README_app.md", "Guide"], ["Data_Dictionary.md", "Data dictionary"], ["Filing_Types.md", "Filing types"]] },
};
const head = (title, lead = "", right = "") => `<div class="page-head"><div><h1>${title}</h1>${lead ? `<p class="lead">${lead}</p>` : ""}</div>${right ? `<div class="right">${right}</div>` : ""}</div>`;
const periodText = () => isAllPeriod() ? "All programmes" : (S.from.slice(5) === "01-01" && S.to.slice(0, 4) === S.from.slice(0, 4) && S.to.slice(5) === "12-31") ? `Calendar ${S.from.slice(0, 4)}` : periodLabel(S.from, S.to);
const companyColumns = [{ key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "state", label: "State", html: pill },
  { key: "order_value", label: "Bought back", num: true, html: (v, r) => Object.keys(r.amounts).length ? amounts(r.amounts) : "–" }, { key: "amount_basis", label: "Basis", html: (v, r) => tag(v, r.amount_working) }, { key: "shares", label: "Shares", num: true, fmt: count }, { key: "max_value", label: "Announced", num: true, html: (v, r) => v ? money(v, r.max_currency) : "" }, { key: "used_pct", label: "Used", num: true, fmt: (v) => v === null ? "" : pc(v) },
  { key: "documents", label: "Notices", num: true }, { key: "last_notice", label: "Latest notice" }, { key: "sector", label: "Sector", clip: true }];
const withMarket = (cols) => S.country === "ALL" ? [{ key: "country", label: "Market" }, ...cols] : cols;

const PAGES = {
  async home() {
    const s = await api("/api/summary", P());
    const nothing = s.markets.every((m) => !m.documents);
    const reviews = s.markets.reduce((a, m) => a + m.open_reviews, 0);
    const charts = s.markets.flatMap((m) => [...new Set([...Object.keys(m.undated), ...Object.keys(m.monthly_by_currency)])].map((currency) => ({ name: m.name, currency,
      rows: [...(m.undated[currency] ? [{ value: m.undated[currency], label: "No month: a notice's first running total, covering the programme up to then", short: "No month" }] : []), ...(m.monthly_by_currency[currency] || []).map((x) => ({ value: x.value, label: monthName(x.month), short: monthShort(x.month) }))] })));
    const tops = Object.entries(s.top.reduce((g, r) => ((g[r.currency] = g[r.currency] || []).push(r), g), {}));
    view().innerHTML = head(`${esc(countryName())} · ${esc(periodText())}`, "Each programme's buying from the notices you have saved, in the currency each notice uses. Hover over Reported or Calculated to see where a figure comes from.") +
      (nothing ? `<div class="banner"><div class="grow"><b>No notices saved yet.</b> Paste a hyperlink or read an Excel list on Add data. Each figure read from a notice will link back to its source.</div><button class="btn primary" id="toCollect">${icon("play")} Add your first notices</button></div>` : "") +
      (reviews ? `<div class="banner warn"><div class="grow"><b>${int(reviews)} item${reviews === 1 ? "" : "s"} to review.</b> These notices could not be read with confidence.</div><button class="btn" id="toQuality">${icon("check")} Open Quality</button></div>` : "") +
      `<div class="grid g-kpi">${s.markets.map((m) => `<div class="card kpi hero click-card" data-c="${esc(m.code)}"><div class="k">${esc(m.flag || "")} ${esc(m.name)} · ${esc(m.exchange)}</div><div class="v">${amounts(m.amounts, m.currency)}</div><div class="s">${Object.values(m.provenance).map((x) => tag(x[0], x[1])).join(" ")}</div><div class="s">${count(m.shares)} shares · ${int(m.active_companies)} of ${int(m.members)} studied companies with buying saved</div>${m.partial ? `<div class="s warn-text">${int(m.partial)} with partial coverage</div>` : ""}<div class="meter" role="img" aria-label="${int(m.active_companies)} of ${int(m.members)} studied companies"><i style="width:${m.members ? 100 * m.active_companies / m.members : 0}%"></i></div></div>`).join("")}</div>
      <div class="grid g-2 mt">${charts.map((c, i) => `<div class="card"><div class="card-head"><h2>${esc(c.name)}: amount by month</h2><span class="right muted small">${esc(c.currency)}, as reported</span></div><div id="cM${i}"></div><div class="legend-note">Calculated. "No month" is a first running total, which covers the programme up to then, so its buying can't be placed in a month. Buying between two saved notices shows in the month of the later notice.</div></div>`).join("")}
        ${tops.map(([cur], i) => `<div class="card"><div class="card-head"><h2>Largest buyers</h2><span class="right muted small">${esc(cur)}, as reported</span></div><div id="cTop${i}"></div></div>`).join("") || `<div class="card"><div class="card-head"><h2>Largest buyers</h2></div><p class="muted">Nothing in this period yet.</p></div>`}</div>`;
    charts.forEach((c, i) => columnChart($(`#cM${i}`), c.rows, c.currency));
    tops.forEach(([cur, list], i) => barList($(`#cTop${i}`), list.slice(0, 10).map((r) => ({ label: !r.company || r.company === r.ticker ? r.ticker : `${r.ticker} ${r.company}`, value: r.value, text: money(r.value, cur), r })), (x) => openCompany(x.r.country, x.r.ticker)));
    if ($("#toCollect")) $("#toCollect").onclick = () => go("collect");
    if ($("#toQuality")) $("#toQuality").onclick = () => go("quality");
    $$(".click-card").forEach((c) => (c.onclick = () => { S.country = c.dataset.c; $("#country").value = S.country; go("companies"); }));
    return;
  },
  async list() {
    const rows = await api("/api/companies", P());
    view().innerHTML = head("Companies", "The companies in your study, plus any with a saved notice. Click a row for its programme, purchases and notices. Sectors come from Wikipedia lists, not from notices.", `<button class="btn primary" id="addCo">Add company</button>`) + `<div id="t"></div>`;
    $("#addCo").onclick = openAddCompany;
    table($("#t"), { rows, csv: `companies_${S.country}_${S.from}_${S.to}.csv`, sort: "order_value", dir: -1, pageSize: S.mode === "analyst" ? 200 : 50, onRow: (r) => openCompany(r.country, r.ticker),
      filters: [{ key: "state", label: "State", auto: true }, { key: "sector", label: "Sector", auto: true }, ...(S.country === "ALL" ? [{ key: "country", label: "Market", auto: true }] : [])],
      csvColumns: ["country", "ticker", "company", "sector", "state", "amounts_text", "amount_basis", "amount_working", "shares", "max_value", "max_currency", "used_pct", "documents", "last_notice", "note"], columns: withMarket(companyColumns) });
  },
  async programmes() {
    if (S.ticker) return programmeCards();
    const rows = await api("/api/programmes", P());
    view().innerHTML = head("Programmes", isAllPeriod() ? "Each announced buyback from start to latest notice, whatever year it ran in. Click a row for its purchases and notices." : "Each announced buyback, what was bought in this period and how much of its announced size has been used.", `<button class="btn primary" id="addCo">Add company</button>`) + `<div id="t"></div>`;
    $("#addCo").onclick = openAddCompany;
    table($("#t"), { rows, sort: "order_value", dir: -1, csv: `programmes_${S.country}_${S.from}_${S.to}.csv`, onRow: (r) => openCompany(r.country, r.ticker), filters: [{ key: "status", label: "Status", auto: true }, { key: "method", label: "Figures from", auto: true }],
      csvColumns: ["country", "ticker", "company", "announced_date", "buyback_type", "start_date", "end_date", "max_value", "max_currency", "max_shares", "amounts_text", "amount_basis", "amount_working", "source_url", "shares", "programme_spent", "programme_spent_currency", "used_pct", "cancelled_shares", "cancelled_working", "avg_price", "avg_currency", "avg_working", "method", "status", "complete", "note"],
      columns: withMarket([{ key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "announced_date", label: "Announced" }, { key: "start_date", label: "Starts" }, { key: "end_date", label: "Ends" }, { key: "status", label: "Status", html: pill }, { key: "max_value", label: "Size", num: true, html: (v, r) => v ? money(v, r.max_currency) : r.max_shares ? count(r.max_shares) + " shares" : r.max_pct ? `${r.max_pct}% of shares` : "" }, { key: "order_value", label: isAllPeriod() ? "Bought so far" : "In period", num: true, html: (v, r) => Object.keys(r.amounts).length ? amounts(r.amounts) : "–" }, { key: "amount_basis", label: "Basis", html: (v, r) => tag(v, r.amount_working) }, { key: "shares", label: "Shares", num: true, fmt: count }, { key: "cancelled_shares", label: "Shares cancelled", num: true, html: (v, r) => v === null ? "" : `${int(v)} ${tag(r.cancelled_basis, r.cancelled_working)}` }, { key: "avg_price", label: "Average price paid", num: true, html: (v, r) => v === null ? "" : `${esc(r.avg_currency)} ${Number(v).toFixed(4)} ${tag(r.avg_basis, r.avg_working)}` }, { key: "used_pct", label: "Used", num: true, fmt: (v) => v === null ? "" : pc(v) }, { key: "last_date", label: "Latest figure" }, { key: "source_url", label: "Link", html: (v) => sourceLink(v) }, { key: "method", label: "Figures from", html: pill }, { key: "complete", label: "Coverage", html: (v, r) => r.shares ? (v ? pill("Full") : `<span class="pill warn" title="${esc(r.note)}">Partial</span>`) : "" }]) });
  },
  async purchases() {
    const rows = await api("/api/transactions", P());
    rows.forEach((r) => { r.year = (r.trade_date || "").slice(0, 4); r.month = MONTH_NAMES[+(r.trade_date || "").slice(5, 7) - 1] || ""; });
    const flat = S.purchView === "flat", csvName = `purchases_${S.country}_${S.from}_${S.to}.csv`;
    const csvCols = ["country", "ticker", "company", "programme_announced", "year", "month", "trade_date", "venue", "shares", "price_avg", "price_high", "price_low", "price_unit", "value", "currency", "value_origin", "waiting"];
    const pick = `<div class="seg" role="tablist" aria-label="Purchases view"><button id="pvGroup" class="${flat ? "" : "on"}">Grouped</button><button id="pvFlat" class="${flat ? "on" : ""}">Flat list</button></div>`;
    view().innerHTML = head("Purchases", flat ? "Each dated purchase in a saved notice. Click a row to see it highlighted in the notice." : `Each dated purchase in a saved notice, by ${S.ticker ? "" : "company, then "}programme, year, month and date. Each total adds up the rows under it, per currency.`, pick)
      + (flat ? `<div id="t"></div>` : rows.length ? `<div class="row-c left"><button class="btn sm" id="pvCsv">${icon("download")} CSV</button><button class="btn sm" id="pvOpen">Open all</button><button class="btn sm" id="pvShut">Close all</button><span class="small muted">${int(rows.length)} purchase${rows.length === 1 ? "" : "s"}. Click a line to open or close it.</span></div><div id="pg">${purchaseGroups(rows, [], (doc, key, label) => doc ? `<button class="linkbtn" data-doc="${doc}" data-key="${esc(key || "")}">${esc(label || "source")}</button>` : "", { full: true, latest: true, companies: !S.ticker })}</div>` : `<p class="muted">No purchases saved for this period.</p>`);
    $("#pvGroup").onclick = () => { S.purchView = "grouped"; PAGES.purchases(); };
    $("#pvFlat").onclick = () => { S.purchView = "flat"; PAGES.purchases(); };
    if (!flat) {
      if (!rows.length) return;
      $$("#pg [data-doc]").forEach((b) => (b.onclick = () => openDoc(+b.dataset.doc, b.dataset.key)));
      $("#pvCsv").onclick = () => download(csvName, csvOf(rows, csvCols));
      $("#pvOpen").onclick = () => $$("#pg details").forEach((d) => (d.open = true));
      $("#pvShut").onclick = () => $$("#pg details").forEach((d) => (d.open = false));
      return;
    }
    table($("#t"), { rows, sort: "trade_date", dir: -1, pageSize: 100, csv: csvName, csvColumns: csvCols, onRow: (r) => openDoc(r.doc_id, `tx|${r.trade_date}|${r.venue}`), filters: [{ key: "ticker", label: "Code", auto: true }, { key: "currency", label: "Currency", auto: true }],
      columns: withMarket([{ key: "trade_date", label: "Date" }, { key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "venue", label: "Venue" }, { key: "shares", label: "Shares", num: true, fmt: int }, { key: "price_avg", label: "Average", num: true, fmt: (v) => v === null ? "" : Number(v).toFixed(4) }, { key: "price_high", label: "High", num: true }, { key: "price_low", label: "Low", num: true }, { key: "price_unit", label: "Unit" }, { key: "value", label: "Value", num: true, html: (v, r) => moneyFull(v, r.currency) }, { key: "value_origin", label: "Value basis", html: (v, r) => r.value === null ? "" : v === "reported" ? tag("Reported", "The amount in the notice") : v === "hand" ? tag("Entered by hand", `Source: ${r.hand_source || ""}`) : v === "updated" ? tag(UPD, (r.updated || {}).value || "") : v === "hand_product" ? tag("Calculated", "Shares x average price, both entered by hand") : v === "entered" ? tag("Calculated", "Entered by hand") : tag("Calculated", "Shares x average price") }]) });
  },
  async activity() {
    const all = (await api("/api/programmes", { country: S.country, ...T() })).filter((p) => p.shares);
    if (!all.length) { view().innerHTML = head("Daily activity") + `<div class="banner"><div class="grow">No programmes with buying are saved for this market yet.</div></div>`; return; }
    if (!all.some((p) => p.prog_id === S.activityProg)) S.activityProg = [...all].sort((a, b) => (b.announced_date || "").localeCompare(a.announced_date || ""))[0].prog_id;
    const a = await api("/api/activity", { prog: S.activityProg }), p = a.programme, cur = a.currency, t = a.target, daily = a.daily;
    const units = [...new Set(daily.filter((r) => r.price_avg !== null).map((r) => `${r.venue_label}|${r.price_unit}`))];
    const unitFmt = (u) => (v) => u === "GBp" ? `${Number(v).toFixed(2)}p` : `${SYM[u] ?? u + " "}${Number(v).toFixed(v < 10 ? 4 : 2)}`;
    const held = new Set(daily.map((r) => r.trade_date)).size;
    view().innerHTML = head("Daily activity", "Each programme from its start to the latest notice saved. Figures come from the filings, in the currency they report.",
      `<select id="actProg" aria-label="Programme">${all.map((x) => `<option value="${x.prog_id}" ${x.prog_id === S.activityProg ? "selected" : ""}>${esc(x.ticker)} · ${esc(x.company || "")} · announced ${esc(x.announced_date || "not stated")}</option>`).join("")}</select>`) +
      `${held < 3 ? `<div class="note">${held ? `Only ${int(held)} purchase day${held === 1 ? " is" : "s are"} saved for this programme` : "No daily notices are saved for this programme"}, so the daily charts are thin. Add every daily notice to your list for a full history.</div>` : ""}
      <div class="grid g-2 mt">
        <div class="card"><div class="card-head"><h2>${t && t.kind === "shares" ? "Cumulative shares vs programme cap" : "Cumulative consideration paid vs programme target"}</h2><span class="right muted small">${t && t.kind === "shares" ? "shares" : esc(cur || "")}</span></div><div id="cPaid"></div>
          <div class="legend-note">Dots are figures from notices; the lines between them only join saved notices.${t && !t.comparable ? ` Target ${esc(money(t.value, t.currency))} isn't drawn, because spending is in ${esc(cur)} and amounts aren't converted.` : ""}${!t ? " No programme size is saved, so there's no target line." : ""}</div></div>
        <div class="card"><div class="card-head"><h2>Daily shares bought back</h2><span class="right muted small">shares</span></div><div id="cShares"></div><div class="legend-note">Only dates with a saved notice appear.</div></div>
        ${units.length ? units.map((u, i) => `<div class="card"><div class="card-head"><h2>Daily average price paid${units.length > 1 ? `: ${esc(u.split("|")[0])}` : ""}</h2><span class="right muted small">${esc(u.split("|")[1])}</span></div><div id="cPrice${i}"></div></div>`).join("") : `<div class="card"><div class="card-head"><h2>Daily average price paid</h2></div><p class="muted small">No daily prices saved for this programme.</p></div>`}
      </div><h2 class="mt">Date-wise daily buy-back activity</h2><div id="t"></div>`;
    $("#actProg").onchange = (e) => { S.activityProg = +e.target.value; go("companies", "activity"); };
    if (t && t.kind === "shares") trendChart($("#cPaid"), a.shares, { fmt: count, target: { value: t.value }, label: "Cumulative shares against the programme cap" });
    else trendChart($("#cPaid"), a.paid, { fmt: (v) => money(v, cur), target: t && t.comparable ? { value: t.value } : null, label: "Cumulative consideration paid against the programme target" });
    dailyBars($("#cShares"), daily);
    units.forEach((u, i) => { const [venue, unit] = u.split("|"); trendChart($(`#cPrice${i}`), daily.filter((r) => r.venue_label === venue && r.price_unit === unit && r.price_avg !== null).map((r) => ({ date: r.trade_date, value: r.price_avg, basis: r.avg_basis })), { fmt: unitFmt(unit), zero: false, label: `Daily average price paid, ${venue}` }); });
    table($("#t"), { rows: [...daily].reverse(), search: false, pageSize: 100, csv: `daily_activity_${p.ticker}_${p.announced_date}.csv`, onRow: (r) => r.doc_id && openDoc(r.doc_id, `tx|${r.trade_date}|${r.venue}`), filters: [{ key: "venue_label", label: "Venue", auto: true }],
      csvColumns: ["trade_date", "filing_date", "venue_label", "shares", "price_high", "price_low", "price_avg", "avg_basis", "price_unit", "value", "currency", "value_basis", "value_working", "security", "also_in", "cancelled", "cancelled_basis", "cancelled_working", "cum_shares", "cum_value", "cum_currency", "cum_basis", "source_url"],
      columns: [{ key: "trade_date", label: "Purchase date", html: (v, r) => esc(v) + (r.date_working ? " " + tag("Calculated", r.date_working) : "") }, { key: "filing_date", label: "Filing date" }, { key: "venue_label", label: "Venue", html: (v, r) => (r.security ? `<span class="small muted">${esc(r.security)}</span> ` : "") + (r.also_in ? `${esc(v)} <span class="tag calc" title="${esc(r.also_in)}">Also in ${esc(String(r.also_in).split(":")[0])} filings</span>` : esc(v)) }, { key: "shares", label: "Shares", num: true, html: (v, r) => `${int(v)}${updTag((r.updated || {}).shares)}` },
        { key: "price_high", label: "High", num: true, html: (v, r) => v === null ? "" : Number(v).toFixed(4) + updTag((r.updated || {}).price_high) }, { key: "price_low", label: "Low", num: true, html: (v, r) => v === null ? "" : Number(v).toFixed(4) + updTag((r.updated || {}).price_low) },
        { key: "price_avg", label: "Average", num: true, html: (v, r) => v === null ? "" : `${Number(v).toFixed(4)} ${esc(r.price_unit)} ${(r.updated || {}).price_avg ? tag(UPD, r.updated.price_avg) : tag(r.avg_basis, (r.updated || {}).derived || (r.avg_basis === "Calculated" ? "Amount paid / shares" : "As the notice states"))}` },
        { key: "value", label: "Amount paid", num: true, html: (v, r) => v === null ? "" : `${moneyFull(v, r.currency)} ${tag(r.value_basis, r.value_working || (r.value_basis === "Calculated" ? "Shares x average price" : "As the notice states"))}` },
        { key: "cancelled", label: "Cancelled", num: true, html: (v, r) => v === null || v === undefined ? "" : `${int(v)} ${tag(r.cancelled_basis, r.cancelled_working)}` },
        { key: "cum_shares", label: "Total shares so far", num: true, html: (v, r) => v === null ? "" : int(v) + (r.cum_basis === UPD ? " " + tag(UPD, r.cum_working) : "") },
        { key: "cum_value", label: "Total paid so far", num: true, html: (v, r) => v === null ? "" : `${money(v, r.cum_currency)} ${tag(r.cum_basis, r.cum_working || (r.cum_basis === "Calculated" ? "Before that day + on the day" : "As the notice states"))}` },
        { key: "broker", label: "Broker", html: (v, r) => v ? `${esc(v)} <span class="small muted" title="${esc(r.broker_text || "")}">${esc(r.broker_role || "")}</span>` : `<span class="small muted">Not disclosed</span>` },
        { key: "source_url", label: "Source", html: (v, r) => v ? sourceLink(v) : r.hand_source ? tag("Entered by hand", `Source: ${r.hand_source}`) : `<span class="muted small">Typed entry</span>` },
        { key: "tx_id", label: "", html: (v, r) => r.doc_id ? updButton({ country: p.country, ticker: p.ticker, programme: p.announced_date, target: "purchase", row: `${r.trade_date}|${r.venue || ""}|${r.price_unit || ""}` }) + (r.cum_shares !== null && r.cum_shares !== undefined ? " · " + updButton({ country: p.country, ticker: p.ticker, programme: p.announced_date, target: "total", row: r.trade_date }, "update total") : "") : "" }] });
  },
  async venues() {
    const rows = await api("/api/venues", P());
    view().innerHTML = head("By venue", "Where each programme's shares were bought. A closing notice gives complete venue totals. Otherwise only saved days can be split, and the rest shows as Not split. Amounts stay in each venue's own currency.") + `<div id="t"></div>`;
    table($("#t"), { rows, sort: "shares", dir: -1, pageSize: 100, csv: `by_venue_${S.country}_${S.from}_${S.to}.csv`, onRow: (r) => r.doc_id ? openDoc(r.doc_id, r.key) : toast("No saved notice covers these shares yet."), filters: [{ key: "ticker", label: "Code", auto: true }, { key: "venue", label: "Venue", auto: true }, { key: "basis", label: "Split from", auto: true }],
      csvColumns: ["country", "ticker", "company", "announced_date", "venue", "shares", "share_pct", "price_avg", "price_unit", "value", "currency", "value_basis", "value_working", "basis", "days"],
      columns: withMarket([{ key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "announced_date", label: "Programme" }, { key: "venue", label: "Venue" }, { key: "shares", label: "Shares", num: true, fmt: int }, { key: "share_pct", label: "Of programme", num: true, fmt: pc }, { key: "price_avg", label: "Average", num: true, html: (v, r) => v === null ? "" : Number(v).toFixed(4) + " " + esc(r.price_unit) }, { key: "value", label: "Value", num: true, html: (v, r) => v === null ? "" : moneyFull(v, r.currency) }, { key: "value_basis", label: "Value basis", html: (v, r) => tag(v, r.value_working) }, { key: "basis", label: "Split from" }, { key: "days", label: "Saved days", num: true }]) });
  },
  async cessations() {
    const c = await api("/api/cessations", P());
    view().innerHTML = head("Cessations", "Securities that have ceased, from Appendix 3H filings, as filed. These are kept apart from purchases and aren't added to or netted against them. A buy-back cancellation is linked to the latest programme announced by its date. Lapsed rights and other reasons are shown too, marked Other.") + `<div id="t"></div>`;
    table($("#t"), { rows: c.rows, sort: "ceased_on", dir: -1, pageSize: 50, csv: `cessations_${S.country}.csv`, onRow: (r) => openDoc(r.doc_id, `cess|${r.n}`), filters: [{ key: "ticker", label: "Code", auto: true }, { key: "kind", label: "Kind", auto: true }],
      csvColumns: ["country", "ticker", "company", "ceased_on", "security_code", "security", "shares", "reason", "kind", "consideration", "currency", "programme_label", "issued_after", "other_info", "filing_date", "source_url"],
      columns: withMarket([{ key: "ceased_on", label: "Ceased on" }, { key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "security", label: "Security", clip: true }, { key: "shares", label: "Number", num: true, fmt: int }, { key: "reason", label: "Reason", wrap: true }, { key: "kind", label: "Kind" },
        { key: "consideration", label: "Consideration", num: true, html: (v, r) => v === null ? `<span class="muted small">Not stated</span>` : `${money(v, r.currency)} ${tag("Reported", "Stated in the filing")}` }, { key: "programme_label", label: "Programme" }, { key: "filing_date", label: "Filed" }, { key: "source_url", label: "Filing link", html: (v) => v ? `<span class="mono small" style="word-break:break-all;white-space:normal">${sourceLink(v, v)}</span>` : "" }]) });
  },
  async cancellations() {
    const c = await api("/api/cancellations", P());
    view().innerHTML = head("Cancellations", "Whether bought shares are cancelled or kept in treasury, from the saved notices only. A reported count is a number the notice gives as cancelled. Per notice wording means the notice says how that day's purchases are treated, and the app applied that to the day's purchase figure. Counts aren't netted, and days without a saved notice are missing.") +
      `<h2>By programme</h2><div id="tP"></div><h2 class="mt">Counts by notice</h2><div id="tE"></div><h2 class="mt">Shares on issue, as each notice states</h2><div id="tC"></div>`;
    table($("#tP"), { rows: c.programmes, search: false, sort: "shares", dir: -1, csv: `cancellations_${S.country}_${S.from}_${S.to}.csv`, onRow: (r) => r.treatment_doc ? openDoc(r.treatment_doc, "prog") : openCompany(r.country, r.ticker), filters: [{ key: "treatment", label: "Treatment", auto: true }],
      csvColumns: ["country", "ticker", "company", "announced_date", "treatment", "treatment_text", "shares", "cancelled_reported", "cancelled_wording", "awaiting_wording", "latest_count", "latest_count_date"],
      columns: withMarket([{ key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "announced_date", label: "Programme" }, { key: "treatment", label: "Treatment", html: pill }, { key: "treatment_text", label: "Words in the notice", clip: true }, { key: "shares", label: "Bought", num: true, fmt: int }, { key: "cancelled_reported", label: "Cancelled, reported count", num: true, fmt: (v) => v ? int(v) : "–" }, { key: "cancelled_wording", label: "Cancelled per notice wording", num: true, fmt: (v) => v ? int(v) : "–" }, { key: "awaiting_wording", label: "Awaiting per notice wording", num: true, fmt: (v) => v ? int(v) : "–" }, { key: "latest_count", label: "Latest shares on issue", num: true, fmt: (v) => v === null ? "–" : int(v) }, { key: "latest_count_date", label: "As of" }]) });
    table($("#tE"), { rows: c.events, sort: "as_of", dir: -1, pageSize: 50, csv: `cancellation_notices_${S.country}.csv`, onRow: (e) => openDoc(e.doc_id, `cancel|${e.as_of}|${e.venue}|${e.kind}`), filters: [{ key: "ticker", label: "Code", auto: true }, { key: "kind", label: "Kind", auto: true }, { key: "venue", label: "Venue", auto: true }],
      columns: withMarket([{ key: "as_of", label: "Notice" }, { key: "ticker", label: "Code" }, { key: "venue", label: "Venue" }, { key: "kind", label: "Kind" }, { key: "shares", label: "Shares", num: true, fmt: int }, { key: "basis", label: "Basis" }, { key: "note", label: "Detail" }]) });
    table($("#tC"), { rows: c.counts, sort: "as_of", dir: -1, pageSize: 50, search: false, csv: `shares_on_issue_${S.country}.csv`, onRow: (s) => openDoc(s.doc_id, "prog"), filters: [{ key: "ticker", label: "Code", auto: true }],
      columns: withMarket([{ key: "as_of", label: "Notice" }, { key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "shares", label: "Shares on issue", num: true, fmt: int }]) });
  },
  async announcements() {
    const picked = new Set();
    const draw = async (q = "") => {
      const { rows, hits } = await api("/api/documents", { country: S.country, ...T(), ...(q ? { q } : {}) });
      const shown = hits ? rows.filter((r) => hits.includes(r.doc_id)) : rows;
      table($("#t"), { rows: shown, sort: "doc_date", dir: -1, pageSize: 100, search: false, csv: `notices_${S.country}.csv`, onRow: (r) => openDoc(r.doc_id),
        filters: [{ key: "ticker", label: "Company", auto: true }, { key: "appendix", label: "Appendix", auto: true }, { key: "filing_type", label: "Type", auto: true }, { key: "status", label: "Status", auto: true }, ...(S.country === "ALL" ? [{ key: "country", label: "Market", auto: true }] : [])],
        csvColumns: ["doc_id", "country", "ticker", "doc_date", "heading", "reason", "appendix", "filing_type", "status", "file_name", "figures", "source_url"],
        columns: withMarket([{ key: "pick", label: "", html: (v, r) => r.source_url ? `<input type="checkbox" data-pick="${r.doc_id}" ${picked.has(r.doc_id) ? "checked" : ""} aria-label="Select this filing">` : "" }, { key: "doc_date", label: "Date" }, { key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "heading", label: "Heading", clip: true }, { key: "reason", label: "Reason for update", clip: true }, { key: "appendix", label: "Appendix" }, { key: "filing_type", label: "Type" }, { key: "status", label: "Status", html: pill }, { key: "figures", label: "Figures", num: true }, { key: "source_url", label: "Filing link", html: (v) => v ? `<span class="mono small" style="word-break:break-all;white-space:normal">${sourceLink(v, v)}</span>` : `<span class="muted small">Typed entry</span>` }, { key: "message", label: "Result", clip: true }, { key: "doc_id", label: "", html: (v, r) => r.source_url ? removeButton(v) : "" }]) });
    };
    view().innerHTML = head("Notices", "Every filing read, with its link. The figures and the link are kept, not the file.") +
      `<div class="row-c left" id="bulk"></div><div id="t"></div>`;
    await draw();
    const paintBulk = () => {
      $("#bulk").innerHTML = `<button class="btn sm" id="tickPage">Tick this page</button>${picked.size ? `<button class="btn sm danger" id="rmMany">Remove ${int(picked.size)} selected</button><button class="btn sm" id="clearPick">Clear</button>` : `<span class="muted small">Tick filings to remove several at once.</span>`}`;
      $("#tickPage").onclick = () => { $$("input[data-pick]", $("#t")).forEach((x) => { x.checked = true; picked.add(+x.dataset.pick); }); paintBulk(); };
      if (!picked.size) return;
      $("#clearPick").onclick = () => { picked.clear(); $$("input[data-pick]", $("#t")).forEach((x) => { x.checked = false; }); paintBulk(); };
      $("#rmMany").onclick = async (e) => {
        const b = e.currentTarget;
        if (!b.dataset.asked) { b.dataset.asked = "1"; b.textContent = `Click again to remove ${int(picked.size)}`; setTimeout(() => { if (b.isConnected) paintBulk(); }, 5000); return; }
        try { const r = await post("/api/filings/remove_many", { doc_ids: [...picked] }); toast(`${int(r.removed)} filing${r.removed === 1 ? "" : "s"} removed, and their companies reconciled by filing date.${r.problems.length ? " Not removed: " + r.problems.join(" ") : ""}`); go(S.sec); }
        catch (x) { toast(x.message); }
      };
    };
    $("#t").addEventListener("change", (e) => { const x = e.target.closest("[data-pick]"); if (!x) return; if (x.checked) picked.add(+x.dataset.pick); else picked.delete(+x.dataset.pick); paintBulk(); });
    paintBulk();
  },
  async market() {
    const a = await api("/api/analysis", P());
    view().innerHTML = head("Markets side by side", "How buying compares across the companies you're studying, from the notices saved so far. Every figure on this page is calculated. Choosing All programmes adds programmes from different years.") +
      `<div class="card flush"><div class="twrap short"><table><thead><tr><th>Market</th><th>Exchange</th><th class="n">Studied</th><th class="n">Buying</th><th class="n">Amount</th><th class="n">Average per buyer</th></tr></thead><tbody>${a.participation.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.exchange)}</td><td class="n">${int(p.members)}</td><td class="n">${int(p.buying)}</td><td class="n">${amounts(p.amounts, p.currency)}</td><td class="n">${Object.keys(p.averages).length ? amounts(p.averages) : "–"}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="grid g-2 mt"><div class="card"><h2>How concentrated is buying?</h2><div class="twrap short"><table class="compact"><thead><tr><th>Market</th><th>Currency</th><th class="n">Buyers</th><th class="n">Largest</th><th class="n">Top 5</th><th class="n">Top 10</th></tr></thead><tbody>${a.concentration.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.currency)}</td><td class="n">${int(c.buyers)}</td><td class="n">${pc(c.top1)}</td><td class="n">${pc(c.top5)}</td><td class="n">${pc(c.top10)}</td></tr>`).join("")}</tbody></table></div><div class="legend-note">Worked out separately for each reported currency, because amounts aren't converted.</div></div>
      <div class="card"><h2>Share of issued shares bought</h2><div id="cap"></div><div class="legend-note">One bar per company: all its programmes' shares bought in the period, against shares on issue in its latest notice.</div></div></div>
      <div class="note mt">These figures cover only the notices saved so far, so a company showing no buying may just have no notices saved yet.</div>`;
    barList($("#cap"), a.capital.slice(0, 12).map((c) => ({ label: !c.company || c.company === c.ticker ? c.ticker : `${c.ticker} ${c.company}`, value: c.pct, text: c.pct < 0.1 ? c.pct.toFixed(3) + "%" : c.pct.toFixed(2) + "%", c })), (x) => openCompany(x.c.country, x.c.ticker));
  },
  async pace() {
    const a = await api("/api/analysis", P());
    view().innerHTML = head("Pace against announced size", "How much of each programme is used, compared with how much of its planned time has passed. Only programmes with a stated money size can be measured. Used, time passed and the gap are calculated.") + `<div id="t"></div>`;
    a.pace.forEach((r) => (r.gap = r.time_used_pct === null ? null : r.used_pct - r.time_used_pct));
    table($("#t"), { rows: a.pace, sort: "used_pct", dir: -1, csv: `pace_${S.country}.csv`, onRow: (r) => openCompany(r.country, r.ticker), columns: withMarket([{ key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "max_value", label: "Size", num: true, html: (v, r) => money(v, r.max_currency) }, { key: "spent", label: "Spent", num: true, html: (v, r) => money(v, r.max_currency) }, { key: "used_pct", label: "Used", num: true, fmt: pc }, { key: "time_used_pct", label: "Time passed", num: true, fmt: pc }, { key: "gap", label: "Ahead or behind (points)", num: true, fmt: (v) => v === null ? "" : (v > 0 ? "+" : "") + v.toFixed(1) }, { key: "start", label: "Start" }, { key: "end", label: "End" }, { key: "status", label: "Status", html: pill }]) });
  },
  async sectors() {
    const a = await api("/api/analysis", P());
    view().innerHTML = head("Sectors", "Amount bought back by sector, in the currency reported. These are calculated totals. Sector labels come from Wikipedia lists, so they do not line up exactly across markets.") + `<div id="t"></div>`;
    table($("#t"), { rows: a.sectors, sort: "value", dir: -1, csv: `sectors_${S.country}.csv`, columns: withMarket([{ key: "sector", label: "Sector" }, { key: "companies", label: "Companies", num: true }, { key: "value", label: "Amount", num: true, html: (v, r) => money(v, r.currency) }, { key: "share", label: "Share", num: true, fmt: pc }]) });
  },
  async price() {
    const a = await api("/api/analysis", P());
    view().innerHTML = head("Purchase prices", "The price each company paid on its first and latest purchase held in this period, using only days with a saved notice. The change is calculated. CSL's daily average is calculated too: amount paid / shares.") + `<div id="t"></div>`;
    table($("#t"), { rows: a.price, sort: "change_pct", dir: -1, csv: `purchase_prices_${S.country}.csv`, onRow: (r) => openCompany(r.country, r.ticker), columns: withMarket([{ key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "first_date", label: "First" }, { key: "first_price", label: "Price", num: true, fmt: (v) => v.toFixed(4) }, { key: "last_date", label: "Latest" }, { key: "last_price", label: "Price", num: true, fmt: (v) => v.toFixed(4) }, { key: "unit", label: "Unit" }, { key: "change_pct", label: "Change", num: true, fmt: pc }, { key: "days", label: "Days held", num: true }]) });
  },
  async reaction() {
    const a = await api("/api/analysis", P()), r = a.reaction;
    view().innerHTML = head("Share price after an announcement", "Change from the last close on or before the announcement. It is a simple description: not adjusted for market moves, and it does not show that a buyback caused the move.") +
      (r.rows.length ? `<div class="grid g-kpi">${r.summary.map((x) => `<div class="card kpi"><div class="k">${x.horizon} trading day${x.horizon === 1 ? "" : "s"} later</div><div class="v">${pc(x.median)}</div><div class="s">median of ${int(x.n)} · ${pc(x.up_pct)} rose</div></div>`).join("")}</div><div class="mt" id="t"></div>`
        : `<div class="banner"><div class="grow"><b>This needs closing prices.</b> The app holds no market prices. To use this page, save <code>inbox\\prices.csv</code> with the columns <code>country,ticker,date,close</code> from a source you may use, then restart the app. It also needs programmes with an announcement date in this period.</div></div>`);
    if (r.rows.length) table($("#t"), { rows: r.rows, sort: "announced", dir: -1, columns: withMarket([{ key: "ticker", label: "Code" }, { key: "announced", label: "Announced" }, { key: "d1", label: "+1 day", num: true, fmt: (v) => v === null ? "" : pc(v) }, { key: "d5", label: "+5 days", num: true, fmt: (v) => v === null ? "" : pc(v) }, { key: "d20", label: "+20 days", num: true, fmt: (v) => v === null ? "" : pc(v) }]) });
  },
  async quality() {
    const q = await api("/api/quality", P());
    const rvLinks = new Set(q.review.filter((r) => r.source_url).map((r) => r.doc_id)).size;
    view().innerHTML = head("Quality", "Files that need a decision, and automatic checks on the figures. Nothing is guessed: unclear values stay out until you confirm them.") +
      `<h2>Waiting for programme (${int(q.waiting.length)})</h2><p class="small muted">Purchases with no programme announcement read. They're left out of every total until linked. Add the announcement the notices cite and they link by themselves; or, if that programme isn't needed, remove its filings.</p><div id="wt"></div>
      <h2 class="mt">To review (${int(q.review.length)})</h2>${rvLinks ? `<div class="row-c left"><button class="btn sm primary" id="rvAll">Read all ${int(rvLinks)} filing${rvLinks === 1 ? "" : "s"} again</button>
        <span class="small muted">Fetches every filing listed here again from its link and reads it with the current reader and approved layouts. A filing that now reads cleanly leaves this list. Needs your document system.</span></div>` : ""}<div id="rv"></div><h2 class="mt">Checks (${int(q.checks.length)})</h2><div id="ck"></div>`;
    table($("#wt"), { rows: q.waiting, search: false, columns: withMarket([{ key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "purchases", label: "Purchases", num: true, fmt: int }, { key: "cessations", label: "3H cancellations", num: true, fmt: int },
      { key: "shares", label: "Shares bought", num: true, fmt: int }, { key: "first", label: "First" }, { key: "last", label: "Last" }, { key: "cited", label: "Programme the notices cite" },
      { key: "ticker", label: "Action", html: (v, r) => `${programmeDocForm(r.country, r.ticker)} <button class="btn sm danger" data-notneeded="${esc(r.country)}|${esc(r.ticker)}">Not needed</button>` }]) });
    bindProgrammeDocForms();
    if ($("#rvAll")) $("#rvAll").onclick = async () => {
      if (!confirm(`Read ${rvLinks} filing${rvLinks === 1 ? "" : "s"} again from ${rvLinks === 1 ? "its link" : "their links"}? Each one's figures are replaced by the new reading.`)) return;
      try { const r = await post("/api/filings/reread_review", { country: S.country, ticker: S.ticker }); toast(`Reading ${int(r.total)} filing${r.total === 1 ? "" : "s"} again. Progress is on Add data.`); go("collect", "import"); } catch (x) { toast(x.message); }
    };
    $$("[data-notneeded]").forEach((b) => (b.onclick = async (e) => {
      e.stopPropagation();
      if (!b.dataset.asked) { b.dataset.asked = "1"; b.textContent = "Click again to remove its filings"; setTimeout(() => { if (b.isConnected) { delete b.dataset.asked; b.textContent = "Not needed"; } }, 5000); return; }
      const [country, ticker] = b.dataset.notneeded.split("|");
      try { const r = await post("/api/waiting/not_needed", { country, ticker }); toast(`Removed ${r.removed} filing${r.removed === 1 ? "" : "s"}. They won't come back when a list is read again.`); go("quality"); } catch (x) { toast(x.message); }
    }));
    table($("#rv"), { rows: q.review, search: false, onRow: (r) => r.doc_id && openDoc(r.doc_id), columns: withMarket([{ key: "kind", label: "Issue" }, { key: "ticker", label: "Code" }, { key: "heading", label: "Heading", wrap: true, fmt: (v, r) => v || r.file_name || "" }, { key: "detail", label: "Detail", wrap: true },
      { key: "review_id", label: "Action", html: (v, r) => `${r.kind === "NO_COMPANY" ? `<select class="assign" data-doc="${r.doc_id}" aria-label="Choose company"><option value="">Choose company…</option>${q.tickers.filter((t) => t.country === r.country).map((t) => `<option value="${esc(t.ticker)}">${esc(t.ticker)} ${esc(t.company || "")}</option>`).join("")}</select>` : ""} <button class="btn sm dismiss" data-id="${v}">Mark as checked</button> ${r.source_url && r.doc_id ? removeButton(r.doc_id) : ""}` }]) });
    $$(".dismiss").forEach((b) => (b.onclick = async (e) => { e.stopPropagation(); await post("/api/review", { review_id: +b.dataset.id }); go("quality"); }));
    $$(".assign").forEach((s) => { s.onclick = (e) => e.stopPropagation(); s.onchange = async () => { if (s.value) { await post("/api/assign", { doc_id: +s.dataset.doc, ticker: s.value }); toast("Company set and file read again."); go("quality"); } }; });
    table($("#ck"), { rows: q.checks, search: false, csv: `checks_${S.country}.csv`, onRow: (r) => r.doc_id && openDoc(r.doc_id), filters: [{ key: "check", label: "Check", auto: true }], columns: withMarket([{ key: "severity", label: "Level", html: pill }, { key: "ticker", label: "Code" }, { key: "check", label: "Check" }, { key: "detail", label: "Detail", wrap: true }]) });
  },
  async import() {
    const c = await api("/api/collect");
    const cs = S.country === "ALL" ? c.countries : c.countries.filter((x) => x.code === S.country);
    const job = await api("/api/filings/status");
    view().innerHTML = head("Add filings", `Paste a hyperlink, or read an Excel list from the folder. The figures and links are kept, not the files. Exchange sites are always refused. ${(() => { const m = S.countries.find((x) => x.code === S.country); return m ? `Tickers the app doesn't know are read as ${esc(m.name)}, the market chosen above.` : "Choose a market above if your list has tickers the app doesn't know."; })()} Version ${esc(job.version)}.`) +
      `<div class="grid g-2">
        <div class="card"><h2>Paste a hyperlink</h2>
          <div class="form"><label for="pLinks">Hyperlink</label><textarea id="pLinks" rows="4" placeholder="Paste the full link. For several, one per line."></textarea>
            <label for="pTicker">Ticker (optional)</label><input type="text" id="pTicker" placeholder="For example CBA" maxlength="10">
            <span></span><div class="row"><button class="btn primary fRun" id="pGo">Read</button></div></div>
          <p class="small muted">Paste the link and press Read: no folder or address is needed. The company and date come from the document. If it can't tell the company, it will ask for the ticker.</p></div>
        <div class="card"><h2>Excel lists</h2>
          <div class="row-c left"><label class="btn primary fRun">Choose Excel file<input type="file" id="fList" accept=".xlsx,.xlsm,.csv" hidden></label> <a class="btn sm" href="/api/template?name=filings_list.xlsx">Template</a></div>
          <p class="small muted">Columns: <b>Ticker</b> and <b>Hyperlink</b>, holding the document ID or a full link. The date comes from each document.</p>
          <p class="small muted">Lists can also be kept in <code>${esc(job.folder)}</code>. They appear here with a Read button. <button class="linkbtn" id="fRefresh">Refresh</button></p>
          <div id="fLists"></div>
          <details class="small"><summary>Document address</summary><p class="muted">An ID becomes <span id="fAccepted"></span></p><input type="text" id="fLoc" value="${esc(job.location)}" aria-label="Document address" style="width:100%"><p class="muted">Change this only if the address changes. It's saved when you next read an Excel list.</p></details>
        </div></div>
      <div class="card mt"><div class="card-head"><h2>Progress</h2><div class="right"><button class="btn sm" id="fStop" hidden>Stop</button> <a class="btn sm" href="/api/filing_links">Accepted links (CSV)</a></div></div><p class="small muted">Every accepted link is also kept in <code>${esc(job.links_file)}</code></p><div id="fStatus"><p class="muted small">Nothing read yet.</p></div></div>
      <div class="card mt" id="fSkipCard" hidden><h2>Skipped or removed (<span id="fSkipN"></span>)</h2><p class="small muted">These links are remembered, so they aren't read again. Nothing from them is kept. If one is a buyback filing, press Read anyway.</p><div id="fSkipped"></div></div>`;
    const accepted = () => { const v = $("#fLoc").value.trim(); $("#fAccepted").textContent = `${v.replace(/\/+$/, "")}/{document ID}${job.suffix}`; };
    $("#fLoc").oninput = accepted; accepted();
    const market = () => S.country === "ALL" ? "" : S.country;
    const locationIfChanged = () => { const v = $("#fLoc").value.trim(); return v && v !== job.location ? v : ""; };
    const drawLists = (lists) => { $("#fLists").innerHTML = lists.length ? `<div class="twrap short"><table class="compact"><thead><tr><th>File</th><th>Saved</th><th></th></tr></thead><tbody>${lists.map((l, i) => `<tr><td class="wrap">${esc(l.name)}</td><td>${esc(l.modified)}</td><td><button class="btn sm primary fRun" data-list="${i}">Read</button></td></tr>`).join("")}</tbody></table></div>` : "";
      $$("#fLists [data-list]").forEach((b) => (b.onclick = async () => { try { if (await readChecked((ok) => post("/api/filings/read_list", { name: lists[+b.dataset.list].name, location: locationIfChanged(), market: market(), new_codes: ok }))) await started(); } catch (e) { toast(e.message); } })); };
    const drawJob = (j) => {
      const c = Object.entries(j.counts && Object.keys(j.counts).length ? j.counts : j.results.reduce((a, r) => ((a[r.result] = (a[r.result] || 0) + 1), a), {})).filter(([, v]) => v);
      $("#fSkipCard").hidden = !j.skipped.length; $("#fSkipN").textContent = int(j.skipped.length);
      $("#fSkipped").innerHTML = j.skipped.length ? `<div class="twrap" style="max-height:260px"><table class="compact"><thead><tr><th>Ticker</th><th>Heading</th><th>Why</th><th>Link</th><th>When</th><th></th></tr></thead><tbody>${j.skipped.map((s, i) => `<tr><td>${esc(s.ticker || "")}</td><td class="wrap">${esc(s.heading || "")}</td><td>${esc(s.reason === "Removed by you" ? "Removed by you" : "Not a buyback")}</td><td class="wrap mono" style="word-break:break-all">${sourceLink(s.link, s.link)}</td><td>${esc(s.skipped_at)}</td><td><button class="btn sm fRun" data-anyway="${i}">Read anyway</button></td></tr>`).join("")}</tbody></table></div>` : "";
      $$("#fSkipped [data-anyway]").forEach((b) => (b.onclick = async () => { try { await post("/api/filings/read_anyway", { link: j.skipped[+b.dataset.anyway].link }); await started(); } catch (e) { toast(e.message); } }));
      $("#fStop").hidden = !j.running; $$(".fRun").forEach((b) => (b.disabled = j.running));
      if (!j.name) return;
      const cls = (r) => r === "read" ? "ok" : r === "failed" || r === "refused" ? "bad" : r === "to review" ? "warn" : "";
      const done = Math.min(j.done, j.total), now = j.running && j.current ? 1 : 0, left = Math.max(j.total - done - now, 0), pct = j.total ? Math.round(100 * done / j.total) : 0;
      const stat = (label, v) => `<div class="job-stat"><span class="v">${int(v)}</span><span class="small muted">${label}</span></div>`;
      $("#fStatus").innerHTML = `<p class="small"><b>${esc(j.name)}</b>: ${j.running ? (j.current ? `reading file ${int(done + 1)} of ${int(j.total)}` : "starting") : done < j.total ? `stopped after ${int(done)} of ${int(j.total)}. ${int(j.total - done)} not read` : `finished, ${int(done)} of ${int(j.total)}`}${c.length ? ` · ${c.map(([k, v]) => `${int(v)} ${esc(k)}`).join(" · ")}` : ""}</p>
        <div class="job-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="Progress"><i style="width:${pct}%"></i></div>
        <div class="job-stats">${stat("Total", j.total)}${stat("Done", done)}${stat("Reading now", now)}${stat("Yet to be done", left)}<div class="job-stat"><span class="v">${pct}%</span><span class="small muted">Complete</span></div></div>
        ${j.running && j.current ? `<p class="small">Now reading: ${j.current.ticker ? `<b>${esc(j.current.ticker)}</b> ` : ""}<span class="mono" style="word-break:break-all">${esc(j.current.link || "")}</span></p>` : ""}
        ${j.error ? `<div class="note">${esc(j.error)}</div>` : ""}
        ${j.results.length ? `<div class="twrap" style="max-height:300px"><table class="compact"><thead><tr><th>Row</th><th>Ticker</th><th>Result</th><th>Detail</th><th>Link</th></tr></thead><tbody>${[...j.results].reverse().map((r) => `<tr><td>${esc(r.row)}</td><td>${esc(r.ticker)}</td><td><span class="pill ${cls(r.result)}">${esc(r.result)}</span></td><td class="wrap">${esc(r.detail)}</td><td class="wrap mono" style="word-break:break-all">${sourceLink(r.link, r.link)}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
    };
    drawLists(job.lists);
    drawJob(job);
    const follow = () => { clearInterval(S.jobWatch); S.jobWatch = setInterval(async () => { if (!$("#fStatus")) return clearInterval(S.jobWatch); const j = await api("/api/filings/status"); drawJob(j); if (!j.running) { clearInterval(S.jobWatch); toast("Finished reading the list."); } }, 1000); };
    const started = async () => { drawJob(await api("/api/filings/status")); follow(); $("#fStatus").scrollIntoView({ block: "center" }); };
    if (job.running) follow();
    $("#fRefresh").onclick = async () => { const j = await api("/api/filings/status"); drawLists(j.lists); toast(`${j.lists.length} list${j.lists.length === 1 ? "" : "s"} in the folder.`); };
    $("#fList").onchange = async (e) => { const f = e.target.files[0]; if (!f) return;
      try { if (await readChecked((ok) => api("/api/filings/start", { location: locationIfChanged(), name: f.name, market: market(), new_codes: ok ? "1" : "" }, { method: "POST", body: f }))) await started(); }
      catch (x) { toast(x.message); }
      e.target.value = ""; };
    $("#pGo").onclick = async () => {
      const text = $("#pLinks").value.trim();
      if (!text) return toast("Paste a hyperlink first.");
      try { if (await readChecked((ok) => post("/api/filings/paste", { text, ticker: $("#pTicker").value, market: market(), new_codes: ok }))) { $("#pLinks").value = ""; await started(); } }
      catch (e) { toast(e.message); }
    };
    $("#fStop").onclick = () => post("/api/filings/stop");
  },
  async reset() {
    view().innerHTML = head("Reset", "Wipe all the data and start empty.") + `<div class="card"><h2>What this does</h2>
      <p class="small"><b>Wiped:</b> every filing, figure, programme, purchase, cancellation and review item, your typed entries and prices, and the accepted links list. Links already read are forgotten, so they can be read again.</p>
      <p class="small"><b>Kept:</b> your study list, countries, document address, Excel lists and exported reports.</p>
      <p class="small">This can't be undone.</p>
      <div class="form"><label for="rWord">Type RESET</label><input type="text" id="rWord" autocomplete="off"><span></span><div class="row"><button class="btn danger" id="rGo" disabled>Wipe all data</button></div></div></div>`;
    $("#rWord").oninput = () => { $("#rGo").disabled = $("#rWord").value.trim() !== "RESET"; };
    $("#rGo").onclick = async () => {
      try { const r = await post("/api/reset", { confirm: "RESET" }); toast(`Wiped ${r.documents} filing${r.documents === 1 ? "" : "s"}. The app is now empty.`); go("home"); }
      catch (e) { toast(e.message); }
    };
  },
  async hand() {
    // Entries made by hand: a programme announcement, a change of terms, a purchase or a completion, for any market. Each needs its source,
    // can be edited or deleted (with a reason), and every change is kept in the history. Nothing is worked out for you.
    const H = S.hand || (S.hand = { kind: "programme", edit: null, vals: {} });
    if (!H.vals.country) H.vals.country = S.country !== "ALL" ? S.country : (S.countries[0] || {}).code;
    if (!H.vals.ticker && S.ticker) H.vals.ticker = S.ticker;
    const upd = H.kind === "update";
    const [list, ch, uc] = await Promise.all([api("/api/hand", { country: S.country, ...T() }), api("/api/hand/choices", { market: H.vals.country || "", company: H.vals.ticker || "" }),
      upd ? api("/api/hand/update_choices", { market: H.vals.country || "", company: H.vals.ticker || "", programme: H.vals.programme || "", target: H.vals.target || "", row: H.vals.row || "", field: H.vals.field || "" }) : null]);
    const mkt = ch.markets.find((m) => m.code === H.vals.country) || {};
    view().innerHTML = head("Add by hand", `For a programme, a change of its terms, a purchase or a completion that exists only as an announcement no reader can take apart, or a filing that isn't in your document system. Every entry needs its source, keeps the mark ${tag("Entered by hand", "Typed by you from the source named")}, and can be edited or deleted. <b>Update a reading</b> changes one figure read from a filing, with its source and reason; the figure keeps the mark ${tag("Updated Manually", "Read from a filing and changed by you")}, and the update can be edited or undone. The list below follows the market and company chosen at the top.`) +
      `<div class="card"><div class="card-head"><h2>${H.edit ? `Edit ${upd ? "update" : "entry"} ${int(H.edit)}` : upd ? "Update a figure read from a filing" : "Add an entry"}</h2><div class="right"><div class="seg" role="tablist" aria-label="What you are adding">${HAND_KINDS.map(([k, label]) => `<button role="tab" data-hkind="${k}" class="${H.kind === k ? "on" : ""}" ${H.edit && H.kind !== k ? "disabled" : ""}>${esc(label)}</button>`).join("")}</div></div></div>
        <div class="form" id="hForm">${upd ? updForm(ch, uc, H.vals, mkt, !!H.edit) : handForm(H.kind, ch, H.vals, mkt)}
          <span></span><div class="row"><button class="btn primary" id="hSave">${H.edit ? "Save changes" : "Save"}</button>${H.edit ? `<button class="btn" id="hCancel">Cancel edit</button>` : ""}<span class="small muted">The same checks as a filing read: dates in order, an amount with its currency. Required fields are marked *.</span></div></div>
        <p class="small muted">${esc(HAND_HELP[H.kind])}</p></div>
      <div class="card mt"><div class="card-head"><h2>Entries made by hand (${int(list.entries.length)})</h2><span class="right small muted">Edit puts an entry back in the form above. Delete asks for a reason.</span></div><div id="hList"></div></div>
      <details class="card mt"><summary><b>Deleted (${int(list.deleted.length)})</b> <span class="small muted">Taken out of every figure; kept here with the reason.</span></summary><div id="hDeleted"></div></details>
      <details class="card mt"><summary><b>History (${int(list.log.length)})</b> <span class="small muted">Every add, edit and delete, with the old and new values and when.</span></summary><div id="hLog"></div></details>`;
    const read = () => {
      const v = { country: H.vals.country, ticker: H.vals.ticker };
      $$("#hForm input[id^=h_], #hForm select[id^=h_]").forEach((el) => { v[el.id.slice(2)] = el.value.trim(); });
      v.ticker = String(v.ticker || "").split(" ")[0].toUpperCase();
      return v;
    };
    $$("[data-hkind]").forEach((b) => (b.onclick = () => { H.vals = { ...read(), programme: "" }; H.kind = b.dataset.hkind; PAGES.hand(); }));
    $("#h_country").onchange = () => { H.vals = { ...read(), country: $("#h_country").value, ticker: "", programme: "" }; PAGES.hand(); };
    $("#h_ticker").onchange = () => { const v = read(); if (v.ticker !== H.vals.ticker) { H.vals = { ...v, programme: "", target: "", row: "", field: "", value: "" }; PAGES.hand(); } };
    if (upd) {  // each choice narrows the next: programme, what, which row, which figure; the figure as held is then shown
      const chain = { programme: ["target", "row", "field", "value"], target: ["row", "field", "value"], row: ["value"], field: ["value"] };
      Object.entries(chain).forEach(([id, clear]) => { const el = $("#h_" + id); if (el) el.onchange = () => { const v = read(); clear.forEach((k) => { v[k] = ""; }); v.value_currency = ""; H.vals = { ...H.vals, ...v }; PAGES.hand(); }; });
      $$("#hForm [data-doc]").forEach((b) => (b.onclick = () => openDoc(+b.dataset.doc, b.dataset.key)));
    }
    $("#hSave").onclick = async () => {
      const v = read();
      try {
        if (upd) { const [td, ve, pu] = String(v.row || "").split("|"); Object.assign(v, v.target === "purchase" ? { trade_date: td, venue: ve ?? "", price_unit: pu ?? "" } : v.target === "total" ? { as_of: v.row } : {}); }
        const r = await post("/api/hand/save", { ...v, kind: H.kind, ...(H.edit ? { entry_id: H.edit } : {}) });
        toast(H.edit ? "Changes saved. The figures are rebuilt for this company." : `Saved: ${r.what}`);
        S.hand = { kind: H.kind, edit: null, vals: { country: v.country, ticker: v.ticker, ...(upd ? { programme: v.programme } : {}) } };
        PAGES.hand();
      } catch (e) { toast(e.message); }
    };
    if ($("#hCancel")) $("#hCancel").onclick = () => { S.hand = { kind: H.kind, edit: null, vals: { country: H.vals.country, ticker: H.vals.ticker } }; PAGES.hand(); };
    const rows = list.entries.map((r) => ({ ...r, review_n: r.review.length, market: r.country }));
    table($("#hList"), { rows, sort: "updated_at", dir: -1, csv: `hand_entries_${S.country}.csv`, filters: [{ key: "kind_label", label: "Kind", auto: true }, { key: "ticker", label: "Code", auto: true }],
      csvColumns: ["entry_id", "country", "ticker", "kind_label", "date", "what", "source", "note", "created_at", "updated_at"],
      columns: withMarket([{ key: "updated_at", label: "Entered", fmt: (v) => String(v || "").slice(0, 10) }, { key: "kind_label", label: "Kind" }, { key: "ticker", label: "Code" }, { key: "date", label: "Date" },
        { key: "what", label: "What", wrap: true }, { key: "source", label: "Source", wrap: true, html: (v) => /^https?:\/\//i.test(v) ? sourceLink(v) + ` <span class="small muted" style="word-break:break-all">${esc(v)}</span>` : esc(v) },
        { key: "review_n", label: "Review", html: (v, r) => v ? `<span class="pill warn" title="${esc(r.review.map((x) => x.detail).join("\n\n"))}">${int(v)} to review</span>` : "" },
        { key: "entry_id", label: "", html: (v, r) => `<button class="btn sm" data-hedit="${v}">Edit</button> <button class="btn sm danger" data-hdel="${v}">${r.kind === "update" ? "Undo" : "Delete"}</button> <button class="linkbtn" data-hshow="${v}">Show</button>` }]) });
    $("#hList").onclick = (e) => {
      const ed = e.target.closest("[data-hedit]"), del = e.target.closest("[data-hdel]"), sh = e.target.closest("[data-hshow]");
      const pick = (b, key) => list.entries.find((x) => x.entry_id === +b.dataset[key]);
      if (ed) {
        const r = pick(ed, "hedit"), f = r.fields;
        const extra = r.kind === "update" ? { row: f.target === "purchase" ? `${f.trade_date}|${f.venue || ""}|${f.price_unit || ""}` : f.as_of || "", value: f.value ?? "", value_currency: f.value_currency || "", was_shown: r.what.split(": ").pop().split(" → ")[0] } : {};
        S.hand = { kind: r.kind, edit: r.entry_id, vals: { ...f, ...extra, country: r.country, ticker: r.ticker, source: r.source, note: r.note || "" } }; PAGES.hand().then(() => window.scrollTo({ top: 0 }));
      }
      if (del) handDelete(pick(del, "hdel"));
      if (sh) {
        const r = pick(sh, "hshow"), f = r.fields;
        if (r.kind === "update") { if (f.doc_id) openDoc(f.doc_id, f.target === "purchase" ? `tx|${f.trade_date}|${f.venue || ""}` : f.target === "total" ? `snap|${f.as_of}` : "prog"); }
        else if (r.doc_id) openDoc(r.doc_id);
      }
    };
    table($("#hDeleted"), { rows: list.deleted, search: false, sort: "deleted_at", dir: -1, csv: `hand_entries_deleted_${S.country}.csv`, csvColumns: ["entry_id", "country", "ticker", "kind_label", "date", "what", "source", "deleted_at", "delete_reason"],
      columns: withMarket([{ key: "deleted_at", label: "Deleted", fmt: (v) => String(v || "").slice(0, 16) }, { key: "kind_label", label: "Kind" }, { key: "ticker", label: "Code" }, { key: "date", label: "Date" }, { key: "what", label: "What it held", wrap: true }, { key: "delete_reason", label: "Reason", wrap: true }, { key: "source", label: "Source", wrap: true }]) });
    table($("#hLog"), { rows: list.log, search: false, sort: "log_id", dir: -1, csv: `hand_history_${S.country}.csv`, csvColumns: ["log_id", "at", "action", "entry_id", "country", "ticker", "kind", "changes", "reason", "old_fields", "new_fields"],
      columns: withMarket([{ key: "at", label: "When", fmt: (v) => String(v || "").slice(0, 16) }, { key: "action", label: "What happened", fmt: (v) => ({ ADDED: "Added", EDITED: "Edited", DELETED: "Deleted", MOVED: "Moved from manual_entries.csv" })[v] || v }, { key: "entry_id", label: "Entry", num: true }, { key: "ticker", label: "Code" },
        { key: "changes", label: "Changes", wrap: true, html: (v, r) => esc(v || (r.action === "ADDED" || r.action === "MOVED" ? "New entry" : "")) }, { key: "reason", label: "Reason", wrap: true }]) });
  },
  async countries() {
    view().innerHTML = head("Countries", "A new market needs no program change. Add it here, then add its companies on the Companies page.") +
      `<div class="grid g-2"><div class="card"><h2>Add a country</h2><div class="form">
        <label for="nC">Code</label><input type="text" id="nC" placeholder="SG" maxlength="3"><label for="nN">Country</label><input type="text" id="nN" placeholder="Singapore">
        <label for="nE">Exchange</label><input type="text" id="nE" placeholder="SGX">
        <label for="nK">Currency</label><input type="text" id="nK" placeholder="SGD" maxlength="3"><label for="nF">Flag (optional)</label><input type="text" id="nF">
        <span></span><div class="row"><button class="btn primary" id="nGo">Add country</button></div></div>
        <p class="small muted">Check that exchange's terms before collecting anything. Notices in a new layout may go to the review list until a reader is added for them.</p></div>
      <div class="card"><h2>Current markets</h2><div class="twrap short"><table class="compact"><thead><tr><th>Code</th><th>Country</th><th>Exchange</th><th>Currency</th></tr></thead><tbody>${S.countries.map((c) => `<tr><td>${esc(c.code)}</td><td>${esc(c.flag || "")} ${esc(c.name)}</td><td>${esc(c.exchange)}</td><td>${esc(c.currency)}</td></tr>`).join("")}</tbody></table></div></div></div>`;
    $("#nGo").onclick = async () => {
      try { const e = await post("/api/country", { code: $("#nC").value, name: $("#nN").value, exchange: $("#nE").value, currency: $("#nK").value, flag: $("#nF").value }); toast(`${e.name} added.`); S.country = e.code; await loadTop(); go("collect", "countries"); }
      catch (e) { toast(e.message); }
    };
  },
  async tkOverview() {
    const w = tkWhere(); if (!w) return tkChoose();
    const o = await api("/api/tracker/overview", w);
    if (!o.plans.length) { view().innerHTML = tkHead(o) + `<div class="card"><p class="muted">No programmes are held for ${esc(o.name)}${o.ticker ? " · " + esc(o.ticker) : ""} yet. They appear here once filings for this exchange are read on Add data.</p></div>`; return tkBind(); }
    const by = (s) => o.plans.filter((p) => p.status === s).length, n = o.counts;
    const tiles = [["Programmes", o.plans.length, `${int(new Set(o.plans.map((p) => p.ticker)).size)} compan${new Set(o.plans.map((p) => p.ticker)).size === 1 ? "y" : "ies"}`], ["In progress", by("In progress"), ""],
      ["Completed", by("Completed"), `${int(by("Target reached"))} target reached · ${int(by("Ended, no final notice"))} ended, no final notice`], ["Notices in scope", n.notices, `${esc(o.from || "")} to ${esc(o.to || "")}`],
      ["Low confidence", n.low, n.notices ? pc(100 * n.low / n.notices) + " of notices" : ""], ["Cross-check differences", n.differences, "listed, never applied"]];
    view().innerHTML = tkHead(o) + `<div class="grid g-kpi">${tiles.map(([k, v, s]) => `<div class="card kpi"><div class="k">${k}</div><div class="v">${int(v)}</div><div class="s">${s}</div></div>`).join("")}</div>
      <div class="card mt"><div class="card-head"><h2>Programmes</h2><span class="right muted small">Click a programme for every field, its changes, its cross-check and its notices</span></div><div id="tkPlans"></div>
        <p class="small muted">Amounts are in the currency each notice reports and are never added or converted across currencies. Used is Calculated: amount spent so far / planned amount, only when both are in the same currency.</p></div>
      ${o.not_covered.length ? `<div class="card mt"><h2>Not covered for this exchange</h2><ul>${o.not_covered.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}`;
    table($("#tkPlans"), { rows: tkSorted(o.plans), columns: tkPlanCols, filters: [{ key: "status", label: "Status", auto: true }, { key: "check", label: "Cross-check", auto: true }], csv: `tracker_programmes_${o.country}.csv`, csvColumns: tkPlanCsv, onRow: (r) => tkPlan(r.plan_id) });
    tkBind();
  },
  async tkProgrammes() {
    const w = tkWhere(); if (!w) return tkChoose();
    const o = await api("/api/tracker/overview", w);
    view().innerHTML = tkHead(o) + `<div class="card"><h2>Programmes: every field</h2><div id="tkPlans"></div></div>`;
    const more = [{ key: "type", label: "Type", clip: true }, { key: "start", label: "Start" }, { key: "end", label: "End" }, { key: "planned_shares", label: "Max shares", num: true, fmt: (v) => v == null ? "" : count(v) }, { key: "shares_on_issue", label: "Shares on issue", num: true, fmt: (v) => v == null ? "" : count(v) },
      { key: "purchases", label: "Purchase days", num: true }, { key: "first_purchase", label: "First purchase" }, { key: "cum_as_of", label: "Running total as of" }, { key: "completed_on", label: "Completed on" },
      { key: "treatment", label: "Shares" }, { key: "brokers", label: "Broker", clip: true }, { key: "announced_basis", label: "How the date is known", clip: true }, { key: "changes", label: "Changes to terms", clip: true }];
    table($("#tkPlans"), { rows: tkSorted(o.plans), columns: [...tkPlanCols, ...more], filters: [{ key: "status", label: "Status", auto: true }, { key: "check", label: "Cross-check", auto: true }], csv: `tracker_programmes_${o.country}.csv`, csvColumns: tkPlanCsv, onRow: (r) => tkPlan(r.plan_id) });
    tkBind();
  },
  async tkNotices() {
    const w = tkWhere(); if (!w) return tkChoose();
    const [o, d] = [await api("/api/tracker/overview", w), await api("/api/tracker/notices", w)];
    view().innerHTML = tkHead(o) + `<div class="card"><h2>Notices in scope</h2><div id="tkRows"></div><p class="small muted">Click a notice for every field read from it, its confidence and how it was tied to its programme.</p></div>`;
    table($("#tkRows"), { rows: d.rows, columns: [{ key: "filed", label: "Filed" }, { key: "ticker", label: "Code" }, { key: "type", label: "Type" }, { key: "confidence", label: "Confidence", html: tkConfidence }, { key: "purchase_date", label: "Purchase date" },
      { key: "shares", label: "Shares", num: true, fmt: (v) => v == null ? "" : int(v) }, { key: "amount", label: "Amount", num: true, html: (v, r) => v == null ? "" : `${money(v, r.currency)} ${tag(r.amount_basis, r.amount_basis === "Calculated" ? "Shares x average price" : "The amount the notice states")}` },
      { key: "total_shares", label: "Total to date", num: true, fmt: (v) => v == null ? "" : count(v) }, { key: "plan_label", label: "Programme", clip: true }, { key: "tie_method", label: "How it was tied", clip: true }, { key: "link", label: "Link", html: (v) => sourceLink(v) }],
      searchKeys: ["title", "low_reason", "company"], filters: [{ key: "type", label: "Type", auto: true }, { key: "confidence", label: "Confidence", auto: true }], csv: `tracker_notices_${o.country}.csv`,
      csvColumns: ["filed", "ticker", "company", "type", "title", "confidence", "low_reason", "purchase_date", "shares", "amount", "amount_basis", "currency", "total_shares", "total_amount", "planned_amount", "plan_label", "tie_method", "link"], onRow: (r) => tkNotice(r.notice_id) });
    tkBind();
  },
  async tkChecks() {
    const w = tkWhere(); if (!w) return tkChoose();
    const [o, d] = [await api("/api/tracker/overview", w), await api("/api/tracker/checks", w)];
    view().innerHTML = tkHead(o) + `<div class="card"><h2>Cross-check</h2><p class="small muted">Each programme against the running totals and final notices in its own filings. A difference is listed and never applied. No outside source is compared.</p><div id="tkRows"></div></div>`;
    table($("#tkRows"), { rows: d.rows, columns: [{ key: "ticker", label: "Code" }, { key: "plan_label", label: "Programme" }, { key: "name", label: "Check" }, { key: "result", label: "Result", html: tkResult }, { key: "detail", label: "Detail", wrap: true }],
      filters: [{ key: "result", label: "Result", auto: true }, { key: "name", label: "Check", auto: true }], csv: `tracker_checks_${o.country}.csv`, csvColumns: ["ticker", "plan_label", "name", "result", "detail", "expected", "found"], onRow: (r) => tkPlan(r.plan_id) });
    tkBind();
  },
  async tkExcluded() {
    const w = tkWhere(); if (!w) return tkChoose();
    const [o, d] = [await api("/api/tracker/overview", w), await api("/api/tracker/excluded", w)];
    view().innerHTML = tkHead(o) + `<div class="card"><h2>Excluded</h2><p class="small muted">Filings left out of the tracker, with the reason. The tracker covers on-market buybacks only.</p><div id="tkRows"></div></div>`;
    table($("#tkRows"), { rows: d.rows, columns: [{ key: "filed", label: "Filed" }, { key: "ticker", label: "Code" }, { key: "type", label: "Type" }, { key: "title", label: "Title", clip: true }, { key: "reason", label: "Reason", wrap: true }, { key: "link", label: "Link", html: (v) => sourceLink(v) }],
      filters: [{ key: "reason", label: "Reason", auto: true }], csv: `tracker_excluded_${o.country}.csv`, onRow: (r) => { if (r.doc_id) openDoc(r.doc_id); } });
    tkBind();
  },
};

// ---------- the Tracker section: one exchange at a time, programme by programme ----------
const tkWhere = () => { const c = S.country !== "ALL" ? S.country : S.tickerCountry; return c ? { country: c, ...(S.ticker ? { ticker: S.ticker } : {}) } : null; };
function tkChoose() {
  view().innerHTML = head("Tracker", "The tracker shows one exchange at a time, programme by programme. Choose the exchange here or at the top of the page.") +
    `<div class="card"><h2>Choose an exchange</h2><div class="row-c left">${S.countries.map((c) => `<button class="btn" data-tkc="${esc(c.code)}">${esc(c.flag || "")} ${esc(c.name)} · ${esc(c.exchange)}</button>`).join("")}</div></div>`;
  $$("[data-tkc]").forEach((b) => (b.onclick = () => { S.country = b.dataset.tkc; $("#country").value = S.country; S.ticker = ""; S.tickerCountry = ""; loadTickers().then(() => go("tracker")); }));
}
const tkHead = (o) => head(`Tracker · ${esc(o.name)} · ${esc(o.exchange)}${o.ticker ? " · " + esc(o.ticker) : ""}`,
  `Every filing held for this exchange, tied to its programme. ${o.from ? `Filings ${esc(o.from)} to ${esc(o.to)}` : "No filings yet"}${o.built ? ` · built ${esc(o.built)}` : ""}. All dates are included; the period at the top does not apply here.`,
  `<button class="btn" id="tkRun" title="Build the tracker again from the filings held">Refresh</button><button class="btn" id="tkXl" title="The tracker for this exchange as an Excel file">${icon("download")} Excel</button>`) +
  (o.behind ? `<div class="note">A list is being read. The tracker updates when it finishes.</div>` : "");
function tkBind() {
  if ($("#tkRun")) $("#tkRun").onclick = async () => { try { const r = await post("/api/tracker/run"); toast(`Tracker built: ${int(r.programmes)} programmes from ${int(r["in scope"])} notices.`); go("tracker"); } catch (e) { toast(e.message); } };
  if ($("#tkXl")) $("#tkXl").onclick = () => { location.href = "/api/tracker/export?" + qs({ country: tkWhere().country }); };
}
const tkPill = (v, cls) => v ? `<span class="pill ${cls}">${esc(v)}</span>` : "";
const tkStatus = (v) => tkPill(v, v === "In progress" ? "ok" : /^Ended/.test(v || "") ? "warn" : "blue");
const tkConfidence = (v, r) => v === "entered by hand" ? tag("Entered by hand", "Typed by you from the source named; nothing was read") : v === "updated manually" ? tag(UPD, (r && r.low_reason) || "A figure of this notice was Updated Manually") : `<span title="${esc((r && r.low_reason) || "")}">${tkPill(v, v === "high" ? "ok" : v === "medium" ? "blue" : v === "low" || v === "not read" ? "warn" : "")}</span>`;
const tkResult = (v) => tkPill(v, v === "Match" ? "ok" : v === "Difference" ? "bad" : "");
const tkSorted = (plans) => [...plans].sort((a, b) => (a.status === "In progress" ? 0 : 1) - (b.status === "In progress" ? 0 : 1) || String(b.announced || "").localeCompare(String(a.announced || "")));
const tkPlanned = (p, full) => p.planned_amount != null ? (full ? `${esc(p.planned_currency || "")} ${amt(p.planned_amount)}` : money(p.planned_amount, p.planned_currency)) : p.planned_shares != null ? `${full ? int(p.planned_shares) : count(p.planned_shares)} shares` : p.planned_pct != null ? `${p.planned_pct}% of shares` : "";
const tkPlanCols = [{ key: "ticker", label: "Code" }, { key: "company", label: "Company", clip: true }, { key: "announced", label: "Announced", html: (v, r) => v ? esc(v) : `<span class="muted">${String(r.announced_basis || "").startsWith("Mandate") ? "Mandate, date not stated" : "Not identified"}</span>` }, { key: "status", label: "Status", html: tkStatus },
  { key: "planned_amount", label: "Planned", num: true, html: (v, r) => tkPlanned(r) || `<span class="muted">Not read</span>` }, { key: "shares_bought", label: "Shares bought", num: true, fmt: count },
  { key: "spent", label: "Spent", num: true, html: (v, r) => v == null ? (r.sum_value != null && r.spent_basis ? `<span class="muted" title="${esc(r.spent_basis)}">Not stated</span>` : "–") : `${money(v, r.buy_currency)} ${tag(r.spent_origin, r.spent_basis)}` },
  { key: "pct_used", label: "Used", num: true, html: (v) => v == null ? `<span class="muted">No planned figure</span>` : `<span class="tkused"><span class="meter"><i style="width:${Math.min(100, v)}%"></i></span>${pc(v)}</span>` },
  { key: "last_purchase", label: "Last purchase" }, { key: "notices", label: "Notices", num: true }, { key: "low", label: "Low", num: true, fmt: (v) => v || "" },
  { key: "check", label: "Cross-check", html: (v, r) => r.differences ? tkPill(`${r.differences} differ`, "bad") : r.matches ? tkPill(`${r.matches} match`, "ok") : `<span class="muted">Not checkable</span>` }];
const tkPlanCsv = ["country", "ticker", "company", "status", "announced", "announced_basis", "type", "start", "end", "planned_amount", "planned_currency", "planned_shares", "shares_on_issue", "brokers", "treatment", "shares_bought", "spent", "buy_currency", "spent_origin", "spent_basis",
  "pct_used", "purchases", "first_purchase", "last_purchase", "cum_shares", "cum_value", "cum_as_of", "final_shares", "final_value", "completed_on", "changes", "notices", "low", "check"];
const tkKvRow = (name, value, sub = "") => `<tr><td>${name}</td><td>${value}${sub ? `<span class="fn">${sub}</span>` : ""}</td></tr>`;
const tkFieldRows = (fields, draw) => fields.map((f) => `<tr><td>${esc(f.name)}${f.form_name ? `<span class="fn">${esc(f.form_name)}</span>` : ""}</td><td class="n">${draw(f)}</td></tr>`).join("");
const tkValue = (v) => typeof v === "number" ? (Number.isInteger(v) ? int(v) : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 })) : typeof v === "boolean" ? (v ? "Yes" : "No") : esc(v);
const tkSheetHead = (kicker, title, extra = "") => `<div class="sh-head"><div class="acts">${extra}<button class="icon-btn" id="closeSheet" aria-label="Close">${icon("x")}</button></div><div class="kicker">${kicker}</div><div class="title">${title}</div>`;
const tkFailed = (e) => openSheet(`<div class="sh-head"><div class="acts"><button class="icon-btn" id="closeSheet" aria-label="Close">${icon("x")}</button></div></div><div class="sh-body"><p>${esc(e.message)}</p></div>`);
async function tkPlan(id) {
  openSheet(`<div class="sh-body"><p class="muted">Loading…</p></div>`, true);
  let p;
  try { p = await api("/api/tracker/plan", { id }); } catch (e) { return tkFailed(e); }
  const draw = (f) => f.key === "status" ? tkStatus(f.value) : f.key === "check" ? tkResult(f.value) : f.key === "pct_used" ? `${pc(f.value)} ${tag("Calculated", "Amount spent so far / planned amount, in the same currency")}`
    : f.key === "spent" ? `${esc(f.currency || "")} ${amt(f.value)} ${tag(p.spent_origin, p.spent_basis)}` : f.key === "changes" ? `<span class="tkwrap">${String(f.value).split(" | ").map(esc).join("<br>")}</span>`
    : f.currency ? `${esc(f.currency)} ${amt(f.value)}` : typeof f.value === "string" ? `<span class="tkwrap">${esc(f.value)}</span>` : tkValue(f.value);
  openSheet(tkSheetHead(`${esc(p.country)} · ${esc(p.ticker)} · programme`, `${esc(p.company)}: announced ${esc(p.announced || "not identified")}`) + `${tkStatus(p.status)}</div>
    <div class="sh-body">
      <h3>Every field</h3><table class="tkkv"><tbody>${tkFieldRows(p.fields, draw)}</tbody></table>
      ${p.fields.some((f) => f.form_name) ? "" : `<p class="small muted">This programme is not known from an ASX notification form, so there are no form field names.</p>`}
      ${periodsBlock(p)}
      <h3>Cross-check</h3><table class="tkkv"><tbody>${p.checks.map((c) => tkKvRow(esc(c.name), tkResult(c.result), esc(c.detail))).join("")}</tbody></table>
      <h3>Timeline: ${int(p.timeline.length)} notice${p.timeline.length === 1 ? "" : "s"}</h3><p class="small muted">In date order. Click a notice for every field read from it.</p><div id="tkTimeline"></div></div>`, true);
  table($("#tkTimeline"), { rows: p.timeline, short: true, compact: true, pageSize: 25, columns: [{ key: "filed", label: "Filed" }, { key: "type", label: "Type" }, { key: "confidence", label: "Confidence", html: tkConfidence },
    { key: "shares", label: "Shares", num: true, fmt: (v) => v == null ? "" : int(v) }, { key: "amount", label: "Amount", num: true, html: (v, r) => v == null ? "" : `${esc(r.currency || "")} ${amt(v)}` },
    { key: "total_shares", label: "Total shares to date", num: true, fmt: (v) => v == null ? "" : int(v) }, { key: "total_amount", label: "Total amount to date", num: true, html: (v, r) => v == null ? "" : `${esc(r.currency || "")} ${amt(v)}` },
    { key: "planned_amount", label: "Planned", num: true, html: (v, r) => v == null ? "" : `${esc(r.currency || "")} ${amt(v)}` }], filters: [{ key: "type", label: "Type", auto: true }], onRow: (r) => tkNotice(r.notice_id) });
  bindPeriods("#sheet");
}
async function tkNotice(id) {
  openSheet(`<div class="sh-body"><p class="muted">Loading…</p></div>`, true);
  let n;
  try { n = await api("/api/tracker/notice", { id }); } catch (e) { return tkFailed(e); }
  const named = n.fields.some((f) => f.form_name), web = /^https?:\/\//i.test(n.link || "");
  const read = n.reader === "manual" ? "Entered by hand on Add data > Add by hand; nothing was read" : n.confidence === "not read" ? "Not read" : n.reader === "appendix_3c" || n.reader === "appendix_3h" ? "The ASX form reader" : n.reader === "capital_change" ? "The NZX Capital Change Notice reader" : n.reader ? "A layout in data\\forms" : "The general reader (prose)";
  openSheet(tkSheetHead(`${esc(n.country)} · ${esc(n.ticker || "company not set")} · ${esc(n.type)}`, `${esc(n.company || n.ticker || "Notice")}: filed ${esc(n.filed || "date not stated")}`) + `</div>
    <div class="sh-body">
      <table class="tkkv"><tbody>
        ${tkKvRow("Title", esc(n.title) || "Not stated")}
        ${tkKvRow("Type", esc(n.type), `Known from: ${esc(n.type_basis === "none" ? "nothing in the filing" : "the " + n.type_basis)}`)}
        ${tkKvRow("Confidence", tkConfidence(n.confidence, n), n.low_reason ? `${esc(n.low_reason)}. A figure not found is left blank, never guessed` : "")}
        ${n.reader === "manual" ? tkKvRow("Read from", "Nothing was read", "Entered by hand on Add data > Add by hand. Open in the app shows what was typed and its source") : tkKvRow("Read from", "The app's reading of this filing", `${esc(read)}. Filing text is not kept; open the filing to see it`)}
        ${tkKvRow("Programme", n.plan_id ? `<button class="btn sm" id="tkToPlan">${esc(n.plan_label)}</button>` : "Not tied to a programme", n.plan_id ? esc(n.tie_method) : esc(n.excluded_reason || ""))}
        ${tkKvRow("Original filing", `${web ? `<a href="${esc(n.link)}" target="_blank" rel="noopener">Open the filing</a>` : n.link ? sourceLink(n.link) : "No link"}${n.doc_id ? ` <button class="btn sm" id="tkOpenDoc">Open in the app</button>` : ""}`,
          `${web ? "Opens through your document system. " : ""}${n.doc_id ? "Open in the app shows the filing with the source text of each figure marked" : ""}`)}
      </tbody></table>
      <h3>Every extracted field</h3>${n.fields.length ? `<table class="tkkv"><tbody>${tkFieldRows(n.fields, (f) => tkValue(f.value))}</tbody></table>${named ? "" : `<p class="small muted">Read from prose, so there are no form field names.</p>`}` : `<p class="muted">No fields were extracted.</p>`}</div>`, true);
  if ($("#tkOpenDoc")) $("#tkOpenDoc").onclick = () => openDoc(n.doc_id);
  if ($("#tkToPlan")) $("#tkToPlan").onclick = () => tkPlan(n.plan_id);
}

// ---------- one company's programmes as cards, as in buyback_viewer.html ----------
async function programmeCards() {
  const c = await api("/api/company", { country: S.tickerCountry, ticker: S.ticker, from: S.from, to: S.to });
  if (!c) { view().innerHTML = head("Programmes") + `<p class="muted">Nothing is saved for ${esc(S.ticker)}.</p>`; return; }
  const span = (id) => { const days = c.transactions.filter((t) => t.prog_id === id && !t.waiting).map((t) => t.trade_date).sort(); return days.length ? `${esc(days[0])} to ${esc(days[days.length - 1])}` : "–"; };
  view().innerHTML = head(`${esc(c.ticker)} · ${esc(c.company || "")}`, `${esc(S.tickerCountry)}${c.sector ? " · " + esc(c.sector) : ""} · ${esc(periodText())}. One card per announced programme. Choose All tickers at the top for the full table.`, `<button class="btn" id="pcPanel">Purchases and notices</button>`) +
    (c.waiting ? `<div class="note">${int(c.waiting)} purchase${c.waiting === 1 ? " is" : "s are"} waiting for a programme document and left out of the totals. See Quality > Waiting for programme.</div>` : "") +
    (c.programmes.length ? `<div class="pcards">${c.programmes.map((p) => `<div class="card"><h2>Announced ${esc(p.announced_date || "not stated")}</h2><dl class="kv">
      <dt>Status</dt><dd>${statusText(p)}</dd>
      <dt>Type</dt><dd>${esc(p.buyback_type || "–")}</dd>
      <dt>Runs</dt><dd class="mono">${periodRuns(p)}${updTag((p.updated || {}).start_date || (p.updated || {}).end_date)}${p.end_note ? `<div class="muted small">${esc(p.end_note)}</div>` : ""}</dd>
      ${p.document_needed ? `<dt>Programme document</dt><dd><span class="pill warn">Needed</span> <span class="small muted">Type, dates and size come from the announcement.</span><div class="mt-s">${programmeDocForm(p.country, p.ticker)}</div></dd>` : ""}
      <dt>Target</dt><dd>${p.max_value ? money(p.max_value, p.max_currency) : p.max_shares ? `${int(p.max_shares)} shares` : "Not stated"}${p.periods ? `<div class="muted small">The newest period's. Each period's target is under Periods below.</div>` : ""}${p.size_note ? `<div class="muted small">${esc(p.size_note)}</div>` : ""}</dd>
      <dt>Broker</dt><dd>${esc(p.broker || "Not disclosed")}${updTag((p.updated || {}).broker)}</dd>
      <dt>${isAllPeriod() ? "Bought" : "Bought in period"}</dt><dd><b>${boughtText(p.shares, p.amounts)}</b> ${tag(p.amount_basis, p.amount_working)}${p.amount_working ? `<div class="muted small">${esc(p.amount_working)}</div>` : ""}</dd>
      <dt>Used of target</dt><dd>${p.used_pct !== null && p.used_pct !== undefined ? `${pc(p.used_pct)} ${tag("Calculated", "Spent since it began / announced size")}` : `<span class="muted">Not comparable or no target</span>`}</dd>
      <dt>Shares cancelled</dt><dd>${p.cancelled_shares === null || p.cancelled_shares === undefined ? "–" : `${int(p.cancelled_shares)} ${tag(p.cancelled_basis, p.cancelled_working)}<div class="muted small">${esc(p.cancelled_working)}</div>`}</dd>
      <dt>Average price paid</dt><dd>${p.avg_price === null || p.avg_price === undefined ? "–" : `${esc(p.avg_currency)} ${Number(p.avg_price).toFixed(4)} ${tag(p.avg_basis, p.avg_working)}<div class="muted small">${esc(p.avg_working)}</div>`}</dd>
      <dt>Purchases read</dt><dd class="mono">${span(p.prog_id)}</dd>
      <dt>Shares</dt><dd>${esc(p.treatment || "Not stated")}${updTag((p.updated || {}).treatment)}${p.treatment_text ? `<div class="muted small">"${esc(p.treatment_text)}"</div>` : ""}</dd>
      <dt>Shares on issue</dt><dd>${p.shares_on_issue ? int(p.shares_on_issue) : "–"}${updTag((p.updated || {}).shares_on_issue)}</dd></dl>${periodsBlock(p)}
      <div class="row-c left"><button class="btn sm" data-activity="${p.prog_id}">View charts and daily activity</button>${p.announced_date ? updButton({ country: p.country, ticker: p.ticker, programme: p.announced_date, target: "programme" }, "Update a figure", "btn sm") : ""}</div>${p.note ? `<div class="note">${esc(p.note)}</div>` : ""}</div>`).join("")}</div>
      <p class="small muted">Amounts are in the currency each notice reports and are never converted. Hover over Reported or Calculated to see where a figure comes from.</p>` : `<p class="muted">No programmes read for this company.</p>`);
  $("#pcPanel").onclick = () => openCompany(S.tickerCountry, S.ticker);
  $$("#view [data-activity]").forEach((b) => (b.onclick = () => { S.activityProg = +b.dataset.activity; go("companies", "activity"); }));
  bindPeriods("#view");
  bindProgrammeDocForms();
}
function markdown(md) {
  const inline = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1 ↗</a>');
  const out = []; let list = false, tbl = null, code = null;
  const close = () => { if (list) { out.push("</ul>"); list = false; } if (tbl) { out.push(`<div class="twrap short"><table class="compact"><thead><tr>${tbl[0].map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${tbl.slice(1).map((r) => `<tr>${r.map((c) => `<td class="wrap">${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`); tbl = null; } };
  for (const line of md.split(/\r?\n/)) {
    if (line.startsWith("```")) { if (code === null) { close(); code = []; } else { out.push(`<pre>${esc(code.join("\n"))}</pre>`); code = null; } continue; }
    if (code !== null) { code.push(line); continue; }
    if (/^\|/.test(line)) { const cells = line.replace(/^\||\|$/g, "").split("|").map((c) => c.trim()); if (cells.every((c) => /^:?-+:?$/.test(c))) continue; (tbl = tbl || []).push(cells); continue; }
    if (tbl) close();
    const h = line.match(/^(#{1,4}) (.*)/);
    if (h) { close(); out.push(`<h${Math.min(h[1].length + 1, 4)}>${inline(h[2])}</h${Math.min(h[1].length + 1, 4)}>`); continue; }
    if (/^[-*] /.test(line)) { if (!list) { out.push("<ul>"); list = true; } out.push(`<li>${inline(line.slice(2))}</li>`); continue; }
    close();
    if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  close();
  return out.join("");
}

// ---------- navigation ----------
async function go(sec, sub) {
  clearInterval(S.watch); clearInterval(S.jobWatch);
  const token = ++goToken;  // a slower earlier page must not replace the page chosen last
  S.sec = sec;
  loadTickers();  // filings read since the page opened add their companies to the selector
  const cfg = SECTIONS[sec];
  if (sub) S.sub[sec] = sub;
  const name = cfg.subs ? (S.sub[sec] || cfg.subs[0][0]) : sec;
  $$("#rail button").forEach((b) => b.classList.toggle("on", b.dataset.sec === sec));
  $("#subtabs").innerHTML = (cfg.subs || []).map(([k, l]) => `<button role="tab" class="${k === name ? "on" : ""}" data-sub="${k}">${esc(l)}</button>`).join("");
  $$("#subtabs button").forEach((b) => (b.onclick = () => go(sec, b.dataset.sub)));
  const real = $("#view");
  real.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    if (sec === "library") {
      const r = await fetch(`/api/library_file?name=${encodeURIComponent(name)}`);
      if (token !== goToken) return;
      real.innerHTML = r.ok ? `<div class="card md">${markdown(await r.text())}</div>` : `<p class="muted">Not written yet.</p>`;
      return;
    }
    await PAGES[name]();
  } catch (e) { if (token === goToken) real.innerHTML = `<div class="note"><b>That did not load.</b> ${esc(e.message)}</div>`; }
}

// ---------- start ----------
$("#country").onchange = (e) => {
  if (e.target.value === "__add") { e.target.value = S.country; return go("collect", "countries"); }
  S.country = e.target.value; S.ticker = ""; S.tickerCountry = ""; loadTickers().then(() => go(S.sec));
};
$("#ticker").onchange = (e) => { const [c, t] = e.target.value.split("|"); S.ticker = t || ""; S.tickerCountry = t ? c : ""; go(S.sec); };
$("#month").onchange = (e) => {
  const v = e.target.value;
  if (v === "custom") { $("#customDates").hidden = false; return; }
  if (v === "all") { S.from = S.periods.default.from; S.to = S.periods.default.to; } else { S.from = v + "-01-01"; S.to = v + "-12-31"; }
  syncPeriod(); go(S.sec);
};
$("#applyCustom").onclick = () => { if ($("#pFrom").value && $("#pTo").value && $("#pFrom").value <= $("#pTo").value) { S.from = $("#pFrom").value; S.to = $("#pTo").value; syncPeriod(); go(S.sec); } else toast("Choose a start date on or before the end date."); };
$("#exportBtn").onclick = () => { location.href = "/api/export?" + qs(P()); };
const storeGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const storeSet = (k, v) => { try { localStorage.setItem(k, v); } catch { /* the page works without saved settings */ } };
const setMode = (m) => { S.mode = m; $$(".seg [data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === m)); storeSet("sbb-mode", m); };
// Dark or light view, remembered in this browser. The colours are the stylesheet's two sets of the same variables.
const setTheme = (t) => { document.documentElement.dataset.theme = t; storeSet("sbb-theme", t); const b = $("#themeBtn"); if (b) { b.title = t === "dark" ? "Switch to light view" : "Switch to dark view"; b.setAttribute("aria-label", b.title); } };
$("#themeBtn").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
setTheme(storeGet("sbb-theme") === "dark" ? "dark" : "light");
$$(".seg [data-mode]").forEach((b) => (b.onclick = () => { setMode(b.dataset.mode); go(b.dataset.mode === "analyst" && S.sec === "home" ? "companies" : S.sec); }));
setMode(storeGet("sbb-mode") || "dashboard");
$$("#rail button").forEach((b) => (b.onclick = () => go(b.dataset.sec)));
$("#scrim").onclick = closeSheet;
document.addEventListener("keydown", (e) => { if (e.key !== "Escape") return; if (!$("#modal").hidden) closeModal(); else closeSheet(); });
loadTop().then(() => go(S.mode === "analyst" ? "companies" : "home")).catch((e) => { view().innerHTML = `<div class="note">${esc(e.message)}</div>`; });

// Dates show as MM/DD/YYYY everywhere on screen. The data keep YYYY-MM-DD, so sorting and reconciling are unchanged.
const ISO_DATE = /\b(\d{4})-(\d{2})-(\d{2})\b/g;
const usDate = (s) => String(s).replace(ISO_DATE, (m, y, mo, d) => `${mo}/${d}/${y}`);
function usDates(root) {
  const skip = (n) => n.parentElement && n.parentElement.closest("script,style,textarea,pre,code");
  const fix = (n) => { if (!skip(n) && ISO_DATE.test(n.nodeValue)) { ISO_DATE.lastIndex = 0; n.nodeValue = usDate(n.nodeValue); } ISO_DATE.lastIndex = 0; };
  if (root.nodeType === 3) return fix(root);
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) fix(n);
}
new MutationObserver((changes) => changes.forEach((c) => (c.type === "characterData" ? usDates(c.target) : c.addedNodes.forEach(usDates)))).observe(document.body, { childList: true, subtree: true, characterData: true });
usDates(document.body);
