"""Clean the NUTS2 data downloaded by fetch_eurostat_nuts2.py.

Input : ./data/*.csv          (one file per indicator)
Output: ./data_clean/
          panel_clean.csv           region-year panel, cleaned, with derived variables
          panel_balanced_gdp.csv    only regions with complete GDP + population for the window
          coverage.csv              valid regions per variable and year
          outliers.csv              suspicious jumps (flagged, NOT removed)
          cleaning_report.txt       every step with counts

Principles: nothing is imputed; observations are only removed when they are
invalid (duplicates, impossible values, flagged unreliable, non-region codes);
suspicious but possible values are flagged for you to judge.

Usage: python clean_nuts2.py [--raw data] [--out data_clean] [--start 2000] [--end 2024] [--keep-non-eu]
Requires: pandas, numpy
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

EU27 = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU",
    "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
}

# per variable: valid range, jump threshold for flagging, whether to compare on log scale
SPEC = {
    "gdp_pps_head":       dict(lo=0, hi=None, jump=0.25, log=True),
    "gdp_eur_head":       dict(lo=0, hi=None, jump=0.25, log=True),
    "employment_rate":    dict(lo=0, hi=100, jump=10, log=False),
    "youth_unemployment": dict(lo=0, hi=100, jump=15, log=False),
    "gva_sectors":        dict(lo=0, hi=None, jump=0.35, log=True),
    "population":         dict(lo=0, hi=None, jump=0.10, log=True),
}
SECTORS = ["A", "B-E", "F", "G-J", "K-N", "O-U"]

LOG = []


def say(msg):
    print(msg)
    LOG.append(msg)


def load(raw: Path, name: str) -> pd.DataFrame:
    path = raw / f"{name}.csv"
    if not path.exists():
        sys.exit(f"Missing {path}. Run fetch_eurostat_nuts2.py first.")
    df = pd.read_csv(path)
    df["geo"] = df["geo"].astype(str).str.strip().str.upper()
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def clean(name: str, df: pd.DataFrame, keep_non_eu: bool):
    spec = SPEC[name]
    say(f"\n== {name}: {len(df):,} raw rows")

    # 1. missing key fields
    n = len(df)
    df = df.dropna(subset=["geo", "year", "value"]).copy()
    df["year"] = df["year"].astype(int)
    say(f"  missing geo/year/value dropped: {n - len(df):,}")

    # 2. duplicates
    keys = ["geo", "year"] + (["nace_r2"] if "nace_r2" in df.columns else [])
    n = len(df)
    df = df.drop_duplicates(keys, keep="last")
    say(f"  duplicate rows dropped: {n - len(df):,}")

    # 3. non-region codes (extra-regio like FRZZ) and, by default, non-EU27 countries
    n = len(df)
    df = df[~df["geo"].str[2:].str.contains("Z")]
    say(f"  extra-regio / unknown codes (..Z.) dropped: {n - len(df):,}")
    if not keep_non_eu:
        n = len(df)
        outside = sorted(set(df.loc[~df["geo"].str[:2].isin(EU27), "geo"].str[:2]))
        df = df[df["geo"].str[:2].isin(EU27)]
        say(f"  non-EU27 rows dropped: {n - len(df):,}  (countries: {', '.join(outside) or '-'})")

    # 4. Eurostat reliability flags: drop low reliability (u) and confidential (c); keep break (b)
    df["flag_break"] = False
    if "OBS_FLAG" in df.columns:
        flag = df["OBS_FLAG"].fillna("").astype(str)
        bad = flag.str.contains("[uc]", regex=True)
        df["flag_break"] = flag.str.contains("b")
        say(f"  flagged low-reliability/confidential removed: {int(bad.sum()):,}; "
            f"series-break flags kept: {int(df['flag_break'].sum()):,}")
        df = df[~bad]
    else:
        say("  no OBS_FLAG column (re-run the updated fetch script to get reliability flags)")

    # 5. impossible values
    n = len(df)
    # level variables (log scale) must be strictly positive; rates may be 0
    ok = df["value"] > spec["lo"] if spec["log"] else df["value"] >= spec["lo"]
    if spec["hi"] is not None:
        ok &= df["value"] <= spec["hi"]
    df = df[ok]
    say(f"  out-of-range values dropped: {n - len(df):,}")

    # 6. flag suspicious jumps (kept)
    gk = [k for k in keys if k != "year"]
    d = df.sort_values(gk + ["year"]).copy()
    v = np.log(d["value"]) if spec["log"] else d["value"]
    d["_jump"] = v.groupby([d[k] for k in gk]).diff().abs()
    d["_gap"] = d.groupby(gk)["year"].diff()
    out = d[(d["_gap"] == 1) & (d["_jump"] > spec["jump"])].copy()
    out.insert(0, "variable", name)
    say(f"  suspicious year-on-year jumps flagged (kept): {len(out):,}")
    out = out.rename(columns={"_jump": "jump"})[["variable", *keys, "value", "jump"]]

    say(f"  clean rows: {len(df):,}, regions: {df['geo'].nunique()}, "
        f"years: {df['year'].min()}-{df['year'].max()}")
    return df, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data")
    ap.add_argument("--out", default="data_clean")
    ap.add_argument("--start", type=int, default=2000)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--keep-non-eu", action="store_true")
    a = ap.parse_args()
    raw, out = Path(a.raw), Path(a.out)
    out.mkdir(exist_ok=True)

    parts, outliers, break_flags = [], [], []
    for name in SPEC:
        df, o = clean(name, load(raw, name), a.keep_non_eu)
        outliers.append(o)
        if name == "gva_sectors":
            w = df.pivot_table(index=["geo", "year"], columns="nace_r2", values="value").add_prefix("gva_")
        else:
            w = df.set_index(["geo", "year"])["value"].rename(name).to_frame()
            if df["flag_break"].any():
                b = df.set_index(["geo", "year"])["flag_break"].rename(f"{name}_break").to_frame()
                w = w.join(b)
        parts.append(w)
    panel = pd.concat(parts, axis=1).reset_index()

    # sector consistency + shares
    say("\n== sectors")
    sec = [f"gva_{s}" for s in SECTORS if f"gva_{s}" in panel.columns]
    if "gva_TOTAL" in panel.columns and len(sec) == len(SECTORS):
        ssum = panel[sec].sum(axis=1, min_count=len(sec))
        rel = (ssum / panel["gva_TOTAL"] - 1).abs()
        say(f"  sector sums differing from TOTAL by >5%: {int((rel > 0.05).sum()):,} "
            f"of {int(rel.notna().sum()):,} comparable rows")
        for c in sec:
            panel[c.replace("gva_", "gva_share_")] = panel[c] / panel["gva_TOTAL"]
    else:
        say("  sector check skipped (missing sector columns)")

    # derived variables
    panel["log_gdp_pps"] = np.log(panel["gdp_pps_head"])
    w = panel["population"].where(panel["gdp_pps_head"].notna())
    mean = (panel["gdp_pps_head"] * w).groupby(panel["year"]).transform("sum") / \
        w.groupby(panel["year"]).transform("sum")
    panel["gdp_pps_rel"] = 100 * panel["gdp_pps_head"] / mean   # population-weighted mean = 100

    panel = panel.sort_values(["geo", "year"])
    panel.insert(2, "country", panel["geo"].str[:2])
    panel.to_csv(out / "panel_clean.csv", index=False)

    # coverage
    say("\n== coverage (valid regions per year)")
    vals = [c for c in panel.columns if c in SPEC or c.startswith("gva_") and "share" not in c]
    cov = panel.groupby("year")[vals].count()
    cov.to_csv(out / "coverage.csv")
    yrs = sorted({cov.index.min(), cov.index.max(), 2000, 2010, 2015, 2024} & set(cov.index))
    say(cov.loc[yrs, [c for c in vals if not c.startswith("gva_") or c == "gva_TOTAL"]].to_string())

    # balanced GDP panel
    end = a.end or int(panel.loc[panel["gdp_pps_head"].notna(), "year"].max())
    sub = panel[(panel["year"] >= a.start) & (panel["year"] <= end)]
    cnt = sub.dropna(subset=["gdp_pps_head", "population"]).groupby("geo").size()
    full = cnt[cnt == end - a.start + 1].index
    bal = sub[sub["geo"].isin(full)]
    bal.to_csv(out / "panel_balanced_gdp.csv", index=False)
    all_geo = sub["geo"].nunique()
    say(f"\n== balanced GDP panel {a.start}-{end}: {len(full)} regions kept, "
        f"{all_geo - len(full)} dropped (incomplete GDP/population)")
    dropped = sorted(set(sub["geo"]) - set(full))
    if dropped:
        say("  dropped: " + ", ".join(dropped))
    say("  likely cause for many drops: NUTS vintage changes (regions split/merged/recoded). "
        "Check these before analysis; do not impute.")

    pd.concat(outliers).to_csv(out / "outliers.csv", index=False)
    (out / "cleaning_report.txt").write_text("\n".join(LOG), encoding="utf-8")
    say(f"\nWritten to {out}/")


if __name__ == "__main__":
    main()