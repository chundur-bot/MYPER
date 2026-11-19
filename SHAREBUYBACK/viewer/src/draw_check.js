const fs = require("fs"), vm = require("vm"), path = require("path");
const html = fs.readFileSync(path.join(__dirname, "..", "buyback_viewer.html"), "utf8");
const grab = (id) => html.match(new RegExp(`<script id="${id}">([\\s\\S]*?)</script>`))[1];
const initSqlJs = require(path.join(__dirname, "sqljs/sql-wasm.js"));
(async () => {
  const SQL = await initSqlJs({ wasmBinary: fs.readFileSync(path.join(__dirname, "sqljs/sql-wasm.wasm")) });
  const db = new SQL.Database(fs.readFileSync(path.join(require("os").tmpdir(), "sbb_viewer_test.db")));
  const el = () => ({ innerHTML: "", style: {}, dataset: {}, querySelectorAll: () => [], addEventListener() {}, getBoundingClientRect: () => ({}) });
  const els = {};
  const ctx = { console, window: {}, NodeFilter: {}, MutationObserver: class { observe() {} }, document: { querySelector: (s) => (els[s] = els[s] || el()), querySelectorAll: () => [], body: {} } };
  vm.createContext(ctx);
  vm.runInContext(grab("viewer-data") + grab("viewer-page") + "\nthis.P={S,draw,companies};", ctx);
  const have = new Set(ctx.P.companies(db, "ALL").map((c) => c.country + "|" + c.ticker));  // CSL comes from the sample filings, which aren't in the package
  for (const [company, tab] of [["AU|CSL", "activity"], ["UK|AV.", "activity"], ["UK|FDEV", "programmes"]].filter(([c]) => have.has(c))) {
    Object.assign(ctx.P.S, { db, company, tab }); ctx.P.draw();
    const tabs = els["#main"].innerHTML.match(/data-tab="\w+" aria-selected="\w+">[^<]+/g).map((s) => s.replace(/.*>/, ""));
    console.log(company, tab, "->", tabs.join(" | "));
  }
  console.log("FDEV card:", els["#tabbody"].innerHTML.match(/<dt>Status<\/dt><dd>.*?<\/dd>/)[0], "|", els["#tabbody"].innerHTML.match(/<dt>Bought<\/dt><dd>.*?<\/b>[^<]*/)[0]);
})();
