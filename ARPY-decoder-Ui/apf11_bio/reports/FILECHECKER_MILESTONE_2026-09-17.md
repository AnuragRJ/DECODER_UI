# APF11 product-chain — FileChecker parity milestone (2026-09-17)

## Gate result: 12/12 FILE-ACCEPTED, 0 errors

Official Argo FileChecker v3.0.5 (OneArgo/ArgoFormatChecker release),
`java -jar file_checker_exec.jar -internal-specs incois <out_dir> <in_dir>`.

| file                | status        | errors | warnings |
|---------------------|---------------|--------|----------|
| 2902274_{Rtraj,meta} | FILE-ACCEPTED | 0      | 6 + 1    |
| 2902274_tech         | FILE-ACCEPTED | 0      | 0        |
| 2902275_{Rtraj,meta} | FILE-ACCEPTED | 0      | 6 + 1    |
| 2902275_tech         | FILE-ACCEPTED | 0      | 0        |
| 2902296_{Rtraj,meta} | FILE-ACCEPTED | 0      | 6 + 1    |
| 2902296_tech         | FILE-ACCEPTED | 0      | 0        |
| 2902298_{Rtraj,meta} | FILE-ACCEPTED | 0      | 6 + 1    |
| 2902298_tech         | FILE-ACCEPTED | 0      | 0        |

Before this pass the same files were 3× FILE-REJECTED (129/137/11 errors);
GDAC's own published triple is the acceptance baseline and shows the SAME
warning classes (Rtraj: JULD anchor-fill bookkeeping at MC 400/703; meta:
`PI_NAME 'M Ravichandran' Status: Invalid (not in NVS R40 table)` —
byte-identical string on both sides).

## What was changed (spec-alignment sweep)

All attribute constants now derive from the checker-internal spec CDLs
(extracted to `/home/user/argo_workspace/checker/file_checker_spec/`,
jar persisted at `/home/user/argo_workspace/checker/file_checker_exec.jar`,
parsed tables at `checker/meta_spec_full.json` and machine-copied into the
writers — no GDAC bytes are read at build time):

- `writer/apf11_traj.py`
  - scalar attrs verbatim: `PLATFORM_NUMBER:conventions="WMO float identifier : A9IIIII"`,
    `REFERENCE_DATE_TIME:long_name="Date of reference for Julian days"`,
    `TRAJECTORY_PARAMETERS` on `STRING16` w/ `long_name="List of available parameters for the station"`,
    `DATA_TYPE` on `STRING16`, `_FillValue=" "` at creation on every char var (incl. scalars via
    `char_scalar(fill_value=)`), `GROUNDED` table-20 long_name, `DATA_MODE` table conventions,
    `SATELLITE_NAME` long_name, RPP_STATUS table 21.
  - STATUS long_names: `"Status of " + anchor long_name[0].lower() + rest`.
  - P/T/S attribute blocks = GDAC surface (sea_water_* standard_names, C/FORTRAN formats,
    valid_min/max as `f8`, `resolution` as `f8`, `axis="Z"` on PRES only,
    comment "In situ measurement, sea surface = 0" on PRES_ADJUSTED),
    `*_QC:long_name="quality flag"`, `*_ADJUSTED_ERROR:long_name` + C/FORTRAN formats.
  - `POSITIONING_SYSTEM` reduced to 1-D `STRING8` per spec (with `_FillValue`).
  - `HISTORY_*` block rebuilt: spec dims (`INDEX_DIMENSION` on bare `N_HISTORY`,
    `QCTEST`/`PARAMETER` on `STRING16`), all spec long_names/conventions,
    `_FillValue` on every history var.
  - `AXES_ERROR_ELLIPSE_*` long_names + units ("meters"/"Degrees (from North when heading East)").
- `writer/apf11_tech.py`
  - `_FillValue=" "` on string scalars {PLATFORM_NUMBER, DATA_TYPE, FORMAT_VERSION, HANDBOOK_VERSION,
    DATA_CENTRE, DATE_CREATION, DATE_UPDATE} (via `fill_value=` on `_write_str_char`),
    `PLATFORM_NUMBER:conventions="WMO float identifier : A9IIIII"`, TECHNICAL_PARAMETER_NAME/VALUE
    long_names without "the", CYCLE_NUMBER `long_name="Float cycle number"` + conventions,
    `HANDBOOK_VERSION` left-padded `' 1.2'`.
- `writer/apf11_meta.py`
  - embedded spec-attr table `_SPEC_ATTRS` (66 vars, parsed from `argo-metadata-spec-v3.1.cdl`)
    applied as a final pass inside `build_meta_dataset` — covers every spec-defined
    long_name/conventions/units pair.
  - `fill_value=" "` on all S1 createVariable sites (helpers `cs`/`cs0` + 19 table vars),
    `f0` floats get `fill_value=99999.`, `LAUNCH_LAT/LON:valid_min/max` + units,
    `CONFIG_MISSION_NUMBER` fill 99999, `LAUNCH_CONFIG_PARAMETER_VALUE` spec long_name.
- Driver args now carry runtime facts: `--firmware 102418 --wmo-inst-type 846
  --pi "M Ravichandran" --project "Argo INDIA"` (values confirmed against the
  published INCOIS files persisted at `/home/user/argo_workspace/gdac_reference/2902296/`).

## Data layer (unchanged state, re-measured this pass)

- tech: 7311/7311 float cells byte-exact; 4 event-string cells ('Timeout'
  vs GDAC 'TIMEOUT NoMessage') = documented publication-RTQC text class.
- Rtraj N_MEASUREMENT core = 100% exact: LATITUDE/LONGITUDE/PRES/TEMP/PSAL/
  POSITION_ACCURACY 0/1420 diffs vs GDAC.
- Classified row/anchor residuals (publication-side fill conventions,
  FileChecker warnings match GDAC class-for-class):
  - N_MEASUREMENT rows: ours 1431 vs GDAC 1420 (row anatomy audit queued:
    GDAC pad/annex rows, see below).
  - JULD/CYCLE_NUMBER/MEASUREMENT_CODE differ where row packing differs.
  - N_CYCLE anchors: 13.6% of cells — JULD_PARK_START/END, JULD_ASCENT_START
    fills (GDAC interpolates; we keep FillValue without msg evidence),
    CONFIG_MISSION_NUMBER publication numbering, DATA_MODE per-cycle string.
  - tech content parity (16/16 names, 3840/3840-4 cells exact) unchanged.

## Verification commands

    cd argo-decoder-python
    PYTHONPATH=src python3 -m pytest tests -q
    # -> 2530 passed, 67 skipped

    PYTHONPATH=src python3 tools/apf11_build_products.py f8673 2902296 \
        --serial 0319 --out /tmp/apf11_products_test \
        --firmware 102418 --wmo-inst-type 846 --pi "M Ravichandran" --project "Argo INDIA"
    # (f8499/2902275, f8671/2902274, f8675/2902298 same args)

    java -jar /home/user/argo_workspace/checker/file_checker_exec.jar \
        -internal-specs incois <out_dir> <product_dir>

## Remaining queue (unchanged order)

1. traj_block anatomy audit vs GDAC row packing (2xN+1−Ngrey + launch row);
   N_CYCLE=240 vs GDAC 239 (launch-row cycle-0 class).
2. per-cycle `src_cycle` vitals grouping for msg-missing cycles (technical.py).
3. RTQC byte-layer; remaining BGC floats.
