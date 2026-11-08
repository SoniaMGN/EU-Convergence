"""Shared helpers for the Project C data pipeline (paths, config, hashing, JSON-stat parsing)."""
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
GISCO_FILE = "nuts2_2024.geojson.gz"


def load_config(path=None):
    p = Path(path) if path else REPO / "config" / "settings.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def get_paths(root=None):
    r = Path(root) if root else REPO
    P = SimpleNamespace(root=r, raw=r / "data" / "raw", processed=r / "data" / "processed",
                        results=r / "results", figures=r / "figures")
    for d in (P.raw, P.processed, P.results, P.figures):
        d.mkdir(parents=True, exist_ok=True)
    return P


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_gz(path, data: bytes):
    """Gzip with a fixed header (no mtime/filename) so identical content gives identical bytes."""
    with open(path, "wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(data)


def read_json_gz(path):
    with gzip.open(path, "rb") as f:
        return json.load(f)


def jsonstat_to_df(js):
    """JSON-stat 2.0 (Eurostat dissemination API) -> long DataFrame: one column per dimension,
    plus value and flag. Missing observations (absent from 'value') are not returned."""
    ids = js["id"]
    sizes = [int(s) for s in js["size"]]
    cats = {}
    for d in ids:
        idx = js["dimension"][d]["category"]["index"]
        cats[d] = sorted(idx, key=idx.get) if isinstance(idx, dict) else list(idx)

    vals = js.get("value", {})
    if isinstance(vals, list):
        pos = [i for i, v in enumerate(vals) if v is not None]
        v = [vals[i] for i in pos]
    else:
        pos = [int(k) for k in vals]
        v = list(vals.values())
    if not pos:
        return pd.DataFrame(columns=list(ids) + ["value", "flag"])

    pos = np.asarray(pos, dtype=np.int64)
    coords = np.unravel_index(pos, sizes)
    out = pd.DataFrame({d: np.asarray(cats[d], dtype=object)[coords[k]] for k, d in enumerate(ids)})
    out["value"] = pd.to_numeric(pd.Series(v), errors="coerce").to_numpy()

    st = js.get("status", {})
    if isinstance(st, list):
        st = {i: s for i, s in enumerate(st) if s}
    else:
        st = {int(k): s for k, s in st.items()}
    out["flag"] = [st.get(int(p), "") for p in pos]
    return out


def _ring_centroid(ring):
    x = np.array([p[0] for p in ring], dtype=float)
    y = np.array([p[1] for p in ring], dtype=float)
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cr = x * y1 - x1 * y
    a = cr.sum() / 2
    if abs(a) < 1e-12:
        return x.mean(), y.mean(), 0.0
    return ((x + x1) * cr).sum() / (6 * a), ((y + y1) * cr).sum() / (6 * a), abs(a)


def geometry_centroid(geom):
    """Area-weighted planar centroid (lon, lat degrees) of a Polygon/MultiPolygon exterior rings."""
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    parts = [_ring_centroid(p[0]) for p in polys]
    w = np.array([p[2] for p in parts])
    if w.sum() == 0:
        return float(np.mean([p[0] for p in parts])), float(np.mean([p[1] for p in parts]))
    return (float(np.average([p[0] for p in parts], weights=w)),
            float(np.average([p[1] for p in parts], weights=w)))


def load_universe(P):
    """The NUTS 2024 level-2 regions with EU_STAT = T from the frozen GISCO file."""
    gj = read_json_gz(P.raw / GISCO_FILE)
    rows = []
    for f in gj["features"]:
        pr = f["properties"]
        if str(pr.get("EU_STAT", "")).upper() != "T":
            continue
        lon, lat = geometry_centroid(f["geometry"])
        rows.append(dict(geo=pr["NUTS_ID"], country=pr["NUTS_ID"][:2], name=pr.get("NAME_LATN", ""),
                         lon=lon, lat=lat))
    return pd.DataFrame(rows).sort_values("geo").reset_index(drop=True)
