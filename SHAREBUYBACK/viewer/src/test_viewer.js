// Runs the viewer's own data layer, taken from the built HTML, against the test database, with the same sql.js engine the page carries.
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const S = __dirname;
const html = fs.readFileSync(path.join(__dirname, "..", "buyback_viewer.html"), "utf8");
const grab = (id) => html.match(new RegExp(`<script id="${id}">([\\s\\S]*?)</script>`))[1];
const initSqlJs = require(path.join(S, "sqljs/sql-wasm.js"));
const ctx = { console };
vm.createContext(ctx);
vm.runInContext(grab("engine") + "\n" + grab("viewer-data") + "\nthis.API = { activity, groupPurchases, checkDatabase, markets, companies, summary, programmes, purchases, runningTotals, cessations, filings, reviews, SQLJS_WASM_BASE64 };", ctx);
const A = ctx.API;
const ok = (cond, msg) => { if (!cond) { console.log("FAIL:", msg); process.exitCode = 1; } else console.log("ok  ", msg); };

(async () => {
  const wasmBinary = Uint8Array.from(Buffer.from(A.SQLJS_WASM_BASE64, "base64"));
  const SQL = await initSqlJs({ wasmBinary });
  ok(wasmBinary.length === fs.statSync(path.join(S, "sqljs/sql-wasm.wasm")).size, "the engine built into the page is complete");
  const db = new SQL.Database(fs.readFileSync(path.join(require("os").tmpdir(), "sbb_viewer_test.db")));
  ok(A.checkDatabase(db) === null, "the test database is accepted");
  const empty = new SQL.Database();
  ok(/doesn't look like/.test(A.checkDatabase(empty) || ""), "another kind of file is refused with a plain message");

  // The saved sample filings (CSL, HSBC and others) aren't in the package. Without them the checks that need them are skipped, and say so.
  const full = A.companies(db, "UK").some((c) => c.ticker === "HSBA");
  const skip = (msg) => console.log("skip", msg, "(needs the sample filings)");
  const ms = A.markets(db);
  console.log("markets:", JSON.stringify(ms));
  ok(ms.map((m) => m.code).join() === (full ? "AU,NZ,UK" : "AU,UK"), "the markets with filings are listed: " + ms.map((m) => m.code).join());
  const uk = A.companies(db, "UK").map((c) => c.ticker);
  ok(uk.join() === (full ? "AV.,FDEV,HSBA,MACF,RKT,SHEL" : "AV.,FDEV,MACF,RKT,SHEL"), "choosing UK lists only UK companies: " + uk.join());
  ok(A.companies(db, "ALL").length === (full ? 12 : 8), `all markets lists all ${full ? 12 : 8} companies`);

  if (full) {
  const sum = A.summary(db, "AU", "CSL");
  console.log("CSL summary:", JSON.stringify(sum));
  const csl = A.programmes(db, "AU", "CSL");
  csl.forEach((p) => console.log(`  CSL programme ${p.announced_date}: ${p.bought.amounts.map((a) => a.currency + " " + a.value + " / " + a.shares).join("; ")} (${p.bought.basis}, ${p.bought.kind}) used ${p.usedPct}`));
  const total = csl.reduce((t, p) => t + (p.bought.amounts[0] ? p.bought.amounts[0].value : 0), 0);
  ok(Math.abs(total - 1165437316.76) < 0.01, "CSL's two programmes add up to A$1,165,437,316.76, as in the app");
  const hsba = A.programmes(db, "UK", "HSBA");
  const hsbaTotal = hsba.reduce((t, p) => t + (p.bought.amounts[0] ? p.bought.amounts[0].value : 0), 0);
  ok(Math.abs(hsbaTotal - 1063.9e6) < 1, "HSBC's programmes add up to US$1,063.9m, as in the app");
  ok(hsba.every((p) => p.bought.amounts.every((a) => a.currency === "USD")), "HSBC stays in USD, not converted");
  } else skip("CSL and HSBC programme totals");

  const rkt = A.purchases(db, "UK", "RKT");
  console.log("RKT purchases:", JSON.stringify(rkt));
  ok(rkt.length === 1 && rkt[0].shares === 49570 && rkt[0].price_avg === 6050.17 && rkt[0].basis === "Calculated", "your Reckitt purchase shows with its calculated value");
  ok(A.programmes(db, "UK", "RKT")[0].treatment === "Treasury", "Reckitt's treatment shows as Treasury");

  const iph = A.cessations(db, "AU", "IPH");
  console.log("IPH cessations:", JSON.stringify(iph.map((c) => [c.ceased_on, c.security_code, c.shares, c.kind, c.programme])));
  ok(iph.length === 2 && iph.some((c) => c.kind === "Other") && iph.some((c) => c.kind === "Buy-back"), "IPH's 3H shows its buy-back and its lapsed rights apart");
  const rf1 = A.cessations(db, "AU", "RF1");
  ok(rf1.length === 4 && rf1.every((c) => c.currency === "AUD" && c.consideration > 0), "Regal's 3H shows four days with consideration");

  if (full) {
  const tot = A.runningTotals(db, "AU", "CSL");
  ok(tot.length > 0 && tot.every((t) => t.basis === "Reported" || t.basis === "Calculated"), `CSL's ${tot.length} running totals each carry a basis`);
  const fil = A.filings(db, "UK", "HSBA");
  ok(fil.length === 11 && fil.every((f) => f.source_url && f.heading), "HSBC's 11 filings show with heading and link");
  } else skip("CSL running totals and HSBC filings");
  const rev = A.reviews(db, "AU", "IPH");
  console.log("IPH review:", JSON.stringify(rev.map((r) => [r.kind, r.detail.slice(0, 60)])));
  for (const c of A.companies(db, "ALL")) {
    for (const f of ["summary", "programmes", "purchases", "runningTotals", "cessations", "filings", "reviews"]) A[f](db, c.country, c.ticker);
  }
  ok(true, "every view runs for every company without an error");

  // New in v2: brokers, venues, waiting purchases, programme document flag, grouped purchases
  const av = A.purchases(db, "UK", "AV.");
  ok(av.length === 1 && av[0].price_avg === 678 && av[0].venue === "London Stock Exchange (XLON)" && av[0].broker === "Citigroup Global Markets Limited" && av[0].broker_role === "Through", "Aviva shows its price, venue and broker");
  ok(A.programmes(db, "UK", "MACF")[0].documentNeeded === true && A.programmes(db, "UK", "MACF")[0].announced_date === "2025-05-15", "Macfarlane's programme shows its document as needed, dated by the notice");
  ok(A.programmes(db, "UK", "AV.")[0].broker === "Citigroup Global Markets Limited", "the programme card has the broker");
  const shel = A.purchases(db, "UK", "SHEL");
  ok(shel.length === 1 && shel[0].waiting === 1, "a purchase with no programme document is marked waiting");
  const shelBought = A.programmes(db, "UK", "SHEL").reduce((t, p) => t + p.bought.amounts.reduce((s, a) => s + (a.shares || 0), 0), 0);
  ok(shelBought === 0, "a waiting purchase is left out of the programme total");
  const g = A.groupPurchases(A.purchases(db, "AU", "CSL"));
  const flat = A.purchases(db, "AU", "CSL").reduce((t, r) => t + r.shares, 0);
  ok(g.reduce((t, p) => t + p.totals.shares, 0) === flat, "grouped programme totals add up to the purchase list");
  ok(g.every((p) => p.years.reduce((t, y) => t + y.totals.shares, 0) === p.totals.shares && p.years.every((y) => y.months.reduce((t, m) => t + m.totals.shares, 0) === y.totals.shares)), "year totals add up to programme totals, and month totals to year totals");
  ok(g.every((p) => p.years.every((y) => y.months.every((m) => m.rows.every((r) => r.trade_date.startsWith(m.month))))), "each date sits under its own month");
  const gw = A.groupPurchases(shel);
  ok(gw[0].totals.shares === 0 && gw[0].totals.waiting === 1, "the grouped list counts a waiting purchase separately");
  console.log("CSL grouping:", JSON.stringify(g.map((p) => ({ programme: p.programme, shares: p.totals.shares, years: p.years.map((y) => ({ year: y.year, months: y.months.map((m) => m.month + ":" + m.totals.shares) })) }))));

  // New in v3: a shares-only running total doesn't blank the amount, and the completed rule
  const fd = A.programmes(db, "UK", "FDEV")[0];
  ok(fd.bought.basis === "Sum of daily purchases read" && fd.bought.amounts[0].value === 200832 && fd.bought.amounts[0].shares === 50208, "Frontier's amount comes from its daily purchase, not its shares-only running total");
  ok(fd.status === "ACTIVE" && !fd.statusBasis, "Frontier stays ACTIVE");
  ok(A.programmes(db, "UK", "HSBA").filter((p) => p.status === "COMPLETED").every((p) => p.statusBasis), "every COMPLETED programme says whether it is reported or calculated");
  const lloy = new SQL.Database(); lloy.run(`create table programmes(prog_id, country, ticker, announced_date, status, max_value, max_currency, buyback_type, start_date, end_date, max_shares);
    create table snapshots(prog_id, as_of, cum_shares, cum_value, currency, origin); create table transactions(prog_id, country, ticker, trade_date, shares, value, currency);
    insert into programmes values (1,'UK','LLOY','2026-01-30','ACTIVE',1750,'GBP',null,null,null,null), (2,'UK','LLOY','2026-07-31','ACTIVE',null,null,null,null,null,null), (3,'UK','LLOY','2025-02-20','ACTIVE',null,null,null,null,null,null);
    insert into transactions values (1,'UK','LLOY','2026-02-02',1000,1000.004,'GBP'), (1,'UK','LLOY','2026-09-25',700,750,'GBP'), (2,'UK','LLOY','2026-09-28',10,10,'GBP'), (3,'UK','LLOY','2025-03-01',5,5,'GBP');`);
  const lp = Object.fromEntries(A.programmes(lloy, "UK", "LLOY").map((p) => [p.announced_date, p]));
  ok(lp["2026-01-30"].status === "COMPLETED" && lp["2026-01-30"].statusBasis === "Calculated" && /target used/.test(lp["2026-01-30"].statusWorking), "a programme at 100% of target shows COMPLETED, Calculated");
  ok(lp["2025-02-20"].status === "COMPLETED" && /began buying on 2026-02-02/.test(lp["2025-02-20"].statusWorking), "an older programme shows COMPLETED once a later one starts buying after it");
  ok(lp["2026-07-31"].status === "ACTIVE", "the newest programme stays ACTIVE");

  // New in v4: Daily activity charts, built the way the app builds them
  if (full) {
  const cslProgs = A.programmes(db, "AU", "CSL");
  const actOld = A.activity(db, cslProgs.find((p) => p.announced_date === "2025-08-20").prog_id);
  ok(actOld.paid.length > 0 && actOld.paid.every((p) => p.basis) && actOld.paid.every((p, i, a) => !i || p.date >= a[i - 1].date), "CSL's cumulative amounts come in date order, each with its basis");
  } else skip("CSL cumulative amounts");
  const fdAct = A.activity(db, A.programmes(db, "UK", "FDEV")[0].prog_id);
  ok(fdAct.paid.length === 1 && fdAct.paid[0].value === 200832 && fdAct.paid[0].basis === "Calculated" && fdAct.daily.length === 1 && fdAct.daily[0].venue_label === "London Stock Exchange (AIMX)", "Frontier's chart adds up its daily purchase, not its shares-only running total");
  const avAct = A.activity(db, A.programmes(db, "UK", "AV.")[0].prog_id);
  ok(avAct.daily[0].price_unit === "GBp" && avAct.daily[0].price_avg === 678, "Aviva's daily price is there for its price chart");
  const shelAct = A.activity(db, A.programmes(db, "UK", "SHEL")[0].prog_id);
  ok(shelAct.daily.length === 0 && shelAct.paid.length === 0, "a waiting purchase stays out of the charts");
  ok(A.activity(db, 999999) === null, "an unknown programme gives nothing rather than an error");

  // the page code itself, drawing every company's charts into a stand-in page
  const el = () => ({ innerHTML: "", hidden: true, style: {}, dataset: {}, onclick: null, onchange: null, value: "", textContent: "", disabled: false, offsetWidth: 100, offsetHeight: 20,
    querySelectorAll: () => [], querySelector: () => el(), addEventListener() {}, getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0, bottom: 0 }) });
  const els = {};
  const page = { console, window: { innerWidth: 1200, scrollY: 0 }, NodeFilter: {}, MutationObserver: class { observe() {} },
    document: { querySelector: (s) => (els[s] = els[s] || el()), querySelectorAll: () => [], body: {}, createTreeWalker: () => ({ nextNode: () => null }) } };
  vm.createContext(page);
  vm.runInContext(grab("viewer-data") + "\n" + grab("viewer-page") + "\nthis.P = { VIEWS, S, programmes, purchases, runningTotals, cessations, filings, reviews };", page);
  let drawn = 0, problems = [];
  for (const c of A.companies(db, "ALL")) {
    page.P.S.db = db; page.P.S.prog = null;
    const data = { programmes: page.P.programmes(db, c.country, c.ticker) };
    try { page.P.VIEWS.activity(data); const h = els["#tabbody"].innerHTML; if (/NaN|undefined/.test(h)) problems.push(c.ticker + " has NaN or undefined"); drawn++; } catch (e) { problems.push(c.ticker + ": " + e.message); }
  }
  ok(!problems.length && drawn === A.companies(db, "ALL").length, `every company's Daily activity draws without an error (${drawn}) ${problems.join("; ")}`);
  if (full) {
  page.P.S.prog = null; page.P.VIEWS.activity({ programmes: page.P.programmes(db, "AU", "CSL") });
  const cslHtml = els["#tabbody"].innerHTML + els["#cPaid"].innerHTML + els["#cShares"].innerHTML;
  ok(/Cumulative consideration paid vs programme target/.test(els["#tabbody"].innerHTML) && /<polyline/.test(els["#cPaid"].innerHTML) && /<path fill="var\(--series-1\)"/.test(els["#cShares"].innerHTML), "CSL's charts draw a cumulative line and daily bars");
  ok(!/\d{4}-\d{2}-\d{2}/.test(els["#cPaid"].innerHTML.replace(/aria-label="[^"]*"/g, "")) && /\d{2}\/\d{2}\/\d{2}/.test(els["#cPaid"].innerHTML), "chart dates show as MM/DD/YY");
  ok(cslHtml.length > 0, "charts produced");
  } else skip("CSL charts");

  // New in v5: shares cancelled and average price paid on each programme, as in the app
  const five = new SQL.Database(); five.run(`create table programmes(prog_id, country, ticker, announced_date, status, max_value, max_currency, buyback_type, start_date, end_date, max_shares);
    create table snapshots(prog_id, as_of, cum_shares, cum_value, currency, origin); create table transactions(prog_id, country, ticker, trade_date, shares, value, currency);
    create table cessations(doc_id, n, prog_id, is_buyback, shares, ceased_on); create table cancellations(prog_id, kind, basis, shares, as_of);
    insert into programmes values (1,'AU','CBA','2023-08-09','COMPLETED',1e9,'AUD',null,null,null,null), (2,'UK','XYZ','2026-01-02','ACTIVE',null,null,null,null,null,null), (3,'UK','XYZ','2025-01-02','ACTIVE',null,null,null,null,null,null);
    insert into snapshots values (1,'2026-08-13',2706964,299709763.92,'AUD','reported');
    insert into cessations values (7,0,1,1,803060,'2024-04-03'), (8,0,1,1,268516,'2024-05-16'), (9,0,1,1,118000,'2024-11-18'), (9,1,1,0,15900000,'2024-04-26');
    insert into transactions values (2,'UK','XYZ','2026-02-02',1000,5000,'GBP'), (2,'UK','XYZ','2026-02-03',1000,null,'GBP'), (3,'UK','XYZ','2025-02-03',100,250,'GBP');
    insert into cancellations values (3,'Cancelled','Reported count',60,'2025-02-04'), (3,'Cancelled','From notice wording',100,'2025-02-03');`);
  const cba = A.programmes(five, "AU", "CBA")[0];
  ok(cba.cancelled.shares === 1189576 && /803,060 on 2024-04-03/.test(cba.cancelled.working), "shares cancelled adds up the buy-back counts filed on Appendix 3H, and nothing else");
  ok(Math.abs(cba.average.price - 110.718046) < 0.00001 && cba.average.currency === "AUD" && /2,706,964 shares/.test(cba.average.working), "average price paid is total paid / total shares, with its working");
  const xyz = Object.fromEntries(A.programmes(five, "UK", "XYZ").map((p) => [p.announced_date, p]));
  ok(xyz["2026-01-02"].average === null && xyz["2026-01-02"].cancelled === null, "a day with no amount leaves the average blank, and no count filed leaves cancelled blank");
  ok(xyz["2025-01-02"].cancelled.shares === 60 && xyz["2025-01-02"].average.price === 2.5, "with no Appendix 3H, only a notice's reported count is used, not its wording");

  // A database from an older version, without the newer columns and tables, still opens
  const old = new SQL.Database(fs.readFileSync(path.join(require("os").tmpdir(), "sbb_viewer_test.db")));
  old.run("drop table cessations; drop table review;");
  ok(A.cessations(old, "AU", "IPH") === null && A.reviews(old, "AU", "IPH").length === 0, "an older database without 3H or review tables still opens");
})();
