# Vendor study: who tracks share buybacks

Checked on 5 November 2026 from public web pages only. No vendor was contacted and no product was tried. Prices are not public unless stated.

## Summary

- **Dedicated buyback data:** Smart Insider and LSEG are the two with public product pages that describe buyback data in detail.
- **Terminals:** I could not confirm what Bloomberg or S&P Capital IQ offer for buybacks, because the public pages found do not describe it. FactSet tracks buyback events; its detail for these markets is unconfirmed.
- **Free totals:** AJ Bell and Janus Henderson publish market totals, not company-level data feeds.
- **For this project:** none of the public pages confirms company-level coverage of all three markets, including NZX. Ask that first if you ever trial one.

## Comparison

| Provider | What it is | What was found | Delivery | Confidence |
|---|---|---|---|---|
| [Smart Insider](https://www.smartinsider.com/) | Buyback specialist | Executed trades and announced intentions, and compares the two. Listings claim 50,000+ equities; country counts vary between its pages (36 and 58). [Listings](https://datarade.ai/data-products/europe-uk-corporate-buyback-data-transactions-and-intenti-smart-insider) exist for Europe/UK and Asia Pacific | SFTP, API, Snowflake, AWS S3, desktop service; trial offered, price not stated | Vendor page |
| [LSEG Repurchases](https://www.lseg.com/en/data-analytics/financial-data/deals-data/repurchases-deals) | Deals data | 55,000+ programmes from 1986, covering terms, expiry, activity and repurchase rounds; a 304-row data dictionary | SFTP/FTP feed, with API, Snowflake and others in the catalogue | Vendor page |
| [FactSet](https://insight.factset.com/stock-buybacks-under-attack-tracking-share-repurchase-events-ahead-of-2023) | Data platform | Its research counts global buyback events and says those counts do not measure dollar value. Also the source named in Janus Henderson's report | Not confirmed | Partial |
| S&P Capital IQ | Data platform | [S&P Dow Jones Indices research](https://www.spglobal.com/spdji/en/documents/research/research-sp-examining-share-repurchases-and-the-sp-buyback-indices.pdf) cites it as a source. No product description found | Not confirmed | Low |
| Bloomberg | Terminal | Nothing found on public pages | Not confirmed | Not confirmed |
| [Nomad Data](https://www.nomad-data.com/data-use-cases/real-time-corporate-buyback-data-for-trading-risk-and-strategy) | Data broker | Connects buyers with data providers; its coverage claims are marketing | Varies | Low |
| [Janus Henderson](https://www.investmentweek.co.uk/news/4535783/global-share-buybacks-jump-268-usd572bn-technology-overtakes-financials) | Periodic report | Global totals across 1,500 large companies, with a scaled global estimate | Report | Secondary source |
| [AJ Bell](https://www.ajbell.co.uk/group/news/uk-share-buyback-bonanza-continues-despite-wider-uncertainties) | Commentary | Running FTSE 100 totals | Articles | Secondary source |

QUICK sells buyback data for Japan, which is outside this project's markets.

## How this project differs

| | This tracker | Licensed vendor |
|---|---|---|
| Cost | Your time saving notices | Paid; price by quote |
| Coverage | Only notices you save | Broad, but check NZX |
| Traceability | Every figure read from a notice opens on its page, highlighted | Depends on the product; ask for a source link per record |
| Effort | Manual, though one ASX notice holds the running total | Automatic feed |
| Permitted use | Private use under the exchanges' terms | Set by the licence |

## Recommendation

Stay with the private tracker while this is personal research. If saving notices by hand becomes too slow, or the use becomes commercial, ask Smart Insider and LSEG the same questions:

1. Is coverage company-level for FTSE 100, S&P/ASX 200 and NZX 50, for both programmes and daily purchases?
2. How soon after a notice does a record appear, and does each record link to the source notice?
3. How are weekly UK notices (allowed since February 2026) and multi-currency purchases handled?
4. What may be stored, charted and shared under the licence, and what does it cost for one user?

Separately, ask whoever provides your Bloomberg, FactSet or Capital IQ access, if you have any, to show the buyback fields directly.
