# Phase 6A — `_Rtraj.nc` implementation plan

Date: 2026-07-27

Stage 1/2 findings and the resulting design, recorded before major
coding began.

## Stage 1 — Reverse engineering the GDAC references

Six references studied (2901339, 2902201, 2902203, 2902206, 2902222,
2902223). They are structurally identical, which makes the format a
stable target rather than a per-float guess.

### Filename

`<wmo>_Rtraj.nc` — the `R` prefix marks real time, consistent with the
`R*.nc` mono profiles. `DATA_TYPE` is `Argo trajectory`.

### Dimensions

| Dimension | Value | Notes |
| --- | --- | --- |
| `N_MEASUREMENT` | 5554-10809 | **unlimited**; one row per event |
| `N_CYCLE` | 216-361 | one row per cycle |
| `N_PARAM` | 3 | PRES/TEMP/PSAL |
| `N_HISTORY` | 1 | |
| `STRING2/4/8/16/32/64`, `DATE_TIME` | fixed | as in the profile files |

102 variables: 17 file-level scalars, 31 on `N_MEASUREMENT`, 40 on
`N_CYCLE`, 14 `HISTORY_*`.

### The `MEASUREMENT_CODE` template (Argo reference table 15)

All six floats emit exactly the same code set. Per cycle, in this order:

| MC | Meaning | Populated in references | Our source |
| ---: | --- | --- | --- |
| 0 | Launch position | 1 row, `CYCLE_NUMBER=-1`, JULD+lat/lon | **registry metadata** |
| 100 | Descent start | JULD_STATUS='9', no value | placeholder |
| 250 | Drift at park | '9' | placeholder |
| 290 | Ascent start | JULD + PRES/TEMP/PSAL | engineering msg |
| 296 | Deep-park descent | JULD + PRES/TEMP | engineering msg |
| 300 | Descent-to-profile start | '9' | placeholder |
| 400 | Profile descent end | '9' | placeholder |
| 500 | Ascent start | '9' | placeholder |
| 600 | Ascent end | JULD (status 3/9) | engineering msg |
| 700 | Transmission start | JULD (status 3/9) | engineering msg |
| 702 | First message | JULD, status '4' | **transmission times** |
| 703 | Surface fix | JULD + lat/lon + accuracy, status '4' | **ARGOS fixes** |
| 704 | Last message | JULD, status '4' | **transmission times** |
| 800 | Transmission end | '9' | placeholder |
| 903 | Grounding / last pump | mostly empty; PRES on 5/339 | engineering msg |

`MC=703` is the trajectory backbone: 6401 of 10809 rows for 2902222.

### Verified against our own data

Comparing our `parse_argos_fixes()` output for raw cycle 327 against the
reference `MC=703` block for cycle 327: **all 7 of our fixes appear in
the reference with bit-identical JULD/LATITUDE/LONGITUDE**, and
`POSITION_ACCURACY` equals the CLS location class we already parse. The
reference carries 11 fixes; the 4 extra come from ARGOS passes present
in the DAC's feed but absent from our archived raw file (our file
contains exactly 7 unique pass headers).

`JULD_LAST_MESSAGE` for cycle 327 equals our last transmission time
exactly.

### N_CYCLE timing variables

Only a minority are populated, and they split cleanly:

* **Derivable from what we already decode** — `JULD_FIRST_MESSAGE`
  (= MC702), `JULD_LAST_MESSAGE` (= MC704), `JULD_FIRST_LOCATION`
  (= first MC703), `JULD_LAST_LOCATION` (= last MC703),
  `CYCLE_NUMBER_INDEX`, `CONFIG_MISSION_NUMBER`, `DATA_MODE`.
* **Requires the APEX engineering message** — `JULD_ASCENT_END`,
  `JULD_DESCENT_START`, `JULD_PARK_START`, `JULD_PARK_END`,
  `JULD_TRANSMISSION_START/END`, `GROUNDED`, `CLOCK_OFFSET`.
* **Empty in the references too** — `JULD_ASCENT_START`,
  `JULD_DESCENT_END`, `JULD_FIRST_STABILIZATION`, `JULD_DEEP_*`,
  `REPRESENTATIVE_PARK_PRESSURE`. These are correctly all-fill.

This is the same engineering-message boundary identified in Phase 5B.

## Stage 2 — What the decoder already has

Reusable today:

* `parse_argos_fixes()` → `ArgosFix(at, lat, lon, location_class,
  satellite)` — exactly the MC=703 payload including accuracy.
* `iter_argos_messages_from_payload()` → per-message `received_at`,
  giving MC=702/704 and the transmission window.
* `datetime_to_juld()`, `position_qc_for_location_class()`.
* `FloatMeta` / registry: launch date, launch lat/lon (MC=0), platform
  number, DAC, project, PI, serial, firmware, WMO inst type.
* `mono_profile.py` helpers: `_encode_padded`, `_scalar_char`,
  `institution_for_data_centre`, `_INTERNAL_ATTRS`, the ADMT parameter
  attribute table, the `_history_*` builders and the netCDF4 writer
  pattern that avoids xarray's spurious `string1` dimension.

Not available: any engineering-message field (the APEX technical message
is not decoded and the MATLAB decoders for it are absent from the
supplied container).

The existing `trajectory/binning.py` is PROVOR-oriented and its
`MeasurementCodes` constants disagree with reference table 15 for ARGOS
(e.g. it maps 703 to "emergency ascent" whereas the ARGOS references use
703 for surface fixes). It is left untouched to avoid regressing the
PROVOR path; Phase 6A introduces a separate, reference-table-15 code set.

## Stage 3 — Architecture

Shared-first, because `_meta.nc` and `_tech.nc` are next:

```
nc/
  admt.py          NEW  shared ADMT primitives (char encoding, fixed
                        dimensions, param attributes, DAC->institution,
                        internal-attr filter, standard globals, a
                        generic netCDF4 writer)
  trajectory.py    NEW  measurement/cycle record models, the reference
                        table 15 code set, and the Rtraj builder
  mono_profile.py  re-exports its helpers from admt.py (no behaviour
                        change; existing imports keep working)
  writer.py        writes <wmo>_Rtraj.nc when a traj dataset exists
platforms/apex_argos/
  trajectory.py    NEW  builds the records from decoder output
```

`nc/admt.py` is the reusable layer `_meta.nc`/`_tech.nc` will build on.
`_prof.nc` behaviour must be preserved exactly — verified by the
existing 381 tests plus the ADMT audit.

## Stage 4-6 outline

1. Extract shared primitives into `nc/admt.py`, re-export from
   `mono_profile.py`, confirm 381 tests still pass.
2. Add `nc/trajectory.py` with `TrajMeasurement` / `TrajCycle` records
   and `build_trajectory_dataset()` / `write_trajectory()`.
3. Add `platforms/apex_argos/trajectory.py` to assemble records from
   fixes + transmissions + metadata; wire into the decoder and writer.
4. Compare against all six references with a dedicated comparator;
   iterate difference -> investigate -> fix -> recompare.
5. Regression tests for dimensions, ordering, attributes, fills, QC,
   HISTORY and event generation.

## Honesty constraints

Carried over from Phase 5B:

* placeholder-only MCs (100/250/300/400/500/800) are emitted with
  `JULD_STATUS='9'` and no value, exactly as the references do — this is
  the ADMT way of saying "event expected, time unknown", not fabrication;
* engineering-derived MCs (290/296/600/700/903) are emitted as
  structural rows with fill values, never invented times;
* `GROUNDED` is `_FillValue` rather than guessed `N`;
* no reference value is ever hardcoded.
