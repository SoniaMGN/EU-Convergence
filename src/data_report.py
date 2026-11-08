"""data_report.py: writes the data section of the report and the codebook FROM results/ (no typed numbers).

Run after fetch.py, panel.py and validate.py (and optionally explore.py):
    python src/data_report.py
Writes
    report/data_section.md   the data section of the report (paste or include in the full report)
    CODEBOOK.md              every variable and column: meaning, unit, source, filters, coverage, flags
"""
import argparse
import json

import pandas as pd

from common import get_paths, load_config

DESCRIPTIONS = {
    "gdp_pps": ("GDP per inhabitant, purchasing power standards (EU27_2020 PPS)", "PPS per inhabitant"),
    "gdp_index_pub": ("GDP per inhabitant in PPS, EU27 = 100: Eurostat's published index (rounded); "
                      "used only to cross-check the reconstructed index", "index, EU27 = 100"),
    "gdp_eur": ("GDP per inhabitant, current euro (for the euro-versus-PPS comparison)", "euro per inhabitant"),
    "real_gdp": ("Real GDP, chain-linked volume index (used for growth)", "index, 2020 = 100"),
    "population": ("Average annual population used to compute regional GDP", "thousand persons"),
    "employment": ("Employment rate, ages 20-64, both sexes", "% of population 20-64"),
    "youth_unemployment": ("Youth unemployment rate, ages 15-24, both sexes, all education levels",
                           "% of labour force 15-24"),
    "household_income": ("Net disposable household income per inhabitant (residence-based), balance",
                         "PPS per inhabitant"),
    "gva_2000": ("Gross value added by sector in 2000 (current prices), basis of the sector shares",
                 "million euro"),
}
FLAGS = {"e": "estimated", "p": "provisional", "b": "break in time series",
         "d": "definition differs", "u": "low reliability", ":": "not available"}
ORDER = ["gdp_pps", "gdp_index_pub", "gdp_eur", "real_gdp", "population", "employment",
         "youth_unemployment", "household_income"]


def md_table(df):
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |")
    return "\n".join(lines)


def filt(spec):
    f = "&".join(f"{k}={v}" for k, v in (spec.get("filters") or {}).items())
    return f or "none"


def flag_text(label):
    if label == "(none)":
        return "no flag"
    return ", ".join(FLAGS.get(c, c) for c in label)


def build(P, cfg):
    y0, y1 = cfg["years"]["start"], cfg["years"]["end"]
    ref = pd.read_csv(P.processed / "region_reference.csv")
    cov = pd.read_csv(P.results / "coverage.csv")
    inc = pd.read_csv(P.results / "sample_inclusions.csv")
    qf = pd.read_csv(P.results / "quality_flags.csv")
    brk = pd.read_csv(P.results / "gdp_break_flags.csv")
    mf = json.loads((P.raw / "manifest.json").read_text())
    val = json.loads((P.results / "validation.json").read_text()) if (P.results / "validation.json").exists() else []
    panel = pd.read_csv(P.processed / "regional_panel.csv")
    N, n_ctry = len(ref), ref["country"].nunique()
    n_years = y1 - y0 + 1

    # ---- sources table
    rows = []
    for v in ORDER + ["gva_2000"]:
        spec = cfg["datasets"][v]
        es = [e for e in mf["files"] if e["variable"] == v]
        rows.append({"Variable": v, "Eurostat dataset": spec["dataset"], "Filters": filt(spec),
                     "Unit kept": spec.get("unit_kept", "as filtered"),
                     "Dataset updated": (es[0]["updated"] or "")[:10] if es else "",
                     "Retrieved (UTC)": min(e["retrieved_utc"] for e in es)[:10] if es else ""})
    sources = md_table(pd.DataFrame(rows))

    # ---- coverage table
    c = cov[cov["variable"].isin(ORDER)].pivot(index="variable", columns="year", values="valid_regions")
    mid = 2015 if 2015 in c.columns else c.columns[len(c.columns) // 2]
    ct = pd.DataFrame({"Variable": ORDER,
                       f"{y0}": [int(c.loc[v, y0]) for v in ORDER],
                       f"{mid}": [int(c.loc[v, mid]) for v in ORDER],
                       f"{y1}": [int(c.loc[v, y1]) for v in ORDER],
                       "Lowest year": [f"{int(c.loc[v].min())} ({int(c.loc[v].idxmin())})" for v in ORDER]})
    coverage = md_table(ct)
    inc_y1 = int(c.loc["household_income", y1])
    sec = cov[cov["variable"] == "gva_2000"]["valid_regions"]
    n_sec = int(sec.iloc[0]) if len(sec) else 0

    # ---- quality flags
    q = []
    for v in ORDER:
        d = qf[qf["variable"] == v]
        tot = int(d["observations"].sum())
        flagged = d[d["flag"] != "(none)"]
        txt = "; ".join(f"{flag_text(r.flag)}: {int(r.observations):,}" for r in flagged.itertuples()) or "none"
        q.append({"Variable": v, "Observations": f"{tot:,}", "Flagged (count by flag)": txt,
                  "Dropped (flag u, labour only)": f"{int(d[d['dropped']]['observations'].sum()):,}"})
    quality = md_table(pd.DataFrame(q))
    n_brk_reg, n_brk_ctry = brk["geo"].nunique(), brk["country"].nunique()
    top = brk.drop_duplicates(["geo"]).groupby("country").size().sort_values(ascending=False).head(5)
    top_txt = ", ".join(f"{k} ({v})" for k, v in top.items()) or "none"

    # ---- panels
    pr = []
    for name, spec in cfg["panels"].items():
        d = inc[(inc["panel"] == name) & inc["included"]]
        pr.append({"Panel": name, "Window": f"{spec['window'][0]}-{spec['window'][1]}",
                   "Variables required": ", ".join(spec["variables"]),
                   "Regions": len(d), "Countries": d["country"].nunique()})
    panels = md_table(pd.DataFrame(pr))
    main = inc[inc["panel"] == "main"]
    ex = main[~main["included"]]
    by_c = ex.groupby("country").size().sort_values(ascending=False)
    ex_txt = ", ".join(f"{k} ({v})" for k, v in by_c.items()) or "none"
    if len(ex) and len(ex) <= 30:
        ex_list = "\n".join(f"- {r.geo} ({r.name}): {r.missing_years}" for r in ex.itertuples())
    else:
        ex_list = f"The {len(ex)} excluded regions and their missing years are listed in `results/sample_inclusions.csv`."
    main_in = main[main["included"]]
    pop_y1 = panel[panel["year"] == y1].set_index("geo")["population"]
    share = pop_y1[pop_y1.index.isin(main_in["geo"])].sum() / pop_y1.sum() * 100 if pop_y1.sum() else float("nan")

    # ---- exploration (optional)
    expl = ""
    mp = P.results / "exploration" / "missingness.csv"
    if mp.exists():
        m = pd.read_csv(mp)
        over = m[m["over_3pct_rule_of_thumb"]]
        expl = ("Missing data were examined descriptively (`src/explore.py`). Share of the region-year grid missing, "
                "by variable: " + "; ".join(f"{r.variable} {r.missing_pct:.1f}%" for r in m.itertuples()) + ". "
                + (f"Variables above the 3% rule of thumb for harmless deletion: {', '.join(over['variable'])}. "
                   if len(over) else "No variable exceeds the 3% rule of thumb. ")
                + "Where the gaps fall by country and year is in `results/exploration/missing_by_country.csv` and "
                  "`missing_by_year.csv`. Missingness is not assumed to be random, and nothing is imputed.")

    ie = cfg["years"]["income_end"]
    income_note = (f"The matched income panel stops in {ie} because the {y1} release covers too few regions; "
                   f"{y1} is shown as a coverage note only." if inc_y1 < 0.9 * N else
                   f"The matched income panel stops in {ie}, as fixed in the plan; {y1} is shown as a coverage note only.")
    n_pass = sum(1 for x in val if x["passed"])
    val_txt = (f"{n_pass} of {len(val)} data-layer validation checks pass (`results/validation.json`)."
               if val else "Validation results were not found; run `src/validate.py`.")

    section = f"""# Data

## Sources and retrieval
All data come from the Eurostat dissemination API (JSON-stat, no key) and the GISCO NUTS 2024 boundary file.
Each response was saved gzipped and unedited in `data/raw/`, with its URL, retrieval time, the dataset's own
update date and a SHA-256 hash recorded in `data/raw/manifest.json`; all later code reads only this frozen cache.

{sources}

Levels and dispersion use purchasing power standards (PPS), which remove national price-level differences;
growth uses real volume indices, which are unit-free. Euro GDP per inhabitant is kept only for the euro-versus-PPS comparison.

## Universe and period
The universe is the {N} NUTS 2024 level-2 regions marked `EU_STAT = T` in the GISCO file, in {n_ctry} countries.
Historical codes, non-EU codes and country or NUTS 1 aggregates are dropped from the panel; only current codes
with Eurostat's back-calculated history are used, never spliced by hand. The period is {y0}-{y1} ({n_years} years).
The brief speaks of thirty years of cohesion funding, but Eurostat's regional accounts under current codes start in
{y0}; earlier years would need another source (for example ARDECO) and are not spliced in silently.

## Coverage
The first step is to count how many of the {N} regions have a valid value for each variable and year
(`results/coverage.csv`; figure below). The count changes over time, so a region present in one year may be absent in another.

{coverage}

![Coverage: valid regions per variable and year](../figures/coverage_heatmap.png)

Household income is available for {inc_y1} regions in {y1} against {int(c.loc['household_income', y1 - 1])} in {y1 - 1}. {income_note}
Sector shares for 2000 are available for {n_sec} regions.

## Cleaning rules
- **No imputation.** Missing values stay missing; no interpolation and no hand-edited values. A region missing any
  year is outside that balanced panel and is never filled in.
- **Flags.** Eurostat flags for estimated (e), provisional (p), break (b) and definition-differs (d) values are kept.
  Observations flagged `u` (low reliability) are dropped for the two labour variables only.
- **Special values and duplicates.** Raw responses are checked for duplicate keys with conflicting values, infinite
  values and sentinel codes (-1, -99, -999, -9999); none may be present (checked in validation). Levels must be
  positive and rates within 0-100.
- **Outliers** are flagged and examined, not removed; persistent extremes such as Ireland and Luxembourg are
  treated with explicit robustness runs in the analysis.

{quality}

GDP break flags (b) on the PPS or real GDP series affect {n_brk_reg} region(s) in {n_brk_ctry} country(ies)
(largest counts: {top_txt}; `results/gdp_break_flags.csv`). Regions are marked `gdp_break_flagged` in `region_reference.csv`
and are excluded in the break-sensitivity runs.

{expl}

## Sample decisions: balanced panels
Every comparison uses a balanced panel, so the set of regions never changes inside a statistic. A region is in a
panel only if every required variable is present in every year of the window. Each outcome has its own panel and
panels must not be compared as if they were one sample.

{panels}

**Main panel.** {len(main_in)} regions in {main_in['country'].nunique()} countries, holding {share:.1f}% of the universe's {y1} population. {len(ex)} regions are excluded
(by country: {ex_txt}):

{ex_list}

All other choices (which series flag a break, the GISCO file, centroids, treatment of {y1} income) are recorded with
reasons in `DECISIONS.md`.

## Limitations
- Regional boundaries were redrawn in 2013, 2016, 2021 and 2024. Current codes with Eurostat's back-calculated
  history are used, but back-calculation can fail for some regions; this appears as missing years and as break flags.
- Output is counted where people work and population where they live, which distorts commuter regions;
  household income (residence-based) is used as a cross-check.
- Labour statistics have a survey break around 2021; the analysis reports windows that stop at 2020 and start at 2021.
- All results from these data are descriptive and associational. They do not estimate the causal effect of cohesion funding.

## Validation
{val_txt}
"""
    return section


def codebook(P, cfg):
    panel = pd.read_csv(P.processed / "regional_panel.csv")
    y0, y1 = cfg["years"]["start"], cfg["years"]["end"]
    out = ["# Codebook", "",
           "Generated by `src/data_report.py` from the settings and the data. One row per region and year in "
           "`data/processed/regional_panel.csv` (all regions in the universe x all years; missing values are empty).", "",
           "## regional_panel.csv", ""]
    rows = [{"Column": "geo", "Meaning": "NUTS 2024 level-2 region code", "Unit": "code", "Source": "GISCO", "Non-missing": "", "Years": ""},
            {"Column": "country", "Meaning": "Country code: first two characters of `geo`", "Unit": "code", "Source": "derived", "Non-missing": "", "Years": ""},
            {"Column": "year", "Meaning": "Reference year", "Unit": "year", "Source": "Eurostat", "Non-missing": "", "Years": f"{y0}-{y1}"}]
    for v in ORDER:
        spec = cfg["datasets"][v]
        d, u = DESCRIPTIONS[v]
        s = panel[v].notna()
        yrs = panel.loc[s, "year"]
        rows.append({"Column": v, "Meaning": d, "Unit": u, "Source": f"{spec['dataset']} ({filt(spec)})",
                     "Non-missing": f"{int(s.sum()):,} of {len(panel):,}",
                     "Years": f"{int(yrs.min())}-{int(yrs.max())}" if len(yrs) else ""})
        rows.append({"Column": f"{v}_flag", "Meaning": f"Eurostat flag attached to `{v}`", "Unit": "text",
                     "Source": "same", "Non-missing": f"{int(panel[f'{v}_flag'].notna().sum()):,}", "Years": ""})
    out += [md_table(pd.DataFrame(rows)), "", "### Flags", "",
            md_table(pd.DataFrame([{"Flag": k, "Meaning": v, "Treatment": (
                "dropped for employment and youth unemployment; kept for other series" if k == "u"
                else "missing" if k == ":" else "kept") } for k, v in FLAGS.items()])), "",
            "Missing means missing: no value was imputed, interpolated or edited. Levels are positive; rates lie within 0-100 (checked in validation).", ""]

    other = {
        "region_reference.csv": [("geo", "region code"), ("country", "country code"), ("name", "region name (NAME_LATN)"),
                                 ("lon, lat", "planar area-weighted centroid in degrees (approximate)"),
                                 ("gdp_break_flagged", "True if the PPS or real GDP series has a break flag (b) in the period"),
                                 ("in_main_panel", "True if the region is in the main balanced panel")],
        "eu27_benchmark.csv": [("year", "year"), ("<variable>", "the EU27_2020 aggregate for that variable (benchmark)"),
                               ("<variable>_flag", "its Eurostat flag")],
        "sector_shares_2000.csv": [("gva_total_meur", "total gross value added in 2000, million euro"),
                                   ("share_A ... share_K-N", "NACE sector shares of the total: agriculture (A), industry (B-E), construction (F), trade-transport-ICT (G-J), business-finance (K-N)"),
                                   ("share_O-U", "public and other services (omitted in regressions)"),
                                   ("share_sum", "check: the six shares add to 1")],
        "<variable>_wide.csv / _source_selected.csv": [("wide", "region by year table of the variable"), ("source_selected", "long table of the rows kept after the flag rules")],
        "results/coverage.csv": [("variable, year", "variable and year"), ("valid_regions", "regions with a valid value"), ("universe", "number of regions in the universe")],
        "results/sample_inclusions.csv": [("panel", "balanced panel name"), ("geo, country, name", "region"), ("included", "True if complete in the window"),
                                          ("n_missing_years, missing_years", "how many years and which (variable:years)")],
        "results/quality_flags.csv": [("variable, flag", "variable and Eurostat flag ((none) = no flag)"), ("observations", "count in the universe and period"), ("dropped", "True if observations with this flag were dropped")],
        "results/gdp_break_flags.csv": [("geo, country, year, series", "region-years with a break flag on a GDP series")],
    }
    for fname, items in other.items():
        out += [f"## {fname}", "", md_table(pd.DataFrame(items, columns=["Column", "Meaning"])), ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--root", default=None)
    a = ap.parse_args()
    cfg, P = load_config(a.config), get_paths(a.root)
    rep = P.root / "report"
    rep.mkdir(exist_ok=True)
    (rep / "data_section.md").write_text(build(P, cfg), encoding="utf-8")
    (P.root / "CODEBOOK.md").write_text(codebook(P, cfg), encoding="utf-8")
    print("Wrote report/data_section.md and CODEBOOK.md")


if __name__ == "__main__":
    main()
