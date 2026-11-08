"""validate.py: automated checks (data layer). Writes results/validation.json; any failure stops the pipeline.

Plan items covered here: 4 (unique keys, 244 x 25 rows), 5 (positive levels, rates 0-100),
6 (real GDP index = 100 in 2020), 14 (reconstructed EU27 index within 1.5 points of Eurostat's
published index). Also: raw files match the manifest hashes; no +-inf / sentinel codes; the
universe has the expected size; balanced-panel membership really is complete.
The analysis steps (OLS recovery, log-t, HP, decompositions, clubs, Shapley, ...) add their own checks.
"""
import argparse
import json
import platform
import sys

import numpy as np
import pandas as pd

from common import get_paths, load_config, sha256_file

LEVELS = ["gdp_pps", "gdp_eur", "population", "real_gdp", "household_income"]
RATES = ["employment", "youth_unemployment"]
SENTINELS = [-1, -99, -999, -9999]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--root", default=None)
    a = ap.parse_args()
    cfg, P = load_config(a.config), get_paths(a.root)
    checks = []

    def check(item, name, passed, detail=""):
        checks.append(dict(plan_item=item, check=name, passed=bool(passed), detail=str(detail)))

    panel = pd.read_csv(P.processed / "regional_panel.csv")
    y0, y1 = cfg["years"]["start"], cfg["years"]["end"]
    n_years = y1 - y0 + 1

    check("4", "unique region-year keys", not panel.duplicated(["geo", "year"]).any())
    check("4", f"panel has exactly {cfg['expected_regions']} x {n_years} rows",
          len(panel) == cfg["expected_regions"] * n_years,
          f"{len(panel)} rows, {panel['geo'].nunique()} regions")

    bad = {v: int((panel[v] <= 0).sum()) for v in LEVELS if v in panel}
    check("5", "GDP, population (and income) positive", not any(bad.values()), bad)
    bad = {v: int(((panel[v] < 0) | (panel[v] > 100)).sum()) for v in RATES if v in panel}
    check("5", "rates lie within 0-100", not any(bad.values()), bad)

    num = panel.select_dtypes("number")
    n_inf = int(np.isinf(num.to_numpy()).sum())
    n_sent = int(num.drop(columns=["year"]).isin(SENTINELS).sum().sum())
    check("-", "no +-inf or sentinel codes (-1, -99, -999, -9999)", n_inf == 0 and n_sent == 0,
          f"inf={n_inf}, sentinel={n_sent}")

    r20 = panel.loc[panel["year"] == 2020, "real_gdp"].dropna()
    check("6", "real GDP index equals 100 in 2020", len(r20) > 0 and (r20 - 100).abs().max() < 0.05,
          f"{len(r20)} regions, max deviation {(r20 - 100).abs().max():.3f}" if len(r20) else "no data")

    eu = pd.read_csv(P.processed / "eu27_benchmark.csv")
    m = panel.merge(eu[["year", "gdp_pps"]].rename(columns={"gdp_pps": "eu_pps"}), on="year")
    m = m.dropna(subset=["gdp_pps", "eu_pps", "gdp_index_pub"])
    dev = (m["gdp_pps"] / m["eu_pps"] * 100 - m["gdp_index_pub"]).abs()
    check("14", "reconstructed EU27 index within 1.5 points of published index",
          len(dev) > 0 and dev.max() <= 1.5,
          f"{len(dev)} region-years, max deviation {dev.max():.2f}" if len(dev) else "no overlap")

    ref = pd.read_csv(P.processed / "region_reference.csv")
    check("-", f"universe has {cfg['expected_regions']} regions", len(ref) == cfg["expected_regions"], len(ref))

    inc = pd.read_csv(P.results / "sample_inclusions.csv")
    ok = True
    for pname, spec in cfg["panels"].items():
        w0, w1 = spec["window"]
        regs = inc[(inc["panel"] == pname) & inc["included"]]["geo"]
        sub = panel[panel["geo"].isin(regs) & panel["year"].between(w0, w1)]
        ok &= bool(sub[spec["variables"]].notna().all().all())
        ok &= bool(sub.groupby("geo").size().eq(w1 - w0 + 1).all()) if len(sub) else True
    check("-", "every balanced panel is complete (no missing, every year present)", ok)

    mf = json.loads((P.raw / "manifest.json").read_text())
    bad = [e["file"] for e in mf["files"]
           if not (P.raw / e["file"]).exists() or sha256_file(P.raw / e["file"]) != e["sha256"]]
    check("-", "raw files match manifest SHA-256 (never edited)", not bad, bad or f"{len(mf['files'])} files")
    check("-", "every dataset in settings.yaml is in the manifest",
          all(any(e["variable"] == v for e in mf["files"]) for v in cfg["datasets"]))

    (P.results / "validation.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    env = dict(python=platform.python_version(), pandas=pd.__version__, numpy=np.__version__)
    try:
        import matplotlib, requests, yaml
        env.update(matplotlib=matplotlib.__version__, requests=requests.__version__, pyyaml=yaml.__version__)
    except ImportError:
        pass
    (P.results / "environment.json").write_text(json.dumps(env, indent=2), encoding="utf-8")

    for c in checks:
        print(("PASS " if c["passed"] else "FAIL ") + c["check"] + (f"  [{c['detail']}]" if c["detail"] else ""))
    if not all(c["passed"] for c in checks):
        sys.exit("Validation failed: pipeline stops.")
    print(f"\n{len(checks)} checks passed")


if __name__ == "__main__":
    main()
