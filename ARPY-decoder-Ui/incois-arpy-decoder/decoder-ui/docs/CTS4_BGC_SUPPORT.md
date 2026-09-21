# CTS4 BGC support in decoder-ui

N_PROF-aware BGC (biogeochemistry) display for 301 floats, built strictly on
top of the frozen 301 backend. No `src/argo_decoder/` file was touched for
this feature.

## Service (`decoder-ui/service/`)

- **`bgc_reader.py`** — parses one `BR<wmo>_<cyc>.nc` file profile-by-profile:
  each profile keeps its own `STATION_PARAMETERS`, pressure grid,
  per-parameter series with level QC, and the file's own `units`/`long_name`.
  Fill reads as `None`; values are never rounded (BGC spans 1e-7..1e2);
  a missing `<PARAM>_QC` variable reads as `"0"` (not assessed — the true
  statement, since no QC was published). Nothing is hardcoded: no parameter
  names, units, or scales. `read_br_file()` also returns the file header
  (cycle, lat/lon, JULD, POSITION_QC) so BR-only cycles get real records.
- **G2-signature flag** (`matches_g2_signature`) is purely observational: the
  file has a non-standard layout (`N_PROF != 4`) AND a profile whose labeled
  sensor channels are entirely fill. Verifiable by inspection; the causal
  explanation (frozen-backend writer template masking) lives in the audit
  report, not in the data.
- **`models.py`** — `CycleRecord` gains `bgc_profiles: list[BgcProfile]`,
  `bgc_source_file`, `bgc_n_prof`, `matches_g2_signature`, `has_core`
  (all defaulted — legacy/APEX/ARVOR records are untouched and old run JSONs
  still validate).
- **`cts4_runner.py`** — `extract_cts4_artifacts()` attaches the matching BR
  to every R cycle; cycles with a BR but no R become BGC-only records
  (`has_core=False`, `levels_count=0`, real position/time) instead of 404s;
  cycles are sorted by cycle number. The verification event reports R/BR/BGC-
  only counts honestly. Shared `_qc_char` now lives in `bgc_reader.py`
  (single definition, imported by the runner).

Legacy parity: APEX/ARVOR paths never call the reader; their cycles carry
empty BGC fields by default (verified: 1902844 → 23/23/0 unchanged).

## Frontend (`decoder-ui/frontend/src/`)

- **`types/index.ts`** — `BgcProfile` interface; new `CycleRecord` fields are
  optional so pre-BGC run records still load.
- **`ScientificProfileChart.tsx`** — additive generic-parameter mode via the
  optional `genericParam` prop (file-true label, units, adaptive decimals for
  1e-7..1e2 spans, generic hover readout, restrained per-parameter palette).
  The TEMP/PSAL CTD path is byte-for-byte unchanged in behavior.
- **`ResultsWorkspace.tsx`** — a BGC section under the CTD charts, shown only
  when the selected cycle has BR data: one card per sensor parameter that
  actually carries measurements (core PRES/TEMP/PSAL excluded by rule);
  all-fill channels are reported as missing and NEVER plotted. G2-matching
  cycles get an amber "sensor data absent" notice; BR-only cycles get a badge
  in the section header and a `BGC` tag on their cycle button. A "BGC
  measurement records" block tabulates every data-bearing profile level by
  level (file-order columns, file units, span-adaptive decimals shared with
  the charts, hover-linked to the cards).
- **`RtqcModal.tsx`** — new `PASS BGC` reference tab documenting the
  pipeline-active BGC tests 57 (DOXY drift), 62 (BBP five sub-tests) and 63
  (CHLA caveat) with their real rules and `rtqc/cts4.py` source pointers.
  Reference only: per-test execution evidence is not published in 301
  files (the writer keeps level flags, discards test numbers), so no
  per-run BGC test status is shown anywhere.
- **`CycleDetailModal.tsx`** — BGC provenance strip (BR filename, N_PROF,
  profile count, G2/BGC-only badges); the empty-CTD message distinguishes
  BGC-only cycles from engineering-telemetry-only ones.

## Data

`decoder-ui/data/cts4/ref/gdac_incois_301/` now holds 15 GDAC meta.nc files
(13 staged earlier + live-fetched `incois_2902130/2902131_meta.nc`), so all
10 staged SBD groups decode (previously 8/10).

## Reports (PDF + email)

`report_data.py` carries a `FloatBgcReport` per float (BR files, cycles with
BGC, series points, N_PROF values, sensor params, BGC-only and flagged
cycles) read from the run's own cycle records — the same evidence the
Results page renders. It feeds the per-float narrative, the assessment's
"BGC findings", the PDF per-float BGC line (`pdf_report.py`), and the email
"BGC Summary" section (`email_notifier.py`, plain + HTML). Legacy floats
(`has_bgc=False`) render exactly as before.

## Out of scope (explicitly not done)

- No `src/argo_decoder/` changes (G2/G3 backend fixes need approval).
- No per-run BGC test status (per-test evidence is not published in 301
  files — reference catalogue only; see `RtqcModal` note above).
- No concurrency guard (changes legacy timing; needs approval).
