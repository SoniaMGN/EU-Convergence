"""Explore the cleaned NUTS2 panel: descriptive statistics, missing data, outliers, plots.

Follows the Lecture 2 workflow (describe -> check distribution shape -> missing values
(MCAR/MAR/MNAR, 3% rule) -> outliers (percentile, z-score, IQR/boxplot, isolation forest)).
Nothing is imputed, removed or written back to data/: it only produces evidence for decisions in DECISIONS.md.

Input : data/processed/regional_panel.csv    (made by panel.py)
Output: results/exploration/
          descriptive_stats.csv   count, mean, std, quartiles, skew, kurtosis per variable and year
          missingness.csv         share missing per variable, 3%-rule flag
          missing_by_country.csv  share missing per variable and country
          missing_by_year.csv     share missing per variable and year
          outlier_summary.csv     how many points each method flags
          outlier_flags.csv       every flagged region-year, with which methods flagged it
          fig_*.png               missingness map, boxplots, histograms, correlation heatmaps

Usage: python src/explore.py [--panel data/processed/regional_panel.csv] [--out results/exploration] [--year 2022]
Requires: pandas, numpy, matplotlib   (optional: scikit-learn for the isolation forest)
"""
import argparse
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

VARS = ["gdp_pps", "gdp_eur", "real_gdp", "employment", "youth_unemployment",
        "population", "household_income"]
LOGVARS = {"gdp_pps", "gdp_eur", "real_gdp", "population", "household_income"}
LOG = []


def say(msg=""):
    print(msg)
    LOG.append(msg)


def describe(panel, vars_, years):
    rows = []
    for y in years:
        d = panel[panel["year"] == y]
        for v in vars_:
            s = d[v].dropna()
            if s.empty:
                continue
            row = dict(year=y, variable=v, count=len(s), missing_pct=100 * d[v].isna().mean(),
                       mean=s.mean(), std=s.std(), min=s.min(), q25=s.quantile(.25),
                       median=s.median(), q75=s.quantile(.75), max=s.max(),
                       skew=s.skew(), excess_kurtosis=s.kurt())
            if v in LOGVARS and (s > 0).all():
                row["skew_of_log"] = np.log(s).skew()
            rows.append(row)
    return pd.DataFrame(rows)


def missingness(panel, vars_, out):
    years = np.arange(panel["year"].min(), panel["year"].max() + 1)
    n_geo = panel["geo"].nunique()
    full = n_geo * len(years)
    rows = []
    for v in vars_:
        miss = 1 - panel[v].notna().sum() / full
        rows.append(dict(variable=v, missing_pct=100 * miss,
                         over_3pct_rule_of_thumb=bool(miss > 0.03)))
    m = pd.DataFrame(rows)
    m.to_csv(out / "missingness.csv", index=False)
    say(f"== missing data (share of the {n_geo} regions x {len(years)} years grid)")
    say(m.round(1).to_string(index=False))
    say("  Lecture rule of thumb: deletion is only 'okay' if MCAR and < 3% missing.")

    # where is it missing? (looking for MAR structure)
    grid = panel.set_index(["geo", "year"])[vars_].reindex(
        pd.MultiIndex.from_product([sorted(panel["geo"].unique()), years], names=["geo", "year"]))
    miss_ind = grid.isna().reset_index()
    miss_ind["country"] = miss_ind["geo"].str[:2]
    by_c = miss_ind.groupby("country")[vars_].mean().mul(100)
    by_y = miss_ind.groupby("year")[vars_].mean().mul(100)
    by_c.to_csv(out / "missing_by_country.csv")
    by_y.to_csv(out / "missing_by_year.csv")
    for v in vars_:
        worst = by_c[v].sort_values(ascending=False).head(3)
        say(f"  {v}: worst countries -> " + ", ".join(f"{c} {p:.0f}%" for c, p in worst.items()))

    # does missingness relate to income? (MCAR vs MAR hint)
    if "log_gdp_pps" in panel.columns:
        say("\n  Is missingness related to income level? (mean log GDP per head, missing vs present)")
        base = panel["log_gdp_pps"]
        for v in vars_:
            if v == "gdp_pps":
                continue
            flag = panel[v].isna()
            if flag.sum() > 10 and (~flag).sum() > 10:
                say(f"    {v}: missing {base[flag].mean():.3f}  vs present {base[~flag].mean():.3f}")
        say("    A clear gap suggests MAR/MNAR: dropping or imputing then biases the sample.")

    # missingness map
    show = [v for v in ["gdp_pps", "employment", "youth_unemployment"] if v in vars_]
    geos = sorted(panel["geo"].unique())
    fig, axes = plt.subplots(1, len(show), figsize=(4.5 * len(show), 9), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, v in zip(axes, show):
        mat = grid[v].isna().unstack("year").reindex(geos).values.astype(float)
        ax.imshow(mat, aspect="auto", cmap="Greys", interpolation="nearest",
                  extent=[years.min() - .5, years.max() + .5, len(geos), 0])
        ax.set_title(f"{v}\n(black = missing)")
    axes[0].set_ylabel("regions (sorted by code)")
    fig.tight_layout()
    fig.savefig(out / "fig_missingness_map.png", dpi=130)
    plt.close(fig)


def outliers(panel, vars_, out):
    say("\n== outliers (detected and flagged, NOT removed; single pass, so no masking)")
    flags, summary = [], []
    for v in vars_:
        d = panel[["geo", "year", v]].dropna().copy()
        if v in LOGVARS:
            d = d[d[v] > 0]
            d["x"] = np.log(d[v])
        else:
            d["x"] = d[v]
        g = d.groupby("year")["x"]
        d["z"] = (d["x"] - g.transform("mean")) / g.transform("std")
        q1, q3 = g.transform(lambda s: s.quantile(.25)), g.transform(lambda s: s.quantile(.75))
        iqr = q3 - q1
        lo_p, hi_p = g.transform(lambda s: s.quantile(.01)), g.transform(lambda s: s.quantile(.99))
        d["flag_z3"] = d["z"].abs() > 3
        d["flag_iqr"] = (d["x"] < q1 - 1.5 * iqr) | (d["x"] > q3 + 1.5 * iqr)
        d["flag_pct"] = (d["x"] < lo_p) | (d["x"] > hi_p)
        d.insert(0, "variable", v)
        flags.append(d[d[["flag_z3", "flag_iqr", "flag_pct"]].any(axis=1)])
        summary.append(dict(variable=v, n=len(d), z_gt_3=int(d["flag_z3"].sum()),
                            iqr_1_5=int(d["flag_iqr"].sum()), outside_1_99_pct=int(d["flag_pct"].sum()),
                            scale="log" if v in LOGVARS else "raw"))

    # multivariate: isolation forest on standardised features, pooled over years
    iso_rows = None
    try:
        from sklearn.ensemble import IsolationForest
        feats = [f for f in ["log_gdp_pps", "employment", "youth_unemployment"] if f in panel.columns]
        feats += ["log_population"] if "population" in panel.columns else []
        p = panel.copy()
        if "population" in p.columns:
            p["log_population"] = np.log(p["population"].where(p["population"] > 0))
        p = p.dropna(subset=feats)
        z = p.groupby("year")[feats].transform(lambda s: (s - s.mean()) / s.std())
        ok = z.notna().all(axis=1)
        if ok.sum() > 100:
            pred = IsolationForest(contamination=0.01, random_state=0).fit_predict(z[ok])
            iso_rows = p.loc[ok, ["geo", "year"]].assign(isolation_forest=(pred == -1))
            iso_rows = iso_rows[iso_rows["isolation_forest"]]
            summary.append(dict(variable="multivariate: " + "+".join(feats), n=int(ok.sum()),
                                isolation_forest=len(iso_rows), scale="standardised per year"))
    except ImportError:
        say("  (scikit-learn not installed: isolation forest skipped; pip install scikit-learn)")

    s = pd.DataFrame(summary)
    s.to_csv(out / "outlier_summary.csv", index=False)
    say(s.fillna("").to_string(index=False))

    f = pd.concat(flags) if flags else pd.DataFrame()
    if not f.empty:
        f["n_methods"] = f[["flag_z3", "flag_iqr", "flag_pct"]].sum(axis=1)
        f.to_csv(out / "outlier_flags.csv", index=False)
        rep = (f[f["flag_z3"]].groupby(["variable", "geo"]).size()
               .sort_values(ascending=False).head(10))
        say("\n  regions most often beyond |z|>3 (persistent = a real feature of the region, "
            "e.g. Ireland, Luxembourg, Inner London; one-off = suspect data):")
        say(rep.to_string())
    if iso_rows is not None and len(iso_rows):
        iso_rows.to_csv(out / "outlier_isolation_forest.csv", index=False)
        say("\n  isolation-forest regions (most frequent): " +
            ", ".join(f"{k} x{v}" for k, v in iso_rows["geo"].value_counts().head(8).items()))


def plots(panel, year, out):
    # boxplots across years (outliers show as dots)
    cols = [("log_gdp_pps", "log GDP per head (PPS)"), ("employment", "employment rate, %"),
            ("youth_unemployment", "youth unemployment, %")]
    cols = [c for c in cols if c[0] in panel.columns]
    fig, axes = plt.subplots(len(cols), 1, figsize=(11, 3.2 * len(cols)), sharex=True)
    axes = np.atleast_1d(axes)
    years = sorted(panel["year"].unique())
    for ax, (c, label) in zip(axes, cols):
        data = [panel.loc[panel["year"] == y, c].dropna().values for y in years]
        ax.boxplot(data, tick_labels=years, flierprops=dict(markersize=3))
        ax.set_ylabel(label)
    axes[-1].tick_params(axis="x", rotation=90)
    fig.tight_layout()
    fig.savefig(out / "fig_boxplots_by_year.png", dpi=130)
    plt.close(fig)

    # histograms: raw vs log GDP -> skew
    d = panel[panel["year"] == year]
    if d["gdp_pps"].notna().any():
        fig, ax = plt.subplots(1, 2, figsize=(10, 3.5))
        ax[0].hist(d["gdp_pps"].dropna(), bins=30)
        ax[0].set_title(f"GDP per head (PPS), {year}: skew {d['gdp_pps'].skew():.2f}")
        lg = np.log(d["gdp_pps"].dropna())
        ax[1].hist(lg, bins=30)
        ax[1].set_title(f"log GDP per head, {year}: skew {lg.skew():.2f}")
        fig.tight_layout()
        fig.savefig(out / "fig_hist_gdp.png", dpi=130)
        plt.close(fig)

    # correlation heatmaps (Pearson linear, Spearman monotonic)
    cand = ["log_gdp_pps", "employment", "youth_unemployment"]
    cand += [c for c in panel.columns if c.startswith("gva_share_")]
    cand = [c for c in cand if c in panel.columns]
    if len(cand) >= 2:
        fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
        for ax, method in zip(axes, ["pearson", "spearman"]):
            cm = d[cand].corr(method=method)
            im = ax.imshow(cm, vmin=-1, vmax=1, cmap="coolwarm")
            ax.set_xticks(range(len(cand)), cand, rotation=90, fontsize=7)
            ax.set_yticks(range(len(cand)), cand, fontsize=7)
            for i in range(len(cand)):
                for j in range(len(cand)):
                    if pd.notna(cm.iloc[i, j]):
                        ax.text(j, i, f"{cm.iloc[i, j]:.2f}", ha="center", va="center", fontsize=6)
            ax.set_title(f"{method}, {year}")
        fig.colorbar(im, ax=axes, shrink=.8)
        fig.savefig(out / "fig_correlation.png", dpi=130, bbox_inches="tight")
        plt.close(fig)
        d[cand].corr().to_csv(out / "correlation_pearson.csv")
        d[cand].corr(method="spearman").to_csv(out / "correlation_spearman.csv")
        say("\n  Correlation is not causation: use it to see structure, not to explain it.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="data/processed/regional_panel.csv")
    ap.add_argument("--out", default="results/exploration")
    ap.add_argument("--year", type=int, default=None, help="year for histograms/correlations")
    a = ap.parse_args()
    path = Path(a.panel)
    if not path.exists():
        raise SystemExit(f"Missing {path}. Run src/panel.py first.")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    panel = pd.read_csv(path)
    panel["log_gdp_pps"] = np.log(panel["gdp_pps"].where(panel["gdp_pps"] > 0))
    vars_ = [v for v in VARS if v in panel.columns]
    yrs = sorted(panel["year"].unique())
    year = a.year or int(panel.loc[panel["gdp_pps"].notna(), "year"].max())
    pick = sorted({yrs[0], 2010, 2015, year} & set(yrs))

    say(f"Panel: {len(panel):,} rows, {panel['geo'].nunique()} regions, {yrs[0]}-{yrs[-1]}")
    say("\n== descriptive statistics (Lecture: count/mean/quartiles, skew, excess kurtosis)")
    ds = describe(panel, vars_, pick)
    ds.to_csv(out / "descriptive_stats.csv", index=False)
    say(ds[["year", "variable", "count", "missing_pct", "mean", "std", "median", "skew",
            "excess_kurtosis"]].round(2).to_string(index=False))
    say("  skew > 0: long right tail (mean > median). Level variables are usually right-skewed, "
        "which is one reason to analyse logs.")

    missingness(panel, vars_, out)
    outliers(panel, vars_, out)
    plots(panel, year, out)
    (out / "explore_report.txt").write_text("\n".join(LOG), encoding="utf-8")
    say(f"\nWritten to {out}/")


if __name__ == "__main__":
    main()
