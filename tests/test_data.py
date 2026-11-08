"""Unit tests for the data layer (synthetic inputs only). Run: pytest tests/"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common import geometry_centroid, jsonstat_to_df  # noqa: E402
from panel import apply_flag_rules, compress_years  # noqa: E402


def make_js():
    return {
        "id": ["freq", "geo", "time"], "size": [1, 2, 2],
        "dimension": {
            "freq": {"category": {"index": {"A": 0}}},
            "geo": {"category": {"index": {"AT11": 0, "AT12": 1}}},
            "time": {"category": {"index": ["2000", "2001"]}},
        },
        "value": {"0": 1.5, "3": 4.0},
        "status": {"3": "b"},
        "updated": "2026-02-01T00:00:00+0100",
    }


def test_jsonstat_positions_and_flags():
    df = jsonstat_to_df(make_js()).sort_values("value").reset_index(drop=True)
    assert list(df["geo"]) == ["AT11", "AT12"]
    assert list(df["time"]) == ["2000", "2001"]
    assert list(df["flag"]) == ["", "b"]


def test_jsonstat_list_values_and_empty():
    js = make_js()
    js["value"] = [1.0, None, None, 9.0]
    df = jsonstat_to_df(js)
    assert len(df) == 2
    js["value"] = {}
    assert jsonstat_to_df(js).empty


def test_compress_years():
    assert compress_years([2000, 2001, 2002, 2005, 2007, 2008]) == "2000-2002,2005,2007-2008"
    assert compress_years([]) == ""


def test_flag_rules_labour_drops_u_only():
    df = pd.DataFrame({"value": [1.0, 2.0, 3.0, np.nan, 5.0], "flag": ["", "u", "bu", "", "e"]})
    assert list(apply_flag_rules(df, labour=True)["value"]) == [1.0, 5.0]
    # non-labour: u is kept (only missing values go); e/p/b/d are always kept
    assert list(apply_flag_rules(df, labour=False)["value"]) == [1.0, 2.0, 3.0, 5.0]


def test_missing_stays_missing():
    df = pd.DataFrame({"value": [np.nan], "flag": [":"]})
    assert apply_flag_rules(df, labour=False).empty


def test_centroid_square_and_multipolygon():
    sq = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    assert np.allclose(geometry_centroid(sq), (1, 1))
    mp = {"type": "MultiPolygon", "coordinates": [sq["coordinates"],
          [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]]]}
    lon, lat = geometry_centroid(mp)
    assert 1 < lon < 10.5 and 1 < lat < 10.5   # area-weighted toward the larger polygon
