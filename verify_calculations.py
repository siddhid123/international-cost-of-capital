"""
Independent checks of the cost-of-capital engine in app.py.
Run:  python verify_calculations.py
(Works without Streamlit installed: a tiny stub is used only for the cache decorator.)
"""
import sys
import types

try:
    import streamlit  # noqa: F401
except ImportError:  # stub so app.py can be imported for testing
    st = types.ModuleType("streamlit")
    st.cache_data = lambda *a, **k: (lambda f: f)
    sys.modules["streamlit"] = st

from app import (compute_cost_of_capital, parse_oecd_csv, parse_ratings_html,
                 parse_te_bonds_html, parse_te_country_page)

TOL = 1e-12
ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name)


# ---- 1. Worked example, computed by hand (same steps as a calculator / spreadsheet) ----
bu, t, w, erp, rf_us, rf_f, s = 1.20, 0.256, 0.30, 0.065, 0.0410, 0.0640, 0.0111
de = w / (1 - w)                                  # 0.428571
bl = bu * (1 + (1 - t) * de)                       # 1.582629
ke_usd = rf_us + bl * erp                          # 0.143871
kd_usd = rf_us + s                                 # 0.052100
wacc_usd = (1 - w) * ke_usd + w * kd_usd * (1 - t)
fx = (1 + rf_f) / (1 + rf_us)
ke_f = (1 + ke_usd) * fx - 1
kd_f = rf_f + s * fx
wacc_f = (1 - w) * ke_f + w * kd_f * (1 - t)
r = compute_cost_of_capital(bu, t, w, erp, rf_us, rf_f, s)
print(f"\nWorked example: beta_L={bl:.6f}  ke_USD={ke_usd:.6%}  WACC_USD={wacc_usd:.6%}  "
      f"ke_FC={ke_f:.6%}  kd_FC={kd_f:.6%}  WACC_FC={wacc_f:.6%}")
for k, v in [("beta_l", bl), ("ke_usd", ke_usd), ("wacc_usd", wacc_usd), ("ke_fc", ke_f),
             ("kd_fc_pre", kd_f), ("wacc_fc", wacc_f)]:
    check(f"worked example {k}", abs(r[k] - v) < TOL)
# auto foreign spread = full parity conversion of USD cost of debt
check("auto FC debt = (1+kd_USD)(1+rf_F)/(1+rf_US)-1", abs(r["kd_fc_pre"] - ((1 + kd_usd) * fx - 1)) < TOL)

# ---- 2. Required verification properties, over a grid of inputs ----
grid = [(b, tx, d, e, ru, rfx) for b in (0.4, 1.2, 2.0) for tx in (0.0, 0.21, 0.35)
        for d in (0.0, 0.3, 0.6) for e in (0.05, 0.065) for ru in (0.02, 0.045) for rfx in (0.01, 0.12, 0.30)]
for m in ("parity", "additive"):
    eq = all(
        all(abs(x[a] - x[b]) < TOL for a, b in [("ke_usd", "ke_fc"), ("kd_usd_pre", "kd_fc_pre"),
                                                ("wacc_usd", "wacc_fc")])
        for x in (compute_cost_of_capital(b, tx, d, e, ru, ru, s, None, m) for b, tx, d, e, ru, _ in grid))
    check(f"[{m}] equal government yields -> equal USD and FC results", eq)

    zd = all(
        abs(x["wacc_usd"] - x["ke_usd"]) < TOL and abs(x["wacc_fc"] - x["ke_fc"]) < TOL
        for x in (compute_cost_of_capital(b, tx, 0.0, e, ru, rfx, s, None, m) for b, tx, _, e, ru, rfx in grid))
    check(f"[{m}] zero debt -> WACC = cost of equity (both currencies)", zd)

    ov = all(
        all(x0[k] == x1[k] for k in ("beta_l", "ke_usd", "kd_usd_pre", "kd_usd_after", "wacc_usd"))
        and x0["wacc_fc"] != x1["wacc_fc"] or d == 0
        for b, tx, d, e, ru, rfx in grid
        for x0, x1 in [(compute_cost_of_capital(b, tx, d, e, ru, rfx, s, None, m),
                        compute_cost_of_capital(b, tx, d, e, ru, rfx, s, 0.0777, m))])
    check(f"[{m}] foreign spread override changes FC only, USD unchanged", ov)

# ---- 3. Parsers on representative snippets of each source ----
ratings_html = """<html><body><p>Data used is as of January 2026</p><table>
<tr><td>If interest coverage ratio is</td><td></td><td></td><td></td><td></td><td>If long term</td></tr>
<tr><td>&gt;</td><td>&le; to</td><td>Rating is</td><td>Spread is</td><td></td><td>&gt;</td><td>&le; to</td><td>Rating is</td><td>Spread is</td></tr>
<tr><td>3</td><td>4.249999</td><td>A3/A-</td><td>0.89%</td><td></td><td>1.5</td><td>2</td><td>A3/A-</td><td>0.89%</td></tr>
<tr><td>2.5</td><td>2.999999</td><td>Baa2/BBB</td><td>1.11%</td><td></td><td>1.2</td><td>1.5</td><td>Baa2/BBB</td><td>1.11%</td></tr>
</table></body></html>"""
sp, d = parse_ratings_html(ratings_html)
check(f"ratings parser -> {sp}% as of {d}", abs(sp - 1.11) < 1e-9 and d == "January 2026")

te_html = """<table><thead><tr><th>Major</th><th>Yield</th><th>Day</th><th>Weekly</th><th>Date</th></tr></thead>
<tr><td><a href="/united-states/government-bond-yield"><b>US 10Y</b></a></td><td>4.123</td><td>0.01</td><td>0.2%</td><td>Nov/13</td></tr>
<tr><td><a href="/germany/government-bond-yield">Germany</a></td><td>2.651</td><td>-0.02</td><td>0.1%</td><td>Nov/13</td></tr>
<tr><td><a href="/south-korea/government-bond-yield">South Korea</a></td><td>3.010</td><td>0.00</td><td>0.0%</td><td>Nov/13</td></tr>
</table>"""
bd = parse_te_bonds_html(te_html).set_index("Country")["Yield"].to_dict()
check(f"Trading Economics table parser -> {bd}",
      bd == {"United States": 4.123, "Germany": 2.651, "South Korea": 3.01})
y, d = parse_te_country_page('<meta content="The yield on US 10Y Note rose to 4.15% on November 13, 2026.">')
check(f"Trading Economics country-page parser -> {y}% on {d}", y == 4.15 and d == "November 13, 2026")

oecd_csv = """STRUCTURE,STRUCTURE_ID,STRUCTURE_NAME,ACTION,REF_AREA,Reference area,MEASURE,Measure,TIME_PERIOD,OBS_VALUE
DATAFLOW,X,Statutory and targeted CIT,I,USA,United States,CIT_C,Combined corporate income tax rate,2024,25.58
DATAFLOW,X,Statutory and targeted CIT,I,USA,United States,CIT_C,Combined corporate income tax rate,2025,25.6
DATAFLOW,X,Statutory and targeted CIT,I,USA,United States,CIT,Corporate income tax rate,2025,21
DATAFLOW,X,Statutory and targeted CIT,I,DEU,Germany,CIT_C,Combined corporate income tax rate,2025,29.94
"""
tx, yr = parse_oecd_csv(oecd_csv)
tmap = dict(zip(tx["ISO3"], tx["Tax rate"]))
check(f"OECD parser -> {tmap} (year {yr})", tmap == {"USA": 25.6, "DEU": 29.94} and yr == "2025")

print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
