# Share Buyback Insight: guide

## Why

To track share buybacks company by company from the companies' own notices, with every figure traceable to its source. You choose the companies by country and code. Figures follow each buyback programme from start to latest notice, whatever year it ran in. More countries can be added.

It is for **private use**. The exchanges' terms restrict automated collection and reuse, so you save notices by hand and the app only reads them. It makes no web requests. Keep the stored copies on this PC: don't share them or put them on a network drive.

## What

| Section | What it shows |
|---|---|
| Home | Amount, shares and companies buying per market, by month, with the largest buyers |
| Companies | The companies in your study; also programmes, purchases, buying by venue and cancellations. Click a row for details. With one ticker chosen at the top, **Programmes** shows that company's programmes as cards |
| Notices | Every filing read, with its full link, the figures found and the result |
| Analysis | Markets, pace, sectors, purchase prices, and share price after an announcement |
| Quality | Files to review and automatic checks |
| Tracker | One exchange at a time, programme by programme: every filing tied to its programme, with a confidence and a cross-check |
| Add data | Read filings, add programmes, changes, purchases and completions by hand, add a country |
| Library | Research report, vendor study and this guide |

At the top: **Country**, **Period** (**All programmes** by default; a calendar year or custom dates are optional), Excel report, light or dark, and **Dashboard** or **Analyst** view.

**Reported or Calculated:** each amount is marked. Reported means a notice states that figure, and it shows the page and wording it came from. Calculated means the app worked it out from notices, such as a difference between running totals or shares x average price; hover to see the working, which also appears in the side panel and Excel. Percentages and market totals are always calculated. Cancellation counts show a reported count separately from those taken from a notice's wording.

**How amounts are worked out:**
- Running totals in notices are used first, because one notice can cover many days.
- Under **All programmes**, a running total is used in full. If you choose a year or dates and a programme began earlier, the total before them is left out. Without a notice from just before them, the programme is marked **Partial**.
- Otherwise daily purchases are added up, which misses any day without a saved notice.
- In monthly charts, a programme's first running total shows as **No month**, because it covers the programme up to then. Saving earlier notices moves more of the buying into months.
- UK prices in pence are converted to pounds. If a notice states no price unit, no value is calculated and it goes to review.
- Amounts appear in the currency each notice reports them in, such as HSBC's running total in US dollars. Currencies are never added together or converted.

## How

### Start

```
python -m pip install --user openpyxl pypdf
python run_app.py
```

The page opens at http://127.0.0.1:8770, reachable from this PC only. Keep the window open while you use it.

### Read filings from your list

Use this only if your company permits it.

On **Add data**, use either of these:

**Paste a hyperlink:** paste the full link, such as `http://ffdocproxy.prod.factset.com/DocProxy/Fetch/{document ID}~0~nocache`, then press **Read**. For several, put one per line. Full links are used exactly as pasted, and no folder or address is needed. The company and date come from the document. If it can't tell the company, enter the ticker in the box or before the link.

**Excel list:**
1. Copy `templates\filings_list.xlsx` and fill in **Ticker** and **Hyperlink**, one row per filing. **Hyperlink** holds the document ID, such as `24b885ac-386e-f111-ac2c-12bc89a8f273`, or a full link. **Title** and **Country** are optional.
2. On **Add data**, press **Choose Excel file**. The list doesn't need to be saved anywhere first, and reading it again skips links already handled. Lists kept in the `filing_lists` folder also appear there with a **Read** button.

**Progress** shows a bar with the total, the number done, the file being read and the number yet to be done. Each row's result appears below it, with its link.

Filings read from a link aren't saved, in a folder or anywhere else: only the figures and the link are kept. A full link is kept exactly as given, including one behind a cell's display text or in a `HYPERLINK` formula. If a cell shows a document ID, the link is built from that ID, and any link hidden behind the cell is ignored.

**Filing date:** this comes from the document, such as the date in an RNS header under the company's name. Some notices only say "announces today" and state no date, so the app uses a **Date** column in your list if there is one, otherwise the latest purchase date, and **Notices** says so in its result. A meeting's date in the wording about the authority to buy is never used. A **Date** column gives a more exact order.

**Which market:** choose it in the selector at the top of the page, and tickers the app doesn't know are read as that market. The reference lists only hold large companies, such as the FTSE 100, so this matters for smaller ones. A ticker known only on another market keeps that market, and a **Country** column in the list always comes first. With **All markets** chosen, an unknown ticker fails and tells you what to do.

The app builds each ID's link from the document address, adding `~0~nocache`. The address is under **Document address**, and you only need to change it if it moves. 

**To start again:** on **Add data**, open **Reset** and type RESET. This wipes every filing and figure, your typed entries and prices, and `filing_links.csv`, and can't be undone. Your study list, countries, document address and Excel lists are kept.

The page shows the version running. If it doesn't match the package you moved, you're running an older copy.

Dates come from each document, so the list needs no date. If it has a **Date** column, a difference of more than a day is flagged on **Quality**.

Any filing is fine: filings without buyback wording in the title or near the top are skipped. If a link opens a viewer page, the app looks for the document behind it; if it can't find one, that row fails with the reason.

**What's kept:** the figures, the page and words they came from, and the full link, which appears on **Notices**, **Programmes**, **Daily activity**, each company's panel and in Excel. **The filing isn't saved**, so it can't open with highlights or be searched inside. A web link opens in your browser, and a file path can be copied.

**Appendix and Type:** each filing shows the form it was recognised as, such as **Appendix 3C** or **Appendix 3H**, and its type, such as **Daily buy-back notification**. A notice with no Appendix shows **None (company notice)**, and a filing that wasn't recognised shows **Not identified**; neither is guessed. They appear on **Notices** (with a filter for each), each company's panel, each filing's panel, Excel, CSV and the data viewer. The names are in `data\filing_forms.csv`, so a new market's forms need no screen change. Filings already read get them automatically, with nothing fetched again.

**Shares cancelled and Average price paid** (**Programmes**, each company's panel, Excel and CSV): both are marked Calculated and follow the Period. Shares cancelled adds up only counts a filing states: Appendix 3H buy-back cancellations or, where there are none, notices giving a count. Lapsed rights, note redemptions and "will be cancelled" wording aren't counted, and it can be lower than the shares bought when a cancellation filing hasn't been read. A cancellation belongs to the latest programme announced by its date. Average price paid is total paid / total shares, in the notice's currency, and is blank if any amount or shares are missing or amounts are in more than one currency.

**Corrections in v19:**
- A number in another convention, such as 1.234,56, is left unread and goes to review. Commas are read only as thousands separators.
- A notice reporting buying over a quarter, month or other period isn't added as a day's purchase. It goes to **Quality** as **PERIOD_PURCHASE**, to enter by hand.
- A notice that restates the size of a programme still open, and gives no dates of its own, is added to that programme and flagged **PROGRAMME_RESTATED**. A notice with its own start or end date is a new programme.
- The dates a notice's purchases cover, such as "purchased from 2 March to 6 March", are no longer taken as the programme's start and end.
- The announced size ignores an amount already spent, such as "for a total of $126.6 million".
- A buy-back cancellation is linked to the latest programme announced by its date that had bought by then.
- An Appendix 3H is recognised when its title sits below a summary page, and one read from the inbox folder now stores its cancellations.
- An amount stated under a label such as "Aggregate price paid" is kept as Reported, and the average is calculated from it.
- More currencies are recognised: HKD, SGD, CAD, TWD, JPY, CNY, CHF, SEK, NOK, DKK, INR, KRW, ZAR, MYR and THB. "5 p.m." no longer reads as pence.
- A phrase in `data\keywords.csv` with a market code in its **market** column is used for that market only. A country in `data\countries.json` can have `"date_order": "MDY"`, so 03/04/2026 reads as 4 March; without it, slash dates are day first.
- A link that gets a server error (500, 502, 503 or 504) is tried once more after 2 seconds. A file over 50 MB isn't read. `--probe` reads with the row's market, or `--country`.
- These apply to filings read from now on. Filings already in the database keep their figures until you press **Re-read this company**, which needs your document system.

**New in v20: layouts described as data, and Singapore.**
- **Why:** each exchange has its own fixed forms. Writing a new reader for each one doesn't scale, so a form's layout is now described in a file and read by one general reader.
- **What:** each file in `data\forms\` describes one layout: the phrases that identify it, the label each figure sits under, the checks to run, and what each figure is (a purchase, a running total, a cancellation, the programme). For a filing, the app takes the definitions for its market and uses the one whose identifying phrases are all present. Only a definition marked `"status": "approved"` is used. A filing no definition matches is read by the existing readers, exactly as before; UK, ASX and NZX filings are untouched.
- **First definition:** `SG_daily_buyback.json`, the SGX Daily Share Buy-Back Notice, checked against three real notices (Singtel, Hong Fok, Sarine) kept as text in `tests\fixtures\`. Singapore (`SG`, SGD) is in `data\countries.json`. `data\constituents_SG.csv` holds only those three companies until your list replaces it.
- **What is read from the SGX notice:** company, SGX code and ISIN; date bought, shares, highest and lowest price and total consideration (Reported; the average is Calculated from it); shares cancelled and shares held as treasury; treasury shares held and issued shares after the purchase; the mandate's start date and maximum shares; the cumulative shares bought.
- **Programme or mandate:** if the notice names a programme with a size, such as "S$2Bn ... Share Buy-back Programme", the purchase belongs to that programme. Its announcement isn't in the notice, so the purchase waits (see **Waiting for programme**) until you read the announcement. Otherwise the buying belongs to the shareholder mandate: the programme's Announced and Start dates are the mandate's start date, its size is the maximum number of shares, and it has no amount.
- **Cumulative shares** on the SGX form are counted from the start of the mandate, so they're kept as a running total only for a mandate. For a named programme they aren't used as its total.
- **Two exchanges:** when the overseas column of a dual-listed company has purchases, they're kept as a separate purchase under that exchange's name, in its own currency. Currencies are never added, so such a programme has no single average price.
- **Checks, shown on Quality:** **TOTAL_MISMATCH** (Section C's rows don't add up to its total, so no running total is kept), **TREATMENT_MISMATCH** (cancelled plus treasury differs from shares bought), **OFF_MARKET** (an equal access scheme purchase, which isn't read), **PURCHASE_UNCLEAR** and **FIELD_MISSING** (a purchase or a required field couldn't be read, so nothing is assumed), and **UNKNOWN_LAYOUT** (in a market that has definitions, a filing that matches none and gave no figures).
- **To add a layout:** copy a definition in `data\forms\`, change its labels, and set `"status": "approved"` once its figures agree with a sample filing. The field options are listed at the top of `sbb\forms.py`. Add its form name to `data\filing_forms.csv` so **Appendix** and **Type** show it.
- SGX's own websites (`sgx.com`, including `links.sgx.com`) are refused, like the other exchanges' sites.

**New in v28: readers for ASX Appendix 3D, 3E, 3F and 3G.**
- **Why:** buy-backs announced before 5 June 2021 were reported on Appendix 3D (changes), 3E (daily notice) and 3F (final notice), which nothing could read: their figures were left out and the filings sat in review. Appendix 3G (securities issued or transferred) shows whether a buy-back really reduced the shares on issue.
- **3E, daily notice:** the shares and amount on the previous day, the total before it, and the highest and lowest prices. **The form gives no date for the previous day**, only the date it was signed, so the purchase is dated the **trading day before** that date and the date carries a **Calculated** mark with the working (your choice, 1a). A public holiday is not known, so after one the date can be a day out: correct it with **Update a reading**. The total before the previous day is dated to the last purchase day, as in v26.
- **3F, final notice:** the total shares and amount of the whole buy-back, on the notice's date; the programme is marked Completed. Built from the layout of the scanned Infratil 3F you gave, as that PDF has no text (your choice, 2b); a scanned 3F still cannot be read (no OCR).
- **3D, changes:** each item has the terms as announced (Column 1) and the change (Column 2), and the PDF text runs the two together. A change is taken only where it can be told apart: a new period with both periods dated, or a new maximum number with both numbers given. Anything else goes to **Quality > To review** as **CHANGE_UNCLEAR**, with the item's wording and the reason given; nothing is guessed. In your CSL 3D (a broker appointment) the change goes to review.
- **3G, issues and transfers:** each issue is kept: the class, the number, the date, the class it was converted from, whether **new securities were issued or existing ones transferred**, and the company's own words. The securities on issue afterwards (Part 4) join the shares-on-issue history. Issues show on the company panel under **Issues and transfers (Appendix 3G)** and on a new Excel sheet **Issues (3G)**. They are kept apart from purchases and never netted against them. A 3G is not a buy-back notice, so the Tracker lists it as excluded.
- **Your earlier filings:** a rebuild uses the readings already stored, so filings read before v28 keep their old (empty) reading. In your data that is Pro Medicus (PME): four Appendix 3E (January 2010) and one 3F (April 2022). Open the company and press **Re-read this company** to read them with the new readers.
- **Database:** one new table, `issues` (one row per issue in a 3G). Nothing existing is changed: on a copy of a database of 3,263 filings every other table is the same after the v28 rebuild.
- **Limits:** built and tested on one real filing of each (3D CSL 2015, 3E Regal Investment Fund 2019, 3G Woodside 2026) and the 3F typed from a scan; other layouts of these forms may need adjusting. A 3G does not say in a clear order whether the issue was under an employee scheme or involved key management personnel, so those answers are not taken. The old Appendix 3C (announcement, before 5 June 2021) has no reader yet.

**New in v27: Update a reading, marked "Updated Manually".**
- **Why:** a figure read from a filing can be wrong (digits misread, a date the reader missed, a row that is not a buyback purchase), and until now the only fix was to remove the filing or wait for the reader to change.
- **What:** **Add data > Add by hand** has a fifth tab, **Update a reading**. Choose the programme, then what (programme terms, a purchase or a running total), the row and the figure. The form shows the figure as held now, the filing, page and the words it was read from. Type the new value, the **Source** (where the right figure is) and the **Reason**; both are required. **Set aside** leaves a row read wrongly out of every figure.
- **Where you start:** an **update** link on each purchase row (company panel, Purchases page, Daily activity), **update total** on Daily activity rows with a running total, and **Update a figure** on each programme card. Each opens the form with the row already chosen.
- **What can be updated:** programme type, start and end dates, maximum shares, maximum amount (with its currency), shares on issue, what happens to the shares, status and broker; a purchase's shares, amount, currency and prices; a running total's shares, amount and currency.
- **Marked everywhere:** the figure carries a purple **Updated Manually** mark (hover for when, the figure as read, the source and the reason) on the programme cards, purchases, Daily activity, Purchases page, the Tracker (whose confidence column says **Updated Manually** for the notices concerned) and the Excel report (Purchases gains a column **Updated Manually**; every update is on the sheet **Entered by hand**).
- **What follows from it:** figures the app works out from an updated one are worked out again and stay **Calculated**, with the working saying so: an average that is amount / shares, an amount that is shares x average, and the day's closing total worked out from the same notice. Totals a notice itself states are never changed by it; update them on their own row if they are wrong too. Nothing is converted between currencies.
- **The filing's reading is never changed.** The update is kept beside it and applied again after every rebuild, and after any new filing for the company is read, so it stays in force. **Edit** puts it back in the form; **Undo** asks for a reason, brings the filing's figure back, and keeps the update in the history.
- **Checked at every rebuild,** on **Quality > To review**: **UPDATE_NOT_FOUND** (the row it updates is gone, for example its filing was removed; the update is kept, not applied), **UPDATE_NOW_READ** (the filing now reads your value, so the update can be undone), **UPDATE_READ_CHANGED** (the filing now reads something else; your value stays in force until you look).
- **Database:** no new table or column. Updates are kept with the entries made by hand (the two tables v25 added): kind "update" in `hand_entries`, every change in `hand_log`. An updated running total or purchase amount is stored with origin "updated", which is shown as Updated Manually. With no updates, a v26 database is unchanged by v27 (checked on a copy of 3,263 filings).
- **Limits:** the program your screenshots come from (with Export to CSV) is not part of this app; it reads the same tables, so it shows the updated figures, but not the mark. Read-only copies show the marks and hide the update links.

**New in v26: running totals from ASX daily notices dated correctly.**
- **Why:** an ASX daily buy-back notice (Appendix 3C) states the total bought "before the previous day" and the purchase on that day. The app dated that "before" total one calendar day before the purchase, so a Monday purchase put a total on the Sunday (445 totals on a database of 3,263 filings fell on a weekend), and after a day with no buying the same total appeared twice on two dates.
- **What:** the "before" total is now dated to the programme's **last purchase day** before the notice's purchase, where the total held for that day agrees with it. Where both exist for a day, the figure the notice states (Reported) is kept and the one worked out (Calculated) is dropped. With no earlier purchase it is dated the **weekday** before; a total of 0 on a programme's first notice is not kept. A weekend date is never written.
- **The closing total for each day** (stated "before" total + that day's purchase, Calculated, with its working such as "AUD 16,925,161.47 before that day + AUD 11,653,240.31 on the day") was already kept and still is. It never replaces a total a notice states for the same day, such as a final notice.
- **Disagreements go to Quality > To review:** **TOTAL_GAP** where the notice's "before" shares differ from the total held after the last purchase read (notices for days in between are probably missing, or a notice was corrected); that total is dated the weekday before and kept as Reported. **TOTAL_DIFFERS** where the shares agree but the amount differs (usually by cents); it is the same day, and the notice's amount is kept.
- **Your data:** nothing is read again. At the first start the figures are rebuilt from the readings held, and only running totals change. On the database tested (3,263 filings): 868 totals on wrong dates removed (445 of them on Sundays), 5 added on corrected dates, 843 on the same date now carry the notice's stated figure in place of the worked-out one (the figures agree to the cent), 0 on a weekend, and every programme's latest total reaches its latest purchase. 35 TOTAL_GAP and 10 TOTAL_DIFFERS items are added to review. Purchases, programmes, cancellations, share counts and evidence are unchanged. No table or column is added. A copy of the database goes to `backups\` first, as at every rebuild.
- **Limits:** a final notice dated after the last purchase states the same total on its own date; both are kept. UK programmes whose notices state no running total still have none; nothing is worked out for them.

**New in v25: Add by hand, for every market.**
- **Why:** in some markets a programme and its completion exist only as announcements in prose that no reader can take apart (NZX programmes and completions among them), and some filings are not in your document system at all. Add by hand took purchases only, asked for a country rather than the exchange, had no source, and its entries could not be listed, changed or deleted. The Tracker never saw them.
- **What:** **Add data > Add by hand** now takes four kinds of entry: **Programme announcement**, **Change of terms**, **Purchase** and **Completion**. The first field is the exchange with its country ("NZX · New Zealand"); a purchase also asks which exchange the shares were bought on. **Source** is required on every entry: a link, or where it came from ("NZX announcement of 2 March 2026"). Below the form, every entry made by hand is listed with **Edit** and **Delete**, followed by the deleted entries and the history.
- **Sizes as stated:** a programme's maximum can be shares, an amount with its currency, or **% of shares** ("up to 0.5% of its ordinary shares"); fill in whichever the announcement states. A percentage stays a percentage: no number of shares is worked out from it. **Intended number** ("approximately 260,000 shares") is kept apart and is never used as the limit.
- **Nothing is worked out for you:** the end date is typed by you. If the announcement gives a period ("up to 12 months from the date of this notice"), type the date and put the wording in **Note**. A purchase with an average price but no amount gets its amount as shares x average price, marked Calculated.
- **Marked everywhere:** every figure from an entry made by hand carries a purple **Entered by hand** mark; hover over it for the source. It shows on the programme cards and company panel (announced date, runs, size, intended number, status, what happens to the shares), the purchase tables, Daily activity, Periods, the Tracker (whose confidence column says **Entered by hand**), and the Excel report, which also gains a sheet **Entered by hand**. Clicking an entry's source shows what was typed and its source; there is no filing text to highlight.
- **Edit and delete:** **Edit** puts the entry back in the form; saving rebuilds that company's figures. **Delete** asks for a reason: the entry leaves every figure and stays in the history with the date and reason. Every add, edit and delete is kept with the old and new values.
- **A hand entry and a filing read:** both are kept. Where they state different figures for the same programme or purchase day, the pair goes to **Quality > To review** as HAND_DIFFERS, and where both report the same day the filing's figure is the one counted. Where a filing reports buying the same day on another exchange, both are counted and you are asked whether it is the same purchase (HAND_TWICE). **Mark as checked** keeps it checked.
- **A completion** marks the programme Completed on its date. If the announcement states final totals, type them; if not, the totals stay as the purchases read.
- **Your earlier entry:** purchases typed on Add by hand before v25 were kept in `inbox\<market>\manual_entries.csv`. At the first start, each one moves into the new list once, with the source "Typed on Add by hand before version 25 (no source was recorded)". Edit it to add the source. The file is kept beside, renamed `manual_entries_moved_to_Add_by_hand_<date>.csv.bak`, so it isn't read twice; if you copy the old file back into the inbox, its rows are not added again.
- **Only you:** in the read-only team copy, Add data stays hidden and every change is refused. Hand entries show there with their mark.
- **What changed in the database:** two new tables, `hand_entries` (what you typed and its source) and `hand_log` (the history), and four new programme columns: `max_pct`, `intended_shares`, and `terms_doc` and `status_doc` (which filing or hand entry the terms in force and the status came from). Each entry is also stored as a filing reading, so rebuilds, the Tracker and Periods treat it like a filing read. On the database tested (3,263 filings) every figure, programme, purchase, review item and Tracker row is the same as in v24.
- **Limits:** a percentage size cannot be compared with what was bought, so **Used** stays blank for it. The **Fill in** helper, which would fill the form from a pasted announcement for you to check, is agreed for later, once there are 5 to 10 real announcements per market to test it on. Checked by script, including the page drawn on a copy of a database of 3,263 filings; not seen on a screen.

**New in v24: a read-only copy for the team, a faster start, and housekeeping.**
- **Why:** you read the filings; your team only views the figures. A database file shared in OneDrive must never be opened by several people at once, so the team gets a published copy and a way to view it that cannot change it.
- **Publish a copy (you):** in a Command Prompt in the app's folder run `python -P maintain.py publish "<shared folder>"`. It writes `buyback_published.db` there in one step, so a reader always opens a whole file, checks the copy before publishing it, and keeps the last 5 published copies in a `history` folder beside it. Your `buyback.db` is only read. The folder is remembered: next time run `python -P maintain.py publish`. Publish again whenever you have added filings.
- **View it (the team):** each person unzips the app and runs `python -P run_app.py --read-only "<shared folder>"` (the folder is remembered: afterwards `python -P run_app.py --read-only`). The app copies the published file to that PC's temporary folder and works on the copy, so the shared file is never written to or locked. A yellow **Read-only copy · published <date>** label shows at the top. **Add data**, **Manage tickers**, and every Remove, Delete and Read button are hidden, and the app refuses any request that would change data. When you publish again, the label's button reads **Load the newer copy**.
- **A faster start:** the app used to rebuild every programme from the stored readings at each start. It now does so only when something they depend on has changed: the version, the filings held, or the company lists and rule files in `data\`. On a database of 3,263 filings a start with nothing changed takes 0.04 seconds of work against 1.9. `python -P run_app.py --rebuild` forces a rebuild.
- **Hong Kong daily report, your companies only:** a daily report lists every company that bought (about 100). From now on only companies on your Hong Kong company list (`data\constituents_HK.csv` or the study list) are kept, which is what stops the database growing by about 1.4 MB a report. The result line says how many were left out. To include a company, add it to the list and use **Read again** on the report. This is the `"report_companies": "list"` line for HK in `data\countries.json`; remove the line to keep every company.
- **A purchase notice's dates are not the programme's.** A UK weekly notice says "from 14 September to 18 September": the days it covers. Those were stored as the programme's start and end, so **Runs** showed one week (Legal & General, Galliford Try). They are now left out, for new readings and for the readings already stored, without reading any filing again. An announcement's own dates are kept.
- **Housekeeping, only when you run it:** `python -P maintain.py backups` lists the copies in `backups\` with their sizes; `python -P maintain.py backups --keep 5` deletes all but the newest 5 after showing them and asking you to type YES; `python -P maintain.py compact` gives back unused space in `buyback.db` (it saves a copy in `backups\` first; close the app before).
- **What changed in the database:** one new small table, `app_state`, which holds when the figures were last rebuilt and, in a published copy, when it was published. On the database tested, two UK programmes lost their wrong start and end dates (GFRD announced 09/17/2025, LGEN announced 09/14/2026). Nothing else changed.
- **Not built: compressing the stored readings.** It would save about 8 MB in 19, but every stored reading would be rewritten in a form that versions 21 to 23 cannot open. Say if you still want it.
- **Limits:** read-only mode shows the copy as it was when the app started or when **Load the newer copy** was pressed; it does not follow your database minute by minute. The team needs Python and the app's folder on their own PC. Before sharing, confirm that giving the team these figures is within your company's feed licence. Checked by script, including a publish and a read-only session on a database of 3,263 filings; not seen on a screen.

**New in v23: the periods of a programme whose terms changed.**
- **Why:** a buy-back can be renewed for another year, have its end date moved, or have its size raised, all under the same original announcement. The card showed only the newest dates and target beside purchases going back to the start, so **Runs** and **Purchases read** did not agree (Kogan, KGN: Runs 05/13/2025 to 05/12/2026, purchases from 05/12/2023).
- **What:** on a programme whose terms changed at least once, **Runs** now shows the whole span with the number of periods, and a **Periods** table sits under the card: one row for each period with its dates and target as that filing stated them (Reported), the shares bought in it, the share of the target used (Calculated, with its working), and the date its filing was made. A change inside a period, such as "size AUD 1,500,000,000 changed to AUD 2,500,000,000", is listed under that period with its date. The newest period is highlighted. Click a period to open its filing. A programme whose terms never changed looks as before.
- **Where:** the programme cards (**Companies > Programmes** with a ticker chosen), the company panel, and the Tracker's programme panel.
- **A period** is one start date. A filing that keeps the start and changes the end or the size is a change within that period. A filing with a new start begins a new period. A purchase belongs to the latest period that had started by its date and had not ended.
- **Used:** a maximum in shares is a limit for that period (the ASX 12-month limit), so it is measured against the period's own purchases. A size in money is the programme's whole size, so it is measured against everything paid from the first purchase to the end of that period, and only when all of it is in the size's currency.
- **Purchases not read:** when the filings' own running or final total is more than the purchases read add up to, the table says how many shares are in notices not read yet (KGN: 414,406).
- **Nothing new is stored.** The periods are worked out each time from the readings already kept for each filing. No filing is read again, the database gains no table or column, and the programme row still holds the newest terms, so every other page is unchanged.
- **Limits:** terms are taken from forms (ASX Appendix 3C, Singapore and Hong Kong forms) and from announcements and changes of terms. A purchase notice in prose is left out, because the dates it gives are the days it covers. A change is shown as the filing states it, so a misread size in one filing shows as a change. The Excel report doesn't list periods yet. Checked by script on a database of 3,263 filings (16 programmes have periods), not on a screen.

**New in v22 2: seventeen faults found in a review of v22 1, all in the Hong Kong work, are corrected.** Use this version, not v22 1, before loading any Hong Kong filing.
- **Daily report purchases are counted.** The report says the buying was under a repurchase mandate but not the mandate's date. Such a company is now shown as **Mandate, date not stated**, and its purchases are in every total. They are no longer left waiting for a programme. When a Next Day Disclosure Return for the company is read, its purchases and the report's join the one mandate, by purchase date, whichever was read first, and the result is the same after a restart.
- **A return that only cancels shares is kept**, with each cancellation's count and dates.
- **Shares awaiting cancellation are a balance.** Each return states the whole balance, so the latest return's figure is shown; returns are never added together.
- **An Excel report is recognised by its content**, so a document-system link with no file ending, or one the server labels loosely, is read.
- **A Hong Kong code with leading zeros** (02429) is the same company as 2429. This is set for Hong Kong in `data\countries.json` (`"code_zeros": "ignore"`); other markets' codes are left as written.
- **A sum is Calculated.** When a day's purchase is reported in several rows (two mandates), its amount is the sum of those rows: marked **Calculated**, with the working, never Reported.
- **Class of share** (Ordinary, H shares, A shares, WVR ordinary) is kept with each Hong Kong purchase and shown beside the venue. On the Tracker, when a company bought two classes, the shares counted are the class bought on the home exchange, and the other is listed as **Other classes bought (not added)**.
- **Two mandates in one return:** its purchases are shown under the later mandate, and no running total is kept from that return, because each total covers one mandate only.
- **The rule for a missing treatment is data:** `data\treatment_rules.csv` holds the Australian rule, with an `except_tickers` column for a company it doesn't apply to, such as one incorporated outside Australia.
- **Also corrected:** a numbered row printed with no space after its number is read; a purchase **by private arrangement** or **general offer**, or one whose prices and amount are in different currencies, is not added and goes to review (**HK_OFF_MARKET**, **HK_CURRENCY_MIXED**); the repair of a split word only rejoins a capital first letter ("T otal"), never "a mount"; false **HK_NO_OTHER_MATCH** review items are no longer left while a paired UK company is rebuilt; a daily report's result line says how many companies it held; the Tracker says why **Spent** is empty when a running total states shares only; the first-start copy of the database is taken before the app opens the file.
- **What changed in existing data:** two new empty columns (`transactions.also_in`, `transactions.security`), and the Rule treatment on Australian programmes that had none. Nothing else. Checked again on the same database of 2,601 filings.
- **Limits:** on the main Programmes and Companies pages, a company's A and H shares are still added into one share count (the Tracker keeps them apart). A purchase under the earlier of two mandates is shown under the later one. Nothing here was seen on a screen; it was checked by script.

**New in v22: Hong Kong, phrase files, a Filing types page, cancelled counts, and a separate layout tool.**
- **Why:** to read Hong Kong buybacks, to show what each market files and whether this tool reads it, and to make a new market's rules a file you copy in. Nothing here changes how Australia, New Zealand, the UK or Singapore were read, except where listed under **What changed in existing data**.
- **Hong Kong (HK, HKD)** is a new market in `data\countries.json`, with `data\constituents_HK.csv` (139 companies from the sample reports; your list replaces it). Three kinds of filing are read:
  - **Next Day Disclosure Return (form FF305)**: one purchase for each day, exchange and currency; shares for cancellation or treasury; the mandate's date, size and amount used; the shares cancelled on each cancellation date; and the balances. The figures come from Section II (the repurchase report). Section I B (shares bought but not yet cancelled) is used to cross-check Section II and is never counted as purchases. A return that reports no repurchase (a share issue, a sale of treasury shares) is left out as **Not a buyback filing**.
  - **Monthly Return (FF301)**: counts only, with no price or exchange. It is kept as repurchase and cancellation events against the month's balances, never as purchases, so a day already reported is not counted twice.
  - **Daily Share Repurchase Report** (an Excel file listing every company that bought): each company's rows become a filing of their own, with the report's link. Read it by link like any filing. An old `.xls` file needs the `xlrd` package (`python -m pip install --user xlrd`); a `.xlsx` file needs nothing extra, so you can open an `.xls` in Excel and save it as `.xlsx`.
- **Currency and exchange:** one company can buy on several exchanges and in several currencies on a day. Each purchase keeps its own exchange (HKEX, New York Stock Exchange, London Stock Exchange, Shanghai and so on) and currency. **A and H shares** are separate rows with their own exchange and currency. Amounts are never added across currencies: the Tracker sums the home currency (HKD) and lists any other currency beside it as **Spent in other currencies (not added)**, and a notice with several currencies shows **Several currencies, not added** in place of an amount.
- **Not stated is never assumed:** if the report gives cancelled or treasury shares as blank, the figure is **Not stated** and the row goes to review (**HK_TREATMENT_NOT_STATED**). The other review kinds for Hong Kong: **HK_TOTAL_DIFFERS**, **HK_TREATMENT_DIFFERS**, **HK_BALANCE**, **HK_PARTB_DIFFERS**, **HK_PRICE_OUTSIDE** (the amount paid divided by the shares is outside the stated price range), **HK_ROW_UNCLEAR**, **HK_CURRENCY_MIXED**.
- **Also in another market's filings:** `data\cross_listings.csv` pairs a Hong Kong code with the same company's code elsewhere (HSBC 5 and HSBA, Standard Chartered 2888 and STAN, Prudential 2378 and PRU). A Hong Kong purchase on another exchange is marked **Also in UK filings** on the daily purchases table when the UK notices hold the same purchase (the same date, venue and shares, or the same total shares for the day). A purchase with no clear match stays unmarked, and goes to review (**HK_NO_OTHER_MATCH**) only when the UK has buying for that company on nearby days. Add a pair to the file to cover another company.
- **Library > Filing types:** for each market, the documents it files about a buyback, a short description and whether this tool reads them (**Yes**, **Partly**, **No**), built from `data\filing_types.csv`. The descriptions were approved by you on 16 November 2026; to mark a row for review again, set its status to Draft in Excel and a note appears on the page.
- **Phrase files:** the reader also takes every `.csv` file in `data\keywords\`, in the same format as `data\keywords.csv`, so a new market's phrases are a file you copy in. No restart. The Data dictionary page lists them too.
- **Cancelled shares, per purchase:** on a programme whose shares are cancelled, each purchase in the daily purchases table shows a **Cancelled** count equal to the shares bought, marked **Calculated** with its working, because no notice states a count for each purchase. For Australia the mark is **Rule**: Australian companies cancel the shares they buy back (Corporations Act 2001, section 257H), so a programme whose notices don't say so shows treatment Cancelled with the text "Rule, not stated in the notice". A notice's own wording always replaces a rule.
- **Singapore:** a notice whose PDF prints a word with its first letter apart ("T otal") is now read, and a mandate start date that falls after the description is found. The Micro-Mechanics notice is a fourth test sample.
- **What changed in existing data:** the first time v22 starts, it saves a copy of your database in `backups\` (named `..._start_of_2026_11_16_v22_2.db`), then reads your saved filings again as every version does. Compared with the same database before, the only changes are: two new empty columns (`transactions.also_in` and `transactions.security`), and the treatment of Australian programmes that had none (18 of 38 in the database tested), now Cancelled with the Rule text. No filing, purchase, running total, cancellation count, review item or evidence was added, removed or altered. The Tracker tables are rebuilt as always.
- **Layout tool (separate):** `SHAREBUYBACK_layout_tool\` is a program of its own that asks Claude, through your company's gateway, to draft a layout file or phrases from sample filings. This app contains no AI and calls none. The tool never extracts a figure: the app's own reader does, and the tool shows each figure beside its source words. A draft is always **draft**; you set **approved**. Its connection (gateway address and token) is set as environment variables on your PC and is kept nowhere. See its `README_layout_tool.txt`.
- **Limits:** Hong Kong is read from the daily report, the Next Day Disclosure Return and the Monthly Return only; the circular and explanatory statement for a mandate are not read. A programme in Hong Kong is the shareholder mandate, dated by its resolution, or shown as Mandate, date not stated when only the daily report has been read; a return that reports two mandates is stored under the later one and says so. The daily report's footnote counts (HSBC, Standard Chartered) are read by footnote number. The cross-listing pairs are the three in the file. The dark view and the new screens were checked by script, not on a screen. Layout files for ASX and NZX forms, and cessation notices in other layouts, are not built.

**New in v21 2: fuller Tracker panels, and Dark or Light view.**
- **Notice panel:** click a notice on **Tracker > Notices**, or in a programme's timeline, to see what the standalone viewer showed: its title; its type and what the type is known from; its confidence and, when low, the reason; which reader read it; the programme it belongs to and how it was tied; a link that opens the original filing through your document system; and **every extracted field**, each with its name on the form beneath it where the filing is an ASX form. **Open in the app** shows the filing with the source text of each figure marked.
- **Programme panel:** **Every field** of the programme, with the ASX form's own field names where the programme comes from a notification form; the cross-check with its detail under each result; and a timeline of its notices with shares, amount, running totals and planned amount in full.
- **Dark or Light view:** the sun button at the top right switches the whole app, the side panels and the **Manage tickers** page. The choice is remembered in this browser. Light view is unchanged from v20. A PDF page in the filing viewer stays white, as the document is.
- **Limits:** the dark colours were chosen by rule and checked by script, not by eye on a screen.

**New in v21: the Tracker section, and the AI drafting tool removed.**
- **Why:** to follow each buyback programme from its announcement to its end in one place, and to see how far each figure can be relied on. The tracker used to be a separate tool with its own database and viewer file; it is now a section of the app and uses the app's database.
- **What:** a new **Tracker** section. It shows **one exchange at a time**, the one chosen at the top of the page, programme by programme. With **All markets** chosen it asks you to pick an exchange. A ticker chosen at the top narrows it to that company. The period at the top doesn't apply: every filing held is included.
- **Overview:** six counts for the exchange (programmes, in progress, completed, notices in scope, low confidence, cross-check differences), then one row per programme: announced date, status, planned amount, shares bought, amount spent, share of the planned amount used, last purchase, notices, and the cross-check result. Click a programme for every field, its changes to terms, its cross-check and its notices in date order. Click a notice there for every field read from it. **Not covered for this exchange** lists that exchange's gaps.
- **Programmes:** the same rows with every field as a column. **Notices:** every in-scope filing with its type, confidence, figures, programme and how it was tied; click one for every field read from it. **Cross-check:** every check. **Excluded:** filings left out, with the reason. Each table has search, filters, sorting and **CSV**.
- **Confidence:** **high** means read from a fixed form or labelled template (ASX Appendix 3C and 3H, NZX Capital Change Notice, a layout in `data\forms\`). **medium** means read from prose by pattern (LSE notices, company letters). **low** means a required figure was not found or a figure failed a check; the figure is left blank, never guessed. **n/a** is a completion or termination letter, where no figures are expected. **not read** means nothing has been read from the filing.
- **Status:** **Completed** (a final notice or completion letter was read), **Target reached** (spent is at least 99.5% of the planned amount, with no final notice), **Ended, no final notice** (the end date has passed, or a later programme of the same company is buying), otherwise **In progress**.
- **How a notice is tied to a programme**, recorded for each notice: the ASX form's field 1.4c; a programme date stated or cited in the notice; a company announcement within 10 days of a programme's notification; a letter restating the size of a programme still running; a change to terms, which joins the latest programme announced before it; otherwise the latest programme announced on or before the purchase. A notice that fits none is kept under **Programme not identified**.
- **Cross-check:** each programme against the running totals and final notices in its own filings: purchases before the first running total, shares and amount between running totals, and spent against the planned amount. A difference is listed and never applied. No outside source is compared.
- **Reported or Calculated:** **Spent** is Reported when it comes from a final notice or a running total, and Calculated when it is the sum of the purchases read. **Used** is always Calculated (spent / planned amount) and only when both are in the same currency. Amounts are never added or converted across currencies.
- **Scope:** on-market buybacks only. Off-market, tender offer, employee share scheme, minimum holding and selective buybacks are listed under **Excluded**.
- **Where it is kept:** in `buyback.db`, in tables whose names start with `tracker_`. They hold nothing new: they are worked out from the readings already stored, and rebuilt in full whenever a filing is added, read again, moved, removed or deleted with its ticker, and when the app starts. **Refresh** rebuilds them on demand. The tracker fetches nothing and keeps no filing text. While a list is being read the tracker waits and says so.
- **Excel:** the **Excel** button on the Tracker section writes that exchange's tracker to `reports\buyback_tracker_<code>_<date>.xlsx`: Summary, Programmes, Notices, Cross-check, Excluded.
- **Removed: the Layouts section and its AI connection.** The app no longer drafts a layout with an AI model, has no place to enter a Base URL, Auth token or API key, and sends no filing text anywhere. `sbb\ai_draft.py`, `sbb\drafts.py` and `data\ai_settings.json` are gone, and the `anthropic` package is not needed. Layouts already approved in `data\forms\` are still read automatically, and a new one is added as a definition file (see **To add a layout** above).
- **Limits:** the tracker shows only what the app has read, so a filing missing from the app is missing here, and a misread carries through until the filing is read again. Most LSE programmes are known only from the date cited in purchase notices, so they have no planned amount. A company letter with no programme date can start a programme of its own when it matches none by date or size. The screens were tested with scripts; the layout on screen has not been checked by eye.

**New in v20AI 3: checks on every filing read.**
- **Why:** a figure read from the wrong place should be caught before anyone relies on it.
- **What is checked**, for every filing and whichever reader read it: the filing date and each purchase date are real dates, not in the future, and the purchase isn't dated after the filing; shares are a whole number above zero; prices and amounts are above zero; the lowest price isn't above the highest; the average price (amount paid divided by shares) sits between the lowest and highest price, with 2% allowed for duties and fees; an amount has a currency; shares bought aren't more than the shares in issue; a running total isn't smaller than the day's purchase or above the stated maximum; a programme doesn't end before it starts.
- **What happens on a failure:** nothing is changed or dropped. The filing is marked **To review** and the failure appears on **Quality** as **CHECK_FAILED**, in plain words.
- These apply to filings read from now on. Filings already in the database are checked when they are read again.

**New in v20AI 9: the Manage tickers page.**
- **Why:** to see at a glance which exchanges and tickers the database holds, and to take one ticker out with everything read for it.
- **What:** a page of its own at `http://localhost:8770/manage`, opened with **Manage tickers** at the top right of the app. It lists every exchange with its tickers: filings, programmes, purchases, first and latest filing dates, items to review, and why the ticker is on the list (Index list, Study list, or Filings only). **Find** filters by code or name, **Exchange** shows one exchange, and the column headings sort. Tickers with nothing held are hidden until you tick **Show tickers with nothing held**.
- **How to delete:** press **Delete** on a ticker's row. The box shows what will go; type the ticker's code to confirm. It deletes that ticker's filings, programmes, purchases, running totals, cancellations, cessations, source text and review items, on that exchange only. A ticker on your study list is taken off it. A ticker on the index list stays on that list with nothing held.
- **Its links:** left as it is, the links are remembered as removed, so a list read again does not bring the filings back. Tick **Also forget its links** if you want to read them again later.
- **What if you delete the wrong one:** before every delete, a full copy of the database is saved in the `backups` folder, named with the date, time, exchange and ticker. To undo, close the app and copy that file over `buyback.db`. The copies are never cleared by the app; delete old ones yourself when you no longer need them.
- **Limits:** it cannot be used while a list is being read. Files and typed entries in the `inbox` folder are read again at restart unless you also remove them there; the box says so when a ticker has any. Entered prices are not touched.

**New in v20AI 8: the code you give, moving a filing, and three reading fixes.**
- **Why:** Aviva's programme announcement was read under the code AVIVA while its purchases were under AV. The app treats two codes as two companies, so the announced size never reached the programme that holds the buying.
- **The code you give is used.** A link's code is taken as you give it whenever the filing states none (UK announcements state none). Only a filing that states a different code of its own (ASX and NZX forms) is held back, under **Quality** as COMPANY_DIFFERS, so a mistyped code can't add one company's figures to another.
- **A code not in your company list is asked about first.** When a list or pasted links carry a code that isn't in the market's company list, nothing is read until you answer: the message names the code and the closest entries ("AVIVA is not in the UK company list. Did you mean AV (Aviva)?"). **OK** reads anyway and adds it as a new company; **Cancel** stops so you can correct the code. Re-reads don't ask.
- **Move a filing to another code.** Each link filing has a **Move** button, on the company's panel under **Notices** and at the top of the filing's own view. Type the right code: the filing's figures leave the old code and join the new one, both are settled again by filing date, and nothing is read again. The code must be in that market's company list. If the old code was in the list only because of that filing, it is taken off.
- **Reading fixes** (from Aviva's announcement of 5 March 2026): "to be completed by {DATE}" gives the programme's end date and "agreement with {NAME} (" gives the broker, both as rows in `data\keywords.csv`; and a number of shares that is the shareholders' general authority ("general authority to repurchase up to 267 million Shares granted by its shareholders") is no longer taken as the programme's maximum shares.
- **What to do for Aviva:** open AVIVA, press **Move** on the announcement and type AV. Then **Re-read this company** on AV to pick up the end date and broker.

**New in v20AI 7: Purchases by programme, year, month and date.**
- **Why:** **Companies > Purchases** was one flat list, a row per purchase. The grouped view existed only on a company's panel.
- **What:** the tab now opens **Grouped**. With one ticker chosen it shows each programme, then each year, then each month, then every date. With **All tickers** each company comes first, closed until clicked. Every line shows its days, shares and amount, marked Calculated, adding up the rows under it. Amounts are given per currency and never added across currencies. Purchases waiting for a programme document are listed and marked, but not counted. Purchases with no programme sit under **Programme not identified**.
- **How:** click a line to open or close it; **Open all** and **Close all** do every line. The latest programme and its latest year start open. Each date has a **source** link that opens the filing with the figure highlighted. **Flat list** at the top right gives the earlier table, for sorting and filtering across companies. **CSV** in either view downloads a row per purchase with Programme announced, Year and Month columns, for a pivot table in Excel.
- **What if:** the From and To dates and the ticker at the top apply as before. It is a screen change only: nothing in the database changes and nothing needs reading again.

**New in v20AI 6: an increase to an existing programme.**
- **Why:** a company can raise the size of a programme that is already running. Such a notice was read as a new programme of the increase alone (seen in Aristocrat's notice of 15 May 2023: "an increase to its existing on-market share buy-back program by up to a further $500 million. This brings the total program size to up to $1.5 billion").
- **What happens now:** a notice whose wording raises an existing programme's size is an update to that programme. It joins the company's latest programme announced by that date and starts no new one. The new total it states becomes the size (Reported), and a new end date is taken too. The programme keeps its original announced date. Its card shows a line under the size, such as "Size raised to AUD 1,500,000,000 on 05/15/2023, an increase of AUD 500,000,000". **Notices** lists the filing as **Programme update**.
- **Only the increase stated:** if the notice gives the increase but no new total, nothing is added up. The size is left as it was and the filing goes to **Quality** as **SIZE_INCREASE**.
- **Wording:** the phrases that mark an increase are the `programme_increase` rows of `data\keywords.csv`, so new wording is a row in Excel. "will run up to {DATE}" is added to the end-date phrases.
- **Removing that filing** puts the programme back to its earlier size and end date, and takes the line off the card.
- Filings read before this change need reading again; the extra programme then goes.

**New in v20AI 5: the older ASX form, and reading everything in review again.**
- **The ASX form headed only "Notification of buy-back":** some ASX filings are the Appendix 3C form without the words "Appendix 3C" on any page (seen in Commonwealth Bank's final notification of 28 June 2023). They were read by the general reader, which took a sentence about the programme's size as a new programme. They are now read by the ASX reader, so a final notification updates the programme it belongs to, with its total shares, total consideration, broker, dates and completed status. Filings read before this change need reading again.
- **Read all filings in review again:** **Quality > To review** has a button that fetches every filing listed there again from its link and reads it with the current reader and approved layouts. A filing that now reads cleanly leaves the list. It covers the market and ticker chosen at the top. Items you marked as resolved, filings you removed, and purchases only waiting for a programme document are left alone. It needs your document system, and each filing's figures are replaced by the new reading.

**New in v20AI 4: missed filings found from the running totals.**
- **Why:** if a filing between two others is left out of your list by mistake, the day's purchase is missing, and nothing else would say so.
- **What:** where two filings of a programme each state a running total of shares, the rise between them should equal the purchases read for the dates in between. **Quality** shows **Purchases missing between filings** when the purchases read fall short, with the two dates and the number of shares not covered. It shows **Purchases exceed the running total** when they add up to more, which points to a misread or a purchase counted twice.
- **What it can't tell you:** which day inside the two dates is missing, or how many filings. It needs running totals, so it works for ASX daily notices, SGX mandate notices and UK notices that state a total; a series of notices giving only each day's purchase can't be checked this way.
- **Nothing is changed.** Programme totals already come from the running totals, so they stay right; the check only says a filing is missing. It runs on the figures already in the database, so nothing needs reading again. Purchases waiting for a programme document are left out.
- Shares only: running totals of money aren't compared, because duties and fees make them differ.

**New in v20AI 3: ticker selector, and programme cards.**
- **Ticker selector:** beside the market at the top of every page. It lists the companies of the chosen market that have a filing or programme saved. **All tickers** shows everything, as before. Choosing one limits Home, Companies, Notices, Analysis, Quality and the Excel report to that company. Changing the market sets it back to **All tickers**.
- **Programme cards:** with one ticker chosen, **Companies > Programmes** shows a card for each announced programme, as in `viewer\buyback_viewer.html`: Status, Type, Runs, Target, Broker, Bought, Used of target, Shares cancelled, Average price paid, Purchases read, Shares, and Shares on issue, each marked Reported or Calculated. **Purchases and notices** opens the company's panel. With **All tickers**, the table of all programmes is shown as before.

**Look:** the app uses the same light colours as the Tender capture tool. There's no dark mode.

**Duplicates:** the same link, or the same file under another link, is read once. A purchase date and venue, or a running total's date, is held once however many filings repeat it. Two filings of the same type on one date are flagged **Possible duplicate** on **Quality**, and nothing is deleted.

**Checks:** a filing naming a different company from your list isn't added and goes to **Quality**. If your list's date differs from the filing's by more than a day, the filing's date is used and it's flagged there.

**Allowed addresses:** the filing location you enter, addresses in `data\allowed_hosts.txt`, internal addresses, file shares and mapped drives. Exchange sites are always refused, including through a redirect. Reading stops after 5 failures in a row.

**From the command line:** `python fetch_from_list.py filings.xlsx` does the same, and `--probe 3` tries three rows and keeps nothing.

### Charts and daily activity

Go to **Companies > Daily activity**, or use **View charts and daily activity** on a company's panel, and choose a programme:
- **Cumulative consideration paid vs programme target:** the target is drawn only if it's in the same currency as the spending. A cap in shares compares cumulative shares instead.
- **Daily shares bought back:** stacked by venue.
- **Daily average price paid:** one chart per venue, because venues can use different currencies.
- **Date-wise table:** purchase date, filing date, venue, shares, prices, amount and totals so far, each marked Reported or Calculated. It's also in Excel.

Purchase dates come from the filings. Only dates with a saved notice appear, so a full daily history needs every daily notice in your list.

### Backfilling a company

Each company's panel shows every programme on its own card: its terms, what was bought, how much of the announced size is used, and its charts and daily activity.

Lists can be in any order. When a list finishes, the app rebuilds each company's programmes by date, so the result is the same as reading oldest first. A notice that names no programme joins the latest one announced by its date. Include each programme's announcement in your list, not just the daily notices.

**Quality** flags a purchase, with the reason **NO_PROGRAMME**, if it falls before any announcement read, or after a programme's end date with no later announcement read. Both usually mean an announcement is missing from the list. Add it and read the list again, and the flag clears. If an announcement states no end date, the second check can't run. A programme's status comes only from the notices read, so one can show as Active after it has ended until its closing notice is in the list.

Filings can be read back and forth, across different lists and days. Each company is settled by filing date, so the latest filing overwrites. On one day, a correction follows what it corrects.

Filings that don't look like buybacks are skipped and remembered: results updates and director notices (Appendix 3X, 3Y, 3Z) are skipped even if they mention a buy-back. **Add data** lists them with their heading and link; if one is a buyback filing, press **Read anyway**.

**Removing a filing:** if an irrelevant filing is captured, press **Remove** on **Notices**, on **Quality > To review**, on the filing's panel, or beside it on the company's panel, then click again to confirm. To remove several, tick them on **Notices** and press **Remove selected**. A programme that only a removed filing created goes with it; a company's programme card has **Remove this filing** for that. Its figures go, and its company is reconciled by filing date, so anything it had overwritten comes back. Its link is listed under **Skipped or removed** on **Add data**, so reading the list again won't bring it back; press **Read anyway** to restore it. An entry made by hand is changed or deleted on **Add data > Add by hand** instead, where the reason is kept.

**Possible duplicate** on **Quality** shows each filing's reason for update and its programme. **To review** and **Notices** show each filing's heading.

### Phrases, keywords and the data dictionary

The phrases the parser looks for, for the programme date, the programme's start and end dates (**programme_runs**), treatment and broker, are in `data\keywords.csv`, which you can edit in Excel. Each row has a market, field, phrase, meaning and example. In a phrase, `{DATE}` and `{NAME}` mark what is captured, and `{...}` stands for a few words. A phrase with a comma in it must be in quotes. Changes apply at the next read, with no restart; use **Re-read this company** to apply them to filings already read.

For **programme_runs**, a phrase with two `{DATE}`s gives the start and the end, such as `from {DATE} until {DATE}`. A phrase with one `{DATE}` says in the **means** column whether it's the **Start** or the **End**, such as `will end no later than {DATE}` with **End**. If no phrase matches, the card's **Runs** shows **? to ?**. "Up until the 12-month anniversary of the date of this announcement" is still worked out from the announcement's date, and the card says so. If a notice has wording for both cancelling and holding in treasury, it goes to **Quality** as **TREATMENT_CONFLICT** rather than one being picked.

**Library > Data dictionary** lists every field the app collects or plans to collect, with its source in UK, ASX and NZX filings, an example, and where it's stored. It's built from `data\data_dictionary.csv`, so editing that file in Excel changes the page.

### Brokers and venues

When a notice names a broker, each purchase keeps it as written, with its role (**From**, **Through** or **Programme broker**) and the sentence it came from; otherwise it shows **Not disclosed**. When a notice has a venue table or a list of individual trades that adds up to the day's total, the day is split by venue. If they don't add up, the day stays as one figure and goes to review as **VENUE_MISMATCH**. A venue table's own **Total** row isn't counted as a venue. Prices written with their unit, such as `641.43p`, are read.

A running total given as shares only, such as "has purchased a total of 1,000,920 Ordinary Shares since the commencement", is kept under **Running totals** as Reported, but the amounts still come from the daily purchases. "There are 3,519,447 shares held in treasury" is kept as the treasury holding.

### Programme cards: status and amounts

**Status** shows **ACTIVE** in bold green and **COMPLETED** in bold red. A completion stated in a notice is Reported. The app also shows a programme as **COMPLETED**, tagged **Calculated** with the reason underneath, when it has used its whole target, or when a later programme of the same company started buying after its last purchase. That's worked out on display, so it isn't saved over what the notices say, and it changes by itself if a missing filing is added later.

**Bought** shows the shares first, then the amount in each currency in full, with pence: for example **1,712,662,647 shares (GBP 1,750,000,020.87)**. A sum of daily purchases can be a few pence off the target because each day's value is shares × a rounded average price.

On a company's panel, **Purchases** are grouped by programme, then year, then month, with each group's total (days, shares and amount per currency). Months open to show each date. Purchases waiting for a programme document are listed but not counted.

### Waiting for programme, and programme documents

Purchases with no programme announcement read go to **Quality > Waiting for programme**, not **To review**. They're listed by company, with the programme date the notices cite, and left out of every total until linked. Paste the announcement's link there and they link by themselves; or press **Not needed** to remove those filings, which then stay out when a list is read again.

A programme known only from daily notices shows **Programme document: Needed** on its card, because its type, dates and size come from the announcement. Paste the announcement's link on the card to read it.

### Re-reading a company

On a company's panel, **Re-read this company** reads its filings again from their links with the latest reading rules, for example after a parser fix. Tick **Only filings with gaps** to re-read just those with a missing price or value, or still to review. The old figures are replaced only after a link has opened, so a link that fails keeps what you had. Removed filings stay out. Your document system must be reachable.

### Dates and links

Dates show as MM/DD/YYYY on screen, in Excel and in CSV files. Filing links show as **Doc**, with the full address when you hover.

### Data viewer

`viewer\buyback_viewer.html` opens `buyback.db` in Edge or Chrome, with no app, Python or internet. Choose a market and company to see programmes, daily purchases (grouped by programme, year and month), **Daily activity** charts as in the app (cumulative amount against the target, daily shares by venue, and daily average price, per programme, with hover details), running totals, cessations, filings and review items. It only reads the database.

Its source is in `viewer\src`: the page template (`viewer_template.html`), sql.js 1.10.3 (`sqljs\`), and `build_viewer.py`, which builds `viewer\buyback_viewer.html` from them. Each programme card also shows **Shares cancelled** and **Average price paid**, worked out as in the app. To check it, run `python -P viewer\src\make_viewer_db.py` (it builds a test database in the system's temporary folder from the test fixtures, never touching `buyback.db`), then `node viewer\src\test_viewer.js` and `node viewer\src\draw_check.js`, which need Node.js. From a package, which has no saved sample filings, the checks that need them are skipped and say so.

### Cessations (Appendix 3H)

**Companies > Cessations** lists every Appendix 3H entry: security, number, reason, date, consideration if stated, and the filing link. They're kept apart from purchases and aren't added to or netted against them. A buy-back cancellation is linked to the latest programme announced by its date. Lapsed rights and other reasons are shown too, marked **Other**.

### No filing is saved

The app keeps only each filing's figures, the page and wording they came from, and its link, so it takes little space. Every accepted link is listed in `filing_links.csv` in the app's folder, also on **Add data** as **Accepted links (CSV)**. If Excel has that file open, the app can't update it until the next run; the links stay in the app. Filings don't open highlighted: click the link to see the document.

### Add by hand or in bulk

Use **Add data > Add by hand** for a programme announcement, a change of terms, a purchase or a completion, on any exchange. Choose the kind at the top of the form, then the exchange and company. Programme, change and completion entries need the programme chosen from the company's list; add its Programme announcement first if it isn't there. **Source** is required. Each entry can be edited or deleted (with a reason) in the list below the form, and every change is kept in **History**. See **New in v25** for how hand entries are marked and checked.

For many purchases at once, fill in `templates\transactions.csv`, save it in the market's folder in `inbox\` (for example `inbox\AU`), and restart the app. These are the only files read from there; PDFs are ignored. These figures have no source wording, and they are changed in the file, not on Add by hand.

### See a figure's source

Click a purchase, or **show source** on a company. The panel lists each figure with its page and wording, and shows the full link to open the document.

### Add a country

Choose **+ Add a country…** in the Country menu, then add its companies. Check that exchange's terms first.

### Add a company

On **Companies**, press **Add company** and enter the country and code. Any company with a saved notice joins the study automatically. To remove one, delete its line from `data\study_companies.csv` and take its notices out of the inbox.

### Price reaction (optional)

Save `inbox\prices.csv` with the columns `country,ticker,date,close` from a source you may use, then restart the app.

## What if

| Situation | What to do |
|---|---|
| A scanned PDF | It has no text to read. Enter the figures on **Add data > Add by hand**, with the filing as the source. OCR is not included |
| An announcement in prose the app can't read (an NZX programme or completion) | Enter it on **Add data > Add by hand**: Programme announcement, Change of terms or Completion |
| "Not in the company list" on Add by hand | Check the code, or add the company with **Add company** on Companies first |
| "No programme is held" on Add by hand | Add the Programme announcement by hand (or read its filing) first, then the change, purchase or completion |
| CHANGE_UNCLEAR on Quality | An Appendix 3D changes a term the reader can't separate from the term as announced. Check the filing; if a term changed, update it with **Update a reading** |
| ISSUE_UNCLEAR or ISSUE_DETAIL_UNCLEAR on Quality | An Appendix 3G could not be read in full; the summary on its first page may have been used. Check the filing |
| An Appendix 3E purchase date is a day out | The form gives no date for the previous day; the app uses the trading day before the notice. After a public holiday, correct it with **Update a reading** |
| A figure read from a filing is wrong | **Add data > Add by hand > Update a reading**, or the **update** link on its row. Give the source and the reason. The filing's reading is kept; the figure is marked Updated Manually |
| A row was read as a purchase but is not one | Update a reading, figure **Set aside**. It leaves every figure and comes back if you undo it |
| UPDATE_NOT_FOUND, UPDATE_NOW_READ or UPDATE_READ_CHANGED on Quality | An update of yours no longer matches the filings: the row is gone, the filing now reads your value, or it reads something else. Undo or edit the update on Add by hand, or press **Mark as checked** |
| TOTAL_GAP on Quality | An ASX daily notice states more (or fewer) shares bought before its day than the notices read add up to. Notices for days in between are probably missing from your list, or one was corrected. Add the missing notices, or press **Mark as checked** |
| TOTAL_DIFFERS on Quality | An ASX daily notice states a different amount for the same shares than the notices read add up to, usually by cents. The notice's amount is kept |
| HAND_DIFFERS or HAND_TWICE on Quality | A filing read disagrees with, or may repeat, an entry made by hand. Both are kept. Edit or delete the hand entry, or press **Mark as checked** |
| "No company" on Quality | Choose the company in the list, and the file is read again |
| A figure looks wrong | Open its link and check the page shown. Report the filing so its layout can be added to the reader |
| A figure has no wording shown | The figure list still shows its value and page |
| Programme marked Partial | Add a notice from just before the period starts |
| The same file added twice | It is read once, as files are matched by content |
| Amount above 100% of the size | The programme was probably raised. Check the latest notice |
| A filing in a form the app doesn't know | It goes to **Quality**. Its layout is added as a definition file in `data\forms\` (see **To add a layout**), or its figures are entered by hand |
| **Purchases missing between filings** on Quality | A filing between the two dates shown is missing from what was read. Find it in your document system and read its link; the check clears by itself |
| Many filings under **To review** after a program update | Press **Read all … filings again** on **Quality > To review** |
| The Tracker asks for an exchange | Choose one at the top of the page or on the Tracker itself. It shows one exchange at a time |
| A programme on the Tracker shows **Programme not identified** | Its purchase notices cite no programme date and no announcement was read before them. Read the programme's announcement |
| A ticker and all its filings must go | Open **Manage tickers**, press **Delete** on its row and type its code. A backup is made first |
| A programme has purchases but no size, and the same company appears under a second code | The announcement was read under the other code. Press **Move** on it and type the right code |
| A size increase shows as a second programme | It was read before v20AI 6. Re-read the company |
| **Runs** and **Purchases read** on a programme card don't agree | The programme was renewed or extended. From v23 the card shows every period under **Periods** |
| The team needs to see the data | Publish a copy (`python -P maintain.py publish "<shared folder>"`); they run `python -P run_app.py --read-only "<shared folder>"`. Never share `buyback.db` itself in a synced folder |
| A read-only copy shows old figures | Its owner has not published since. When they do, press **Load the newer copy** |
| A Hong Kong daily report says companies were left out | They are not on your Hong Kong company list. Add them and use **Read again** on the report |
| A figure looks stale after a manual change to a file in `data\` | Start with `python -P run_app.py --rebuild` |
| After a program update | Figures already read stay as they were. To read them again with the update, use **Reset** and run your Excel lists again |
| A Hong Kong daily report in `.xls` form says to save it as `.xlsx` | Install the reader (`python -m pip install --user xlrd`), or open it in Excel and save it as `.xlsx` |
| Hong Kong rows show **Not stated** for cancelled or treasury shares | The report left that count blank. It is never assumed; check the row on the review list |
| A Hong Kong purchase on another exchange has no **Also in UK filings** mark | The UK notices don't hold the same purchase yet, or the company isn't in `data\cross_listings.csv` |
| You need to go back to how your database was before v22 | Close the app and copy the file in `backups\` named `..._start_of_2026_11_16_v22_2.db` over `buyback.db` |

**Known limits:**
- `fetch_from_list.py` is tested only against a local test server, not your company's system. Filings keep the figures they had when first read.
- Cancellations: only what saved notices state. Counts aren't netted, and separate cancellation notices, such as ASX cessation notices, aren't read yet.
- By venue: complete only where a closing notice gives venue totals. Otherwise only saved days are split and the rest shows as Not split. HSBC groups the London Stock Exchange, Aquis, Cboe and Turquoise as "UK Venues"; separating them needs its trade-by-trade files.
- Real notices tested so far: Appendix 3C forms (including CSL), Meridian Energy's web notices, Oceania Healthcare's notices and HSBC's UK notices. Other UK layouts, such as Shell's or Tesco's, are untested and may go to review.
- Singapore: only the Daily Share Buy-Back Notice layout is described, tested on four notices. Off-market equal access purchases and other SGX announcements aren't read by it. **Library > Data dictionary** doesn't yet list SGX sources.
- Sectors come from Wikipedia lists, and a company not on those lists has none.
- Membership changes during the year are not tracked.

Files: `sbb\` (program), `filing_lists\` (your Excel lists), `data\` (countries and study list; `constituents_*.csv` only look up names and sectors; `forms\` holds the layout definitions; `keywords\` holds phrase files; `filing_types.csv` and `cross_listings.csv` feed Library > Filing types and the cross-listing mark), `inbox\` (typed entries and prices only), `filing_links.csv` (accepted links), `buyback.db` (database), `reports\` (Excel), `tests\` (run `python -P tests\test_parsers.py`, `python -P tests\test_fetch.py`, `python -P tests\test_forms.py`, `python -P tests\test_app.py`, `python -P tests\test_v22.py`, `python -P tests\test_v23.py` and `python -P tests\test_v24.py`).
