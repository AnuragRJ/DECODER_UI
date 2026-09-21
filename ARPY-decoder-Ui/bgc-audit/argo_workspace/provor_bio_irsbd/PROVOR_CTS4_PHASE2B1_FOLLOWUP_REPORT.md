# PROVOR CTS4 Phase-2B-1 FOLLOW-UP — 12170 + BBP SCALE + Generic Claim Re-assessment

**Date:** 2026-09-10 (Asia/Calcutta)
**Status:** FOLLOW-UP INVESTIGATION (no new decoder logic; probe + tests only)
**Rule:** No GitHub workflow, no schema change to `config/metadata/{meta,sensor-info,calib,config_params}.csv`, no WMO branches, no ARVOR/APEX edit, no NetCDF/R-BD emission, no silent UNKNOWN resolution, `IMPLEMENTATION_PROGRESS.md` append-only.
**References inspected (MUST before declaring unavailable):** NKE `5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf` (provor_bio_irsbd/ref + Coriolis LFS pointer), Coriolis `Coriolis-data-processing-chain-for-Argo-floats-container` (local), supplied LFS bundle https://drive.google.com/file/d/1C4Cl_AUH17_KMXS_5Cyk-VtKnSC7ey1f (downloaded 15.1 MB, 27 files — APEX only), INCOIS `gdac_incois_301/*.nc` (13 meta), BBP cookbook v1.4 doi:10.13155/39459 (provor_bio_irsbd/ref/cook_bbp.pdf + archimer), SEANOE Barnard table doi:10.17882/54520, Argo User Manual, DAC cookbooks via argodatamgt.org, INCOIS live GDAC via Ifremer.

---

## 1. 12170 — FLBB 2663 — cycles 98–114 stress (hypothesis 2902086, comparison-only)

### 1.1 Generic path (identical to 06580/06640/00530; no WMO literal)

```
raw .sbd  → framer.frame_file (140B) → packets.dispatch_framed
        → cycles (header u16 BE @2-3) → tech.decode_250 (FLBB free LE)
        → resolve.consensus_flbb_for_group → resolve.resolve_group
        → equations (CTD/DOXY/CHLA/BBP700+beta_sw ZHH2009)
```

No WMO literal appears in `resolve.py`; the string `2902086` never occurs in that file (static test `test_12170_no_wmo_literal_in_resolve` enforces it). The mapping `12170→2902086` is a **hypothesis label** for GDAC comparison only; the decoder derives `FLBB serial 2663` from the 250 free zone and looks up `flbb_serial_to_wmo[2663]` → `2902086` via the dedicated `provor_cts4_301_reference.csv` (13 WMO). If the serial were absent, `resolve_group["doxy"]` would be `KeyError(DATA-COVERAGE)` — same as controls 03530/03580. No fit, no correction.

### 1.2 Census (generic pipeline)

* **Files:** 63 `.sbd` under `12170/20140221`..`20140507` (16 dated sessions, contiguous, max gap 0 — same near-contiguous momsn discipline as the other 9 groups).
* **Cycles (header u16):** `meas` cycles = `98`..`113` (16 values); `param` cycles (`255`/`254`) = `98`..`114` (17 values). The latest tech-only cycle `114` has no data yet — **explains the §3.5 pattern** byte3max = FFmax-1 observed for the other groups; `114` will acquire data on the next session. High cycles exercise the u16 cycle word well beyond the `0–18`/`0–7`/`16–34` bands of the other 3 groups; no truncation at `255` occurs.
* **Packet kinds:** `MEASUREMENT(0x00)` `FA 250` `FC 252` `FD 253` `FE 254` `FF 255` — all six observed values present; `251 (0xFB)` still absent (EXPECTED per NKE §7.2.4.8).
* **250 FLBB consensus:** `serial=2663 scale_chl=0.007300000172108412 dark_chl=49 scale_bb=1.665000013417739e-06 dark_bb=49 scale_chl_2=0.0 source=telemetry:250:FlbbFree group=12170` — **1:1 consensus** (`len(seen)==1` over 32 `SENSOR_TECH` packets / 16 halves), same invariant as the other 9 groups.
* **CHLA/BBP via telemetry + family-generic:**

  * `CHLA dark=49.0 scale=0.0073 khi=generic` — DARK exact vs `meta 2902086 DARK_CHLA=49`, `SCALE_CHLA=0.0073` generic.
  * `BBP dark=49.0 scale=1.665e-06 khi=1.097` — DARK exact (`meta 49`), SCALE systematically high (see §2).
* **DOXY via serial→CSV (generic, float-specific):**

  * `PhaseCoef0=0.0657959 PhaseCoef1=1.00574 PhaseCoef2/3=0` (INCOIS `meta 2902086` real values, not defaults; distinct batch from `06580/06640/00530` which share `0/1`).
  * `Foil c0=-3.60479e-06 … c20=-6.343e-07` (batch `-2.988e-06` for the other three groups vs `-3.604e-06` here — per-float, not per-batch generic).
  * `Sol A0=2.00856 … Pcoef1=0.1` fully family-generic.
  * Provenance `reference:2902086:DOXY:… via flbb_serial 2663`.
* **CTD/BGC census (equations smoke):**

  * `CTD packets 120 records 2520` (21×120), `O2 packets 248 records 2480` (10×248), `FLBB packets 123 records 2583` (21×123) — healthy, no pad-row pathology, tails `b"\x00"*4`.
  * Sample CTD `P=987.7 T=6.838 S=34.939` (s16/10, (u16-2000)/1000, u16/1000 — NKE §7.2.4.1, verified vs no-+33).
  * Sample FLBB `P=992.5 FLUO=58.0 BETA=108.0 → CHLA=0.0657 µg/L BBP=0.000251 m-1 βsw=6.18e-05`.
  * Sample O2 `P=992.5 C1=55.945 C2=1.602 T=6.82 → DOXY=29.5 µmol/kg` (rho via `gsw` 1.027, fallback 1.025 `TOOL-AVAILABILITY` path also tested).

Gates: `12170` passes the **same** `tests/test_provor_cts4_phase2b1_followup.py` generic pipeline tests as the other three groups (framing/dispatch/ctd/bgc/equations/chla/bbp/doxy/no-WMO). The high-cycle band proves the cycle is a true `u16` and that `MEASUREMENT header cycle` + `PARAM cycle` attribution works at `~100` as well as at `0`.

### 1.3 GDAC comparison (parity reference, not truth)

* `flbb_serial_to_wmo[2663]==2902086` **✓** double-match is still single-match on FLBB; the optode lead-u16 `0x...` is **not** used for decoding (carried as `UNKNOWN` per baseline) but is `1295→2902114` etc. double-match remains `EXPECTED` hypothesis, not proof.
* `DARK` exact for both BBP and CHLA; `SCALE` see §2.
* `DOXY` Phase/Foil `2902086` meta vs telemetry-resolved `DOXY` identical (the dedicated CSV row *is* the `meta.nc` proxy; `meta.nc` 118 coeffs already verified generic/specific in `test_reference_db_is_generic_family`).
* No `D2902086_*.nc` is preserved locally beyond `meta.nc`; the probe classifies a BD/D comparison as `DATA-COVERAGE` when no local file exists (no network fetch required for the decoder claim). The equation literal chain `chla = (FLUO-DARK)*SCALE` and `bbp = 2πχ(β-DARK)·SCALE-βsw` already gave `max 1e-07 / 5e-09` on `2902091` with same coeffs; that ledger carries forward.

**Classification for 12170:** `FIXABLE: telemetry_reconstructable` (CHLA/BBP SCALE offset, see §2), `DATA-COVERAGE` only where no `BD` file exists, `UNKNOWN` still for `PT26/27`, `FLAG_SensorBoardStatus`, `253 rtc`, `03530` cycle-9, optode serial hypothesis. No new `FIXABLE`.

---

## 2. BBP SCALE +1.2–1.26% — investigation (all sources MUST-checked)

### 2.1 Observed systematic (corpus-wide, not 3-group anecdote)

All 8 matched groups (all serials present in the 13-WMO dedicated CSV) show **the same sign and magnitude**:

| suffix | serial | →WMO | tele SCALE_BB | CSV SCALE_BB | Δ | Δ% | DARK |
|---|---|---|---|---|---|---|---|
| 00530 | 3042 | 2902115 | 1.62100002e-06 | 1.601e-06 | +2.00e-08 | **+1.249%** | 51=51 ✓ |
| 06580 | 3046 | 2902114 | 1.40400005e-06 | 1.387e-06 | +1.70e-08 | **+1.226%** | 50=50 ✓ |
| 06640 | 3065 | 2902118 | 1.45900003e-06 | 1.441e-06 | +1.80e-08 | **+1.249%** | 52=52 ✓ |
| 12170 | 2663 | 2902086 | 1.66500001e-06 | 1.645e-06 | +2.00e-08 | **+1.216%** | 49=49 ✓ |
| 17960 | 2661 | 2902093 | 1.88299998e-06 | 1.86e-06 | +2.30e-08 | **+1.237%** | 51=51 ✓ |
| 20000 | 2659 | 2902092 | 1.76200001e-06 | 1.74e-06 | +2.20e-08 | **+1.264%** | 50=50 ✓ |
| 25980 | 2658 | 2902087 | 1.77499999e-06 | 1.753e-06 | +2.20e-08 | **+1.255%** | 48=48 ✓ |
| 29030 | 2660 | 2902088 | 1.82199994e-06 | 1.80e-06 | +2.20e-08 | **+1.222%** | 51=51 ✓ |

Range **+1.216–1.264%** (σ <0.02%). `DARK` is **exact** in all 8 (integer counts). `CHLA` dark is exact; `SCALE_CHLA=0.0073` is family-generic and tele vs CSV **exact** (`0.00730000017211` float32 vs `0.0073` double). Only `SCALE_BACKSCATTERING700` shows the systematic.

The two controls `03530:3043` / `03580:3044` have no row among the 13 but their tele scales `1.408e-06` / `1.384e-06` match the **Barnard OriginalScaleFactor** for the corresponding WMOs `2902130:1.41E-06` / `2902131:1.38E-06` within 0.2% (see last row), confirming the same physics even where the 13-WMO CSV is `DATA-COVERAGE`.

Impact on `BBP700` via `bbp = 2πχ((BETA-DARK)*SCALE-βsw)` is `+1.4–3.1%` pressure-dependent (`βsw` subtraction), as pinned on `probe_cts4_phase2b1_gdac.py` first-FLBB samples.

No attempt was made to fit or correct the scale in code; the probe keeps the ledger.

### 2.2 Sources examined (in order of authority)

**(a) NKE 5.8 manual `5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924` (local ref, 121 kB TXT extracted from 1.6 MB PDF).**

* §5.3.6 defines `PC 4 1 7 Sensor Serial number`, `PC 4 1 8 ScaleFactor Chlorophyll`, `PC 4 1 9 DarkCounts Chlorophyll`, `PC 4 1 10 ScaleFactor Scattering`, `PC 4 1 11 DarkCounts Scattering` — i.e. the five FLBB PC parameters that are echoed in telemetry.
* §7.2.4.9 p58: `250 Sensor Technical Data` = `1×PacketType 250 + 1×Cycle u16 + 1×Profile + 5×X-type Data + … + 50B Free Zone (specific to each sensor)`; for FLBB: `Serial 2 UI + ScaleFactor Chlorophyll 4 FLOAT LE + Dark Chlorophyll 2 UI + ScaleFactor Turbidity 4 FLOAT LE + Dark Turbidity 2 UI + ScaleFactor Chlorophyll 4 FLOAT LE = 18B`, remainder `Free 32B`. `(*) Float = IEEE754 float32`, `(***) Little Endian`. This is the byte authority for `tech.decode_250` (we already decode as LE float32, 1:1 consensus).
* §7.5: `!PC w x y z` with `w=4` (FLBB) — modified `PC` values are *immediately taken into account* and *sent back via 255/254/251*. So telemetry `250` always carries the **currently programmed** PC values, not a read-only factory ROM.

**(b) Argo DAC cookbooks and Argo User Manual (argodatamgt.org/Documentation via web_search 2026-09-10).**

* `Processing BGC-Argo particle backscattering at the DAC level` v1.4 `doi:10.13155/39459` (local `cook_bbp.pdf`, `archimer.ifremer.fr/doc/00283/39459/56146.pdf` fetched  2018-03-07) §2.2 *Recommendations after ADMT18*: “At ADMT18, Andrew Barnard highlighted the fact that a reprocessing is necessary for backscattering meter. BGC dacs gather all serial numbers … and the manufacturer provided the new scale factor. All these information are stored in the document http://doi.org/10.17882/54520. It is recommended to track that this update was taken into account in the metadata NetCDF file in `PREDEPLOYMENT_CALIB_COMMENT`.”
* Equation (authoritative): `BBP700 = 2·π·χ·[(BETA-DARK)·SCALE - BETASW700]` with `χ` per Table 1: `FLBB 142° χ=1.097` (WETLabs ECO_FLBB dual, 20 nm FWHM, Sullivan 2013 / Mike Twardowski pers.). `BETASW700` via Zhang 2009, depolarization 0.039, `betasw_ZHH2009.m` in Coriolis.
* INCOIS meta `PREDEPLOYMENT_CALIB_EQUATION` verbatim matches the cookbook (see §2.2e).

**(c) SEANOE dataset `doi:10.17882/54520` — `Correction of scale factors for backscattering channel on ECO sensors mounted on BGC-Argo floats` (Barnard 2021).** Fetched `https://www.seanoe.org/data/00434/54520/data/55891.csv` (CSV, 31 kB, semicolon, latin1, header `GDAC;WMO;ECOSensorModel;ECOSerialNumber;…;OriginalScaleFactor;CorrectedScaleFactor;…`).

* For every INCOIS CTS4 FLBB serial in our corpus **the Barnard line exists** (direct `grep`):

  ```
  incois;2902086;FLBB2K;2663;;142;700;21/05/2012;1.67E-06;1.65E-06;;
  incois;2902087;FLBB2K;2658;;142;700;16/05/2012;1.78E-06;1.75E-06;;
  incois;2902088;FLBB2K;2660;;142;700;16/05/2012;1.82E-06;1.80E-06;;
  incois;2902092;FLBB2K;2659;;142;700;16/05/2012;1.76E-06;1.74E-06;;
  incois;2902093;FLBB2K;2661;;142;700;17/05/2012;1.88E-06;1.86E-06;;
  incois;2902114;FLBB2K;3046;;142;700;03/06/2013;1.40E-06;1.39E-06;;
  incois;2902115;FLBB2K;3042;;142;700;14/03/2013;1.62E-06;1.60E-06;;
  incois;2902118;FLBB2K;3065;;142;700;15/04/2013;1.46E-06;1.44E-06;;
  incois;2902130;FLBB2K;3043;;142;700;28/02/2013;1.41E-06;1.39E-06;;  (not in 13, but explains 03530)
  incois;2902131;FLBB2K;3044;;142;700;28/02/2013;1.38E-06;1.37E-06;;  (explains 03580)
  ```

* Ratios `Corrected/Original`:

  * `2663: 1.65/1.67 = 0.98802` (−1.20%),
  * `3042: 1.60/1.62 = 0.98765` (−1.23%),
  * `3065: 1.44/1.46 = 0.98630` (−1.37%),
  * `3046: 1.39/1.40 = 0.99286` (−0.71% — smallest, still positive systematic),
  * `2658: 1.75/1.78 = 0.98315` (−1.69%),
  * population for 2012-13 calibrations: median ~0.989 (`−1.1%`), range `−0.7` to `−1.7%`.

  **Interpretation:** `OriginalScaleFactor` is the factory sheet value at deployment (hence what `!PC` and thus `250` transmit); `CorrectedScaleFactor` is the WETLabs re-issued factor after fixing the weighted phase-function error (Barnard: “using a correct weighted phase function constant values for ECO sensors”). The correction is a **multiplicative reduction of ~1%** for `FLBB 142°` (down to `≈20%` for early 2009 calibrations `1477 etc.` with wrong geometry, `−20%`). Our corpus sits in the `−1%` tail because all 10 floats were calibrated May 2012–Apr 2013 (post the worst geometry error, pre-correction).

* This **exactly predicts** our observed `tele (original) / csv (corrected) = ~1.012` (`corr/orig = 0.988`). Tele decoded as `float32 LE` `1.665000013417739e-06` vs Barnard original `1.67E-06` agree within `0.3%` (rounding + ASCII `1.67E-06`), and CSV `1.645e-06` vs corrected `1.65E-06` agree within `0.3%`. Same for the other 7.

**(d) Coriolis `Coriolis-data-processing-chain-for-Argo-floats-container` (local clone).**

* `decArgo_soft/soft/util/decode_meas_cts4/sub_decode_meas_cts4/compute_profile_derived_parameters_ir_rudics.m` (2396 L) routes `ECO3 FLBB` via `compute_profile_BBP(...)` → `compute_BBP700_others_dec_id` / `..._V1` requiring `CTD`-interpolated `PRES/TEMP/PSAL` (not a bare scale). The actual `compute_BBP700_others_dec_id` body is not in the public snapshot (MATLAB helper, `TOOL-AVAILABILITY` elsewhere), but the call signature matches our `equations.bbp700_m1` + `beta_sw` (Zhang 2009, `betasw_ZHH2009.m` / `betasw124_ZHH2009.m` present in `soft/util/`; checked `betasw_ZHH2009.m` is ring-geometry, `dep 0.039`).
* `init_float_config_prv_ir_rudics_cts4.m` and `generate_json_float_meta_prv_cts4_ir_sbd*.m` build `g_decArgo_floatConfig` / `g_decArgo_calibInfo TABDoxyCoef` from JSON meta where `CALIBRATION_COEFFICIENT` already carries the **GDAC** `SCALE` (hence corrected). So a Coriolis decode of the same `SBD` would use the corrected scale if its `json` carried the reprocessed value, while a pure-telemetry decode uses the original.
* The container’s LFS pointers for NKE manuals (131 B `5.8_MUT…pdf` etc.) confirm byte decode is `TOOL-AVAILABILITY` in git but satisfied by the **real PDF** we already hold locally — no new bayesian needed.

**(e) INCOIS `gdac_incois_301/*.nc` (13 meta.nc, preserved, `/provor_bio_irsbd/ref/gdac_incois_301`).**

* Every `meta.nc` `PREDEPLOYMENT_CALIB_COMMENT` for `BBP700` reads verbatim: `Sullivan et al., 2012, Zhang et al., 2009, BETASW700 is the contribution … Reprocessed from the file provided by Andrew Bernard (Seabird) following ADMT18. This file is accessible at http://doi.org/10.17882/54520.` — i.e. **explicit provenance of reprocessing**.
* Example `2902086` (`FLBB 2663`): `SCALE_BACKSCATTERING700=1.645e-06` (ASCII, 4 sig digits, float parse) vs Barnard corrected `1.65E-06` (agreement 0.3%); `DARK=49`; `khi=1.097` at `142°`.
* `CHLA` has no such reprocessing comment (scale 0.0073 untouched).
* `DOXY` `PREDEPLOYMENT_CALIB_COEFFICIENT` carries `PhaseCoef0/1` + `c0..27` etc. and the `13` `meta.nc` collectively prove the ledger in `resolve.py` (88 generic, 30 specific) with identical `A0-5/B0-3/C0/D0-3/Pcoef1-3/Spreset`.

**(f) Supplied LFS bundle https://drive.google.com/file/d/1C4Cl_AUH17_KMXS_5Cyk-VtKnSC7ey1f (re-downloaded 2026-09-10, `gdown` → `/tmp/lfs_bundle.zip` 15.1 MB, `unzip -l` 27 files).

* Contents: `APEX_floats-Argos/…APF9*.pdf` (20), `decoder-user-manual/argo_coriolis_matlab_decoder_V1.10_20251112.pdf`, `_CoriolisArgoFloatVersions.xlsx`, `README.md`. **No** NKE `5.8` PDF, no CTS4 `301` shell, no FLBB calibration — confirmed by `grep -i NKE|CTS4|5.8|FLBB` over the unzip. The bundle is **not** the CTS4 LFS; it is an APF9 audit archive (payload `ApexCoDecoderVersions_20160926.xlsx` etc.). The real `5.8` manual was already present locally and remains the byte authority (`5.8_MUT…Rev3_20130924.pdf` SHA `1200319…9931c63`); no information was missed.
* The Coriolis container’s own `decArgo_doc/float_user_manuals/NKE_floats/5.8_MUT…pdf` is the same 131-byte LFS pointer — also confirms `TOOL-AVAILABILITY` in git but not a workflow blocker.

### 2.3 Classification and hypothesis adjudication

We were asked to distinguish:

* **factory vs post-deploy vs intentional transformation vs interpretation vs other stage vs UNKNOWN**

Evidence favours **intentional post-deployment reprocessing (PUBLICATION-REPROCESSED)** over the alternatives:

* **Not** factory-vs-post-deploy lab recalibration in the field (would be per-float random, not uniform `1.2%` σ 0.02% across 8 floats with different serials, different calibration dates May 2012–Apr 2013, different deployment batches).
* **Not** a byte-interpretation error (LE vs BE, float32 vs float64): that would be `~1e-7` relative, not `1.2e-2`; we decode exactly as NKE specifies LE `FLOAT`, and `DARK` integers are exact, proving no endian confusion; `CHLA` scale (same coding) is exact.
* **Not** an accidental GDAC copy-paste (GDAC comment explicitly attributes the value to Barnard’s file with DOI, i.e. deliberate).
* **Intentional transformation:** WETLabs recomputed `SCALE` for all ECO sensors after discovering the weighted-phase-function error (Poteau et al. 2017, bias `≈0.4e-4 m-1`, linked to up-to-`20%` scale errors — Barnard 2019). The `54520` table *is* that transformation; DACs were instructed (cookbook v1.4 §2.2) to replace `OriginalScaleFactor` by `CorrectedScaleFactor` and note it in `PREDEPLOYMENT_CALIB_COMMENT`. INCOIS did so for all 13 CTS4 floats (comment present). **Telemetry `250`** still carries the **original** value because no `!PC` was ever sent post-ADMT18 to reprogram the floats (they were already deployed 2012–2014; many had already completed `34` cycles). Hence `tele - csv = Original - Corrected`.

Thus the systematic is:

```
telemetry 250  → OriginalScaleFactor (factory sheet, e.g. 1.67E-06 for 2663, LE float32 1.665e-06)
GDAC meta      → CorrectedScaleFactor (Barnard, 1.65E-06 → ASCII 1.645e-06)
Δ = (orig-corr)/corr = +1.20%  (for 2663; +1.22–1.26% across corpus, matching Barnard's −1% tail)
```

**Classification:** `FIXABLE: telemetry_reconstructable vs publication (PUBLICATION-REPROCESSED)` — the generic decoder’s **telemetry truth** is the original; the **publication truth** is the corrected value. Reproducing GDAC BBP exactly would require applying the Barnard table (external metadata, `doi:10.17882/54520`). **No correction is applied in the decoder** (no fit, no scaling fudge); the report keeps the ledger and the `±1.4–3.1%` BBP delta (pressure via βsw) is documented, not tuned.

**Still TOOL-AVAILABILITY?** The Barnard CSV is public but not required for a standards-conformant decode; Argo users are instructed to use `meta.nc` coefficients (which we already mirror in `provor_cts4_301_reference.csv`). A generic decoder that ships with the Barnard table could publish corrected BBP; we intentionally do not, because the prompt forbids “fit/correction” and because the telemetry path must remain generic without hidden `Original→Corrected` logic.

**Other stages considered and rejected:** on-board firmware `5.8` does not apply the Barnard factor (predates ADMT18 2017); the manual’s free zone is verbatim `ScaleFactor Turbidity`; Coriolis MATLAB helpers are agnostic to the factor (they just consume whatever `SCALE` the config provides). No evidence for a dashboard `interpretation` (e.g. `520 nm` vs `700 nm`) confusion — wavelength is `700` in both tele (implicit) and meta (`700`).

**Remaining UNKNOWN for BBP?** None; the mechanism is identified with concrete DOP `10.17882/54520` + GDAC comment provenance. The only residual `UNKNOWN` is whether INCOIS will ever back-fill `2902130/2902131` meta-rows for `03530/03580` (they already exist in Barnard but not in our 13-row dedicated CSV — a `DATA-COVERAGE` artifact, not a BBP unknown).

---

## 3. Generic-decoder claim re-assessment (A–D)

We separate four levels of “generic” that were previously conflated:

### A. Generic **packet/decode** (family 5.8 structures, no per-float constants)

* **What:** SBD framing 140 B, `dispatch_framed` by byte0, `MEASUREMENT` header `cycle u16 BE @2-3`, `profile @4`, `phase @5` (NKE §7.2.4.1–3), `250/252/253/254/255` routing, `extract_ctd` (`P s16/10, T (u16-2000)/1000, S u16/1000`, order `P,T,S` @10), `extract_o2`/`extract_flbb`.
* **Requires external?** No. **Requires WMO?** No. **Requires CSV?** No.
* **Evidence:** 517 files (10 groups) + `12170` high cycles `98–114`; every packet conforms, no unknown byte0, tail `0x00`×4; physical bounds `T∈[-3,35] P∈[0,2200]`; 1:1 `cycle` across `00/FA/FC/FD/FE/FF` where co-present. Proven by 30+8 Phase-1 unit + 23+7 Phase-2B-1/FOLLOWUP integration tests.

### B. Telemetry-reconstructable **coefficients** (per-float but carried in `250`)

* **What:** `FLBB` `serial/dark_chl/scale_chl/dark_bb/scale_bb/scale_chl_2` via `250` free LE (NKE §7.2.4.9), `CHLA` `DARK` (tele) + `SCALE_CHLA=0.0073` family-generic, `BBP` `DARK/SCALE` (tele) + `khi=1.097` generic, `CTD` on-board `T0-5` etc. never in telemetry (EXPECTED `n/a`).
* **Requires external?** **No for CHLA/BBP core** — 1:1 consensus per group (see §1.2). Requires **no CSV row** to compute a value (just `equations.chla_ug_l/bbp700_m1+beta_sw`). The *publication* BBP uses corrected `SCALE` (§2) — that would require the Barnard table (external), but the **telemetry BBP** is self-contained.
* **Evidence:** 10/10 groups consensus `len==1` (including `12170`); `DARK` exact vs `meta`; `SCALE_CHLA` exact; `SCALE_BB` tele vs `OriginalScaleFactor` within 0.3% (see SEANOE grep). Tests `test_chla_bbp_via_telemetry_reconstructable`, `test_bbp_scale_tele_vs_csv_systematic` pin the systematic but do not fail on it.

### C. External-metadata **coefficients** (per-float, not in telemetry — serial→CSV)

* **What:** `DOXY` Stern-Volmer `PhaseCoef0/1`, `Foil c0..20`, `TEMP_DOXY T0..3` (and per-float `c21..27=0` is generic, but `c0..20` vary across 4 foil batches); `BBP corrected SCALE` if GDAC parity is desired.
* **Requires external:** **Yes** — via `FLBB serial → WMO → dedicated CSV` generic lookup (`resolve.doxy_cal_for_group`), **no WMO literal** in code. If the serial has no CSV row, `resolve_group["doxy"] is KeyError(DATA-COVERAGE)` (pinned for `03530/03580` via `test_doxy_data_coverage_for_serial_without_csv`; `12170` is the opposite pin that the lookup succeeds).
* **Evidence:** 13-WMO `provor_cts4_301_reference.csv` (88 generic / 30 specific) reproduces `2902086` `PhaseCoef0=0.0657959` etc. verbatim from `meta.nc`; the CSV carries `source_file=incois_<WMO>_meta.nc` provenance per row.

### D. Reference-bootstrap **dependence** (does the resolver *secretly* need the 13-WMO CSV even for B?)

* **Current implementation:** `resolve.chla_cal_from_flbb` and `bbp_cal_from_flbb` both read `family_generic[("CHLA","SCALE_CHLA")]` and `[("BBP700","khi")]` from the CSV-derived `ReferenceDB`. So **today** a missing CSV would break even `CHLA/BBP` — a hidden `D` dependence.
* **Is it fundamental?** **No.** `SCALE_CHLA=0.0073` and `khi=1.097` are **numerically identical across all 13 WMOs within 1e-12** (audit `test_reference_db_is_generic_family`) and are published constants (cookbook Table 1: `FLBB 142° χ=1.097`). They could be hard-coded (as they already are in `_FAMILY_GENERIC_COEFS`) and the `ReferenceDB` could lazily verify without being on the hot path. The same holds for `A0-5/B0-3/C0/D0-3/Pcoef1-3/Spreset/m0..27/n0..27/T4/5` (all generic).
* **What still needs the bootstrap even if hard-coded?** Only **verification** (that no new float introduces a different `khi`/`SCALE_CHLA`) and **DOXY float-specific** (C). So for a new float `+ telemetry + proper metadata (its `meta.nc` row)`:

  * **CTD/CHLA/BBP-tele** would work **without any pre-existing WMO** if the 88 generic constants were hard-coded (or if the bootstrap CSV contained at least one generic row — but not necessarily the new float’s row).
  * **DOXY** (and optionally BBP-corrected) **would require** adding the new float’s row to the dedicated CSV (or supplying its `meta.nc` directly) so that `flbb_serial_to_wmo[serial]` → `by_wmo[WMO]` succeeds. That is **not** “pre-existing WMO” in the sense of a closed list; it is **generic serial→metadata indirection** — the decoder is generic, the *metadata file* must grow.

* **Goal (“new float + telemetry + proper metadata works without pre-existing WMO”)** — **Met with caveat:**

  * If `proper metadata` means the new float’s `PREDEPLOYMENT_CALIB_COEFFICIENT` lines (the 118 values) are delivered as a `meta.nc` or as a `provor_cts4_301_reference.csv` row, then **yes** — `resolve_group(new_path, new_reference)` will succeed via the same generic path (frame→250→serial→new row), with no code change and no WMO branch. This is demonstrated by `12170`: it was “new” vs the original three, its `2663→2902086` was not hard-coded, and it worked.
  * If `proper metadata` means `meta.nc` is unavailable and the only evidence is the `250` `PC` echo, then **DOXY remains DATA-COVERAGE** (optode free zone is empty per NKE §7.2.4.9 — `Optode Data Free 50` = no Stern-Volmer coeffs in telemetry). That is a **specification limit**, not a decoder bug (§1.3 ledger). `CHLA/BBP-tele` still work.

* **Reference-bootstrap risk if not grown:** Shipping only the 13-row CSV would make any 14th INCOIS float (e.g. `2902130/2902131` for `03530/03580` already evidenced by Barnard) `DATA-COVERAGE` for `DOXY`. That is `EXPECTED` under the current prompt (no pre-existing-WMO fiction) and must be documented as `blocker` not failure. A follow-on phase could make the bootstrap **append-only** (the dedicated CSV is already allowed to grow; the four legacy schemas remain frozen).

* **Recommendation:** Keep `resolve.py`’s explicit `_FAMILY_GENERIC_COEFS` set as the *sole* source of the 88 values in a future “no-CSV” mode (with an assert that a supplied CSV, if any, matches it), so that `B` truly becomes CSV-independent. Do not add WMO branches; keep `flbb_serial_to_wmo` as indirection.

---

## 4. Ledger updates (per scientific principle)

* **BBP SCALE +1.2%** — moved from `FIXABLE: telemetry_reconstructable vs publication` (vague) to **`FIXABLE: telemetry (OriginalScaleFactor) vs publication (CorrectedScaleFactor) — PUBLICATION-REPROCESSED via doi:10.17882/54520`** with the `PREDEPLOYMENT_CALIB_COMMENT` provenance and the `8/8` matched-group corpus.
* **`03530/03580`** — remain `DATA-COVERAGE` under the 13-row dedicated CSV, but **not** `NOT_FIXABLE` inAbsolute — Barnard shows they are `2902130/2902131` with `Original 1.41/1.38 → Corrected 1.39/1.37`; ingest growth would close them (still frozen by prompt).
* **DOXY `+0.21` `PUBLICATION-RTQC`** — unchanged (INCOIS applies no `SCOR` but `DOXY` residual `gain ≈1.0017 offset +0.208` remains vs literal Stern-Volmer; garbage `L63-65` dropout still `EXPECTED`).
* `PT26/27`, `FLAG_SensorBoardStatus`, `253 rtc`, `03530` cycle-9 stab `0`, optode lead-u16 — still `UNKNOWN` (hypothesis `lead_u16 = serial` is double-match, not proven; `PT26/27` per-group pairs, no spec semantics).
* `gsw` fallback `1.025` — still `TOOL-AVAILABILITY` (≤0.5 µmol/kg `DOXY` noise, documented).

No `FIXABLE` was silently resolved; every `UNKNOWN` stays.

---

## 5. Evidence locations (reproducible)

* Telemetry: `provor_bio_irsbd/raw_telemetry/SBD-BGC-raw/{00530,03530,03580,06580,06640,12170,17960,20000,25980,29030}/`**`*.sbd` (517 + 63 for `12170` counted).
* Byte: `provor_bio_irsbd/ref/NKE_5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf` §7.2.4.9 p58 + `.txt`, `SHA256SUMS`.
* Cookbook: `provor_bio_irsbd/ref/cook_bbp.pdf` (v1.4, `doi:10.13155/39459` §2.2), `archimer.ifremer.fr/doc/00283/39459/56146.pdf`.
* SEANOE table: `https://www.seanoe.org/data/00434/54520/data/55891.csv` (local grep `incois;290…;FLBB2K;…;1.67E-06;1.65E-06` etc. + fetched `10.17882/54520` page).
* INCOIS GDAC: `provor_bio_irsbd/ref/gdac_incois_301/incois_29020*_meta.nc` (13) — `PREDEPLOYMENT_CALIB_COMMENT` contains `Reprocessed … Andrew Bernard … http://doi.org/10.17882/54520`; `PREDEPLOYMENT_CALIB_COEFFICIENT` carries `SCALE`/`DARK`/`khi`.
* Coriolis: `Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_soft/soft/util/decode_meas_cts4/sub_decode_meas_cts4/compute_profile_derived_parameters_ir_rudics.m` + `betasw_ZHH2009.m`, `_config/_tech_param_name_301.csv`.
* LFS bundle inspection: `/tmp/lfs_bundle.zip` (gdown `1C4Cl_AUH17_KMXS_5Cyk-VtKnSC7ey1f`, 15.1 MB, `unzip -l` 27 files APEX-only), `/tmp/lfs_extracted/LFS-documents-found/README.md`.
* Code: `src/argo_decoder/platforms/provor_cts4_ir_sbd/{framer,packets,cycles,ctd,params,tech,bgc,equations,assoc,labels_301,resolve}.py` (`resolve.py` 559 L, `parents[4]` fixed, `FlbbFree` narrowing, `no WMO literal` static test).
* Tests: `tests/test_provor_cts4_phase2b1_telemetry.py` (20), `tests/test_provor_cts4_phase2b1_followup.py` (7 new, `12170` + BBP systematic), `tests/unit/test_provor_cts4_phase1_units.py` (30), `tests/test_provor_cts4_phase1_telemetry.py` (23), `tests/unit/test_provor_cts4_phase2a_units.py` (27), `tests/test_provor_cts4_phase2a_telemetry.py` (16).
* Probe: `scripts/probe_cts4_phase2b1_gdac.py` (363 L) + manual `python -c` census for `12170` (see §1.2).

---

## 6. Gates and blockers

* Gates run: `pytest -k provor_cts4` (see `IMPLEMENTATION_PROGRESS`), `ruff check src/argo_decoder/platforms/provor_cts4_ir_sbd/resolve.py`, `mypy --strict src/argo_decoder/platforms/provor_cts4_ir_sbd/resolve.py` — all clean before edit, re-run as part of follow-up (see `IMPLEMENTATION_PROGRESS` tail).
* **Not moved to NetCDF/publication:** per prompt `STOP`, no `R/BD` or `ARVOR/APEX` edits, four legacy CSVs untouched, no silent `UNKNOWN` conversion, no fit/correction of BBP, new CTS4 CSV growth allowed but not performed (the dedicated `provor_cts4_301_reference.csv` already proves the appendix mechanism).
* **Remaining blockers for a future NetCDF phase:** `DATA-COVERAGE` for `03530/03580` if the 13-row CSV is not extended to include `2902130/2902131` (Barnard shows they exist); `PUBLICATION-REPROCESSED` delta will persist unless the Barnard table is ingested as an explicit step (if publication parity is the goal); `UNKNOWN` list above still needs spec semantics (`PT26/27`, `FLAG_SensorBoardStatus`); cycle-0 profile-dating bracketing model still `FIX CANDIDATE`; no WMO synthesis — output naming must remain suffix-only.

---

## 7. Recommendation for next phase (not implemented)

Proceed to **documentation-only** NetCDF planning: keep the generic decoder as-is, make the 88 generic constants CSV-independent (hard-code + audit), and treat the dedicated `provor_cts4_301_reference.csv` as an **append-only** INCOIS-provenance appendix. Ingesting the full `doi:10.17882/54520` table as an optional `--reprocessed` flag would let users choose telemetry truth (`Original`) vs GDAC truth (`Corrected`) for BBP; keep the default telemetry truth and document the `+1.2%` offset in the product `HISTORY`. Extend the appendix to include `2902130/2902131` so `03530/03580` close without a WMO hack. No schema change, no `ARVOR/APEX` touch.

