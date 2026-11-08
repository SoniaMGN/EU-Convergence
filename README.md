# EU regional convergence: data layer (Project C)

Question: are EU NUTS 2 regions converging on income and employment? This repository part covers the data work:
**download, cleaning, sample decisions, codebook, README and the data section of the report.** The analysis
(sigma, beta, clubs, ...) is built by other people on top of the files produced here.

## Run everything
```
python -m pip install -r requirements.txt
python run_data.py
```
`run_data.py` runs all the steps below in order and stops at the first failure.

## Or run the steps one by one
```
python src/fetch.py         # download: raw JSON-stat + GISCO -> data/raw/ (+ manifest.json). Only network step.
python src/panel.py         # cleaning + sample: universe, flags, coverage, balanced panels
python src/validate.py      # automated checks -> results/validation.json (any failure stops)
python src/explore.py       # optional: descriptive stats, missing data, outliers (Lecture 2 techniques)
python src/data_report.py   # writes report/data_section.md and CODEBOOK.md from the results
python -m pytest tests/     # unit tests on synthetic data
```
Or run everything in one go:
```
python src/run_all.py       # fetch, panel, validate, explore, report (add --skip-fetch to reuse frozen data)
```
Or `make data validate report-data test`. After the first good run: commit `data/raw/` and tag `v0.1-data`.
Never re-run `fetch.py --force` after that: it would replace the frozen data.

## What each deliverable is
| Deliverable | File |
|---|---|
| Download (frozen, hashed) | `src/fetch.py`, `data/raw/`, `data/raw/manifest.json` |
| Cleaning | `src/panel.py`, `src/validate.py`, `src/explore.py`, `results/quality_flags.csv` |
| Sample decisions | `config/settings.yaml`, `results/sample_inclusions.csv`, `DECISIONS.md` |
| Codebook | `CODEBOOK.md` (generated) |
| README | this file |
| Data section of the report | `report/data_section.md` (generated; every number comes from `results/`) |

## Main outputs
| File | Content |
|---|---|
| `results/coverage.csv`, `figures/coverage_heatmap.png` | valid regions per variable and year |
| `results/sample_inclusions.csv` | each region in each balanced panel, with its missing years |
| `results/quality_flags.csv` | observation counts by Eurostat flag, and whether dropped |
| `results/gdp_break_flags.csv` | region-years with a `b` flag on GDP series |
| `data/processed/regional_panel.csv` | full region x year grid, one column per variable (+ `_flag`) |
| `data/processed/region_reference.csv` | code, country, name, centroid, break flag, main-panel membership |
| `data/processed/eu27_benchmark.csv`, `sector_shares_2000.csv` | EU27 series and 2000 sector shares |

Rules: no imputation, interpolation or hand edits; a region missing any year is outside that balanced panel.
Choices and their reasons: `DECISIONS.md`. Column meanings: `CODEBOOK.md`.
