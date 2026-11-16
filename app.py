"""
International Cost of Capital App
---------------------------------
Compares a project's cost of equity, cost of debt and WACC in USD and in the
currency of a selected country.

Data sources (fetched live, cached, refreshable):
  * Industry unlevered betas ........ Aswath Damodaran (NYU Stern), betas.xls
  * BBB (Baa2) USD default spread ... Aswath Damodaran, ratings.html (large non-financial firms)
  * Corporate income tax rates ...... OECD Corporate Tax Statistics (combined statutory CIT rate)
  * 10-year government bond yields .. Trading Economics, /bonds

Run locally:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import io
import re

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BETAS_XLS_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
BETAS_HTML_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/Betas.html"
RATINGS_URLS = [
    "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html",
    "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html",
]
OECD_REPORT_URL = (
    "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/"
    "full-report/statutory-corporate-income-tax-rates_440f9286.html#chapter-d1e2342-08e74a33fb"
)
OECD_STATLINK_URL = "https://stat.link/sbmte4"   # Excel data behind Figure 2.1 of the 2024 report
OECD_SDMX_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,/all"
    "?startPeriod=2020&dimensionAtObservation=AllDimensions&format=csvfilewithlabels"
)
TE_BONDS_URL = "https://tradingeconomics.com/bonds"
TE_COUNTRY_URL = "https://tradingeconomics.com/{slug}/government-bond-yield"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "United States"
DEFAULT_ERP = 6.5      # %
DEFAULT_DEBT = 30      # % of capital

# Country name (Trading Economics style) -> ISO3 code (used to match OECD tax data)
COUNTRY_ISO3 = {
    "United States": "USA", "Canada": "CAN", "Mexico": "MEX", "Brazil": "BRA", "Argentina": "ARG",
    "Chile": "CHL", "Colombia": "COL", "Peru": "PER", "United Kingdom": "GBR", "Germany": "DEU",
    "France": "FRA", "Italy": "ITA", "Spain": "ESP", "Portugal": "PRT", "Netherlands": "NLD",
    "Belgium": "BEL", "Austria": "AUT", "Switzerland": "CHE", "Sweden": "SWE", "Norway": "NOR",
    "Denmark": "DNK", "Finland": "FIN", "Ireland": "IRL", "Greece": "GRC", "Poland": "POL",
    "Czech Republic": "CZE", "Hungary": "HUN", "Romania": "ROU", "Bulgaria": "BGR", "Croatia": "HRV",
    "Slovakia": "SVK", "Slovenia": "SVN", "Lithuania": "LTU", "Latvia": "LVA", "Estonia": "EST",
    "Iceland": "ISL", "Luxembourg": "LUX", "Malta": "MLT", "Cyprus": "CYP", "Serbia": "SRB",
    "Russia": "RUS", "Ukraine": "UKR", "Turkey": "TUR", "Israel": "ISR", "Japan": "JPN",
    "China": "CHN", "Hong Kong": "HKG", "Taiwan": "TWN", "South Korea": "KOR", "India": "IND",
    "Indonesia": "IDN", "Malaysia": "MYS", "Philippines": "PHL", "Singapore": "SGP",
    "Thailand": "THA", "Vietnam": "VNM", "Pakistan": "PAK", "Bangladesh": "BGD", "Sri Lanka": "LKA",
    "Australia": "AUS", "New Zealand": "NZL", "South Africa": "ZAF", "Nigeria": "NGA",
    "Egypt": "EGY", "Kenya": "KEN", "Morocco": "MAR", "Namibia": "NAM", "Botswana": "BWA",
    "Uganda": "UGA", "Zambia": "ZMB", "Mauritius": "MUS", "Saudi Arabia": "SAU", "Qatar": "QAT",
    "Bahrain": "BHR", "Jordan": "JOR", "Kazakhstan": "KAZ", "Costa Rica": "CRI",
}

CURRENCY = {
    "United States": "USD", "Canada": "CAD", "Mexico": "MXN", "Brazil": "BRL", "Argentina": "ARS",
    "Chile": "CLP", "Colombia": "COP", "Peru": "PEN", "United Kingdom": "GBP", "Germany": "EUR",
    "France": "EUR", "Italy": "EUR", "Spain": "EUR", "Portugal": "EUR", "Netherlands": "EUR",
    "Belgium": "EUR", "Austria": "EUR", "Ireland": "EUR", "Greece": "EUR", "Finland": "EUR",
    "Slovakia": "EUR", "Slovenia": "EUR", "Lithuania": "EUR", "Latvia": "EUR", "Estonia": "EUR",
    "Luxembourg": "EUR", "Malta": "EUR", "Cyprus": "EUR", "Croatia": "EUR",
    "Switzerland": "CHF", "Sweden": "SEK", "Norway": "NOK", "Denmark": "DKK", "Poland": "PLN",
    "Czech Republic": "CZK", "Hungary": "HUF", "Romania": "RON", "Bulgaria": "BGN", "Iceland": "ISK",
    "Serbia": "RSD", "Russia": "RUB", "Ukraine": "UAH", "Turkey": "TRY", "Israel": "ILS",
    "Japan": "JPY", "China": "CNY", "Hong Kong": "HKD", "Taiwan": "TWD", "South Korea": "KRW",
    "India": "INR", "Indonesia": "IDR", "Malaysia": "MYR", "Philippines": "PHP", "Singapore": "SGD",
    "Thailand": "THB", "Vietnam": "VND", "Pakistan": "PKR", "Bangladesh": "BDT", "Sri Lanka": "LKR",
    "Australia": "AUD", "New Zealand": "NZD", "South Africa": "ZAR", "Nigeria": "NGN",
    "Egypt": "EGP", "Kenya": "KES", "Morocco": "MAD", "Namibia": "NAD", "Botswana": "BWP",
    "Uganda": "UGX", "Zambia": "ZMW", "Mauritius": "MUR", "Saudi Arabia": "SAR", "Qatar": "QAR",
    "Bahrain": "BHD", "Jordan": "JOD", "Kazakhstan": "KZT", "Costa Rica": "CRC",
}

# --- Last-resort fallbacks (used ONLY if a live fetch fails; clearly flagged in the UI) ---
# Snapshots taken from the source documents themselves.
# Combined statutory CIT rates (%), OECD Corporate Tax Statistics 2024, Figure 2.1 (rates for 2024),
# read from the figure's bar lengths (precision about +/-0.1 pp). Jurisdictions shown at 0% have no CIT.
FALLBACK_TAX_LABEL = "OECD Corporate Tax Statistics 2024, Figure 2.1 (embedded snapshot)"
FALLBACK_TAX = {
    'ABW': 22.1, 'AGO': 25.0, 'AIA': 0.0, 'ALB': 15.1, 'AND': 10.0, 'ARE': 9.0, 'ARG': 30.1, 'ARM': 18.1,
    'ATG': 25.0, 'AUS': 30.1, 'AUT': 23.0, 'AZE': 20.0, 'BEL': 25.0, 'BEN': 30.1, 'BFA': 27.5, 'BGR': 10.0,
    'BHR': 0.0, 'BHS': 0.0, 'BIH': 10.0, 'BLZ': 0.0, 'BMU': 0.0, 'BRA': 34.0, 'BRB': 9.0, 'BRN': 18.6,
    'BWA': 22.1, 'CAN': 26.2, 'CHE': 19.6, 'CHL': 27.0, 'CHN': 25.0, 'CIV': 25.0, 'CMR': 33.0, 'COD': 30.1,
    'COG': 28.0, 'COK': 20.0, 'COL': 35.0, 'CPV': 22.5, 'CRI': 30.1, 'CUW': 22.1, 'CYM': 0.0, 'CZE': 21.1,
    'DEU': 29.9, 'DJI': 25.0, 'DMA': 25.0, 'DNK': 22.1, 'DOM': 27.0, 'EGY': 22.5, 'ESP': 25.0, 'EST': 20.0,
    'FIN': 20.0, 'FRA': 25.8, 'FRO': 18.1, 'GAB': 30.1, 'GBR': 25.0, 'GEO': 15.1, 'GGY': 0.0, 'GIB': 12.5,
    'GRC': 22.1, 'GRD': 28.0, 'GRL': 26.5, 'HKG': 16.5, 'HND': 30.1, 'HRV': 18.1, 'HTI': 30.1, 'HUN': 9.0,
    'IDN': 22.1, 'IMN': 0.0, 'IND': 25.1, 'IRL': 12.5, 'ISL': 21.1, 'ISR': 23.0, 'ITA': 27.8, 'JAM': 25.0,
    'JEY': 0.0, 'JOR': 20.0, 'JPN': 29.7, 'KAZ': 20.0, 'KEN': 30.1, 'KNA': 25.0, 'KOR': 26.4, 'KWT': 15.1,
    'LBR': 25.0, 'LCA': 30.1, 'LIE': 12.5, 'LKA': 30.1, 'LTU': 15.1, 'LUX': 24.9, 'LVA': 20.0, 'MAC': 12.0,
    'MAR': 32.0, 'MCO': 25.0, 'MDV': 15.1, 'MEX': 30.1, 'MKD': 10.0, 'MLT': 35.0, 'MNE': 15.1, 'MNG': 25.0,
    'MRT': 25.0, 'MSR': 30.1, 'MUS': 15.1, 'MYS': 24.0, 'NAM': 32.0, 'NGA': 30.1, 'NLD': 25.8, 'NOR': 22.1,
    'NZL': 28.0, 'OMN': 15.1, 'PAK': 29.0, 'PAN': 25.0, 'PER': 29.5, 'PHL': 25.0, 'PNG': 30.1, 'POL': 19.0,
    'PRT': 31.5, 'PRY': 10.0, 'QAT': 10.0, 'ROU': 16.0, 'SAU': 20.0, 'SEN': 30.1, 'SGP': 17.0, 'SLE': 25.0,
    'SMR': 17.0, 'SRB': 15.1, 'SVK': 21.1, 'SVN': 22.1, 'SWE': 20.6, 'SWZ': 27.5, 'SYC': 25.0, 'TCA': 0.0,
    'TGO': 27.0, 'THA': 20.0, 'TTO': 30.1, 'TUN': 15.1, 'TUR': 20.0, 'UKR': 18.1, 'URY': 25.0, 'USA': 25.6,
    'UZB': 15.1, 'VCT': 28.0, 'VGB': 0.0, 'VNM': 20.0, 'WSM': 27.0, 'ZAF': 27.0, 'ZMB': 30.1,
}
# 10Y government bond yields (%), Trading Economics /bonds snapshot of Nov 16, 2026.
FALLBACK_YIELDS_DATE = "Nov 16, 2026 snapshot"
FALLBACK_YIELDS = {
    'United States': 5.131, 'United Kingdom': 5.3515, 'Japan': 2.888, 'Australia': 5.124, 'Germany': 3.379,
    'Brazil': 15.345, 'Russia': 16.683, 'India': 7.318, 'Canada': 3.81, 'Italy': 4.457,
    'France': 4.952, 'South Africa': 8.72, 'China': 1.6331, 'Switzerland': 0.57, 'Mexico': 9.299,
    'Netherlands': 3.48, 'New Zealand': 4.774, 'Portugal': 3.838, 'South Korea': 3.986, 'Spain': 3.952,
    'Greece': 4.295, 'Turkey': 36.475, 'Finland': 3.755, 'Lithuania': 4.339, 'Norway': 4.391,
    'Poland': 6.336, 'Romania': 7.16, 'Slovakia': 4.3, 'Slovenia': 3.939, 'Sweden': 3.1,
    'Hungary': 5.525, 'Iceland': 6.81, 'Ireland': 3.514, 'Austria': 3.626, 'Belgium': 4.385,
    'Croatia': 3.867, 'Czech Republic': 5.231, 'Denmark': 3.171, 'Euro area': 3.94, 'Peru': 6.2414,
    'Chile': 6.01, 'Colombia': 12.698, 'Singapore': 2.3429, 'Taiwan': 1.87, 'Thailand': 1.983,
    'Vietnam': 4.573, 'Hong Kong': 3.996, 'Indonesia': 7.607, 'Israel': 4.127, 'Malaysia': 3.8654,
    'Pakistan': 12.622, 'Philippines': 7.703, 'Zambia': 14.74, 'Kenya': 12.5, 'Nigeria': 16.598,
}
# Unlevered betas, Damodaran betas.xls (US, Industry Averages), updated Jan 5, 2026.
FALLBACK_BETAS_DATE = "January 05, 2026 (embedded snapshot)"
FALLBACK_BETAS = {
    'Advertising': 0.930086, 'Aerospace/Defense': 0.846669,
    'Air Transport': 0.70405, 'Apparel': 0.757982,
    'Auto & Truck': 1.269033, 'Auto Parts': 1.021714,
    'Bank (Money Center)': 0.341059, 'Banks (Regional)': 0.286516,
    'Beverage (Alcoholic)': 0.613172, 'Beverage (Soft)': 0.555671,
    'Broadcasting': 0.286362, 'Brokerage & Investment Banking': 0.580849,
    'Building Materials': 0.930162, 'Business & Consumer Services': 0.773588,
    'Cable TV': 0.352392, 'Chemical (Basic)': 0.580033,
    'Chemical (Diversified)': 0.366552, 'Chemical (Specialty)': 0.792227,
    'Coal & Related Energy': 1.016535, 'Computer Services': 0.91551,
    'Computers/Peripherals': 1.305062, 'Construction Supplies': 1.016068,
    'Diversified': 0.78893, 'Drugs (Biotechnology)': 1.034129,
    'Drugs (Pharmaceutical)': 0.886211, 'Education': 0.660196,
    'Electrical Equipment': 1.147795, 'Electronics (Consumer & Office)': 0.829853,
    'Electronics (General)': 0.897365, 'Engineering/Construction': 1.094912,
    'Entertainment': 0.737184, 'Environmental & Waste Services': 0.814469,
    'Farming/Agriculture': 0.81302, 'Financial Svcs. (Non-bank & Insurance)': 0.318882,
    'Food Processing': 0.457418, 'Food Wholesalers': 0.640882,
    'Furn/Home Furnishings': 0.624788, 'Green & Renewable Energy': 0.463301,
    'Healthcare Products': 0.829063, 'Healthcare Support Services': 0.688916,
    'Heathcare Information and Technology': 0.991301, 'Homebuilding': 0.78496,
    'Hospitals/Healthcare Facilities': 0.55173, 'Hotel/Gaming': 0.832251,
    'Household Products': 0.717816, 'Information Services': 0.737177,
    'Insurance (General)': 0.56364, 'Insurance (Life)': 0.427156,
    'Insurance (Prop/Cas.)': 0.435656, 'Investments & Asset Management': 0.529716,
    'Machinery': 0.867976, 'Metals & Mining': 0.963643,
    'Office Equipment & Services': 0.980604, 'Oil/Gas (Integrated)': 0.271219,
    'Oil/Gas (Production and Exploration)': 0.56276, 'Oil/Gas Distribution': 0.465076,
    'Oilfield Svcs/Equip.': 0.743039, 'Packaging & Container': 0.723069,
    'Paper/Forest Products': 0.721553, 'Power': 0.310024,
    'Precious Metals': 0.793243, 'Publishing & Newspapers': 0.477307,
    'R.E.I.T.': 0.392904, 'Real Estate (Development)': 0.478288,
    'Real Estate (General/Diversified)': 0.577859, 'Real Estate (Operations & Services)': 0.814892,
    'Recreation': 0.695091, 'Reinsurance': 0.438409,
    'Restaurant/Dining': 0.76742, 'Retail (Automotive)': 0.698433,
    'Retail (Building Supply)': 1.307014, 'Retail (Distributors)': 0.782683,
    'Retail (General)': 0.759964, 'Retail (Grocery and Food)': 0.804751,
    'Retail (REITs)': 0.436173, 'Retail (Special Lines)': 0.948783,
    'Rubber& Tires': 0.143534, 'Semiconductor': 1.489258,
    'Semiconductor Equip': 1.348073, 'Shipbuilding & Marine': 0.644013,
    'Shoe': 0.933675, 'Software (Entertainment)': 1.012781,
    'Software (Internet)': 1.546064, 'Software (System & Application)': 1.225392,
    'Steel': 0.903514, 'Telecom (Wireless)': 0.387259,
    'Telecom. Equipment': 0.863491, 'Telecom. Services': 0.365434,
    'Tobacco': 0.67759, 'Transportation': 0.675311,
    'Transportation (Railroads)': 0.806948, 'Trucking': 0.850418,
    'Utility (General)': 0.148613, 'Utility (Water)': 0.281177,
    'Total Market': 0.72173, 'Total Market (without financials)': 0.877517,
}
FALLBACK_BBB_SPREAD = 1.11  # %, Damodaran January 2026, Baa2/BBB, large non-financial firms


# ---------------------------------------------------------------------------
# Calculation engine (pure functions -- no Streamlit, easy to verify)
# ---------------------------------------------------------------------------
def levered_beta(beta_u: float, tax: float, debt_share: float) -> float:
    """Hamada: beta_L = beta_U * (1 + (1 - t) * D/E), with D/E = w_d / (1 - w_d)."""
    if debt_share >= 1:
        raise ValueError("Debt share must be below 100%.")
    de = debt_share / (1.0 - debt_share)
    return beta_u * (1.0 + (1.0 - tax) * de)


def compute_cost_of_capital(
    beta_u: float,
    tax: float,
    debt_share: float,
    erp: float,
    rf_us: float,
    rf_f: float,
    spread_usd: float,
    spread_f_override: float | None = None,
    method: str = "parity",
) -> dict:
    """All rates are decimals (0.065 = 6.5%).

    USD:
        k_e(USD)  = rf_US + beta_L * ERP
        k_d(USD)  = rf_US + BBB spread
        WACC(USD) = (1 - w_d) k_e + w_d k_d (1 - t)

    Foreign currency, method = "parity" (international Fisher / interest-rate parity):
        k_e(FC)   = (1 + k_e(USD)) * (1 + rf_F) / (1 + rf_US) - 1
        spread_FC = spread_USD * (1 + rf_F) / (1 + rf_US)        (auto)
        k_d(FC)   = rf_F + spread_FC
                  = (1 + k_d(USD)) * (1 + rf_F) / (1 + rf_US) - 1 when the spread is auto
    Foreign currency, method = "additive":
        k_e(FC)   = rf_F + beta_L * ERP,  spread_FC = spread_USD (auto),  k_d(FC) = rf_F + spread_FC
    """
    bl = levered_beta(beta_u, tax, debt_share)
    we = 1.0 - debt_share

    ke_usd = rf_us + bl * erp
    kd_usd = rf_us + spread_usd
    kd_usd_at = kd_usd * (1.0 - tax)
    wacc_usd = we * ke_usd + debt_share * kd_usd_at

    if method == "parity":
        fx = (1.0 + rf_f) / (1.0 + rf_us)
        ke_f = (1.0 + ke_usd) * fx - 1.0
        spread_f_auto = spread_usd * fx
    elif method == "additive":
        ke_f = rf_f + bl * erp
        spread_f_auto = spread_usd
    else:
        raise ValueError(f"Unknown method: {method}")

    spread_f = spread_f_auto if spread_f_override is None else spread_f_override
    kd_f = rf_f + spread_f
    kd_f_at = kd_f * (1.0 - tax)
    wacc_f = we * ke_f + debt_share * kd_f_at

    return {
        "beta_u": beta_u, "beta_l": bl, "tax": tax, "debt_share": debt_share, "equity_share": we,
        "de_ratio": debt_share / we, "erp": erp,
        "rf_usd": rf_us, "rf_fc": rf_f,
        "spread_usd": spread_usd, "spread_fc": spread_f, "spread_fc_auto": spread_f_auto,
        "ke_usd": ke_usd, "kd_usd_pre": kd_usd, "kd_usd_after": kd_usd_at, "wacc_usd": wacc_usd,
        "ke_fc": ke_f, "kd_fc_pre": kd_f, "kd_fc_after": kd_f_at, "wacc_fc": wacc_f,
    }


# ---------------------------------------------------------------------------
# Parsers (pure functions operating on downloaded bytes/text)
# ---------------------------------------------------------------------------
def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def _to_float(x) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float, np.floating)) and not pd.isna(x):
        return float(x)
    m = re.search(r"-?\d+(?:\.\d+)?", str(x).replace(",", ""))
    return float(m.group()) if m else None


def _frame_from_header_row(raw: pd.DataFrame) -> pd.DataFrame | None:
    """Find the row that starts with 'Industry Name' and use it as the header."""
    for i in range(min(len(raw), 40)):
        if any(_clean(v).lower() == "industry name" for v in raw.iloc[i].tolist()):
            df = raw.iloc[i + 1:].copy()
            df.columns = [_clean(c) for c in raw.iloc[i].tolist()]
            return df
    return None


def _pick_unlevered_col(columns) -> str | None:
    cols = list(columns)
    for c in cols:  # exact "Unlevered beta" (not the cash-corrected one)
        if c.lower() == "unlevered beta":
            return c
    for c in cols:
        if c.lower().startswith("unlevered beta") and "cash" not in c.lower():
            return c
    return None


def _tidy_betas(df: pd.DataFrame) -> pd.DataFrame:
    ucol = _pick_unlevered_col(df.columns)
    if ucol is None:
        raise ValueError("Unlevered beta column not found")
    keep = {"Industry Name": "Industry", ucol: "Unlevered beta"}
    for c in df.columns:
        cl = c.lower()
        if cl.startswith("number of firms"):
            keep[c] = "Number of firms"
        elif cl == "beta":
            keep[c] = "Levered beta (Damodaran)"
        elif cl.startswith("d/e"):
            keep[c] = "D/E (Damodaran)"
    out = df[list(keep)].rename(columns=keep)
    out["Industry"] = out["Industry"].map(_clean)
    out["Unlevered beta"] = pd.to_numeric(out["Unlevered beta"], errors="coerce")
    out = out[(out["Industry"] != "") & (out["Industry"].str.lower() != "nan")]
    out = out.dropna(subset=["Unlevered beta"]).drop_duplicates("Industry").reset_index(drop=True)
    if out.empty:
        raise ValueError("No industries parsed")
    return out


def parse_betas_xls(content: bytes) -> tuple[pd.DataFrame, str]:
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
    order = sorted(sheets, key=lambda n: 0 if "industry" in n.lower() else 1)
    for name in order:
        raw = sheets[name]
        df = _frame_from_header_row(raw)
        if df is None:
            continue
        date_label = ""
        for i in range(min(len(raw), 15)):
            row = raw.iloc[i].tolist()
            for j, v in enumerate(row):
                if "date updated" in _clean(v).lower() or "updated" == _clean(v).lower().rstrip(":"):
                    rest = [r for r in row[j + 1:] if not pd.isna(r) and _clean(r)]
                    if rest:
                        d = rest[0]
                        date_label = d.strftime("%B %d, %Y") if hasattr(d, "strftime") else _clean(d)
                    break
            if date_label:
                break
        return _tidy_betas(df), date_label
    raise ValueError("No sheet with an 'Industry Name' header found")


def parse_betas_html(text: str) -> tuple[pd.DataFrame, str]:
    for t in pd.read_html(io.StringIO(text), header=None):
        df = _frame_from_header_row(t)
        if df is not None:
            m = re.search(r"(January|February|March|April|May|June|July|August|September|October|"
                          r"November|December)\s+\d{4}", text)
            return _tidy_betas(df), (m.group(0) if m else "")
    raise ValueError("No betas table in HTML")


def parse_ratings_html(text: str, rating: str = "Baa2/BBB") -> tuple[float, str]:
    """Return (spread in %, date label) for the first (= large non-financial) Baa2/BBB entry."""
    tables = pd.read_html(io.StringIO(text), header=None)
    for t in tables:
        for _, row in t.iterrows():
            cells = [_clean(v) for v in row.tolist()]
            if rating in cells:
                idx = cells.index(rating)
                for c in cells[idx + 1:]:
                    if "%" in c or _to_float(c) is not None:
                        val = _to_float(c)
                        if val is not None:
                            if "%" not in c and val < 1:   # stored as a decimal
                                val *= 100
                            m = re.search(r"as of\s+([A-Za-z]+\s+\d{4})", text)
                            return val, (m.group(1) if m else "")
    raise ValueError(f"{rating} not found in ratings table")


def _slug_to_name(slug: str) -> str:
    name = slug.replace("-", " ").title()
    return {"Hong Kong": "Hong Kong", "Czech Republic": "Czech Republic"}.get(name, name)


def parse_te_bonds_html(html: str) -> pd.DataFrame:
    """Parse Trading Economics /bonds. Returns DataFrame[Country, Yield, TE date, slug]."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    pat = re.compile(r"/([a-z\-]+)/government-bond-yield", re.I)
    recs, seen = [], set()
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=pat)
        if a is None:
            continue
        slug = pat.search(a["href"]).group(1).lower()
        if slug in seen:
            continue
        tds = tr.find_all("td")
        pos = next((i for i, td in enumerate(tds) if a in td.descendants), 0)
        yld = None
        for td in tds[pos + 1:]:
            yld = _to_float(td.get_text(" ", strip=True))
            if yld is not None:
                break
        if yld is None:
            continue
        date_txt = tds[-1].get_text(" ", strip=True) if tds else ""
        if re.fullmatch(r"\d{1,2}:\d{2}", date_txt):       # intraday quote -> today's date
            date_txt = f"{dt.date.today():%b/%d} {date_txt}"
        seen.add(slug)
        recs.append({"Country": _slug_to_name(slug), "Yield": yld, "TE date": date_txt, "slug": slug})

    if not recs:  # fallback: generic table read
        for t in pd.read_html(io.StringIO(html)):
            cols = [_clean(c) for c in t.columns]
            if "Yield" in cols:
                t.columns = cols
                first = cols[0]
                for _, r in t.iterrows():
                    y = _to_float(r["Yield"])
                    if y is None:
                        continue
                    name = re.sub(r"\s*\d+Y$", "", _clean(r[first]))
                    recs.append({"Country": name, "Yield": y,
                                 "TE date": _clean(r.get("Date", "")),
                                 "slug": name.lower().replace(" ", "-")})
    df = pd.DataFrame(recs)
    if df.empty:
        raise ValueError("No bond yields parsed from Trading Economics")
    return df.drop_duplicates("Country").reset_index(drop=True)


def parse_te_country_page(html: str) -> tuple[float, str]:
    """Parse a TE country bond page meta text, e.g. '... rose to 4.15% on November 13, 2026'."""
    m = re.search(r"(-?\d+(?:\.\d+)?)%\s+on\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", html)
    if not m:
        raise ValueError("Yield sentence not found")
    return float(m.group(1)), m.group(2)


def parse_oecd_csv(text: str) -> tuple[pd.DataFrame, str]:
    """Latest combined statutory CIT rate per jurisdiction from the OECD SDMX CSV (with labels)."""
    df = pd.read_csv(io.StringIO(text), low_memory=False)
    upper = {c.upper(): c for c in df.columns}
    area, year, val = upper.get("REF_AREA"), upper.get("TIME_PERIOD"), upper.get("OBS_VALUE")
    if not (area and year and val):
        raise ValueError("Unexpected OECD CSV layout")
    label_cols = [c for c in df.columns
                  if not c.upper().startswith("STRUCTURE")
                  and (df[c].dtype == object or pd.api.types.is_string_dtype(df[c]))]
    row_txt = df[label_cols].astype(str).agg(" ".join, axis=1).str.lower()
    d = df[row_txt.str.contains("combined")].copy()
    d[val] = pd.to_numeric(d[val], errors="coerce")
    d[year] = pd.to_numeric(d[year], errors="coerce")
    d = d[(d[val] >= 0) & (d[val] <= 100)].dropna(subset=[val, year])
    if d.empty:
        raise ValueError("No combined CIT rows")
    name_col = next((c for c in df.columns if c.lower() == "reference area"), area)
    latest = d[year].groupby(d[area]).transform("max")
    d = d[d[year] == latest]
    # standard (headline) rate = highest combined rate for that jurisdiction-year
    out = (d.groupby([area, name_col, year])[val].max().reset_index()
             .rename(columns={area: "ISO3", name_col: "Jurisdiction", year: "Year", val: "Tax rate"}))
    out["Year"] = out["Year"].astype(int)
    return out, f"{int(out['Year'].max())}"


def parse_oecd_statlink(content: bytes) -> pd.DataFrame:
    """Generic reader for the OECD StatLink workbook: find a column of ISO3 codes and the rate next to it."""
    for name, raw in pd.read_excel(io.BytesIO(content), sheet_name=None, header=None).items():
        for c in raw.columns:
            col = raw[c].astype(str).str.strip()
            iso = col.str.fullmatch(r"[A-Z]{3}")
            if iso.sum() < 30:
                continue
            for c2 in raw.columns[list(raw.columns).index(c) + 1:]:
                vals = pd.to_numeric(raw.loc[iso, c2], errors="coerce")
                if vals.notna().mean() > 0.8 and vals.between(0, 100).all():
                    if vals.max() <= 1:          # stored as decimals
                        vals = vals * 100
                    out = pd.DataFrame({"ISO3": col[iso].values, "Tax rate": vals.values})
                    out["Jurisdiction"] = out["ISO3"]
                    out["Year"] = 2024
                    return out.dropna().drop_duplicates("ISO3").reset_index(drop=True)
    raise ValueError("No ISO3/rate columns found in StatLink file")


# ---------------------------------------------------------------------------
# Fetchers (cached; each returns a dict with value + provenance)
# ---------------------------------------------------------------------------
def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _get(url: str, timeout: int = 30) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_betas() -> dict:
    errors = []
    try:
        df, date = parse_betas_xls(_get(BETAS_XLS_URL).content)
        return {"data": df, "status": "live", "source": "Damodaran, betas.xls (Industry Averages, US)",
                "url": BETAS_XLS_URL, "date": date or "see file", "fetched": _now()}
    except Exception as e:
        errors.append(f"xls: {e}")
    try:
        df, date = parse_betas_html(_get(BETAS_HTML_URL).text)
        return {"data": df, "status": "live", "source": "Damodaran, Betas.html (US)",
                "url": BETAS_HTML_URL, "date": date or "see page", "fetched": _now(),
                "note": "; ".join(errors)}
    except Exception as e:
        errors.append(f"html: {e}")
    df = pd.DataFrame({"Industry": list(FALLBACK_BETAS), "Unlevered beta": list(FALLBACK_BETAS.values())})
    return {"data": df, "status": "fallback", "source": "Damodaran betas.xls - embedded snapshot (fetch failed)",
            "url": BETAS_XLS_URL, "date": FALLBACK_BETAS_DATE, "fetched": _now(), "note": "; ".join(errors)}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_bbb_spread() -> dict:
    errors = []
    for url in RATINGS_URLS:
        try:
            spread, date = parse_ratings_html(_get(url).text)
            return {"value": spread, "status": "live",
                    "source": "Damodaran, ratings.html - Baa2/BBB, large non-financial firms",
                    "url": url, "date": date or "see page", "fetched": _now()}
        except Exception as e:
            errors.append(f"{url}: {e}")
    return {"value": FALLBACK_BBB_SPREAD, "status": "fallback",
            "source": "Embedded value (Damodaran Jan-2026)", "url": RATINGS_URLS[0],
            "date": "January 2026", "fetched": _now(), "note": "; ".join(errors)}


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_tax_rates() -> dict:
    errors = []
    # Route 1: OECD Data Explorer (same database as the report; has the most recent tax year)
    try:
        df, year = parse_oecd_csv(_get(OECD_SDMX_URL, timeout=60).text)
        return {"data": df, "status": "live",
                "source": "OECD Corporate Tax Statistics - combined statutory CIT rate (OECD Data Explorer)",
                "url": OECD_REPORT_URL, "api": OECD_SDMX_URL, "date": f"tax year {year}",
                "fetched": _now()}
    except Exception as e:
        errors.append(f"OECD API: {e}")
    # Route 2: the StatLink Excel file behind Figure 2.1 of the linked 2024 report
    try:
        df = parse_oecd_statlink(_get(OECD_STATLINK_URL, timeout=60).content)
        return {"data": df, "status": "live",
                "source": "OECD Corporate Tax Statistics 2024, Figure 2.1 data (StatLink)",
                "url": OECD_REPORT_URL, "date": "tax year 2024", "fetched": _now(), "note": "; ".join(errors)}
    except Exception as e:
        errors.append(f"StatLink: {e}")
    df = pd.DataFrame({"ISO3": list(FALLBACK_TAX), "Tax rate": list(FALLBACK_TAX.values())})
    df["Jurisdiction"] = df["ISO3"]
    df["Year"] = 2024
    return {"data": df, "status": "fallback", "source": FALLBACK_TAX_LABEL + " - fetch failed",
            "url": OECD_REPORT_URL, "date": "tax year 2024", "fetched": _now(), "note": "; ".join(errors)}


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_bond_table() -> dict:
    try:
        df = parse_te_bonds_html(_get(TE_BONDS_URL).text)
        return {"data": df, "status": "live", "source": "Trading Economics - 10Y government bond yields",
                "url": TE_BONDS_URL, "date": f"retrieved {_now()}", "fetched": _now()}
    except Exception as e:
        df = pd.DataFrame({"Country": list(FALLBACK_YIELDS), "Yield": list(FALLBACK_YIELDS.values())})
        df["TE date"] = FALLBACK_YIELDS_DATE
        df["slug"] = df["Country"].str.lower().str.replace(" ", "-")
        return {"data": df, "status": "fallback",
                "source": "Trading Economics - embedded snapshot (fetch failed)",
                "url": TE_BONDS_URL, "date": FALLBACK_YIELDS_DATE, "fetched": _now(), "note": str(e)}


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_country_yield(slug: str) -> dict | None:
    """Second route: the individual Trading Economics country page."""
    url = TE_COUNTRY_URL.format(slug=slug)
    try:
        y, date = parse_te_country_page(_get(url).text)
        return {"value": y, "status": "live", "source": "Trading Economics country page",
                "url": url, "date": date, "fetched": _now()}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
def pct(x: float, d: int = 2) -> str:
    return f"{x * 100:.{d}f}%"


def status_badge(s: str) -> str:
    return "🟢 live" if s == "live" else "🟠 fallback"


def main() -> None:
    st.set_page_config(page_title="International Cost of Capital", page_icon="🌐", layout="wide")
    st.title("🌐 International Cost of Capital")
    st.caption("Cost of equity, cost of debt and WACC for a project in USD and in a selected country's currency.")

    # ---------------- data ----------------
    with st.sidebar:
        st.header("Data")
        if st.button("🔄 Refresh data", width="stretch",
                     help="Clear the cache and re-download all sources"):
            st.cache_data.clear()
            for k in list(st.session_state):
                if k.startswith("ov_"):
                    del st.session_state[k]
            st.rerun()

    with st.spinner("Fetching latest data from Damodaran, OECD and Trading Economics..."):
        betas = fetch_betas()
        bbb = fetch_bbb_spread()
        taxes = fetch_tax_rates()
        bonds = fetch_bond_table()

    beta_df: pd.DataFrame = betas["data"]
    bond_df: pd.DataFrame = bonds["data"]
    tax_df: pd.DataFrame = taxes["data"]
    tax_by_iso = dict(zip(tax_df["ISO3"], tax_df["Tax rate"]))
    tax_year_by_iso = dict(zip(tax_df["ISO3"], tax_df["Year"]))

    industries = beta_df["Industry"].tolist()
    countries = sorted(set(bond_df["Country"]) | {DEFAULT_COUNTRY})

    # ---------------- inputs ----------------
    with st.sidebar:
        st.header("Project inputs")
        industry = st.selectbox("Industry", industries,
                                index=industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0)
        country = st.selectbox("Target country", countries, index=countries.index(DEFAULT_COUNTRY))
        tax_choice = st.radio("Project tax rate", ["U.S. rate", "Selected-country rate"], horizontal=True,
                              help="One tax rate is used for both the USD and the foreign-currency calculation.")
        erp = st.number_input("Equity risk premium (%)", 0.0, 20.0, DEFAULT_ERP, 0.1) / 100
        debt_share = st.slider("Target debt share D/(D+E) (%)", 0, 90, DEFAULT_DEBT, 1) / 100
        method = st.radio(
            "Currency conversion", ["Interest-rate parity (multiplicative)", "Additive (swap risk-free rate)"],
            help="Parity: k_FC = (1+k_USD)(1+rf_F)/(1+rf_US) - 1. Additive: k_FC = rf_F + beta_L x ERP.")
        method_key = "parity" if method.startswith("Interest") else "additive"

    # fetched (auto) values
    iso_f = COUNTRY_ISO3.get(country)
    beta_auto = float(beta_df.loc[beta_df["Industry"] == industry, "Unlevered beta"].iloc[0])
    tax_us_auto = tax_by_iso.get("USA")
    tax_f_auto = tax_by_iso.get(iso_f) if iso_f else None

    def yield_for(name: str) -> tuple[float | None, dict]:
        row = bond_df.loc[bond_df["Country"] == name]
        if not row.empty and bonds["status"] == "live":
            return float(row["Yield"].iloc[0]), {"status": "live", "date": f"TE date {row['TE date'].iloc[0]}"
                                                 f" · {bonds['date']}", "url": bonds["url"]}
        slug = row["slug"].iloc[0] if not row.empty else name.lower().replace(" ", "-")
        alt = fetch_country_yield(slug)
        if alt:
            return alt["value"], alt
        if not row.empty:
            return float(row["Yield"].iloc[0]), {"status": "fallback", "date": FALLBACK_YIELDS_DATE,
                                                 "url": bonds["url"]}
        return None, {"status": "fallback", "date": "n/a", "url": bonds["url"]}

    rf_us_auto, rf_us_meta = yield_for("United States")
    rf_f_auto, rf_f_meta = yield_for(country)

    # ---------------- overrides ----------------
    with st.sidebar:
        st.header("Manual overrides")
        st.caption("Tick a box to replace the fetched value.")

        def override(label, key, auto, fmt_default, step=0.01, minv=-5.0, maxv=100.0, force=False):
            on = st.checkbox(f"Override {label}", key=f"ov_{key}_on", value=force)
            default = float(auto) if auto is not None else fmt_default
            if on:
                v = st.number_input(f"{label}", minv, maxv, default, step, key=f"ov_{key}_val",
                                    format="%.4f" if "beta" in label.lower() else "%.2f")
                return v, True
            st.caption(f"↳ fetched {label}: **{'n/a' if auto is None else f'{auto:.4f}' if 'beta' in label.lower() else f'{auto:.2f}%'}**")
            return default, False

        beta_u, beta_ov = override("unlevered beta", "beta", beta_auto, 1.0, 0.01, 0.0, 5.0)
        tax_us_pct, tax_us_ov = override("U.S. tax rate (%)", "taxus", tax_us_auto, 21.0, 0.1, 0.0, 60.0,
                                         force=tax_us_auto is None)
        tax_f_pct, tax_f_ov = override(f"{country} tax rate (%)", f"taxf_{country}", tax_f_auto, 25.0, 0.1, 0.0, 60.0,
                                       force=tax_f_auto is None)
        spread_pct, spread_ov = override("USD BBB spread (%)", "spread", bbb["value"], 1.11, 0.01, 0.0, 20.0)
        rf_us_pct, rf_us_ov = override("U.S. 10Y yield (%)", "rfus", rf_us_auto, 4.0, 0.01, -2.0, 50.0,
                                       force=rf_us_auto is None)
        rf_f_pct, rf_f_ov = override(f"{country} 10Y yield (%)", f"rff_{country}", rf_f_auto, 4.0, 0.01, -2.0, 100.0,
                                     force=rf_f_auto is None)

        # auto foreign spread shown when override is off
        tax_used = (tax_us_pct if tax_choice.startswith("U.S.") else tax_f_pct) / 100
        preview = compute_cost_of_capital(beta_u, tax_used, debt_share, erp, rf_us_pct / 100,
                                          rf_f_pct / 100, spread_pct / 100, None, method_key)
        fspread_on = st.toggle("Override foreign-currency BBB spread", key="ov_fspread_on")
        if fspread_on:
            fspread_pct = st.number_input("Foreign-currency BBB spread (%)", 0.0, 50.0,
                                          round(preview["spread_fc_auto"] * 100, 4), 0.01, key="ov_fspread_val")
            spread_f_override = fspread_pct / 100
        else:
            st.caption(f"↳ auto foreign-currency spread: **{pct(preview['spread_fc_auto'], 3)}**"
                       + ("  = USD spread × (1+rf_F)/(1+rf_US)" if method_key == "parity" else "  = USD spread"))
            spread_f_override = None

    if country == "United States":
        st.info("Selected country is the United States, so both columns are in USD and should match "
                "(choose another target country to compare currencies).")
    if tax_f_auto is None:
        st.warning(f"No OECD tax rate found for {country}; enter it under Manual overrides.")

    r = compute_cost_of_capital(beta_u, tax_used, debt_share, erp, rf_us_pct / 100, rf_f_pct / 100,
                                spread_pct / 100, spread_f_override, method_key)
    ccy = CURRENCY.get(country, "local currency")

    # ---------------- results ----------------
    st.subheader(f"{industry} · USD vs {ccy} ({country})")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 🇺🇸 USD")
        m1, m2, m3 = st.columns(3)
        m1.metric("Cost of equity", pct(r["ke_usd"]))
        m2.metric("After-tax cost of debt", pct(r["kd_usd_after"]))
        m3.metric("WACC", pct(r["wacc_usd"]))
    with c2:
        st.markdown(f"#### {country} · {ccy}")
        m1, m2, m3 = st.columns(3)
        m1.metric("Cost of equity", pct(r["ke_fc"]), f"{(r['ke_fc'] - r['ke_usd']) * 1e4:+.0f} bp vs USD",
                  delta_color="off")
        m2.metric("After-tax cost of debt", pct(r["kd_fc_after"]),
                  f"{(r['kd_fc_after'] - r['kd_usd_after']) * 1e4:+.0f} bp vs USD", delta_color="off")
        m3.metric("WACC", pct(r["wacc_fc"]), f"{(r['wacc_fc'] - r['wacc_usd']) * 1e4:+.0f} bp vs USD",
                  delta_color="off")

    detail = pd.DataFrame(
        [
            ["10-year government bond yield (rf)", pct(r["rf_usd"]), pct(r["rf_fc"])],
            ["Unlevered beta", f"{r['beta_u']:.4f}", f"{r['beta_u']:.4f}"],
            ["Project tax rate", pct(r["tax"]), pct(r["tax"])],
            ["Debt share D/V  ·  D/E", f"{pct(r['debt_share'], 1)}  ·  {r['de_ratio']:.4f}",
             f"{pct(r['debt_share'], 1)}  ·  {r['de_ratio']:.4f}"],
            ["Levered beta", f"{r['beta_l']:.4f}", f"{r['beta_l']:.4f}"],
            ["Equity risk premium", pct(r["erp"]), pct(r["erp"])],
            ["Cost of equity", pct(r["ke_usd"]), pct(r["ke_fc"])],
            ["BBB spread", pct(r["spread_usd"], 3),
             pct(r["spread_fc"], 3) + (" (override)" if spread_f_override is not None else " (auto)")],
            ["Pre-tax cost of debt", pct(r["kd_usd_pre"]), pct(r["kd_fc_pre"])],
            ["After-tax cost of debt", pct(r["kd_usd_after"]), pct(r["kd_fc_after"])],
            ["WACC", pct(r["wacc_usd"]), pct(r["wacc_fc"])],
        ],
        columns=["Item", "USD", f"{ccy} ({country})"],
    )
    st.dataframe(detail, hide_index=True, width="stretch")

    # ---------------- sources ----------------
    st.subheader("Data sources")
    src = pd.DataFrame(
        [
            ["Unlevered beta", f"{beta_auto:.4f}", betas["source"], betas["date"], status_badge(betas["status"]),
             "✏️ yes" if beta_ov else "", betas["url"]],
            ["U.S. corporate tax rate", "n/a" if tax_us_auto is None else f"{tax_us_auto:.2f}%", taxes["source"],
             f"tax year {tax_year_by_iso.get('USA', 'n/a')}", status_badge(taxes["status"]),
             "✏️ yes" if tax_us_ov else "", taxes["url"]],
            [f"{country} corporate tax rate", "n/a" if tax_f_auto is None else f"{tax_f_auto:.2f}%",
             taxes["source"], f"tax year {tax_year_by_iso.get(iso_f, 'n/a')}", status_badge(taxes["status"]),
             "✏️ yes" if tax_f_ov else "", taxes["url"]],
            ["USD BBB spread", f"{bbb['value']:.2f}%", bbb["source"], bbb["date"], status_badge(bbb["status"]),
             "✏️ yes" if spread_ov else "", bbb["url"]],
            ["U.S. 10Y yield", "n/a" if rf_us_auto is None else f"{rf_us_auto:.3f}%", "Trading Economics",
             rf_us_meta["date"], status_badge(rf_us_meta["status"]), "✏️ yes" if rf_us_ov else "",
             rf_us_meta["url"]],
            [f"{country} 10Y yield", "n/a" if rf_f_auto is None else f"{rf_f_auto:.3f}%", "Trading Economics",
             rf_f_meta["date"], status_badge(rf_f_meta["status"]), "✏️ yes" if rf_f_ov else "",
             rf_f_meta["url"]],
        ],
        columns=["Input", "Fetched value", "Source", "Data date", "Status", "Overridden", "Link"],
    )
    st.dataframe(src, hide_index=True, width="stretch",
                 column_config={"Link": st.column_config.LinkColumn("Link", display_text="open")})
    notes = [f"{n}: {d['note']}" for n, d in [("Betas", betas), ("BBB spread", bbb), ("Tax", taxes),
                                              ("Bonds", bonds)] if d.get("note")]
    if notes:
        with st.expander("⚠️ Fetch diagnostics"):
            st.write("\n\n".join(notes))
    st.caption(f"Fetched: betas {betas['fetched']} · spread {bbb['fetched']} · tax {taxes['fetched']} · "
               f"bonds {bonds['fetched']}. Data are cached for a few hours; use **Refresh data** to re-download.")

    # ---------------- assumptions ----------------
    with st.expander("📘 Formulas and main assumptions", expanded=False):
        st.markdown(
            rf"""
**Shared across both currencies:** unlevered beta, project tax rate *t* (U.S. or selected country, chosen
with the switch), target debt share $w_d$, equity risk premium (ERP).

1. **Levered beta (Hamada):** $\beta_L = \beta_U\,[1 + (1-t)\,D/E]$, with $D/E = w_d/(1-w_d)$.
2. **USD cost of equity (CAPM):** $k_e^{{USD}} = r_f^{{US}} + \beta_L \times ERP$.
3. **USD pre-tax cost of debt:** $k_d^{{USD}} = r_f^{{US}} + s_{{BBB}}$ (Damodaran Baa2/BBB spread, large non-financial firms).
4. **Foreign-currency rates (interest-rate parity / international Fisher effect):**
   $k^{{FC}} = (1+k^{{USD}})\,\frac{{1+r_f^{{F}}}}{{1+r_f^{{US}}}} - 1$.
   Hence the auto foreign spread is $s^{{FC}} = s_{{BBB}}\,\frac{{1+r_f^{{F}}}}{{1+r_f^{{US}}}}$ and
   $k_d^{{FC}} = r_f^{{F}} + s^{{FC}}$. With the *Additive* option instead: $k_e^{{FC}} = r_f^{{F}} + \beta_L \times ERP$ and $s^{{FC}} = s_{{BBB}}$.
   If the foreign spread override is on, the typed spread replaces $s^{{FC}}$ (USD results are untouched).
5. **WACC:** $WACC = (1-w_d)\,k_e + w_d\,k_d\,(1-t)$, in each currency.

**Assumptions:** 10-year government yields are treated as risk-free in their own currency (the difference between
the two yields captures expected inflation / currency depreciation, including any default risk priced into the
foreign yield). The project's business risk is the U.S. industry beta. The tax rate is the combined statutory
CIT rate (central + sub-central) from OECD. Debt is BBB-rated; the U.S. ERP is applied in both currencies.
"""
        )

    # ---------------- built-in checks ----------------
    with st.expander("✅ Verification checks (computed live)", expanded=False):
        base = dict(beta_u=beta_u, tax=tax_used, debt_share=debt_share, erp=erp, rf_us=rf_us_pct / 100,
                    spread_usd=spread_pct / 100, method=method_key)
        eq = compute_cost_of_capital(**base, rf_f=rf_us_pct / 100, spread_f_override=None)
        c_eq = all(abs(eq[a] - eq[b]) < 1e-12 for a, b in
                   [("ke_usd", "ke_fc"), ("kd_usd_after", "kd_fc_after"), ("wacc_usd", "wacc_fc")])
        z = compute_cost_of_capital(**{**base, "debt_share": 0.0}, rf_f=rf_f_pct / 100, spread_f_override=None)
        c_z = abs(z["wacc_usd"] - z["ke_usd"]) < 1e-12 and abs(z["wacc_fc"] - z["ke_fc"]) < 1e-12
        a0 = compute_cost_of_capital(**base, rf_f=rf_f_pct / 100, spread_f_override=None)
        a1 = compute_cost_of_capital(**base, rf_f=rf_f_pct / 100, spread_f_override=0.05)
        c_o = all(a0[k] == a1[k] for k in ["ke_usd", "kd_usd_pre", "kd_usd_after", "wacc_usd"])
        st.markdown(
            f"- {'✅' if c_eq else '❌'} Equal yields (rf_F = rf_US = {rf_us_pct:.2f}%, spread override off) → "
            f"WACC {pct(eq['wacc_usd'], 4)} vs {pct(eq['wacc_fc'], 4)}\n"
            f"- {'✅' if c_z else '❌'} Zero debt → WACC = cost of equity: USD {pct(z['wacc_usd'], 4)} = "
            f"{pct(z['ke_usd'], 4)}; FC {pct(z['wacc_fc'], 4)} = {pct(z['ke_fc'], 4)}\n"
            f"- {'✅' if c_o else '❌'} Overriding the foreign spread (to 5.00%) leaves USD results unchanged: "
            f"USD WACC {pct(a0['wacc_usd'], 4)} → {pct(a1['wacc_usd'], 4)} (FC WACC "
            f"{pct(a0['wacc_fc'], 4)} → {pct(a1['wacc_fc'], 4)})"
        )

    # ---------------- all-industry comparison ----------------
    st.subheader("All-industry comparison")
    st.caption("Same country, tax rate, debt share, ERP, yields and spreads; only the unlevered beta changes. "
               "The unlevered-beta override applies to the selected industry only.")
    rows = []
    for ind, bu in zip(beta_df["Industry"], beta_df["Unlevered beta"]):
        bu_used = beta_u if ind == industry else float(bu)
        x = compute_cost_of_capital(bu_used, tax_used, debt_share, erp, rf_us_pct / 100, rf_f_pct / 100,
                                    spread_pct / 100, spread_f_override, method_key)
        rows.append({"Industry": ind, "Unlevered beta": bu_used, "Levered beta": x["beta_l"],
                     "Cost of equity USD (%)": x["ke_usd"] * 100, f"Cost of equity {ccy} (%)": x["ke_fc"] * 100,
                     "After-tax cost of debt USD (%)": x["kd_usd_after"] * 100,
                     f"After-tax cost of debt {ccy} (%)": x["kd_fc_after"] * 100,
                     "WACC USD (%)": x["wacc_usd"] * 100, f"WACC {ccy} (%)": x["wacc_fc"] * 100})
    all_df = pd.DataFrame(rows).sort_values("WACC USD (%)", ascending=False).reset_index(drop=True)

    tab1, tab2 = st.tabs(["Table", "Chart"])
    with tab1:
        num_cols = [c for c in all_df.columns if c != "Industry"]
        st.dataframe(all_df, hide_index=True, width="stretch", height=420,
                     column_config={c: st.column_config.NumberColumn(c, format="%.2f" if "(%)" in c else "%.4f")
                                    for c in num_cols})
    with tab2:
        import altair as alt
        which = st.radio("Show WACC in", ["USD", ccy], horizontal=True) if ccy != "USD" else "USD"
        col = "WACC USD (%)" if which == "USD" else f"WACC {ccy} (%)"
        cd = all_df[["Industry", col]].rename(columns={col: "WACC"}).copy()
        cd["Selected"] = np.where(cd["Industry"] == industry, "Selected industry", "Other industries")
        chart = (
            alt.Chart(cd).mark_bar()
            .encode(
                x=alt.X("WACC:Q", title=f"WACC in {which} (%)"),
                y=alt.Y("Industry:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
                color=alt.Color("Selected:N", scale=alt.Scale(domain=["Selected industry", "Other industries"],
                                                              range=["#d9480f", "#4c6ef5"]),
                                legend=alt.Legend(title=None, orient="top")),
                tooltip=["Industry", alt.Tooltip("WACC:Q", format=".2f")],
            )
            .properties(height=max(300, 14 * len(cd)))
        )
        st.altair_chart(chart, width="stretch")

    # ---------------- downloads ----------------
    st.subheader("Download results")
    inputs_df = pd.DataFrame(
        [
            ["Industry", industry], ["Target country", country], ["Currency", ccy],
            ["Tax rate choice", tax_choice], ["Project tax rate (%)", tax_used * 100],
            ["Equity risk premium (%)", erp * 100], ["Debt share (%)", debt_share * 100],
            ["Conversion method", method], ["Unlevered beta", beta_u],
            ["USD BBB spread (%)", spread_pct], ["U.S. 10Y yield (%)", rf_us_pct],
            [f"{country} 10Y yield (%)", rf_f_pct],
            ["Foreign spread (%)", r["spread_fc"] * 100],
            ["Foreign spread override", "on" if spread_f_override is not None else "off (auto)"],
            ["Generated", _now()],
        ],
        columns=["Parameter", "Value"],
    )
    results_long = pd.DataFrame(
        {"Metric": ["Levered beta", "Cost of equity (%)", "Pre-tax cost of debt (%)",
                    "After-tax cost of debt (%)", "WACC (%)"],
         "USD": [r["beta_l"], r["ke_usd"] * 100, r["kd_usd_pre"] * 100, r["kd_usd_after"] * 100,
                 r["wacc_usd"] * 100],
         ccy if ccy != "USD" else "USD (selected country)":
             [r["beta_l"], r["ke_fc"] * 100, r["kd_fc_pre"] * 100, r["kd_fc_after"] * 100, r["wacc_fc"] * 100]})

    xbuf = io.BytesIO()
    with pd.ExcelWriter(xbuf, engine="openpyxl") as xw:
        inputs_df.astype({"Value": str}).to_excel(xw, sheet_name="Inputs", index=False)
        results_long.to_excel(xw, sheet_name="Results", index=False)
        all_df.to_excel(xw, sheet_name="All industries", index=False)
        src.to_excel(xw, sheet_name="Sources", index=False)

    d1, d2, d3 = st.columns(3)
    d1.download_button("⬇️ Results (Excel, all sheets)", xbuf.getvalue(),
                       f"cost_of_capital_{country.replace(' ', '_')}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       width="stretch")
    d2.download_button("⬇️ Side-by-side results (CSV)",
                       pd.concat([inputs_df.astype(str).rename(columns={"Parameter": "Item", "Value": "USD"}),
                                  pd.DataFrame([["", "", ""]], columns=detail.columns), detail])
                       .to_csv(index=False),
                       "side_by_side_results.csv", "text/csv", width="stretch")
    d3.download_button("⬇️ All-industry comparison (CSV)", all_df.to_csv(index=False),
                       f"all_industries_{country.replace(' ', '_')}.csv", "text/csv", width="stretch")


if __name__ == "__main__":
    main()
