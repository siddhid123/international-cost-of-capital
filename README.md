# International Cost of Capital App

A Streamlit app that compares a project's **cost of equity, cost of debt and WACC in USD** and in the
**currency of any selected country**, using live data from Damodaran, the OECD and Trading Economics.

**Live app:** `https://intnl-cost-of-capital.streamlit.app/`  ·  **Repository:** `https://github.com/siddhid123/international-cost-of-capital`

## Features
- **Live data, with sources and dates shown, plus a 🔄 Refresh data button**
  | Input | Source | How it's retrieved |
  |---|---|---|
  | Industry unlevered beta (US) | [Damodaran `betas.xls`](https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls), the "Unlevered beta" column | Excel download (falls back to Damodaran's `Betas.html`) |
  | USD BBB spread | [Damodaran `ratings.html`](https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html), Baa2/BBB, large non-financial firms | HTML table scrape |
  | Corporate tax rates | [OECD Corporate Tax Statistics](https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html#chapter-d1e2342-08e74a33fb), the combined (central + sub-central) statutory CIT rate | OECD Data Explorer SDMX API (`DSD_TAX_CIT@DF_CIT`), the database behind the report figure; uses the latest year available |
  | 10-year government yields | [Trading Economics bonds](https://tradingeconomics.com/bonds) | HTML scrape (falls back to the country's own Trading Economics bond page) |

  If a source can't be reached, the app uses an embedded fallback value, marks it 🟠 *fallback*, and lists the error under *Fetch diagnostics*.
- **Inputs:** industry, target country, equity risk premium, target debt share, and a **switch between the U.S. and the selected country's tax rate** (one project tax rate is used in both currencies).
- **Manual overrides:** unlevered beta, U.S. and foreign tax rates, USD BBB spread, and both countries' 10Y yields. The **foreign-currency BBB spread** has its own toggle. When the toggle is off, the app shows the auto-calculated spread.
- **Outputs:** side-by-side USD vs. foreign-currency results, a formulas & assumptions panel, live verification checks, an **all-industry comparison** (table and chart), and **downloads** (Excel workbook with inputs, results, all industries and sources; CSVs).
- **Defaults:** Software (System & Application), United States, U.S. tax rate, ERP 6.5%, debt share 30%.

## Formulas
Shared parameters: unlevered beta β<sub>U</sub>, project tax rate *t*, debt share *w<sub>d</sub>*, ERP.

1. Levered beta (Hamada): β<sub>L</sub> = β<sub>U</sub> [1 + (1 − t) · D/E], with D/E = w<sub>d</sub> / (1 − w<sub>d</sub>)
2. USD cost of equity: k<sub>e</sub><sup>USD</sup> = r<sub>f</sub><sup>US</sup> + β<sub>L</sub> × ERP
3. USD pre-tax cost of debt: k<sub>d</sub><sup>USD</sup> = r<sub>f</sub><sup>US</sup> + s<sub>BBB</sub>
4. Foreign currency (interest-rate parity / international Fisher effect, the default):
   k<sup>FC</sup> = (1 + k<sup>USD</sup>) (1 + r<sub>f</sub><sup>F</sup>) / (1 + r<sub>f</sub><sup>US</sup>) − 1
   - auto foreign spread: s<sup>FC</sup> = s<sub>BBB</sub> (1 + r<sub>f</sub><sup>F</sup>) / (1 + r<sub>f</sub><sup>US</sup>), so k<sub>d</sub><sup>FC</sup> = r<sub>f</sub><sup>F</sup> + s<sup>FC</sup>
   - optional *Additive* method: k<sub>e</sub><sup>FC</sup> = r<sub>f</sub><sup>F</sup> + β<sub>L</sub> × ERP and s<sup>FC</sup> = s<sub>BBB</sub>
5. WACC = (1 − w<sub>d</sub>) k<sub>e</sub> + w<sub>d</sub> k<sub>d</sub> (1 − t), in each currency

> If the formulas given in class differ (for example, additive rather than multiplicative conversion), change the *Currency conversion* option in the sidebar or edit `compute_cost_of_capital()` in `app.py`. All of the math is in that one function.

## Verification
`python verify_calculations.py` checks:
- a hand-computed worked example
- **equal government yields → identical USD and foreign results** (foreign spread override off)
- **zero debt → WACC = cost of equity** in both currencies
- **overriding the foreign spread leaves all USD results unchanged**
- each parser, against sample HTML/CSV shaped like the real sources

The same three properties are also re-checked live in the app (*Verification checks* panel).

Worked example with the real January 2026 / November 16, 2026 data (app defaults: Software (System & Application), U.S. tax rate):

| Input | Value | Source |
|---|---|---|
| Unlevered beta | 1.225392 | Damodaran betas.xls, Jan 5 2026 |
| U.S. tax rate | 25.6% | OECD CTS 2024, Fig. 2.1 (25.58%) |
| U.S. 10Y yield | 5.131% | Trading Economics, Nov 16 2026 |
| Brazil 10Y yield | 15.345% | Trading Economics, Nov 16 2026 |
| BBB spread | 1.11% | Damodaran ratings.html, Jan 2026 |
| ERP / debt share | 6.5% / 30% | defaults |

- D/E = 0.30/0.70 = 0.428571; β<sub>L</sub> = 1.225392 × (1 + 0.744 × 0.428571) = **1.616117**
- k<sub>e</sub><sup>USD</sup> = 5.131% + 1.616117 × 6.5% = **15.636%**; k<sub>d</sub><sup>USD</sup> = 6.241% → 4.643% after tax
- **WACC<sub>USD</sub> = 0.7 × 15.636% + 0.3 × 4.643% = 12.338%**
- Brazil (BRL): k<sub>e</sub> = 1.156358 × 1.15345 / 1.05131 − 1 = **26.870%**; spread = 1.11% × 1.15345/1.05131 = 1.218% → k<sub>d</sub> = 16.563% → 12.323% after tax; **WACC<sub>BRL</sub> = 22.506%**

(With live data the numbers will move. The app's tax rate comes from the OECD API, which may be a newer year than 2024.)

## Fallback snapshots
If a source can't be reached from the server, the app uses snapshots embedded in `app.py`, taken from the source documents:
Damodaran betas.xls (96 industries, Jan 5 2026), the ratings page (Baa2/BBB 1.11%, Jan 2026), Trading Economics /bonds (55 countries, Nov 16 2026) and OECD CTS 2024 Figure 2.1 (143 jurisdictions; rates read from the chart's bar lengths, ±0.1 pp). These rows are labelled 🟠 fallback in the *Data sources* table. Russia, Taiwan and the Euro area have no OECD rate, so their tax rate must be entered manually.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud
1. Push `app.py`, `requirements.txt` and `README.md` to a public GitHub repository.
2. At [share.streamlit.io](https://share.streamlit.io), click **Create app**, then pick the repo, branch `main` and file `app.py`, and click **Deploy**.

## Notes and limitations
- The Trading Economics data comes from scraping its public web page. If the site's layout changes, or it blocks the hosting server, the app falls back to the country's own bond page and then to the embedded Nov 16, 2026 snapshot (flagged 🟠). You can override any yield by hand.
- The beta is Damodaran's U.S. industry unlevered beta. The country's risk is assumed to be reflected in its government bond yield.
- Data are cached (3–24 hours depending on the source). **Refresh data** clears the cache and resets all overrides.
