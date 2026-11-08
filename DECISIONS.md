# DECISIONS.md (data layer, milestone M1)

Every place where the plan says *your choice*, or leaves a data-handling detail open, with the reason.
Other sections (clubs, bootstrap, commuter groups, ...) are filled in by the people who own those steps.

## Process note: blind-first rule
While the data layer was being built, the sealed Appendix (reference results) and the first-run
notebook (`analysis.ipynb` outputs) were opened by mistake, before the `v0.3-independent` tag exists.
Nothing from them was used: every rule below follows the plan text and the course material, and no
threshold, filter or panel definition was chosen by looking at a reference number. The team should
still decide whether this affects the claim of blind work, and record that decision here.

## Fixed by the plan (implemented as written)
- Universe: 244 GISCO NUTS 2024 level-2 regions with `EU_STAT = T`; historical codes, non-EU codes,
  NUTS 0/1 and aggregates are dropped from the panel. Only current codes and Eurostat's back-calculated
  history are used, never spliced by hand.
- Period 2000-2024; household income used to 2023.
- Datasets and filters exactly as in the plan; the `EU27_2020` aggregate rows are kept (`eu27_benchmark.csv`).
- Flags e, p, b, d kept; observations flagged `u` dropped for labour variables only; counts in `quality_flags.csv`.
- No imputation, interpolation or hand edits. A region missing any year is out of that balanced panel.
- Raw responses gzipped, never edited, with URL, UTC time, `updated` field and SHA-256 in `manifest.json`.

## Choices made here
1. **2024 household income.** Shown as a coverage note: `coverage.csv` and the heatmap include 2024, the
   2024 values stay in `regional_panel.csv`, but the matched GDP-income panel stops in 2023 as the plan says.
2. **Unit kept is applied after download.** The plan's filter column omits `unit` for real GDP,
   population and household income, so the request uses the plan's filters exactly and the unit is
   selected from the response (`I20`, `THS`, `PPS_EU27_2020_HAB`).
3. **Request strategy.** One request per dataset. If the API refuses it (too large), the same request is
   repeated in blocks of 60 regions (+ `EU27_2020`); each response is its own frozen file. Values are the same.
4. **What counts as a valid observation.** A non-missing numeric value, after the flag rule above. A flag with no
   value (for example `:`) is missing. Values are not range-trimmed here: impossible values would fail
   `validate.py` instead of being silently dropped.
5. **"GDP break flagged" region.** A region with a `b` flag in `gdp_pps` or `real_gdp` (the two series used in the
   beta regressions) in 2000-2024. Listed in `results/gdp_break_flags.csv`; marked in `region_reference.csv`.
   Break flags on other series are counted in `quality_flags.csv` but do not flag a region.
6. **Outcome-specific panels** (all in `config/settings.yaml`, results in `sample_inclusions.csv`):
   main = GDP (PPS), population and real GDP, 2000-2024; GDP 2010-2024 and 2015-2024 = the same variables over those windows (the RQ1 sigma samples; the plan names the 2010-2024 sample in RQ1 but not in the sample rules, so it is added here);
   employment and youth unemployment each for 2000-2024 and 2015-2024; GDP + household income 2000-2023.
7. **GISCO file.** The 20M-resolution 2024 file (`NUTS_RG_20M_2024_4326_LEVL_2.geojson`): only boundaries
   and centroids are needed. Centroids are planar, area-weighted, in lon/lat degrees. For the Moran I
   k-nearest-neighbour weights this is an approximation; the owner of RQ3 may want projected (EPSG:3035)
   distances and should record it.
8. **Sector shares 2000.** A, B-E, F, G-J, K-N over TOTAL; O-U kept as `share_O-U` and `share_sum` as a check.
9. **Exploration (`src/explore.py`).** Descriptive only (Lecture 2: describe, missing data MCAR/MAR/MNAR and the 3%
   rule, outliers by z-score, IQR, percentile, isolation forest). It never changes `data/`.
   Outliers are flagged, not removed: persistent extremes (Ireland, Luxembourg) are real, and the plan
   treats them with explicit robustness runs instead.

## Still open (not data-layer)
- Commuter groups, HP lambda, club trim and lag, bootstrap draws: owners of those steps.
