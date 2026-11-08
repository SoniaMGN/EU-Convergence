"""panel.py: universe, flags, coverage and balanced panels (plan: "Sample construction rules").

Reads ONLY the frozen raw cache in data/raw/. Nothing is imputed, interpolated or hand-edited.

Writes
  data/processed/region_reference.csv      geo, country, name, centroid, break flag, main-panel membership
  data/processed/<var>_source_selected.csv rows kept for each variable (universe, window, flag rules applied)
  data/processed/<var>_wide.csv            region x year
  data/processed/regional_panel.csv        full 244 x 25 grid, one column per variable (+ <var>_flag)
  data/processed/eu27_benchmark.csv        EU27_2020 aggregate series
  data/processed/sector_shares_2000.csv    GVA shares 2000 (A, B-E, F, G-J, K-N over TOTAL)
  results/coverage.csv, sample_inclusions.csv, quality_flags.csv, gdp_break_flags.csv
  figures/coverage_heatmap.png
"""
import argparse
import json

import matplotlib
import numpy as np
import pandas as pd

from common import get_paths, jsonstat_to_df, load_config, load_universe, read_json_gz

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SECTORS = ["A", "B-E", "F", "G-J", "K-N"]          # public and other services (O-U) omitted
UNRELIABLE = "u"


def compress_years(years):
    ys = sorted({int(y) for y in years})
    out, i = [], 0
    while i < len(ys):
        j = i
        while j + 1 < len(ys) and ys[j + 1] == ys[j] + 1:
            j += 1
        out.append(str(ys[i]) if i == j else f"{ys[i]}-{ys[j]}")
        i = j + 1
    return ",".join(out)


def apply_flag_rules(df, labour):
    """Keep e/p/b/d flagged values. Drop observations flagged u (low reliability) for labour data only.
    Missing values stay missing (never filled)."""
    keep = df["value"].notna()
    if labour:
        keep &= ~df["flag"].fillna("").str.contains(UNRELIABLE)
    return df[keep]


def load_variable(name, spec, P, manifest):
    entries = [e for e in manifest["files"] if e["variable"] == name]
    if not entries:
        raise SystemExit(f"{name}: no raw files in manifest. Run src/fetch.py first.")
    df = pd.concat([jsonstat_to_df(read_json_gz(P.raw / e["file"])) for e in entries], ignore_index=True)
    if spec.get("unit_kept"):
        df = df[df["unit"] == spec["unit_kept"]]
    key = ["geo", "time"] + (["nace_r2"] if name == "gva_2000" else [])
    leftover = [c for c in df.columns if c not in set(key) | {"value", "flag"} and df[c].nunique() > 1]
    if leftover:
        raise SystemExit(f"{name}: dimensions {leftover} still vary; check the filters in settings.yaml")
    dup = df.duplicated(key, keep=False)
    if dup.any() and df[dup].groupby(key)["value"].nunique().gt(1).any():
        raise SystemExit(f"{name}: duplicate keys with different values")
    df = df.drop_duplicates(key)
    df["year"] = pd.to_numeric(df["time"], errors="coerce")
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)
    df["flag"] = df["flag"].fillna("").astype(str)
    return df[["geo", "year"] + (["nace_r2"] if name == "gva_2000" else []) + ["value", "flag"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--root", default=None)
    a = ap.parse_args()
    cfg, P = load_config(a.config), get_paths(a.root)
    manifest = json.loads((P.raw / "manifest.json").read_text())
    ref = load_universe(P)
    universe = list(ref["geo"])
    y0, y1 = cfg["years"]["start"], cfg["years"]["end"]
    years = list(range(y0, y1 + 1))
    print(f"Universe: {len(universe)} regions, {len(set(ref['country']))} countries; years {y0}-{y1}")

    grid = pd.MultiIndex.from_product([universe, years], names=["geo", "year"]).to_frame(index=False)
    grid.insert(1, "country", grid["geo"].str[:2])
    quality, eu, wide = [], pd.DataFrame({"year": years}), {}

    for name, spec in cfg["datasets"].items():
        if name == "gva_2000":
            continue
        df = load_variable(name, spec, P, manifest)
        win = df[df["year"].between(y0, y1)]
        uni = win[win["geo"].isin(universe)].copy()
        aggr = win[win["geo"] == cfg["eu_aggregate"]].copy()
        other = len(win) - len(uni) - len(aggr)
        labour = bool(spec.get("labour"))

        label = uni["flag"].replace("", "(none)")
        for lab, n in label.value_counts().sort_index().items():
            quality.append(dict(variable=name, flag=lab, observations=int(n),
                                dropped=bool(labour and lab != "(none)" and UNRELIABLE in lab)))
        kept = apply_flag_rules(uni, labour)
        n_special = int((~np.isfinite(kept["value"])).sum())
        print(f"{name:20s} universe rows {len(uni):6,}  kept {len(kept):6,}  "
              f"dropped (flag u) {len(uni) - len(kept) - int(uni['value'].isna().sum()):4,}  "
              f"other geo (historical/non-EU/country) {other:6,}  non-finite {n_special}")

        kept.sort_values(["geo", "year"]).to_csv(P.processed / f"{name}_source_selected.csv", index=False)
        grid = grid.merge(kept[["geo", "year", "value", "flag"]]
                          .rename(columns={"value": name, "flag": f"{name}_flag"}),
                          on=["geo", "year"], how="left")
        eu = eu.merge(apply_flag_rules(aggr, labour)[["year", "value", "flag"]]
                      .rename(columns={"value": name, "flag": f"{name}_flag"}), on="year", how="left")
        wide[name] = grid.pivot(index="geo", columns="year", values=name).reindex(universe)
        wide[name].to_csv(P.processed / f"{name}_wide.csv")

    grid.to_csv(P.processed / "regional_panel.csv", index=False)
    eu.to_csv(P.processed / "eu27_benchmark.csv", index=False)
    pd.DataFrame(quality).to_csv(P.results / "quality_flags.csv", index=False)

    # sector shares 2000
    sec = load_variable("gva_2000", cfg["datasets"]["gva_2000"], P, manifest)
    sec = sec[(sec["year"] == 2000) & sec["geo"].isin(universe)].dropna(subset=["value"])
    gv = sec.pivot(index="geo", columns="nace_r2", values="value").reindex(universe)
    shares = pd.DataFrame(index=gv.index)
    for s in SECTORS + ["O-U"]:
        shares[f"share_{s}"] = gv[s] / gv["TOTAL"] if s in gv and "TOTAL" in gv else np.nan
    shares["share_sum"] = shares.sum(axis=1, min_count=len(SECTORS) + 1)
    shares.insert(0, "gva_total_meur", gv["TOTAL"] if "TOTAL" in gv else np.nan)
    shares.reset_index(names="geo").to_csv(P.processed / "sector_shares_2000.csv", index=False)
    n_sec = int(shares[[f"share_{s}" for s in SECTORS]].notna().all(axis=1).sum())
    print(f"{'gva_2000':20s} regions with all five sector shares in 2000: {n_sec}")

    # coverage (variable x year), incl. the 2024 household income coverage note
    cov = []
    for name in wide:
        for y in years:
            cov.append(dict(variable=name, year=y, valid_regions=int(wide[name][y].notna().sum()),
                            universe=len(universe)))
    cov.append(dict(variable="gva_2000", year=2000, valid_regions=n_sec, universe=len(universe)))
    cov = pd.DataFrame(cov)
    cov.to_csv(P.results / "coverage.csv", index=False)

    m = cov[cov["variable"] != "gva_2000"].pivot(index="variable", columns="year", values="valid_regions")
    m = m.reindex(list(wide))
    fig, ax = plt.subplots(figsize=(12, 3.8))
    im = ax.imshow(m.values, aspect="auto", cmap="viridis", vmin=0, vmax=len(universe))
    ax.set_xticks(range(len(years)), years, rotation=90, fontsize=7)
    ax.set_yticks(range(len(m)), m.index, fontsize=8)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            ax.text(j, i, int(m.values[i, j]), ha="center", va="center", fontsize=5,
                    color="white" if m.values[i, j] < len(universe) * .6 else "black")
    fig.colorbar(im, ax=ax, label=f"valid regions (of {len(universe)})")
    ax.set_title("Coverage: valid regions per variable and year")
    fig.tight_layout()
    fig.savefig(P.figures / "coverage_heatmap.png", dpi=150)
    plt.close(fig)

    # GDP break flags
    brk = []
    for s in cfg["gdp_break_series"]:
        b = grid[grid[f"{s}_flag"].fillna("").str.contains("b")]
        brk.append(b[["geo", "country", "year"]].assign(series=s))
    brk = pd.concat(brk, ignore_index=True)
    brk.to_csv(P.results / "gdp_break_flags.csv", index=False)
    flagged = set(brk["geo"])

    # balanced panels and inclusions
    rows = []
    for pname, spec in cfg["panels"].items():
        w0, w1 = spec["window"]
        for _, r in ref.iterrows():
            miss = {}
            for v in spec["variables"]:
                ys = [y for y in range(w0, w1 + 1) if pd.isna(wide[v].loc[r["geo"], y])]
                if ys:
                    miss[v] = ys
            rows.append(dict(panel=pname, geo=r["geo"], country=r["country"], name=r["name"],
                             included=not miss, n_missing_years=sum(len(v) for v in miss.values()),
                             missing_years=";".join(f"{v}:{compress_years(ys)}" for v, ys in miss.items())))
    inc = pd.DataFrame(rows)
    inc.to_csv(P.results / "sample_inclusions.csv", index=False)
    print("\nBalanced panels (regions / countries):")
    for pname in cfg["panels"]:
        d = inc[(inc["panel"] == pname) & inc["included"]]
        print(f"  {pname:22s} {len(d):4d} / {d['country'].nunique():2d}")
    ex = inc[(inc["panel"] == "main") & ~inc["included"]]
    print(f"\nMain panel exclusions ({len(ex)}):")
    print(ex.groupby("country").size().to_string())

    ref = ref.assign(gdp_break_flagged=ref["geo"].isin(flagged),
                     in_main_panel=ref["geo"].isin(inc[(inc["panel"] == "main") & inc["included"]]["geo"]))
    ref.to_csv(P.processed / "region_reference.csv", index=False)
    print("\nWrote data/processed/, results/coverage.csv, sample_inclusions.csv, quality_flags.csv, "
          "gdp_break_flags.csv, figures/coverage_heatmap.png")


if __name__ == "__main__":
    main()
