"""fetch.py: download the frozen raw data. This is the ONLY network step in the project.

Every response is saved gzipped in data/raw/ and never edited. data/raw/manifest.json records, per
file: the full URL, retrieval time (UTC), the dataset's own `updated` field and the file's SHA-256.
Existing files are never overwritten unless you pass --force (do not do that after milestone M1).

Usage:  python src/fetch.py [--config config/settings.yaml] [--root .] [--only gdp_pps ...] [--force]
"""
import argparse
import datetime as dt
import json
import sys
import time

import requests

from common import GISCO_FILE, get_paths, load_config, load_universe, sha256_file, write_gz


def http_get(url, params, ua, retries=3):
    last = None
    for i in range(retries):
        try:
            return requests.get(url, params=params, headers={"User-Agent": ua}, timeout=300)
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (i + 1))
    sys.exit(f"Network error for {url}: {last}")


def is_good(r):
    if r.status_code != 200:
        return False
    try:
        return "error" not in r.json()
    except ValueError:
        return False


def fetch_dataset(cfg, name, spec, universe, ua):
    """One full request; if the API refuses it (too big), the same request split by region."""
    url = f"{cfg['api_base']}/{spec['dataset']}"
    base = [("lang", "en"), ("freq", "A")] + list((spec.get("filters") or {}).items())
    r = http_get(url, base, ua)
    if is_good(r):
        return [(r.url, r.content)]
    print(f"  full request refused (HTTP {r.status_code}); splitting by region "
          f"in blocks of {cfg['chunk_size']}")
    geos = sorted(universe) + [cfg["eu_aggregate"]]
    parts = []
    n = cfg["chunk_size"]
    for i in range(0, len(geos), n):
        rr = http_get(url, base + [("geo", g) for g in geos[i:i + n]], ua)
        if not is_good(rr):
            sys.exit(f"{name}: request failed (HTTP {rr.status_code}): {rr.text[:300]}")
        parts.append((rr.url, rr.content))
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--root", default=None)
    ap.add_argument("--only", nargs="*", default=None, help="fetch only these variables")
    ap.add_argument("--force", action="store_true", help="re-download (breaks the freeze!)")
    a = ap.parse_args()
    cfg, P = load_config(a.config), get_paths(a.root)
    ua = cfg["user_agent"]
    mpath = P.raw / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"files": []}

    def have(variable):
        es = [e for e in manifest["files"] if e["variable"] == variable]
        return bool(es) and all((P.raw / e["file"]).exists() for e in es)

    def drop(variable):
        for e in [e for e in manifest["files"] if e["variable"] == variable]:
            (P.raw / e["file"]).unlink(missing_ok=True)
        manifest["files"] = [e for e in manifest["files"] if e["variable"] != variable]

    def save(variable, dataset, fname, url, content, updated):
        write_gz(P.raw / fname, content)
        manifest["files"].append(dict(
            variable=variable, dataset=dataset, file=fname, url=url,
            retrieved_utc=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            updated=updated, sha256=sha256_file(P.raw / fname), bytes=len(content)))
        mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # 1. GISCO boundaries (defines the universe)
    if a.force or not have("nuts2_2024"):
        print("Fetching GISCO NUTS 2024 level 2 ...")
        r = http_get(cfg["gisco_url"], None, ua)
        if r.status_code != 200:
            sys.exit(f"GISCO download failed (HTTP {r.status_code}). Check gisco_url in settings.yaml.")
        drop("nuts2_2024")
        save("nuts2_2024", "GISCO", GISCO_FILE, r.url, r.content, None)
    universe = list(load_universe(P)["geo"])
    print(f"Universe: {len(universe)} regions (EU_STAT = T)")

    # 2. Eurostat datasets
    for name, spec in cfg["datasets"].items():
        if a.only and name not in a.only:
            continue
        if have(name) and not a.force:
            print(f"Skipping {name}: already frozen in data/raw/")
            continue
        print(f"Fetching {name} ({spec['dataset']}) ...")
        parts = fetch_dataset(cfg, name, spec, universe, ua)
        drop(name)
        for k, (url, content) in enumerate(parts):
            updated = json.loads(content).get("updated")
            fname = f"{name}.json.gz" if len(parts) == 1 else f"{name}_part{k + 1:02d}.json.gz"
            save(name, spec["dataset"], fname, url, content, updated)
        print(f"  saved {len(parts)} file(s); dataset updated: {updated}")
    print("Done. Manifest:", mpath)


if __name__ == "__main__":
    main()
