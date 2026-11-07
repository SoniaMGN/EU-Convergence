"""Fetch NUTS2 data for Project C (EU regional convergence) from the Eurostat SDMX API.

Free, no key, no registration. Output: one tidy CSV per indicator in ./data,
plus a merged panel (data/panel_nuts2.csv).

Filters are given by dimension NAME. The script reads each dataset's structure
(DSD) from Eurostat to get the dimension order and builds the key itself, so no
positions are hard-coded. Datasets already downloaded are skipped (delete the
CSV in ./data to re-fetch).

Requires: pandas, requests
"""
import io
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

ROOT = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1"
OUT = Path("data")
OUT.mkdir(exist_ok=True)

# name -> (dataset code, {dimension: value or [values]})
DATASETS = {
    "gdp_pps_head": ("nama_10r_2gdp", {"freq": "A", "unit": "PPS_EU27_2020_HAB"}),
    "gdp_eur_head": ("nama_10r_2gdp", {"freq": "A", "unit": "EUR_HAB"}),
    "employment_rate": (
        "lfst_r_lfe2emprt",
        {"freq": "A", "sex": "T", "age": "Y20-64", "unit": "PC"},
    ),
    "youth_unemployment": (
        "lfst_r_lfu3rt",
        {"freq": "A", "sex": "T", "age": "Y15-24", "unit": "PC"},
    ),
    "gva_sectors": (
        "nama_10r_3gva",
        {
            "freq": "A",
            "unit": "MIO_EUR",
            "nace_r2": ["A", "B-E", "F", "G-J", "K-N", "O-U", "TOTAL"],
        },
    ),
    "population": (
        "demo_r_d2jan",
        {"freq": "A", "unit": "NR", "age": "TOTAL", "sex": "T"},
    ),
}


def dimension_order(code: str):
    """Return the dimension ids of a dataset in key order, or None if unavailable."""
    for dsd in (code.upper(), code.lower()):
        try:
            r = requests.get(f"{ROOT}/datastructure/ESTAT/{dsd}", timeout=60)
            if r.status_code != 200:
                continue
            tree = ET.fromstring(r.content)
            dims = []
            for el in tree.iter():
                if el.tag.split("}")[-1] == "Dimension" and el.get("id"):
                    dims.append((int(el.get("position", len(dims) + 1)), el.get("id")))
            if dims:
                return [d for _, d in sorted(dims)]
        except Exception:
            continue
    return None


def build_key(order, filters):
    parts = []
    for dim in order:
        v = filters.get(dim, filters.get(dim.lower(), ""))
        parts.append("+".join(v) if isinstance(v, (list, tuple)) else v)
    return ".".join(parts)


def fetch(code: str, filters: dict, start: int = 1990) -> pd.DataFrame:
    order = dimension_order(code)
    if order:
        key = build_key(order, filters)
        print(f"  dimensions: {'.'.join(order)}  ->  key: {key}")
        url = f"{ROOT}/data/{code}/{key}"
    else:
        print("  (could not read dataset structure; fetching unfiltered and filtering locally)")
        url = f"{ROOT}/data/{code}"
    params = {"format": "SDMX-CSV", "startPeriod": start, "compressed": "false"}
    r = requests.get(url, params=params, timeout=300)
    if not r.ok:
        print("  Eurostat said:", r.text[:500])
        r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))

    # safety net: apply the same filters locally, by column name
    for dim, v in filters.items():
        if dim in df.columns:
            vals = v if isinstance(v, (list, tuple)) else [v]
            df = df[df[dim].isin(vals)]

    # keep only NUTS2 (4-char geo codes, e.g. DE21, FR10)
    df = df[df["geo"].str.len() == 4].copy()
    df = df.rename(columns={"TIME_PERIOD": "year", "OBS_VALUE": "value"})
    df["year"] = df["year"].astype(int)
    keep = [c for c in df.columns if c in {"geo", "year", "value", "nace_r2", "unit", "OBS_FLAG"}]
    return df[keep]


def main():
    frames = {}
    for name, (code, filters) in DATASETS.items():
        path = OUT / f"{name}.csv"
        if path.exists():
            print(f"Skipping {name} (already in {path})")
            frames[name] = pd.read_csv(path)
            continue
        print(f"Fetching {name} ({code}) ...")
        df = fetch(code, filters)
        df.to_csv(path, index=False)
        frames[name] = df
        print(f"  {len(df):,} rows, {df['geo'].nunique()} regions, "
              f"{df['year'].min()}-{df['year'].max()}")

    # merged wide panel (one row per region-year)
    panel = None
    for name, df in frames.items():
        if name == "gva_sectors":
            wide = df.pivot_table(index=["geo", "year"], columns="nace_r2",
                                  values="value").add_prefix("gva_").reset_index()
        else:
            wide = df[["geo", "year", "value"]].rename(columns={"value": name})
        panel = wide if panel is None else panel.merge(wide, on=["geo", "year"], how="outer")
    panel.sort_values(["geo", "year"]).to_csv(OUT / "panel_nuts2.csv", index=False)
    print(f"Panel: {panel.shape[0]:,} rows -> {OUT/'panel_nuts2.csv'}")


if __name__ == "__main__":
    main()