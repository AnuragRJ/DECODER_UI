# PROVOR CTS4 Phase-4 — Float-level real-time products: IMPLEMENTED + VALIDATED (2026-09-11)

**Milestone reached:** R/BR + meta + accumulating tech + accumulating Rtraj
implemented correctly, validated structurally (FileChecker v3.0.5: 34/34
FILE-ACCEPTED) and scientifically (GDAC event-time/value parity).
**Not declared publication-ready** — see §7.

## 1. Delivered

**New modules** (`src/argo_decoder/platforms/provor_cts4_ir_sbd/`):
* `mission_clock.py` — telemetry-derived mission epoch (median-of-differences,
  midnight rounding with guards, `AnchorInconsistentError`); adjudicated
  event conversions (253 fields → absolute JULD; 252 phase anchoring).
* `rtraj_build.py` — adjudicated MC row builder (see
  `PROVOR_CTS4_RTRAJ_ADJUDICATION_2026-09-11.md`) + N_CYCLE summaries.
* `tech_build.py` — 95-row/cycle tech builder, GDAC row order, values only
  from 253/250/CTD telemetry; unknowns → explicit `'none'`.
* `external_meta_io.py` — ExternalMeta extraction from authoritative GDAC
  meta.nc (clean replacement for the quarantined draft's helpers).
* `cts4_realtime.py` — **production pipeline** `process_float()`:
  attribution → decode → gsw-DOXY/CHLA/BBP → mono-cycle R/BR + single meta +
  accumulating tech + accumulating Rtraj in the float layout
  `<WMO>/{meta,tech,Rtraj}.nc + profiles/R|BR<WMO>_<ccc>.nc`.
* `nc/rtraj_cts4.py` — **rewritten** to the adjudicated 3.2 spec (supersedes
  the provisional (be) builder; old behavior not reused).
* Scripts: `run_cts4_realtime.py` (CLI), `validate_cts4_phase4_gdac.py`
  (durable GDAC-parity validator; auto-fetches the tech reference),
  `refetch_gdac_references.sh` (budget-removed references).

**Writer fixes (`writer/nc.py`, spec-driven via FileChecker -internal-specs
CDLs):** canonical attribute strings (dates `YYYYMMDDHHMISS`, A9IIIII,
Table-6/9/15/19/23 conventions, PREDEPLOYMENT/SCIENTIFIC_CALIB long_names,
*_ADJUSTED mirroring); profile dims restricted to v3.1 set (no
STRING128/4096); B-file DATA_TYPE STRING32; B-files carry NO PRES_QC/
PRES_ADJUSTED* (UM §2.6); QC arrays blanked exactly where data is fill;
DATA_STATE_INDICATOR 2B; TRANS_SYSTEM_ID from ExternalMeta PTT.

**Defects found & removed (evidence-classified):**
1. `decode_253` FloatTime yy↔dd mislabel (source of the 25977/year-2021
   artifact in (ba)–(bc)) — FIXED + regression test. **FIXABLE→FIXED.**
2. Writer copied originals into `*_ADJUSTED` + hard-coded DOXY gain 1.167
   (delayed-mode SAGEO2 artifact) — REMOVED; real-time ADJUSTED = pure fill.
   **Forbidden hidden computation — removed.**
3. Quarantined draft's `DOXY=200.0` bare-except fallback — not carried into
   production (module kept on disk, zero importers, documented).

## 2. 12170 full-float run (real telemetry, 63 files)

* Mission anchor 23008.0 (16 estimates, spread 66 s, midnight-rounded).
* Layout: 1 meta + 1 tech (1,615 rows = 17×95) + 1 Rtraj (944 measurements,
  18 N_CYCLE) + 15 R (98–113 minus 102) + 16 BR (98–113).
* Partial cycles honest: 102 → BR without DOXY/BBP (no CTD → QC-9 fill, no
  fabricated salinity); 114 tech-only → no profiles. Skips classified
  DATA-COVERAGE.
* Science: gsw TEOS-10 per-record potential density (ρ 1.0209–1.0277;
  DOXY deep-median 39.2 / surface 182.4 µmol/kg — BoB OMZ-consistent);
  BBP full β_sw recompute (exemplar 0.000251 exact vs GDAC-derived);
  CHLA counts path (surface median 0.060).

## 3. Validation results

| Gate | Result |
|---|---|
| Full pytest | **2,295 passed / 1 pre-existing skip / 0 failed** |
| CTS4 subset (incl. 14 new unit + 7 new integration) | 179 passed |
| mypy --strict (4 new modules) | 0 errors |
| ruff (5 new modules) | clean (writer/nc.py + rtraj_cts4.py carry documented pre-existing style debt) |
| `validate_cts4_phase4_gdac.py` | **ALL PASS** (event JULDs ±0.00 min; series counts + 0.000 min; pressures exact; tech 92/95 exact + 3 known-UNKNOWN; R/BR structure) |
| **FileChecker v3.0.5 `-internal-specs`** | **34/34 FILE-ACCEPTED** (15 R + 16 BR + meta + tech + Rtraj), 0 rejected |
| Invariants | no D/BD; frozen 4 CSVs byte-schema-identical; WMO external (6-digit/IMEI rejected); 517-file corpus intact |

Known-UNKNOWN tech rows (honest `'none'`/raw fills, GDAC diff documented):
`FLAG_RTCStatus_LOGICAL` (raw 0 vs GDAC 1 — semantics UNKNOWN per (ak)),
`FLAG_SensorBoardStatus_NUMBER` (`'none'`; GDAC '0' constant is not a
function of sensor statuses — derivation UNKNOWN),
`PRES_LastAscentPumpedRawSample_dbar` (4-dec source UNKNOWN),
`PRES_SurfaceOffsetBeforeReset...` (offset_p mapping matched on c98 — kept,
provenance noted).

## 4. Workspace budget (user instruction)

Workspace trimmed 156.4 → **132.2 MB** (< 128 MiB snapshot cap) removing ONLY
regenerable/redundant items, each documented + scripted for refetch
(`scripts/refetch_gdac_references.sh`):
`phase5_reference/` (16.3 MB, GDAC 2901339 golden set — unused by pytest,
refetchable), `incois_2902086_tech.nc` (6 MB — validate script auto-fetches),
`incois_2902091_Rtraj.nc` (4.8 MB — unused, refetchable), 5 byte-duplicate
uploads txt (0.3 MB), regenerable decoded product bundles from
final_audit/final_parity/parity_6990711 (4.5 MB — the .md/.filecheck verdict
records all retained). Also restored the 127 `phase4_reference` APEX burst
files that the >cap snapshot had silently dropped (base-zip sha re-verified).
**KEPT:** `uploads/arvor_i_fleet_expansion_bundle.7z` (contains 31 APEX
manual PDFs absent elsewhere), all raw telemetry, all NKE/Argo/cookbook
references, all 2902086/91 meta + 2902086 Rtraj evidence, APEX/ARVOR trees.

## 5. Architecture (as built)

```
raw SBD (517 corpus)
  → attribution (packet-header cycles)            cycles.py
  → framing/dispatch (140 B; type-0 subtypes 0/3/6; 250/252/253/254/255)
  → decode + padding filters + nearest_ctd        ctd/bgc/assoc/tech/params
  → mission clock (telemetry-derived anchor)      mission_clock.py
  → calibration resolve (family/telemetry/CSV)    resolve.py + family_constants.py
  → science: CHLA, BBP (full β_sw), DOXY (gsw TEOS-10 ρ)   equations.py + derived/density.py
  → R/BR mono-cycle (4-profile PROVOR structure)  writer/nc.py (R/BR only)
  → tech rows (95/cycle, accumulating rebuild)    tech_build.py + write_tech
  → Rtraj rows (adjudicated MC set, accumulating) rtraj_build.py + nc/rtraj_cts4.py
  → meta (single, ExternalMeta-driven)            write_meta
  → FileChecker v3.0.5 + GDAC parity validator
```

## 6. What was NOT done (explicit)

* No WMO allocation/routing (2902086 is a comparison-only hypothesis supplied
  externally; decoder never branches on it).
* No D/BD anywhere; no GDAC value copied into logic; no residual fitting.
* MC 290/590 dated series deferred (design step, DATA-COVERAGE/UNKNOWN rules).
* No other float family touched; ARVOR-I/APEX frozen (suite-wide regression
  proof: full suite green).

## 7. Publication posture

**Structurally FileChecker-clean and GDAC-corroborated on one float group,
but NOT declared publication-ready**: (a) external R/BR GDAC parity for the
301 fleet remains UNAVAILABLE (exhaustive search, (bd)); (b) MC 290/590
deferral; (c) 3 known-UNKNOWN tech rows; (d) single-group validation — a
second group (e.g. 06580→2902114) should pass through before any DAC
ingestion trial. Next bounded steps, in order: second-group validation →
MC 590 dating design → (optional) FileChecker batch over a full fleet.
