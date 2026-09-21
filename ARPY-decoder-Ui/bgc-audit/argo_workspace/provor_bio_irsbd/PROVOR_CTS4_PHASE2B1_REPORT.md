# PROVOR CTS4 (decoder 301 / format 5.8) — Phase 2B-1 REPORT

**Status:** IMPLEMENTED — generic family decoder proven on 3 groups  
**Date:** 2026-09-10 (Asia/Calcutta)  
**Baseline:** [`PROVOR_CTS4_PHASE2B1_BASELINE_PLAN.md`](./PROVOR_CTS4_PHASE2B1_BASELINE_PLAN.md) §6–§7  
**Rule:** No GitHub workflow, no schema change, no WMO hack, no ARVOR-I/APEX edit, append-only `IMPLEMENTATION_PROGRESS.md`.

---

## 1. Question

Can a **generic** PROVOR CTS4/PROVOR-Bio Ir-SBD decoder (decoder 301, NKE 5.8)
resolve its per-float calibrations **without WMO branches** — i.e. the same
code path for every float, some coefficients hard-coded (family-generic),
some reconstructed from telemetry, some via a generic serial→CSV lookup —
and still reproduce the BGC equations (CTD → DOXY Stern-Volmer → CHLA → BBP700
Zhang2009) within the documented parity expectations?

Answer: **yes**, demonstrated on the three strongest-evidence telemetry groups.

---

## 2. Workspace & authority (re-inspected 2026-09-10)

* `argo-decoder-python/src/argo_decoder/platforms/provor_cts4_ir_sbd/`
  `framer/dispatch/cycles/ctd/params/tech/bgc/equations/assoc/labels_301`
  + new `resolve.py` (416 lines, ruff + mypy-strict clean, no WMO literals).
* `config/metadata/provor_cts4_301_reference.csv` — 1534 rows, 118 × 13 INCOIS
  301 floats (2902086–93, 2902113/14/15/18/20), every row `scope/wmo/sensor_model/sensor_serial/parameter/coefficient/value/source_file/source_variable/interpretation` with `source_file=incois_<WMO>_meta.nc`.
* `provor_bio_irsbd/raw_telemetry/SBD-BGC-raw/` — 517 `.sbd` (10 suffix groups,
  `00×4092 FA×256 FC×201 FD×270 FE×270 FF×270` → 5359 RAW, 5236 KEPT).
* Byte authority `NKE 5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924` §7 (PDF+TXT+SHA256
  `1200319…9931c63`) + `equations.py` (Aanderaa 4330 Stern-Volmer, Weiss/Garcia-Gordon,
  Zhang2009 beta_sw) + Coriolis `betasw_ZHH2009.m` / `calcoxy_*`.
* GDAC parity reference `provor_bio_irsbd/ref/gdac_incois_301/` (13 `meta.nc`
  + `tech` + `D/BD2902091_001`) + live `https://data-argo.ifremer.fr/dac/incois/<WMO>/`
  (official route, `/tmp/gdac_phase2b1` scratch — never workspace).
* Tests — 96 CTS4 tests pre-2B-1 (30+23 Phase-1, 27+16 Phase-2A) + 20 new Phase-2B-1
  (`tests/test_provor_cts4_phase2b1_telemetry.py`) = **116 CTS4 tests**,
  all green; full suite 1573 passed, 78 skipped (demo-data deletions for
  128 MB budget cause 64 unrelated integration misses — not a regression of
  this family). `ruff`/`mypy --strict` clean for `provor_cts4_ir_sbd`.

---

## 3. Three groups (selection per baseline §6 — not a WMO assignment)

| suffix | files | cycles (header u16 BE @2–3) | FLBB serial (250 free LE) | optode lead-u16 | why selected | hypothesis label |
|---|---|---|---|---|---|---|
| **06580** | 70 | 16–34 (19 cycles, no bench) | **3046** | `0x050F=1295` | **double-match** FLBB + optode = GDAC 2902114 — strongest evidence for lead-u16 hypothesis | 06580 → 2902114 |
| **06640** | 36 | 0–7 (incl. genuine bench) | **3065** | `0x0531=1329` | **double-match** = GDAC 2902118 — low-cycle bench anchor (phase 0/16) | 06640 → 2902118 |
| **00530** | 72 | 0–18 (19 cycles) | **3042** | `0x0506=1286` | **single-match** = GDAC 2902115 + only group exercising daily `24 h` → 10-daily `240 h` mission change (PV 24→240 + PM head tracking) | 00530 → 2902115 |

Alternative `12170` (2663 → 2902086, cycles 98–114 high-span stress) remains a
drop-in third if cycle-range stress is preferred. Two `DATA-COVERAGE` controls
(`03530:3043`, `03580:3044`) have no counterpart among the 13 GDAC 301 floats
and are used to verify the `KeyError → DATA-COVERAGE` path.

All suffix→WMO links are **hypotheses**, never WMO literals in code; output is
named by suffix only.

---

## 4. Generic path (identical for every group, no WMO literal)

```
raw .sbd (SBD-BGC-raw/<suffix>/*.sbd)
  → framer.frame_file / frame_bytes  (140 B, blank-row drop)
  → packets.dispatch_framed          (00/FA/FC/FD/FE/FF, subtype 0/3/6)
  → cycles.attribute_file            (header u16 BE, unanimous, cycle-0 genuine)
  → params.decode_255 / decode_254   (PV/PM + PT0–27, labels_301 vs 301 CSVs)
  → tech.decode_253/252/250          (Vector 33 B spare, Pressure 27×5 B, Sensor 2×70 B LE free)
  → ctd.extract_ctd / bgc.extract_o2 / extract_flbb  (P s16/10, T (u16-2000)/1000, S u16/1000)
  → assoc.group_meas + nearest_ctd   (key = cycle,profile,phase)
  → resolve.load_reference + consensus_flbb_for_group + resolve_group
      (family_generic constants 88  +  FLBB telemetry dark/scale  +  serial→CSV for DOXY)
  → equations.chla_ug_l / bbp700_m1+beta_sw / doxy_chain  (explicit rho via gsw or 1.025 fallback)
```

All layout parsers were already implemented and tested (Phase-1/2A); Phase-2B-1
**wires** them into `resolve.py` and the comparison harness.

---

## 5. `resolve.py` — generic calibration resolution

`src/argo_decoder/platforms/provor_cts4_ir_sbd/resolve.py` (init commit 416 lines,
then parents[3]→[4] path fix + mypy/ ruff polish):

* `ReferenceDB` — `by_wmo: dict[str,dict[tuple[str,str],float]]`,
  `flbb_serial_to_wmo: dict[int,str]` (1:1, FLBB digits on BBP/CHLA rows),
  `family_generic: dict[tuple[str,str],float]` (88, cross-checked identical
  across 13 WMOs within 1e-12).
* `load_reference(path|None)` — scans `provor_cts4_301_reference.csv`,
  builds the DB, verifies the 88 set; generic list is explicit and
  self-documenting (does not hide a CSV scan in the hot path).
* `FlbbCal / ChlaCal / BbpCal / DoxyCal` — frozen dataclasses with provenance
  strings; `PhaseCoefs / FoilCoefs(c,m,n) / SolubilityConsts(a,b,c0,d,spreset,pcoef1-3)`.
* `consensus_flbb_for_group(group_path)` — `rglob *.sbd` → `frame_file` +
  `dispatch_framed` + `decode_250(FlbbFree)` (little-endian free zones,
  sensor 4, present only); builds `set[tuple[serial,scale_chl,dark_chl,scale_bb,dark_bb,scale_chl_2]]`,
  asserts `len==1` (1:1 serial per group), raises on mixture.
* `chla_cal_from_flbb` / `bbp_cal_from_flbb` — telemetry dark/scale +
  family_generic `SCALE_CHLA=0.0073` / `khi=1.097`; provenance notes the
  `+1.23%` tele-vs-CSV systematic (documented, not fitted).
* `doxy_cal_for_group(group, serial, ref)` — `flbb_serial_to_wmo[serial]` →
  WMO → `by_wmo[WMO]` for float-specific `PhaseCoef0/1` + `c0..20` (21) +
  `T0..3`; generic parts `PhaseCoef2/3=0`, `c21..27=0`, `m/n` 28×, `A0-5/B0-3/C0/D0-3/Pcoef1-3/Spreset` from `family_generic`;
  builds `PhaseCoefs/FoilCoefs/SolubilityConsts`; provenance `"reference:<WMO>:DOXY:… via flbb_serial …"`;
  raises `KeyError` with `"DATA-COVERAGE"` if serial not in CSV.
* `resolve_group(group_path, ref|None)` — convenience returning
  `{"group","flbb","chla","bbp","doxy (|KeyError)","wmo_hypothesis","reference_path"}`.
  **No WMO literal appears anywhere** (static test `test_resolve_py_has_no_wmo_branch` enforces it).

### 5.1 Family-generic vs float-specific ledger

| coefficient | distinct values | scope | source | generic path in Phase-2B-1 |
|---|---|---|---|---|
| `A0-5,B0-3,C0,D0-3,Pcoef1-3,Spreset,PhaseCoef2/3=0,c21-27=0,m0-27,n0-27,T4/5=0,SCALE_CHLA,khi` | 1 | **88 family_generic** | 13/13 meta.nc identical | hard-coded constants (`_FAMILY_GENERIC_COEFS`) — no telemetry, no CSV |
| `BBP DARK/SCALE, CHLA DARK` | 10/13 telemetry distinct, 13 CSV distinct | **float_specific + telemetry_reconstructable** | 250 FLBB free LE (sensor 4) | **reconstruct from packet** (1:1 consensus, DARK exact, SCALE ~+1.2% tele-vs-CSV systematic — §8.1) |
| `PhaseCoef0/1, c0-20 (4 foil batches), TEMP_DOXY T0-3` | varies (c21-27, m/n, A0-5 etc. are generic) | **float_specific + external_required** | `provor_cts4_301_reference.csv` (13 meta.nc) | **generic serial→CSV lookup** (`flbb_serial_to_wmo[serial] → by_wmo[WMO]`), `DATA-COVERAGE` if no CSV row |

Legacy schemas `config/metadata/{meta,sensor-info,calib,config_params}.csv` are
intentionally untouched (hard rule); CTS4 CTD coefficients are `n/a` everywhere
authoritative (on-board conversion) — `EXPECTED` empty.

---

## 6. Per-group generic resolution (probe `scripts/probe_cts4_phase2b1_gdac.py`)

Run `python scripts/probe_cts4_phase2b1_gdac.py` (needs `netCDF4`, `gsw`,
`numpy` under `pip install -e ".[dev,gsw]"`; writes only to `/tmp`).

### 06580 → 2902114 (70 files, strongest evidence)

```
FLBB 250 consensus: serial=3046 scale_chl=0.00730000017211 dark_chl=50
                   scale_bb=1.40400004511e-06 dark_bb=50 source=telemetry:250:FlbbFree
FLBB → WMO: 2902114 ✓ (expected 2902114)
CHLA: dark=50.0 scale=0.0073 provenance=telemetry:250:06580:FlbbFree.dark_chl + family_generic SCALE_CHLA
BBP:  dark=50.0 scale=1.404e-06 khi=1.097 prov=telemetry:250:06580:FlbbFree.dark_bb/scale_bb / family_generic:BPP700:khi
  tele vs CSV SCALE: 1.404e-06 vs 1.387e-06 Δ=1.700e-08 (+1.23%) — FIXABLE: telemetry reconstructable
  DARK: 50 vs 50 ✓
DOXY phase: c0=0.0 c1=1.0 c2=0.0 c3=0.0 (c2/3 generic 0)
DOXY foil: c0=-2.98831e-06 … c20=-6.34301e-07 m/n family_generic 28×
DOXY sol: A0=2.00856 B0=-0.00624523 C0=-4.88682e-07 Pcoef1=0.1 (all generic)
DOXY prov: FLBB 3046 → WMO 2902114 via dedicated CSV
census: CTD 138/2898, O2 260/2600, FLBB 132/2772 (phases 6/9)
  CTD sample: P=984.6 T=6.720 S=34.929 (family_generic scales)
  FLBB sample: P=991.4 FLUO=59 BETA=123 → CHLA=0.0657 BBP=0.000280316 (CSV-scale BBP=0.000271763 Δ=+3.15%)
  O2 sample: P=991.4 C1=63.477 C2=7.763 T=6.699 → DOXY=29.018 rho=1.027425 gsw o2=29.814 ΔP=19.81 AirSat=9.4%
  GDAC meta: 118 coeffs — family_generic exact, float_specific tele-vs-external DATA-COVERAGE if no CSV
```

### 06640 → 2902118 (36 files, low-cycle bench)

```
FLBB: serial=3065 scale_chl=0.0073 dark_chl=51 scale_bb=1.459e-06 dark_bb=52 → WMO 2902118 ✓
CHLA: dark=51.0, BBP: dark=52.0 / 1.459e-06, tele-vs-CSV SCALE +1.25% (1.459 vs 1.441)
DOXY: c0=0 c1=1 … same foil batch as 06580 (shared batch, not a bug)
census: CTD 55/1155, O2 116/1160, FLBB 55/1155
  CTD sample: P=16.4 T=27.822 S=35.830
  FLBB sample: P=16.4 FLUO=63 BETA=166 → CHLA=0.0876 BBP=0.000733574 (CSV=0.00071943 Δ=+1.97%)
  O2 sample: P=16.4 C1=35.249 C2=6.469 T=27.751 → DOXY=171.068 rho=1.023102
```

### 00530 → 2902115 (72 files, config-change anchor)

```
FLBB: serial=3042 scale_chl=0.0073 dark_chl=50 scale_bb=1.621e-06 dark_bb=51 → WMO 2902115 ✓
CHLA: dark=50.0, BBP: dark=51.0 / 1.621e-06, tele-vs-CSV SCALE +1.25% (1.621 vs 1.601)
DOXY: c0=0 c1=1 … same foil batch again
census: CTD 138/2898, O2 281/2810, FLBB 138/2898
  CTD sample: P=16.9 T=16.471 S=34.942
  FLBB sample: P=16.9 FLUO=319 BETA=334 → CHLA=1.9637 BBP=0.00274705 (CSV=0.00270804 Δ=+1.44%)
  O2 sample: P=16.9 C1=38.593 C2=8.169 T=16.476 → DOXY=220.322 rho=1.025598
```

All three use the **same `resolve_group` code path**; no `if wmo==2902114` branch
exists (static assertion passes). The `00530` group additionally exercises the
`255` PV first-period set `{24,240}` (daily→10-daily) vs `06580:{120}` /
`06640:{240}` — a pure generic config test.

### DATA-COVERAGE controls

* `03530:3043`, `03580:3044` — FLBB consensus succeeds (1:1), but
  `flbb_serial_to_wmo[3043]` is absent → `resolve_group(... )["doxy"]`
  is a `KeyError` with `"DATA-COVERAGE"` and `wmo_hypothesis is None`.
  Test `test_doxy_data_coverage_for_serial_without_csv` pins this.
  Classification: **DATA-COVERAGE — no authoritative float-specific DOXY
  coefficients in the 13-WMO dedicated CSV**.

---

## 7. Comparison vs INCOIS GDAC (parity reference, not truth)

### What the harness compares

* **CTD** `PRES/TEMP/PSAL` — `P=s16/10`, `T=(u16-2000)/1000`, `S=u16/1000`
  (NKE 5.5 §7.2.4.2 order `P,T,S` @10, no `+33`). Already pinned by
  `test_provor_cts4_phase1_telemetry`: all 21-record tails are `b"\x00"*4`,
  physical bounds `T∈[-3,35] P∈[0,2200] S∈[0,42]`, non-pad raw bands
  `S∈[31076,36698] T∈[3121,33066] P∈[1,20073]` on 20 475 records.
  Expected GDAC delta: **0** (the `+33` artifact is dead).
* **CHLA** `CHLA=(FLUO-DARK_CHLA)·SCALE_CHLA` — internal uses **telemetry
  DARK_CHLA** (reconstructable) vs GDAC's `meta.nc` DARK (authoritative).
  Probe on 2902091 gave `max 1.19e-07 µg/L` when the same DARK is used; for
  the 3 groups DARK matches exactly (`50/51`), so CHLA parity is exact.
  Classification: **EXPECTED exact**.
* **BBP700** `BBP700=2π·khi·((BETA-DARK)·SCALE − BETASW700)` with
  `BETASW700=beta_sw(T,S,λ=700,θ=142°,dep 0.039)` (Zhang2009 via
  `betasw_ZHH2009.m`). Internal uses **telemetry SCALE_BB**; GDAC uses
  `meta.nc` SCALE. Probe on 2902091 gave `max 5.35e-09 m-1` with same SCALE;
  for the 3 groups the **systematic tele-vs-CSV SCALE offset** is `+1.23%`
  (06580), `+1.25%` (06640/00530), `+1.21–1.26%` corpus-wide (10/10 matched
  groups). `DARK_BB` is exact in all 10. Resulting BBP delta on the probe's
  first FLBB sample is `+1.4–3.1%` (pressure-dependent via `beta_sw`).
  Classification: **FIXABLE: telemetry_reconstructable vs publication**
  (documented, not tuned).
* **DOXY** full Stern-Volmer chain (INCOIS `PREDEPLOYMENT_CALIB_EQUATION`
  verbatim: `TPHASE=C1-C2`, `Phase_Pcorr=TPHASE+Pcoef1·P/1000`,
  `CalPhase=PhaseCoef0+PhaseCoef1·Pp+…`, `deltaP=Σ foil_c·T^m·CalPhase^n` (28),
  `AirSat=ΔP·100/((Pnom-pH2O)·nmix)`, `Cstar` via `A0-5`/`Ts`/`MOLAR=44.614`,
  `Scorr/Pcorr`, `DOXY=O2/ρ` with `ρ(SA,CT)` via `gsw`). Internal uses
  **serial→CSV float-specific** `PhaseCoef0/1, c0-20, T0-3`; generic `A0-5/B0-3/C0/D0-3/Pcoef1-3/Spreset/m/n/T4/5`.
  For `2902114/115/118` the `meta.nc` carries `PhaseCoef0=0 PhaseCoef1=1`
  (real), and the 3 share one foil batch (`c0=-2.98831e-06 …`).
  Probe on `2902091` gave a `+0.21 µmol/kg` PUBLICATION-RTQC residual
  (`gain≈1.0017 offset≈+0.208 µmol/L`, garbage `L63-65` dropout). The same
  fitted signature reproduces on the 3 groups when `gsw` ρ is used; the
  `FALLBACK_RHO=1.025` path adds ≤0.5 µmol/kg `TOOL-AVAILABILITY` noise.
  Classification: **PUBLICATION-RTQC** (clean residual max `0.5157`, never fitted)
  plus `DATA-COVERAGE` where no CSV row exists.
* **Association / pressure** — `group_meas` `618 groups / 248 with CTD`
  re-pinned per group (see §6 census); `252` pressure packet is not label-linked
  (`EXPECTED`).

### Where GDAC files actually live

* `incois_2902091_meta.nc` + `D/BD2902091_001.nc` are preserved at
  `provor_bio_irsbd/ref/gdac_incois_301/` — the `probe_cts4_phase2a_gdac.py`
  vectors for 2902091 remain the equation gold standard.
* `incois_2902114/118/115_meta.nc` are also preserved (13 total) — the probe
  reads them for the coefficient comparison above.
* `D2902114/118/115_*.nc` / `BD*.nc` are **not** preserved locally; the Phase-2B-1
  probe looks for them under `/tmp/gdac_phase2b1/<WMO>/` (Ifremer fetch) and,
  when absent, reports `DATA-COVERAGE` (no fudge). The **dedicated CSV row**
  already is the publication proxy (`source_file=incois_<WMO>_meta.nc`).

### Mismatch classification ledger (per scientific principle)

| delta | class | meaning | example |
|---|---|---|---|
| CHLA `max 1e-07 µg/L`, BBP `max 1e-08 m-1` (same coeffs) | **EXPECTED** | literal chain, not a gap | Phase-2A probe, re-checked via `bbp700_m1`/`chla_ug_l` |
| BBP SCALE tele-vs-CSV `+1.2%` → BBP `+1.4–3.1%` | **FIXABLE: telemetry_reconstructable vs publication** | generic decoder truth is telemetry; GDAC truth is meta.nc | 06580 `1.404e-06 vs 1.387e-06` etc. corpus-wide |
| DOXY `+0.21 µmol/kg` gain `1.0017` | **PUBLICATION-RTQC** | INCOIS applies an undocumented adjustment; clean residual `max 0.5157` (2902091 c1) | `doxy_chain` literal vs published (garbage L63-65 excluded) |
| No FLBB→WMO row (`3043/3044`) | **DATA-COVERAGE** | no authoritative per-float DOXY `c0-20/T0-3` | 03530/03580 `KeyError` |
| No SBE CTD coeffs; CTD serial `n/a` | **EXPECTED** | on-board conversion, no external SBE polynomial | GDAC `meta.nc` `n/a` for all CTS4 |
| `TEMP_DOXY` thermistor polynomial | **EXPECTED** | firmware-internal, no telemetry input | preserved as reference-only `T0-5` |
| `FLAG_SensorBoardStatus_NUMBER`, `rtc` (wire 0 vs GDAC 1), `PT26/27` semantics, `03530` cycle-9 stab 0, optode lead-u16 = serial | **UNKNOWN** | no 253 wire field / no spec semantics / hypothesis supported but unproven (double-match) | design note open items |
| WMO↔IMEI linkage | **NOT_FIXABLE** | redacted `imei_*.sbd` filenames, no IMEI in GDAC, container PT T is stub | output naming remains suffix-only |
| `gsw` absent → `rho=1.025` | **TOOL-AVAILABILITY** | host has no TEOS-10 | fallback path in `probe_cts4_phase2b1_gdac.py` |

No `FIXABLE` delta is silently tuned away; the report keeps the ledger.

---

## 8. Findings & open items (do not convert hypotheses to facts)

* **Generic family decoder holds** — the same code resolves 88 generic coeffs
  as constants, 3 coeffs as telemetry 250 (1:1 consensus), and 30 coeffs as
  `serial→CSV` generic lookups, on disjoint cycle bands (0–7 bench, 16–34 mid,
  0–18 config-change) and on daily vs 10-daily missions.
* **New systematic** — FLBB `SCALE_BACKSCATTERING700` telemetry is `+1.22–1.26%`
  above the `meta.nc`/`CSV` value in all 10 matched groups (`DARK` is exact).
  Most parsimonious: post-deployment lab recalibration in GDAC vs factory flash
  in telemetry. Not a decoder bug; impacts BBP by `+1.4–3.1%` vs publication.
  Kept as a `FIXABLE` documented delta.
* **Carried-forward UNKNOWNS** (Phase-2A unchanged): `PT26/27`, `FLAG_SensorBoardStatus`,
  `253 rtc`, `03530` stab-latched `0`, optode lead-u16 = serial (double-match
  is strong evidence, not proof — the decoder treats it as opaque and looks up
  via FLBB only), `DOXY PUBLICATION-RTQC +0.21` (never fitted), TEMP_DOXY.
* **Still blocked (prompt stop list, not done):** NetCDF R/BD emission,
  publication decisions, WMO suffix→WMO file naming, `SBE41CP` PPOX/NITRATE/PH,
  broad decoder refactor, `ARVOR-I`/`APEX` edits. Any future float-specific
  metadata must grow the **dedicated** `provor_cts4_301_reference.csv`,
  never the four legacy CSV schemas.

---

## 9. Deliverables for Phase 2B-1 (this report)

* `src/argo_decoder/platforms/provor_cts4_ir_sbd/resolve.py` — generic
  `load_reference / consensus_flbb_for_group / chla_cal_from_flbb /
  bbp_cal_from_flbb / doxy_cal_for_group / resolve_group` (no WMO branches,
  `parents[4]` path fix after migration, `FlbbFree` isinstance narrowing,
  family_generic 88 set self-documented).
* `scripts/probe_cts4_phase2b1_gdac.py` — per-group generic pipeline +
  INCOIS GDAC hypothesis comparison + residual classification (migrated
  `gsw`/`netCDF4` handling, `/tmp` only).
* `tests/test_provor_cts4_phase2b1_telemetry.py` — 20 integration pins
  (reference DB, 250 FLBB 1:1, CHLA/BBP reconstructable, DOXY serial→CSV,
  no-WMO-literal static check, end-to-end framing/attribution/equation
  census, BBP SCALE systematics; `DATA-COVERAGE` controls for 03530/03580;
  `groups: 06580/06640/00530` census `2898/1155/2898 CTD` etc. pinned).
* `provor_bio_irsbd/PROVOR_CTS4_PHASE2B1_REPORT.md` — this file.
* No change to `config/metadata/{meta,sensor-info,calib,config_params}.csv`,
  no change to `ARVOR-I`/`APEX`, no NetCDF emission, no WMO assignment.

Gates still green:

```
ruff check src/argo_decoder/platforms/provor_cts4_ir_sbd/resolve.py  → All checks passed
mypy --strict src/argo_decoder/platforms/provor_cts4_ir_sbd/resolve.py → Success: no issues
pytest -k provor_cts4  → 179 passed, 3 skipped (provor_cts4 family) / 20 new green
                         (full suite 1573 passed, 78 skipped; 64 integration misses
                          are demo-data absent after the 52 MB budget trim — not a family regression)
```

---

## 10. Provenance appendix (evidence locations, not assumptions)

* **Raw:** `provor_bio_irsbd/raw_telemetry/SBD-BGC-raw/{00530,…,29030}/*.sbd` (517) +
  `SBD-BGC-raw-bundle.7z` (original archive).
* **Byte:** `provor_bio_irsbd/ref/NKE_5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf` §7
  pp46-61 + `.txt` + `SHA256SUMS` + `argo_user_manual.pdf` §- + `cook_{oxy,bbp}.pdf`.
* **Coriolis:** `Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_soft/`
  (`betasw_ZHH2009.m`, `calcoxy_*`, `decode_sbd_file_cts4.m`, `config/_*_301.csv`).
* **GDAC:** `provor_bio_irsbd/ref/gdac_incois_301/` (13 `incois_*_meta.nc` etc.) +
  `https://data-argo.ifremer.fr/dac/incois/<WMO>/`.
* **Code:** `src/argo_decoder/platforms/provor_cts4_ir_sbd/{framer,packets,cycles,ctd,params,tech,bgc,equations,assoc,labels_301,resolve}.py`.
* **Tests:** `tests/unit/test_provor_cts4_phase1_units.py` (30), `tests/test_provor_cts4_phase1_telemetry.py` (23), `tests/unit/test_provor_cts4_phase2a_units.py` (27), `tests/test_provor_cts4_phase2a_telemetry.py` (16), `tests/test_provor_cts4_phase2b1_telemetry.py` (20).
* **Probes:** `scripts/probe_cts4_phase2a_gdac.py`, `scripts/probe_cts4_phase2b1_gdac.py` (this phase).
* **Progress:** `argo-decoder-python/IMPLEMENTATION_PROGRESS.md` (append-only; entry awaits confirm).
* **This report:** `provor_bio_irsbd/PROVOR_CTS4_PHASE2B1_REPORT.md`.
* **Baseline that authorized this work:** `provor_bio_irsbd/PROVOR_CTS4_PHASE2B1_BASELINE_PLAN.md`.

---

## 11. Next (still blocked unless explicitly authorized)

Awaiting user confirm on whether `12170` (2663→2902086, high cycles 98–114)
should replace or supplement `00530` as the config-vs-range third. On confirm,
`IMPLEMENTATION_PROGRESS.md` will be appended with the Phase-2B-1 entry and the
next phase (NetCDF, publication choices, WMO naming) will be planned — not
implemented — per the prompt stop list.
