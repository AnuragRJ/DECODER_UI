# PROVOR CTS4 Phase-2B-2 ARCHITECTURAL CLEANUP — 4-layer generic decoder (no 13-WMO whitelist)

**Date:** 2026-09-10 (Asia/Calcutta)
**Status:** ARCHITECTURAL CLEANUP — refactor (no new science value, no NetCDF/R-BD, no publication fit)
**Rule:** No GitHub workflow, no schema change to `config/metadata/{meta,sensor-info,calib,config_params}.csv`, no WMO branches, no ARVOR/APEX edit, no NetCDF/R-BD emission, no silent UNKNOWN resolution, `IMPLEMENTATION_PROGRESS.md` append-only. New dedicated CTS4 CSV allowed.
**References re-checked (research before refactor):** NKE `5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf` §5.3.6 / §7.2.4.9, BGC cookbooks via `argodatamgt.org/Documentation` (`39459 BBP v1.4 §2.2`, `39468 CHLA`, `39795 O2`, `54541/51541` provenance), SEANOE `10.17882/54520` (`55891.csv` Barnard), Coriolis `Coriolis-data-processing-chain-for-Argo-floats-container` (`decArgo_20260202_082q`, `compute_profile_derived_parameters_ir_rudics.m` + `betasw_ZHH2009.m` + `generate_json_float_meta_prv_cts4_ir_sbd*.m`), `archimer.ifremer.fr` (PROVOR-CTS4 remOcean/NAOS docs), NKE 5.8 Wayback source, INCOIS `gdac_incois_301/*.nc` `PREDEPLOYMENT_CALIB_*` + `PREDEPLOYMENT_CALIB_COMMENT` (Reprocessed … Bernard), LFS bundle `1C4Cl_AUH17_KMXS_5Cyk-VtKnSC7ey1f` (re-checked 15.1 MB APEX-only), Argo User Manual / DAC cookbook hierarchy.

---

## 0. Problem — ReferenceDB was a hidden whitelist for 88 family-generics

Phase-2B-1 resolver `resolve.py` obtained every coefficient through the dedicated reference CSV `config/metadata/provor_cts4_301_reference.csv` (13 WMO, 1534 rows). The file correctly carried `source_file` provenance per row, but the code used it as **source** for constants that are numerically identical across the 13 INCOIS meta.nc (88 values, max |Delta| < 1e-12, audit `test_reference_csv_scope_labels`):

* `SCALE_CHLA = 0.0073` (cookbook `39468`), `khi = 1.097` (cookbook `39459` Table 1, FLBB 142 deg), `Spreset = 0`, `PhaseCoef2/3 = 0`, `T4/T5 = 0`, `c21-27 = 0`, all 56 `m/n` exponents, and the 22 DOXY solubility constants (`A0-5/B0-3/C0/D0-3/Pcoef1-3`). These are **decoder-family** constants, not per-float metadata.

A hypothetical new INCOIS 301 float that ships with valid `250 FLBB` telemetry and its own `PREDEPLOYMENT_CALIB_COEFFICIENT` lines would therefore have been blocked for *even* `CHLA`/`BBP` (telemetry-only) by the absence of a pre-existing WMO row — an implicit whitelist. DOXY was already correctly gated as `DATA-COVERAGE` via `FLBB serial -> WMO -> CSV`, but the mechanism offered no way to present the coefficients without growing the 13-row file (or forging a WMO). BBP distinction `OriginalScaleFactor` (telemetry) vs `CorrectedScaleFactor` (GDAC publication via Barnard `54520` reprocessing `+1.216-1.264%`) was correctly kept as telemetry truth but relied on the same CSV for `khi`.

---

## 1. Desired 4-layer architecture (implemented)

| Layer | Source | What | Needs external metadata? | Needs pre-existing WMO in 13-row file? |
|---|---|---|---|---|
| 1 | `src/argo_decoder/platforms/provor_cts4_ir_sbd/family_constants.py` (new, authoritative) | 88 family-generic constants (`FAMILY_GENERIC`, `SCALE_CHLA`, `KHI_700`, solubility `A0-5/B0-3/C0/D0-3/Spreset/Pcoef1-3`, `m/n`, `T4/5`, `c21-27`). Values verified against every INCOIS `meta.nc` (provenance: NKE 5.8, cookbooks 39468/39459/39795, Coriolis `betasw_ZHH2009.m` dep 0.039, `compute_profile_BBP` chi table). | No | No |
| 2 | Telemetry 250 free zone (NKE 5.8 §7.2.4.9, LE float32) | `FlbbCal`: `serial`, `DARK_CHLA`/`DARK_BB` (int counts), `SCALE_CHLA` / `SCALE_BB` (`OriginalScaleFactor` under Planck/Barnard semantics), `scale_chl_2`.  `CHLA = (FLUO-DARK)*SCALE_CHLA`, `BBP = 2*pi*khi*((BETA-DARK)*SCALE-BETASW700)`. `BBP khi` is layer 1. | No — telemetry self-contained. | No |
| 3 | External per-float metadata via dedicated CTS4 mechanism | DOXY Stern-Volmer float-specific coefficients that telemetry never carries (`NKE Optode Data Free 50`): `PhaseCoef0/1`, `Foil c0-20` (21 values), `TEMP_DOXY T0-3` (4 values). Legacy path: `FLBB serial -> WMO -> dedicated CSV row` (`doxy_cal_for_group`). New generic path: explicit dict / new dedicated CSV keyed by `flbb_serial` (`doxy_cal_from_external` / `doxy_cal_from_external_dict`, or example file `config/metadata/provor_cts4_external_doxy_example.csv`). BBP *Corrected* scale (if GDAC publication parity is desired) would follow the same layer via Barnard `54520` table but is **not auto-applied** — decoder keeps telemetry Original truth; synthesis is an explicit caller decision. | Yes for DOXY (and optionally for BBP-corrected) — but the key is `flbb_serial`, not WMO. | **No** — a new float supplies its own coefficients without any row for its WMO/serial in the 13-row file. The 13-row file is reduced to bootstrap/provenance. |
| 4 | GDAC reference CSV `provor_cts4_301_reference.csv` | Bootstrap / provenance / cross-check. When a reference is supplied, `load_reference` verifies the 88 family generics against `family_constants` within 1e-12 and raises on divergence (so a future FLBB geometry with different `chi` is versioned with a decoder-family guard, not a WMO branch). `source_file=incois_<WMO>_meta.nc` per row remains for audit. | Verifies layer 1, supplies layer 3 for legacy floats. | Legacy floats only — new floats do not need a row. |

The four legacy schemas (`meta.csv`, `sensor-info.csv`, `calib.csv`, `config_params.csv`) remain **untouched** (hard rule). The new dedicated example CSV `provor_cts4_external_doxy_example.csv` (2 synthetic rows for FLBB 99999/88888, schema `flbb_serial,PhaseCoef0/1,c0..c20,TEMP_T0..T3,provenance`) carries `synthetic:` provenance and is *not* one of the legacy schemas; it documents the mechanism without touching the frozen contracts. Real deployments would extend that mechanism with the new float's `meta.nc` row (or equivalently a new dedicated `provor_cts4_301_reference.csv` row keyed by the new `flbb_serial`).

---

## 2. Implementation

### 2.1 `family_constants.py` (new, pure data, no IO)

* 88 entries in `FAMILY_GENERIC` with per-constant provenance in the module docstring: NKE 5.8 §7.2.4.9 `PC 4 1 7..11` & 50 B free-zone layout, cookbook 39459 §2.2 `chi=1.097` for 142 deg + Zhang 2009 `BETASW700` (`betasw_ZHH2009.m` dep 0.039), cookbook 39468 `SCALE_CHLA=0.0073`, cookbook 39795 §4.2.2 `PhaseCoef2/3=0 c21-27=0 T4/5=0 Pcoef1=0.1`, Aanderaa 4330 standard-foil `A0-5/B0-3/C0/D0-3/Spreset` and 28 `m/n` exponents, `M/N/C21_27_ZERO/TEMP_DOXY_T4/5` typed tuples. Values are literally identical across 13 `incois_2902*_meta.nc` (`probe_cts4_phase2a_gdac.py` audit, now pinned by `test_family_constants_are_authoritative_and_match_csv`).
* `__all__` sorted, `ruff`/`mypy --strict` clean.

### 2.2 `resolve.py` (refactored, backward-compatible, no WMO literal)

* `from .family_constants import family_constants as _fc` is the authoritative source. `_FAMILY_GENERIC_COEFS` now aliases `FAMILY_GENERIC_KEYS` (kept under that name so the `family_generic` string guard in legacy tests still passes).
* `load_reference(path)` keeps its public shape (`ReferenceDB` with `by_wmo`, `flbb_serial_to_wmo`, `family_generic`) but `family_generic` is now **verified** via `_verify_reference_against_authoritative` (`|Delta| <= 1e-12`, or `ValueError` — a future geometry change must be a decoder-family version bump, not a per-WMO branch).
* `chla_cal_from_flbb(flbb, reference=None)` and `bbp_cal_from_flbb(flbb, reference=None)` now take an **optional** reference. The hot path is `reference=None`: `SCALE_CHLA` from `_fc.SCALE_CHLA`, `khi` from `_fc.KHI_700` (provenance `family_constants:... (family_generic authoritative; telemetry:250:…) [verified vs reference]` — keeps `"family_generic"` substring for the legacy guard `assert "family_generic" in chla.provenance`). When a reference is supplied it is verified (`<=1e-12`) and the values are still taken from `family_constants`. No endian/float32 path was changed; `DARK` remains telemetry integers (exact vs meta) and `CHLA` `scale_chl` float32 `0.00730000017211` matches double `0.0073` within the documented `1e-9` ledger (Phase-2B-1 §2).
* `DoxyCal` / `_solubility_from_family_constants()` now source the 22 solubility constants from `family_constants` (the legacy helper `_solubility_from_reference` delegates there after verification — kept for compat).
* **New external path:** `doxy_cal_from_external(flbb, float_specific, group?, wmo_hypothesis?)` and `doxy_cal_from_external_dict(flbb, external_by_serial, group?)`. `float_specific` is the `Mapping[(param,coef) -> float]` of the 26 required keys `_DOXY_EXTERNAL_REQUIRED` = `PhaseCoef0/1 + c0-20 + T0-3`; missing keys raise `KeyError` with `DATA-COVERAGE`-style guidance. Internally it sources the 62 family-generics (`PhaseCoef2/3` 0, `c21-27` 0, all `m/n`, all `A0-5/B0-3/C0/D0-3/Spreset/Pcoef1-3` via `_solubility_from_family_constants`) and builds `PhaseCoefs` + `FoilCoefs(c,m,n)` + `SolubilityConsts`. Provenance uses `external:… for flbb_serial …` + `family_constants:family_generic` for the generic solubles, so a synthetic float's provenance is distinguishable from a `reference:` legacy provenance. No WMO literal appears anywhere (guard re-passes for `12170`/`2663`/`2902086` and for `2902114/115/118`).
* `doxy_cal_for_group(group, flbb_serial, reference)` is now a **projection** through the external path: it builds the `float_specific` subset from the reference's `by_wmo[WMO]` (the 26 keys) and calls `doxy_cal_from_external` with that `WMO` as hypothesis, then rewrites provenance keys that came from `"external:"` to the historical `"reference:<WMO>:DOXY:… via flbb_serial …"` phrasing so existing `test_doxy_via_serial_lookup_generic_path` that asserts `flbb_serial 3046/…` text continues to pass verbatim. The legacy `DATA-COVERAGE` `KeyError` now also suggests the external path (`via doxy_cal_from_external / dedicated CTS4 CSV`).
* `consensus_flbb_for_group` and `resolve_group` keep their public shapes; `consensus_flbb_for_group` still accepts an optional `reference` for backward-compat (unused — calibration is telemetry-only); `resolve_group` loads the default reference when none is supplied, but would work for `CHLA/BBP` without it (tests call the cal helpers directly with `reference=None` to prove it).
* `__all__` gains `doxy_cal_from_external` + `doxy_cal_from_external_dict`, retains every legacy symbol, remains `ruff clean` and `mypy --strict` 0 errors (`unused-ignore` for the synthetic WMO hint removed). Import order is `I001`-clean.

### 2.3 New example CSV `config/metadata/provor_cts4_external_doxy_example.csv`

* Append-only, documented-header example (2 rows, FLBB 99999/88888) for the Layer-3 mechanism. Header carries `flbb_serial,PhaseCoef0,PhaseCoef1,c0..c20,TEMP_T0..T3,provenance` — deliberately not one of the 4 frozen schemas. Values are `synthetic:`-prefixed (perturbed from `2902086` by `+1e-4` on `PhaseCoef0`) and must not be treated as GDAC truth; they exist only to document and smoke the synthetic path. Real deployments would append a real row derived from the new float's `meta.nc` `PREDEPLOYMENT_CALIB_COEFFICIENT` lines (the 13-row file already carries `source_file=incois_<WMO>_meta.nc` per row for that growth).

---

## 3. Verification — new tests + legacy parity

### 3.1 New Phase-2B-2 tests `tests/test_provor_cts4_phase2b2_arch_cleanup.py` 14 green (integration)

* `test_family_constants_are_authoritative_and_match_csv` — 88 `FAMILY_GENERIC` entries == `reference.family_generic` within `1e-12`; `SCALE_CHLA 0.0073` / `KHI_700 1.097` pins.
* `test_family_generic_not_sourced_from_csv_hot_path` — `chla_cal_from_flbb(flbb, None)` + `bbp_cal_from_flbb(flbb, None)` succeed on a synthetic `FlbbCal(99998, 1.5e-06/50)` without any `ReferenceDB`; with a reference the values are **identical** (verified path, not sourced). Provenance contains both `"family_constants"` and `"family_generic"`.
* `test_four_legacy_groups_identical_with_and_without_reference[00530/06580/06640/12170]` — real `consensus_flbb_for_group` for the 4 `INCOIS` groups; `chla/bbp` without reference == with reference (scale/khi/dark) and `equations.chla_ug_l` + `bbp700_m1` + `beta_sw` remain physical (`chla> -1`, `0 < bbp < 0.01`, `beta_sw ~= 6e-05`).
* `test_four_legacy_groups_resolve_group_still_uses_family_constants[...]` — `resolve_group(…)` (legacy path) now surfaces `chla.scale==0.0073` from `family_constants` (`"family_constants"` in provenance) and `bbp.provenance_khi=="family_generic:BPP700:khi"`.
* `test_synthetic_new_float_via_external_dict_without_wmo_in_csv` — **core demonstration**: FLBB `99999` is absent from `provor_cts4_301_reference.csv` (`assert 99999 not in flbb_serial_to_wmo`). Layer 2: `chla/bbp` via telemetry+`family_constants` only (`chla dark 49, scale 0.0073`, `bbp dark 49, scale 1.665e-06, khi 1.097`; `chla_ug_l 58->0.0657`, `bbp700_m1 108->~0.00025`). Layer 3 legacy: `doxy_cal_for_group(99999, …)` raises `KeyError DATA-COVERAGE`. Layer 3 new: `doxy_cal_from_external(flbb, synth_float_specific)` where `synth_float_specific` is a dict perturbed from `2902086` (`PhaseCoef0 +1e-4`, `PhaseCoef1/c0-20/T0-3` verbatim, not real metadata) **succeeds** — `PhaseCoef0` matches perturbation, `foil c0` matches source, `sol A0==2.00856`, provenance `external:…` + `family_constants:family_generic`, `doxy_chain` with fallback `rho 1.025` gives `DOXY 0-500` and `0-200` airsat. Wrapper `doxy_cal_from_external_dict({99999: dict})` reproduces it; missing required key raises `KeyError missing keys`.
* `test_synthetic_new_float_preserves_bbp_original_vs_corrected_distinction` — synthetic `FlbbCal(88888, SCALE 1.60e-06)` keeps telemetry Original truth; a hypothetical `Corrected 1.58e-06` delta is `+1.26%` inside the documented systematic (`1.216-1.264%`, see `PROVOR_CTS4_PHASE2B1_FOLLOWUP_REPORT.md` §2), and **no Barnard correction is applied** — the decoder is truthful to telemetry.
* `test_resolve_py_has_no_hard_coded_wmo_and_mentions_new_architecture` — `resolve.py` contains zero literals `"2902086"/"2902114"/"2902115"/"2902118"/"2902091"` and does contain `"family_constants"`, `"doxy_cal_from_external"`, `"flbb_serial_to_wmo"`.
* `test_external_doxy_csv_example_exists_and_is_parseable` — `provor_cts4_external_doxy_example.csv` exists, its first non-comment header carries `flbb_serial, PhaseCoef0, c0, TEMP_T0`.

### 3.2 Legacy parity — 06580/06640/00530/12170 still identical

Re-run of every `provor_cts4` test:

* `test_provor_cts4_phase2b1_telemetry.py` 20/20, `test_provor_cts4_phase2b1_followup.py` 7/7, `test_provor_cts4_phase1_telemetry.py` 23/23, `test_provor_cts4_phase2a_telemetry.py` 16/16, `tests/unit/test_provor_cts4_phase2a_units.py` 27, `tests/unit/test_provor_cts4_phase1_units.py` 30 — all **green**.
* `-k provor_cts4` **150 passed, 0 failed** (was `135` at Phase-2B-1 follow-up; `+14` are the new architecture tests, `+1` is the existing `test_architecture` that now also checks `family_constants.py`).
* `-k provor` **201 passed 3 skipped** (was `186` +14 new; the 4 `test_provor_ir_sbd` demo-data failures are pre-existing data-coverage, not a family regression).
* Full suite `pytest -q` **1595 passed 78 skipped 64 failed 18 errors** (was `1580 passed` before this slice; `+15` CTS4 tests, 0 change in `64 failed` — the failing set is the unrelated full-suite baseline that passed Phase-2B-1 gates). `provor` family is the gate.
* `ruff check src/argo_decoder/platforms/provor_cts4_ir_sbd/family_constants.py src/argo_decoder/platforms/provor_cts4_ir_sbd/resolve.py` **All checks passed** (new docstrings wrapped to avoid `RUF002/E501`; split constants file and `m/n` tables pass `E501`). `ruff check tests/test_provor_cts4_phase2b2_arch_cleanup.py` All checks passed. `mypy --strict` on `resolve.py + family_constants.py` **Success: no issues found** (`family_constants` is pure floats; `resolve.py` `Mapping[tuple[str,str], float]` + `doxy_cal_from_external` `Mapping` + the retained `type: ignore[arg-type]` on `decode_250` dispatch are the only strict-required ignores, now verified clean).
* `config/metadata/provor_cts4_301_reference.csv` parity: `load_reference` still derives `by_wmo 13`, `flbb_serial_to_wmo 13`, `family_generic 88` and cross-validates the 88 against `family_constants` at construction (so the CSV cannot silently diverge). Every `REFERENCEDB` identity verified for `06580/06640/00530/12170`: `CHLA dark` exact `49/50/51/52`, `BBP dark` exact `49/50/51/52`, `CHLA scale` exact `0.0073`, `BBP tele scale` `1.404/1.459/1.621/1.665e-06` within `0.3%` of SEANOE `OriginalScaleFactor` (`1.40/1.46/1.62/1.67E-06`) and `+1.216-1.264%` above GDAC `CorrectedScaleFactor` (`1.387/1.441/1.601/1.645e-06`); `khi` `1.097` from `family_constants`; `DOXY PhaseCoef2/3` `0`, `c21-27` `0`, `m/n` `56` exponents, `Spreset 0`, `Pcoef1 0.1` — identical on all 13 (probe verified).

### 3.3 BBP `Original vs Corrected` — deliberately kept, not auto-applied

The systematic `tele(Original) - csv(Corrected) = +1.216-1.264%` (sigma 0.02%) from the SEANOE `55891.csv` Barnard reprocessing (`doi:10.17882/54520` — weighted-phase-function fix; GDAC `PREDEPLOYMENT_CALIB_COMMENT Reprocessed … Andrew Bernard … http://doi.org/10.17882/54520`) is re-proved via the legacy 8/8 corpus and the synthetic `88888` example. `BBP700 = 2*pi*chi*((BETA-DARK)*SCALE - BETASW700)` with `betasw_ZHH2009.m`/`ZHH2009` dep 0.039 gives `+1.4-3.1%` on `BBP700` pressure-dependent (layer-2 equations unchanged). The decoder **keeps telemetry truth** (the value in `250 FLBB` `ScaleFactor Scattering FLOAT LE`, which was never re-flashed via `!PC 4 1 10` post-ADMT18) and never applies the Barnard `Original -> Corrected` table as a hidden scaling fudge — identical to Phase-2B-1. A caller that wants GDAC publication parity can ingest the Barnard table as an explicit `--reprocessed` step; that is `EXPECTED` (publication-reprocessed) and documented in `cook_bbp.pdf v1.4 §2.2`, not a decoder bug.

---

## 4. Ledger updates (per scientific principle)

* `BBP SCALE +1.2%` stays `FIXABLE: telemetry(Original) vs publication(Corrected) — PUBLICATION-REPROCESSED via doi:10.17882/54520`.
* `03530:3043 / 03580:3044` stay `DATA-COVERAGE` under the 13-row dedicated CSV (they exist in Barnard `2902130/2902131 1.41->1.39 / 1.38->1.37` but not in the reference file — CSV growth would close them, frozen per prompt caveat).
* `DOXY +0.21 PUBLICATION-RTQC`, `PT26/27`, `FLAG_SensorBoardStatus`, `253 rtc`, `03530 cycle-9` remain `UNKNOWN` (no guesswork).
* `family_generic` (88) is now `AUTHORITATIVE` in `family_constants.py`; `provor_cts4_301_reference.csv` is `PROVENANCE/BOOTSTRAP` (not `FIXABLE`). `gsw` fallback `1.025` remains `TOOL-AVAILABILITY` (<=0.5 umol/kg noise).

No `FIXABLE` was silently resolved; no `UNKNOWN` was turned into a fact.

---

## 5. Evidence locations (reproducible)

* Telemetry: `provor_bio_irsbd/raw_telemetry/SBD-BGC-raw/{00530,03530,03580,06580,06640,12170,17960,20000,25980,29030}/*.sbd` (517 + 63 for `12170` counted).
* Byte: `provor_bio_irsbd/ref/NKE_5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf` §7.2.4.9 p58 + `.txt`, `SHA256SUMS`.
* Cookbooks: `argodatamgt.org/Documentation` (enumerated `39459 BBP`, `39468 CHLA`, `39795 O2`, `46121/54541/57195` etc.), `provor_bio_irsbd/ref/cook_bbp.pdf` (§2.2 `ADMT18` + `doi:10.17882/54520`), `archimer.ifremer.fr/doc/00283/39459/56146.pdf`.
* SEANOE table: `https://www.seanoe.org/data/00434/54520/data/55891.csv` (latin1, `;`, `GDAC;WMO;…;OriginalScaleFactor;CorrectedScaleFactor`) — grep `incois;2902086;2663 1.67->1.65`, `3043/3044 1.41->1.39 / 1.38->1.37`, etc.
* INCOIS GDAC: `provor_bio_irsbd/ref/gdac_incois_301/incois_29020*_meta.nc` (13) — `PREDEPLOYMENT_CALIB_COMMENT` provenance; `PREDEPLOYMENT_CALIB_COEFFICIENT` carries `SCALE/DARK/khi`.
* Coriolis: `Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_soft/soft/util/decode_meas_cts4/sub_decode_meas_cts4/compute_profile_derived_parameters_ir_rudics.m` + `betasw_ZHH2009.m`/`betasw124_ZHH2009.m`, `init_float_config_prv_ir_rudics_cts4.m`, `generate_json_float_meta_prv_cts4_ir_sbd*.m`, `decArgo_soft/util/decode_meas_cts4/*`, `_config/_tech_param_name_301.csv`.
* Code: `src/argo_decoder/platforms/provor_cts4_ir_sbd/{family_constants.py (NEW, 88), resolve.py (559L -> 679L, layer 1-4, two new DOXY entrypoints), framer.py/packets.py/cycles.py/ctd.py/params.py/tech.py/bgc.py/equations.py/assoc.py/labels_301.py}` (equations pure-math, no defaults; `MOLAR_VOLUME 44.614`, `N_FOIL_TERMS 28`, `betasw_ZHH2009` scalar transcription).
* Reference: `config/metadata/provor_cts4_301_reference.csv` (1534 rows, 13 WMO, `source_file=incois_<WMO>_meta.nc` per row, `by_wmo` / `flbb_serial_to_wmo` / `family_generic 88` verified vs `family_constants`) + NEW `config/metadata/provor_cts4_external_doxy_example.csv` (synthetic, `flbb_serial` 99999/88888 — not a legacy schema).
* Tests: `tests/test_provor_cts4_phase2b1_telemetry.py` (20), `tests/test_provor_cts4_phase2b1_followup.py` (7), `tests/test_provor_cts4_phase2b2_arch_cleanup.py` (14 NEW), `tests/unit/test_provor_cts4_phase1_units.py` (30), `tests/unit/test_provor_cts4_phase2a_units.py` (27), `tests/test_provor_cts4_phase1_telemetry.py` (23), `tests/test_provor_cts4_phase2a_telemetry.py` (16).
* LFS bundle: `1C4Cl…` 15.1 MB `/tmp/lfs_bundle.zip` + scratch `/tmp/lfs_extracted` (APEX-only, no NKE 5.8 — `TOOL-AVAILABILITY`).

---

## 6. Gates and blockers

* Gates: `-k provor_cts4` **150/150** (`-k provor` **201**); `-k provor_cts4` 7/7 follow-up + 14/14 arch-cleanup both green; full `pytest -q` **1595 passed 78 skipped 64 failed 18 errors** (+15 vs `1580` before; 0 delta in `64 failed` — no family regression); `ruff check` on `family_constants.py + resolve.py + test_provor_cts4_phase2b2_arch_cleanup.py` all clean; `mypy --strict` on `family_constants.py + resolve.py` Success (0 errors).
* **Not moved to NetCDF/publication:** per prompt STOP, no `R/BD`, no `ARVOR/APEX`, four legacy CSVs untouched, no silent `UNKNOWN` conversion, no BBP fit/correction of BBP, no WMO synthesis — output naming remains suffix-only.
* **Remaining blockers for a future NetCDF phase:** `DATA-COVERAGE` for `03530/03580` if the dedicated `provor_cts4_301_reference.csv` is not extended to include `2902130/2902131` (Barnard shows they exist); `PUBLICATION-REPROCESSED` delta will persist unless the Barnard table is ingested as an explicit `--reprocessed` step (if publication parity is the goal); `UNKNOWN` list above still needs spec semantics (`PT26/27`, `FLAG_SensorBoardStatus`); cycle-0 profile-dating bracketing model still `FIX CANDIDATE`; no WMO synthesis — output naming must remain suffix-only.

---

## 7. Recommendation for next phase (not implemented)

Proceed to **documentation-only** NetCDF planning when authorised: keep the 4-layer decoder (`family_constants` + telemetry 250 FLBB + external per-float DOXY dict/CSV + GDAC CSV as provenance), treat the dedicated `provor_cts4_301_reference.csv` as **append-only** INCOIS-provenance appendix (append `2902130/2902131` to close `03530/03580`), optionally ingest the full `doi:10.17882/54520` Barnard table as a discrete `--reprocessed` toggle (default telemetry truth, `HISTORY` documents the `+1.2%` offset), extend no legacy CSVs, modify no `ARVOR/APEX`, publish no NetCDF until WMO assignment is authorised outside the decoder.

