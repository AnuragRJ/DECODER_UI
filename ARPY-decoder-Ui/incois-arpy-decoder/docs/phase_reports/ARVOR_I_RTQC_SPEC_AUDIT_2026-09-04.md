# ARVOR-I RTQC Specification Audit — Official Manuals vs Project Implementation

**Date:** 2026-09-04 · **Step 0 of the RTQC authorization path — research & documentation only. No code, config or product was changed.**

**Floats in scope:** 1902844, 2904082, 6990711, 7902408 (ARVOR-I SBE41CP, Iridium SBD, ≤2000 dbar, core P/T/S only).
**Rule applied:** the Coriolis MATLAB implementation remains the scientific decoder reference; the official Argo manuals are authoritative for the *meaning and specification* of RTQC. Differences are documented, never silently changed.

---

## 1. Authoritative documents used (versions + URLs — for independent traceability)

| # | Document | Version / date | URL | Role here |
|---|---|---|---|---|
| D1 | **Argo Quality Control Manual for CTD and Trajectory Data** (Wong, Keeley, Carval, ADMT) | **Version 3.9, 20 Feb 2025** (current; DOI always resolves to latest) | https://doi.org/10.13155/33951 · PDF: https://archimer.ifremer.fr/doc/00228/33951/32470.pdf | Authoritative test list/numbering, thresholds, flag policy, application order |
| D2 | **Implementation of Argo real time quality controls by Coriolis data centre** (Rannou, Cabanes, Coatanoan, Lagadec, Thierry) | **v1.1, 17 May 2019** (describes Coriolis Matlab decoder **029a**, profile RTQC **4.1**, trajectory RTQC **2.5**) | https://doi.org/10.13155/49438 · PDF: https://archimer.ifremer.fr/doc/00383/49438/67595.pdf | What the Coriolis MATLAB (our science reference) actually implements |
| D3 | **Argo User's Manual** | current at DOI (format/flag reference tables) | https://doi.org/10.13155/29825 | Ref Table 2 (flag scale), 2a (profile flags), netCDF QC variables |
| D4 | Ref Table 2 / 2a official mirrors (older QC-manual copies, unchanged wording) | v2.7 (2017-12-01) / Coriolis copy (2004-11-23) | https://cdn.ioos.noaa.gov/media/2017/12/argo-quality-control-manual-v2.7.pdf · https://www.coriolis.eu.org/content/download/370/2828/file/argo-quality-control-manual.pdf · https://www.marine.csiro.au/argo/dmqc/user_doc/QC_flags.html | Verbatim flag-scale text (v3.9 appendix §6.1–6.2 is beyond the PDF fetch cap; wording unchanged since 2017 per D1's version history) |
| D5 | Argo DAC cookbook (Annex H — Test 20) | per DOI | https://doi.org/10.13155/29824 | Questionable-Argos-position test source |
| D6 | MEDD test Matlab package | per repo | https://github.com/ArgoRTQC/matlab_MEDD | Test 25 reference implementation |
| D7 | Argo BGC QC manual | v2.x current | https://doi.org/10.13155/40879 | Out of scope (core float) — cited only to bound scope |

**Fetch limitation (declared):** D1's PDF is 2-up (56 physical pages); the parser cap returned chapters 1–2.5 only. Appendix §6.1–6.3 (Ref Tables 2, 2a, 11) and §4 (trajectory RT) were cross-referenced through D2 (§4/§6), D4 verbatim mirrors, D1's own version-history notes, and the GDAC files themselves. Every such item is labelled below. **Which version the existing implementation targets: the repo's `rtqc/` modules cite "QC Manual v3.9" in-source (PROVEN by comment scan) — i.e. the current manual, not v3.3.**

---

## 2. Authoritative list and numbering of the real-time QC tests (D1 v3.9 §2.1.2–2.1.3 — PROVEN)

Core CTD tests on vertical profiles (test number *n* is permanent; ≠ application order):

| n | Test | Status in v3.9 |
|---|---|---|
| 1 | Platform identification | active |
| 2 | Impossible date (17167 ≤ JULD < date-of-check) | active |
| 3 | Impossible location (±90 / ±180) | active |
| 4 | Position on land (bathymetry lookup) | active |
| 5 | Impossible speed (3 m/s) | active (ARGOS floats may use test 20 instead) |
| 6 | Global range (PRES ≥ −5; [−5,−2.4]→'3'; TEMP −2.5..40; PSAL 2..41) | active |
| 7 | Regional range (Red Sea / Mediterranean only) | active, region-conditional |
| 8 | Pressure increasing (PRES_reversal = 20 dbar; middle-out; near-surface: deep-up) | active (formulation revised 07-Feb-2024, H. Bittig) |
| 9 | Spike (T 6.0/2.0 °C, S 0.9/0.3 psu at 500-dbar split) | active |
| 10 | Top/bottom spike | **obsolete (Oct 2003, ADMT4)** |
| 11 | Gradient | **declared obsolete (Oct 2019, ADMT20) — replaced by 25** |
| 12 | Digit rollover (ΔT > 10 °C, ΔS > 5 psu) | active |
| 13 | Stuck value (identical measurements → whole profile '4') | active |
| 14 | Density inversion (0.03 kg/m³, mid-point ref, both directions) | active |
| 15 | Supplemental sensor **exclusion list** test (ex-"grey list", renamed 20-Feb-2025) | active — DAC-managed mechanism |
| 16 | Gross salinity/temp sensor drift (deepest 100 dbar; ΔS > 0.5 psu, ΔT > 1 °C → '3') | active |
| 17 | Visual QC | **"not mandatory before real-time distribution"** |
| 18 | Frozen profile (50-dbar slabs; max/min/mean: T 0.3/0.001/0.02, S 0.3/0.001/0.004 → '4') | active |
| 19 | Deepest pressure (CONFIG_ProfilePressure + tolerance; ramp 150 %@10 dbar → 10 %@1000 dbar, +100 dbar above; '3') | active |
| 20 | Questionable Argos position (trajectory; D5 Annex H) | Argos-only |
| 21/22 | Near-surface unpumped salinity / mixed air-water | near-surface data only |
| 23 | Deep SBE CTD > 2000 dbar flag scheme | deep floats only |
| 24 | RBR-argo³|2K scheme | RBR only |
| 25 | MEDD (median-with-distance) | active — replaces 11 in the v3.9 application order |
| 26 | TEMP_CNDC scheme | RBR only |
| 57–63 | BGC-specific (DOXY, CDOM, NITRATE, PAR, IRRADIANCE, BBP, CHLA) | **Coriolis' own numbering** (D2); BGC manual governs |

**v3.9 application order (§2.1.3, verbatim rows):** 1, 2, 3, 4, 5, **15**, **19**, 6, 7, 8, 9, **25**, 12, 13, 14, 16, 18, 23, 26, 24, **17** — with the policy note: a flag '4' from a test is *ignored* by later tests; '2'/'3' are still tested. **Coriolis's order (D2 §2.2):** 19 first, then 1,2,3,4,5,6,7,8,9,11,12,13,14,15; **16 and 18 "not used"** (Coriolis decided not to apply them — designed for fixed-pressure / fixed-cycle floats, "not for Iridium floats with a mission that can be modified at sea"); trajectory order (D2 §4.2): 1,2,3,4,**20**,6,7,15.

## 3. The ten required findings

1. **Authoritative list/numbering** — §2 above (D1 §2.1.2–2.1.3). Test numbers are permanent identifiers used to fill `HISTORY_QCTEST` (D1 §2.1.3 note; Ref Table 11 lists the binary IDs — appendix, not directly parsed, labelled).
2. **Mandatory vs optional** — D1 marks only **17 (visual QC) as "not mandatory"** and describes **15 as a DAC-managed list mechanism**; 20/21/22/23/24/26 are conditional (platform/sensor/data-type); the core 1–14, 16, 18, 19 carry no optional label — the §2.1.1 framing is that the applicable set is applied automatically by DACs within 12–24 h. Coriolis additionally opts **out** of 16/18 (D2) — a DAC decision, not a manual exemption.
3. **Applicable to a core P/T/S ARVOR-I SBE41CP** — **1, 2, 3, 4, 5, 6, 8, 9, 11(→25), 12, 13, 14, 16, 18, 19** = automatic set; **7 vacuous** (none of the four floats operates in the Red Sea/Mediterranean); **15** exists but is DAC-side (empty list ⇒ no-op); **17** human; **20 N/A** (Iridium); **21/22 N/A** (no near-surface sampling scheme in these floats — primary sampling only); **23 N/A** (2000-dbar class, not >2000 dbar); **24/26 N/A** (SBE, not RBR); **57–63 N/A** (no BGC sensors).
4. **Is the applicable set 14? — No. It is 15 automatic tests** (the list in item 3; 14 + test 19). The earlier "14" statement in the parity report §16 undercounted by omitting **test 19 (deepest pressure)**; §16 has been corrected in step. **Direct proof from our own reference files:** every GDAC mono file examined carries a `QCP$` history row with mask **`D7B7E`** — which decodes (project mapping, validated in earlier phases against INCOIS's published files) to **tests 1–6, 8, 9, 11–14, 16, 18, 19 = 15 tests** (cycle 1: `C7B7E`, same minus 16 — no previous profile). Verified live in `1902844/6990711/7902408` mono files; the engine set matches INCOIS's practice exactly (PROVEN).
5. **GEBCO/bathymetry test** — **Test 4.** D1: *"Use can be made of any topography/bathymetry file that allows an automatic test… We suggest the use of at least the 5-minute bathymetry file… ETOPO5/TerrainBase"* (https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ngdc.mgg.dem:3141) — **no dataset/version is mandated**. Coriolis 2019 used **ETOPO2v2g_i2_MSB.bin** (D2 §2.1.4); the current Coriolis MATLAB the repo mirrors uses a **GEBCO netCDF grid** (`get_gebco_elev_zone.m`; elevation positive-up, land = elevation ≥ 0). The repo accepts any GEBCO-shaped grid (`elevation/z/Band1` aliases), version-agnostic — **no manual conflict**; a grid must be supplied locally to run the test (absent in sandbox ⇒ test skipped and *not reported* as performed).
6. **Other external reference datasets** — Test 7 needs no dataset (regions defined in manual text; Coriolis hard-codes 5 rectangles/sea). Test 15 needs the DAC exclusion-list CSV (`<dac>_exclusionlist.csv`, e.g. `coriolis_exclusionlist.csv`; repo default `ar_exclusionlist.txt` — naming differs, our-implementation origin). Test 25 references the MEDD Matlab package (D6). **WOA13 (`woa13_all_n00_01.nc`) and `SLOPE_RT_2024.txt` in our config are BGC-RTQC references (DOXY climatology / CHLA slope) — not required for any core test** (origin: docker operational config parity).
7. **QC flag meanings (Ref Table 2, D3/D4)** — `0` no QC was performed; `1` good data (RT comment: *all Argo real-time QC tests passed*); `2` probably good data; `3` bad but potentially correctable (RT: not to be used without scientific correction); `4` bad data; `5` value changed; `8` **estimated** (changed from "interpolated" 08-Dec-2017 per D1 history; older mirrors still read "interpolated"); `9` missing value.
8. **PROFILE_*_QC (Ref Table 2a, D3/D4)** — `' '` no QC was performed; `A` N=100 % all profile levels good; `B` 75≤N<100; `C` 50≤N<75; `D` 25≤N<50; `E` 0<N<25; `F` N=0 % all bad. N = percentage of good levels (flags 1, 2, 5, 8 good; 9 not used; computed from `_ADJUSTED_QC` if available else `_QC`). **GDAC's 'A' on our files therefore means "RTQC applied, 100 % of levels good"** — not merely "applied". Our blank = "no QC performed", consistent with flag '0' per-level.
9. **HISTORY_QCTEST** — D1 §2.1.3: the permanent **test number (n)** is what fills `HISTORY_QCTEST` (Ref Table 11 binary IDs). D2 §6: passed/failed test lists are reported through `HISTORY_QCTEST`; in Coriolis C-files the reported tests are 1–9, 11–15, 19, 20, 21, 22, 23 (not BGC). Live GDAC convention (our refs): a history row `ACTION='QCP$'`, `QCTEST='<hex mask>'` where mask bits encode the test numbers performed (`D7B7E`); failure masks reported likewise. Our writer mirrors this (`rtqc_tests_done_hex`/`rtqc_tests_failed_hex` → `QCP$`/`QCF$` rows) and only writes a mask when tests genuinely ran — blank otherwise (truthful "no QC performed").
10. **What QC operates on** — the **decoded products at the DAC**: single-cycle R profile files and trajectory files (D1 §2.1.1: automatic checks on netCDF files forwarded to GDACs; D2: inside the Coriolis Matlab chain that *produces* the Argo V3.1 netCDFs). Trajectory profile-measurement rows duplicate the **profile QC flags** (deepest points as MC 203/503; dated levels as MC 190/590 — D2 §4.3), which is why GDAC Rtraj science rows carry '1's. **Our equivalent surfaces: the mono `R*.nc` profiles (primary) and the Rtraj duplicated rows.** Nothing in the manuals asks for QC on raw telemetry/intermediate representations.

## 4. Master cross-check table

"Engine" = `src/argo_decoder/rtqc/` as wired into the **APEX-Argos** path (`apply_rtqc`, default off). "ARVOR-I chain executes" = **no** for every test today (no RTQC invocation in `ArvorISbdDecoder`).

| Official test (v3.9 n) | Project implementation | ARVOR-I applicable? | Reference dataset | Engine runs (APEX wiring) | ARVOR-I chain | GDAC relevance |
|---|---|---|---|---|---|---|
| 1 Platform ident. | `profile_scalar` TEST001 (decoder-table membership; always passes in practice) | yes | — | yes | **no** | in `D7B7E` (reported; Coriolis reports "always passed") |
| 2 Impossible date | `profile_scalar` TEST002 (17167 ≤ JULD < now_utc) — manual-exact | yes | — | yes | **no** | in `D7B7E`; explains GDAC JULD_QC='1' |
| 3 Impossible location | `profile_scalar` TEST003 (±90/±180) — manual-exact | yes | — | yes | **no** | in `D7B7E`; POSITION_QC='1' |
| 4 Position on land | `bathymetry` GEBCO window lookup; skips (logged) when grid absent | yes | GEBCO netCDF (manual: *any* bathy, ETOPO5 suggested; Coriolis 2019: ETOPO2) | yes if grid present | **no** | in `D7B7E` (bit 4) — INCOIS runs it |
| 5 Impossible speed | `cross_cycle` TEST005 (3 m/s) — manual-exact | yes | — | yes (2nd pass) | **no** | in `D7B7E` |
| 6 Global range | `non_density` TEST006 — **differences, §5** | yes | — | yes | **no** | in `D7B7E` |
| 7 Regional range | **not implemented** (config flag only) | vacuous (floats outside Med/Red Sea) | region defs in manual | no | **no** | **not in `D7B7E`** (INCOIS doesn't apply it to these floats) |
| 8 Pressure increasing | `non_density` TEST008 — **2 dbar vs manual's 2024 20-dbar formulation, §5** | yes | — | yes | **no** | in `D7B7E` |
| 9 Spike | `non_density` TEST009 — **MATLAB median-window form + single thresholds, §5** | yes | — | yes | **no** | in `D7B7E` |
| 10 Top/bottom spike | — (obsolete 2003) | no | — | — | **no** | — |
| 11 Gradient | `non_density` TEST011 (flag-gated) — **thresholds/normalization differ, §5** | yes (legacy; v3.9 replaces with 25) | — | yes | **no** | in `D7B7E` (INCOIS still runs 11) |
| 12 Digit rollover | `non_density` TEST012 (ΔT>10 °C, ΔS>5 psu; MATLAB '4'+rest-'3' policy) | yes | — | yes | **no** | in `D7B7E` |
| 13 Stuck value | `non_density` TEST013 (whole-profile identical → '4') — manual-exact | yes | — | yes | **no** | in `D7B7E` |
| 14 Density inversion | `density_inversion` TEST014 (0.03 kg/m³, mid-point, both directions, TEOS-10) — manual-exact | yes | — | yes | **no** | in `D7B7E` |
| 15 Exclusion list | **not implemented** (config flag + `ar_exclusionlist.txt` default only) | mechanism exists, empty ⇒ no-op | DAC exclusion CSV | no | **no** | **not in `D7B7E`** (no listed parameters for these floats) |
| 16 Gross sensor drift | `cross_cycle` TEST016 (100 dbar, 0.5 psu / 1 °C, previous-*good* profile) — manual-exact | yes | — | yes | **no** | in `D7B7E` (cycles ≥2) — **INCOIS applies it though Coriolis's 2019 doc says "not used"** |
| 17 Visual QC | — (human test by design) | n/a (not mandatory) | — | — | **no** | not representable in files |
| 18 Frozen profile | `cross_cycle` TEST018 (50-dbar slabs; 0.3/0.001/0.02 °C; 0.3/0.001/0.004 psu) — manual-exact | yes | — | yes | **no** | in `D7B7E` — same INCOIS-vs-Coriolis-2019 note as 16 |
| 19 Deepest pressure | `non_density` TEST019 — max(10 %, 100 dbar); **no shallow ramp, §5** | yes | CONFIG_ProfilePressure from meta | yes | **no** | in `D7B7E` |
| 20 Questionable Argos pos. | **not implemented** | no (Iridium) | D5 Annex H | no | **no** | not in `D7B7E` (N/A) |
| 21/22 Near-surface | **not implemented** (config flags only) | no (no near-surface scheme) | — | no | **no** | not in `D7B7E` |
| 23 Deep SBE scheme | **not implemented** (config flag only) | no (≤2000 dbar) | — | no | **no** | not in `D7B7E` |
| 24/26 RBR schemes | **not implemented** (config flags only) | no (SBE) | — | no | **no** | not in `D7B7E` |
| 25 MEDD | **not implemented** (config flag only) | replacement for 11 per v3.9 | MEDD package (D6) | no | **no** | not in `D7B7E` (INCOIS runs legacy 11) |
| 57–63 BGC | not implemented (config flags echo docker parity) | no (no BGC) | BGC refs (WOA13 etc.) | no | **no** | not in `D7B7E` |

Config note: `RtqcTestFlags` (32 flags, 27 on) mirrors the operational docker config; only 6 flags actually gate engine code (`global_range`, `pressure_increasing`, `spike`, `gradient`, `digit_rollover`, `deepest_pressure`); the remainder are accepted-but-unwired knobs (documented, unchanged).

## 5. Differences between repo engine and official manual (documented — NOT changed)

| # | Item | Repo (engine) | Manual v3.9 | Coriolis (D2/docstring) | Origin / disposition |
|---|---|---|---|---|---|
| 5.1 | Test 6 TEMP upper | **42.0 °C** | 40.0 °C | 40.0 °C (2019 doc) | Coriolis MATLAB source ("deep Arvor" variant) — exceeds even Coriolis's own doc; **reconcile at wiring time** |
| 5.2 | Test 6 PRES upper | 12000 dbar | none stated (lower bound only) | none stated | our/Coriolis deep headroom — benign, document |
| 5.3 | Test 6 CNDC range | (0, 8.5 S/m) | not in CTD manual (BGC-adjacent) | — | extra coverage; harmless for PSAL floats |
| 5.4 | Test 8 tolerance | **2.0 dbar** inversion tolerance | **20 dbar PRES_reversal** (formulation revised 07-Feb-2024) | (older doc silent; MATLAB 2 dbar) | **manual changed after the Coriolis code was frozen** — code is older-Arigo/Coriolis spec; flag for decision |
| 5.5 | Test 9 algorithm + thresholds | `|v − median(window)|` with **T 6.0, S 0.5** single thresholds | `|V2−(V3+V1)/2|−|(V3−V1)/2|` with **T 6.0/2.0, S 0.9/0.3** at 500 dbar | MATLAB median-window form | Coriolis MATLAB origin (matches INCOIS practice via D7B7E bit 9) |
| 5.6 | Test 11 thresholds/normalisation | T 9.0, S 1.0 **per dbar** | T 9.0/3.0, S 1.5/0.5 per adjacent pair (obsolete test) | MATLAB per-dbar form | Coriolis MATLAB origin; test itself obsolete since 2019 |
| 5.7 | Test 19 tolerance schedule | `max(10 %, 100 dbar)` | ramp 150 %→10 % over 10–1000 dbar, then **flat +100 dbar above 1000** (revised 10-Jan-2022) | ramp below 1000 dbar and **10 % above 1000 dbar** (`add_rtqc_to_profile_file.m` V4.1 note + `nc_get_rtqc_deepest_pres_test.m`) | **CORRECTED 2026-09-04 (step-1 audit): repo = current MATLAB (10 % ⇒ 2200 dbar at CONFIG 2000); the v3.9 manual (flat 100 ⇒ 2100) is the outlier** after its 2022 revision. Supersedes this report's original claim that repo "matches the manual ≥ 1000 dbar". Keep Coriolis behavior (scientific reference + INCOIS practice); document manual divergence |
| 5.8 | Test 19 unknown config | returns all-good, invents no limit | manual assumes meta value present | — | our no-fabrication doctrine; matches "truthful mask" rule |
| 5.9 | Test 1 semantics | actively validated (decoder-table membership) | correspondence WMO↔PTT | Coriolis: nothing implemented, "always passed" | ours stricter than Coriolis; no conflict |
| 5.10 | Tests 16/18 enabled | implemented | manual active | **Coriolis opted out** (2019) | INCOIS (our GDAC) **runs both** (in `D7B7E`) — engine matches INCOIS, not Coriolis-2019; Coriolis may have re-enabled later (UNKNOWN) |
| 5.11 | Tests 7/15/20/21/22/23/24/25/26/57+ | not implemented | active/conditional | Coriolis implements 7, 15, 20, 21, 22 (+BGC) | coverage gap vs Coriolis; **none affects this fleet's parity** (7 vacuous; 15 empty; 20 Argos; 21/22/23/24 no data; 25 superseded-by-practice 11; BGC absent) |
| 5.12 | Exclusion-list filename | `ar_exclusionlist.txt` | `<dac>_exclusionlist.csv` | **`ar_exclusionlist.txt`** (`nc_add_rtqc_flags_prof_and_traj.m`) | **CORRECTED 2026-09-04 (step-1 audit): the repo default is Coriolis-faithful verbatim**; the manual's `<dac>_exclusionlist.csv` convention is the different one. No change needed |

## 6. GDAC-side evidence for our four floats (live files, PROVEN)

* Mono files: per-level `*_QC='1'`, `PROFILE_*_QC='A'` (Table 2a: 100 % good levels), `HISTORY` row `QCP$ / D7B7E` → the 15-test set ran and passed. Our files: '0'/blank/blank — truthful pre-RTQC state, exactly the semantics gap the parity report §7 records (PUBLICATION/RTQC class).
* Rtraj: JULD/POSITION QC carry the RTQC results; profile-measurement rows inherit the profile flags (D2 §4.3) — consistent with the GDAC-only '0'/'1' patterns in the Rtraj comparison.
* `D7B7E` verified in the mono files of 1902844, 6990711, 7902408 (2904082 not re-opened this pass; identical generator, expected same — INFERRED).

## 7. Preconditions before any RTQC enablement for ARVOR-I (no change made)

1. Supply a bathymetry grid locally (GEBCO-shaped netCDF; sandbox has none) — else test 4 must be skipped and *omitted from the mask*, exactly as the engine already handles it.
2. Resolve the §5 threshold reconciliations (5.1, 5.4, 5.5 at minimum) — Coriolis-MATLAB fidelity vs v3.9-2024 text is a scientific decision, not a mechanical patch.
3. Decide 11 vs 25 (INCOIS practice: 11) and whether 16/18 stay enabled (INCOIS: yes).
4. Wire the engine into the ARVOR-I chain + QCP$-truthful masks + validators — all under explicit authorization only.

**STOP — diagnosis and documentation only. Nothing in `src/`, `config/`, tests or products was modified by this audit.**

*Sources: D1–D6 as listed in §1 (all URLs exact, fetched 2026-09-04). Engine facts from source scan of `src/argo_decoder/rtqc/`, `config/models.py`, `platforms/apex_argos/decoder.py`; GDAC facts from `../gdac_arvor_i_ref/` files.*

---

# Step-1 Addendum (2026-09-04, later session) — gap analysis, QCP$ decode, harness, integration plan

Research/audit + standalone harness only. **No production code changed; RTQC still NOT enabled for ARVOR-I.** New evidence base: the **current Coriolis MATLAB chain vendored in-workspace** (`Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_soft`, incl. `nc_add_rtqc_flags_prof_and_traj.m`, `get_qctest_flag.m`, `nc_get_rtqc_deepest_pres_test.m`, `get_gebco_elev_zone.m`, GEBCO_2024 path) and the engine file `tests/data/arvor_i/coriolis_src/add_rtqc_to_profile_file.m` (mirror of chain 20250516_076a). Artifacts: `validation_rtqc_harness/` (per-float RTQC reports, GDAC mask oracle, fleet summary).

## 8. GDAC QCP$/QCF$ masks — rigorous decode, all four floats directly (no inference)

Method: every mono file's `HISTORY_ACTION`/`HISTORY_QCTEST` rows; mask semantics from Coriolis' own `get_qctest_flag.m` (hex → 4-bit groups → reverse → drop first bit → position n = Test n), i.e. **bit n of the integer = test n**; identical to the repo writer's `_encode_mask`. Machine-readable: `validation_rtqc_harness/gdac_qcp_masks.json`.

| WMO | files | QCP$ (all cycles) | decoded executed set | cycles with non-zero QCF$ (failed tests) |
|---|---|---|---|---|
| 1902844 | 23 | `D7B7E` | 1,2,3,4,5,6,8,9,11,12,13,14,16,18,19 | c6→{14}; c9,c13,c18→{11,12} |
| 2904082 | 24 | `D7B7E` | same 15 | c1→{5}; c9→{11}; c12→{11,12}; c21→{14} |
| 6990711 | 7 | `D7B7E` | same 15 | c7→{5} |
| 7902408 | 16 | `D7B7E` | same 15 | c11→{11} |

**Independent confirmation of the 15-test set**: `D7B7E` is invariant across all 70 files of all four floats; bits 7, 10, 15, 17, 20+ are clear (INCOIS does not execute 7/15/20 for this fleet). INCOIS's RTQC is *not* a no-op: 10 cycles carry real failures, and the failing levels are visible in-file as QC '3'/'4' + `PROFILE_*_QC='B'` (e.g. 1902844 c6: one TEMP/PSAL level '3' from test 14 — note INCOIS flags test-14 failures **'3'**, not the manual's '4').

## 9. Per-test implementation-gap audit (the 15 applicable tests)

"complete" = engine code exists AND semantics match official spec ∩ current MATLAB ∩ INCOIS practice. A config flag is never counted as an implementation.

| # | Official spec (v3.9) | Current Python (`rtqc/`) | Coriolis MATLAB (current) | INCOIS/GDAC evidence | applic. | complete? | required change |
|---|---|---|---|---|---|---|---|
| 1 | WMO↔platform correspondence; else no GTS | `profile_scalar` — decoder-table membership, always-pass in practice | "nothing implemented; always reported passed" (D2) | bit 1 in D7B7E | yes | **yes** | none |
| 2 | 17167 ≤ JULD < check date; fail → JULD_QC '4' | exact (Argo epoch + now-UTC bound) | same (D2 §2.1.2) | bit 2; JULD_QC='1' | yes | **yes** | none |
| 3 | ±90/±180; fail → POSITION_QC '4' | exact | same | bit 3 | yes | **yes** | none |
| 4 | ocean position; **any** bathy file (≥5-min suggested, ETOPO5 URL) | GEBCO window lookup; **skips honestly when grid absent** | `GEBCO_2024.nc` via `get_gebco_elev_zone.m` (2019: ETOPO2v2g) | bit 4 (ran at INCOIS) | yes | **yes** (needs local grid) | none in code; supply GEBCO grid for local runs |
| 5 | ≤3 m/s between surface fixes; else flag both endpoints | cross-cycle great-circle 3.0 m/s, both-endpoint doctrine, mono-to-mono | implemented in current driver (D2 2019: replaced by test 20 for Argos) | bit 5; **real failures** (2904082 c1, 6990711 c7 — anchored vs trajectory/launch rows) | yes | **partial** | anchor cycle-1 leg vs launch position (4 CSVs); optionally trajectory-row anchoring |
| 6 | PRES ≥ −5 ([−5,−2.4]→'3'); TEMP −2.5..**40**; PSAL 2..41 | TEMP max **42**; PRES −5..12000; CNDC extra; **non-finite levels escalated to BAD** | TEMP {−2.5, **40**} verbatim; PRES branch with '3' band; tests **defined values only** (`idNoDef`) | bit 6; no failures | yes | **partial — 2 deviations** | TEMP 42→**40**; fills → "not tested" (leave fill) instead of BAD |
| 8 | PRES_reversal **20 dbar**, middle-out (2024 revision) | tolerance **2.0 dbar**, middle-out | **`PRES_REVERSAL = 20`** (updated) | bit 8; passed | yes | **partial — stale tolerance** | 2 → **20 dbar** |
| 9 | triplicate form, T 6/2, S 0.9/0.3 @500-dbar split | median-window form, single T 6.0 / **S 0.5** | **triplicate + {6}{2}/{0.9}{0.3} split** (verbatim) | bit 9; passed | yes | **partial — form + thresholds** | adopt manual/MATLAB form + split thresholds |
| 11 | obsolete (ADMT-20) — replaced by 25 | per-dbar thresholds (T 9, S 1) | **removed for core at v4.5 (2020), DOXY-only; MEDD on** | **INCOIS runs 11 on core** (bit set; failures on 5 cycles) | yes (INCOIS practice) | **partial** | keep 11 (GDAC parity), align form to manual gradient (¦V2−(V1+V3)/2¦) + split thresholds; 25 optional later |
| 12 | ΔT > 10, ΔS > 5 → '4' | exact incl. Coriolis '4' + rest-'3' policy | same (test12 lists {10}/{5}) | bit 12; failures — **cycle-exact match with our engine** (§11) | yes | **yes** | none |
| 13 | identical T/S values → whole profile '4' | whole-profile constant detection | same; needs meta file else skip | bit 13 | yes | **yes** | none |
| 14 | 0.03 kg/m³ mid-point, both directions → '4' | TEOS-10 exact, both directions | 0.03 verbatim | bit 14; failures c6/c21 flagged **'3'** — our engine passed those cycles | yes | **yes (spec-exact)** | none code-wise; log GDAC '3'-severity + our non-detection of those 2 events as a parity-investigation item |
| 16 | deepest-100-dbar mean vs prev good; ΔS > 0.5 / ΔT > 1 → '3' | exact + previous-good doctrine | implemented but **DISABLED ({0})** in current driver | **INCOIS runs it** (bit 16; absent cycle 1 = C7B7E) | yes (INCOIS) | **yes** | none; investigate our c15 flag on 7902408 (§11) |
| 18 | 50-dbar slabs; max/min/mean (T .3/.001/.02, S .3/.001/.004) → '4' | exact thresholds | implemented but **DISABLED ({0})** | INCOIS runs it | yes (INCOIS) | **yes** | none |
| 19 | ramp 150 %→10 % (10→1000 dbar); **flat +100 above** (2022 rev.) | `max(10 %, 100)` — **= current MATLAB above 1000 dbar** | 10 % above 1000 (V4.1 note) + ramp below; skips w/o meta value | bit 19; passed | yes | **yes (Coriolis semantics)** | none (documented manual divergence; CONFIG=2000 ⇒ 2200 vs manual 2100) |
| 7/15/20 | — | not implemented (flags unwired) | implemented (7, 15, 20) | **not executed by INCOIS** (bits clear in D7B7E) | n/a | n/a (correctly absent) | none required for parity; optional future 7/15 wiring |

Engine inventory beyond the 15: MEDD (25) present in MATLAB only; tests 21–26/56–63 conditional, unwired in the repo (correct for this fleet).

## 10. Specification conflicts — resolved on current-source evidence (decisions pending authorization)

1. **Test 8 (2 vs 20 dbar):** current MATLAB `PRES_REVERSAL = 20` + manual 2024 revision agree ⇒ repo's 2 dbar is stale. *Resolution: adopt 20 dbar.*
2. **Test 9 (form/thresholds):** current MATLAB = manual triplicate + {6,2}/{0.9,0.3} split ⇒ repo's median-window single-threshold form is the legacy outlier. *Resolution: adopt manual/MATLAB form.*
3. **Test 11 vs 25:** v3.9 declares 11 obsolete (→25); current Coriolis removed 11 for core and runs 25; **INCOIS still runs 11 and fails it on real cycles**. *Resolution: keep 11 for GDAC parity; 25 remains optional/flag-gated.*
4. **Tests 16/18:** Coriolis 2019 said "not used" and the current driver still sets {0}; INCOIS demonstrably runs both. *Resolution: keep enabled (engine already matches the manual); note the Coriolis-disable as reference-chain divergence.*
5. **Test 19 (tolerance):** current MATLAB and repo use 10 % above 1000 dbar; the manual's 2022 revision says flat +100 dbar. *Resolution: keep Coriolis behavior (scientific decoder reference + INCOIS practice); document manual divergence.* (Corrects this report's §5.7 — see correction note there.)
6. **Test 6 (new, from harness evidence):** repo TEMP max 42 and fill→BAD escalation both deviate from manual **and** current MATLAB (40; defined-values-only). *Resolution: 42→40; fills not tested.* (Exclusion-list filename §5.12 corrected — repo is Coriolis-faithful.)

## 11. RTQC execution harness — built and run (`scripts/rtqc_harness.py`)

Semantics: every test × cycle gets exactly one of executed→passed/failed or skipped+reason; **skipped is never counted as passed**; inputs, reference data and engine config recorded; truthful `QCP$`/`QCF$` masks per cycle (bit n = test n); optional side-by-side vs the GDAC oracle. Generic: WMOs from CLI, launch + config from the four CSVs / decoded products, raw from configurable roots; **no WMO-specific logic, no registry dependency**. Products decoded to /tmp through the validated pipeline.

Fleet run (sandbox, no GEBCO ⇒ test 4 skipped everywhere — the single reason our QCP$ ≠ D7B7E today):

| Float | profiles | all-pass tests | failures (cycle → tests) | notable skips |
|---|---|---|---|---|
| 1902844 | 23 | 1,2,3,6,8,9,11,13,14,16,18,19 | c9,c13,c18 → **12** (2 levels each) | c1: 5/16/18 (no previous); test-4 ×23 |
| 2904082 | 24 | same set | c12 → **12** | c1: 5/16/18; c21: 16/18 (overlap) |
| 6990711 | 7 | 1,2,3,12,14,16,18,19 | c6 → 6,8,9,11,13 (all driven by **one PRES fill level**) | c7: 5 (equal-timestamps leg) |
| 7902408 | 15 | 1,2,3,5,6,8,9,11,12,13,14,18,19 | c15 → **16** (73 levels) | c1: 5/16/18 |

**Oracle convergence (vs §8 GDAC QCF$):** our test-12 failures land on **exactly** INCOIS's 11+12 cycles (1902844: 9/13/18; 2904082: 12) — same physical events detected. Divergences, all classified: (i) 6990711 c6 failures are the engine's fill→BAD escalation of a single PRES fill (GDAC has the same fill and passes — MATLAB tests defined values only; engine deviation §10.6); (ii) 7902408 c15 test-16 flag where INCOIS passed — engine deep-band/slab semantics to investigate before integration; (iii) cycle-1 test-5: INCOIS anchors against the launch/trajectory row (their c1 fails on 2904082), our mono-to-mono harness skips the first leg — the integration design must decide the anchor; (iv) GDAC's 11-only (2904082 c9) and 14 (c6/c21) events not flagged by our engine — smaller-amplitude events below the engine's current 11-normalization/14 thresholds; flagged as parity-investigation items, not defects.

## 12. Reference-data requirements (exact; nothing substituted, nothing fabricated)

| Test | Dataset | Why | Supply |
|---|---|---|---|
| 4 | **GEBCO global grid netCDF** — current Coriolis uses `GEBCO_2024.nc` (elevation positive-up; `elevation/z/Band1` aliases accepted). Manual allows any bathymetry ≥ ETOPO5-class | only external dataset any of the 15 tests needs | local run: `--gebco /path/gebco.nc` (harness) or `rtqc.reference_files.gebco_file` / `TEST004_GEBCO_FILE=/mnt/ref/gebco.nc` (decoder config). **Absent in sandbox — test skipped, never fabricated** |
| 19 | none (CONFIG_ProfilePressure_dbar, from decoded `_meta.nc` / config sheet) | | already wired generically |
| 7/15/20+ | none applicable (region text in manual; DAC list; Argos-only) | | not needed for this fleet |

WOA13 (`woa13_all_n00_01.nc`) and `SLOPE_RT_2024.txt` remain BGC-RTQC references only — not required for the 15-test core suite.

## 13. Recommended minimal implementation plan (NOT implemented — for authorization)

Target chain (unchanged products before the RTQC stage):

```
4 CSVs → ARVOR-I decode (validated, pre-RTQC baseline preserved)
       → RTQC stage (opt-in): 15 tests → truthful QC flags + QCP$/QCF$
       → final RT-QC products
```

1. **Threshold/semantics fixes in `rtqc/`** (3 small, generic, test-covered changes): test 6 TEMP 42→40 + fill→"not tested"; test 8 tolerance 2→20 dbar; test 9 → manual triplicate form + {6,2}/{0.9,0.3} split. (Test 11 form likewise if 11 is retained as parity target.)
2. **Investigations before wiring** (not code): 7902408 c15 test-16 flag vs INCOIS pass; GDAC '3'-severity on test 14; cycle-1 test-5 anchoring (recommend: anchor vs launch position from the 4 CSVs — matches INCOIS behavior, stays generic).
3. **Wire the existing engine into the ARVOR-I chain** behind `apply_rtqc` (default False — baseline products unchanged), reusing the APEX pattern: per-profile pass + `cross_cycle_pass` second pass; masks via existing `_encode_mask`; `mono_profile.py` already emits QCP$/QCF$ only when tests ran.
4. **No new tests to write** for the 15-set: 13/15 already complete; 7/15/20 stay unexecuted (INCOIS parity); MEDD (25) explicitly out of scope unless later authorized.
5. **Local full-fleet run** with `GEBCO_2024.nc` mounted (per §12) — expected result: QCP$ = D7B7E on all cycles ≥ 2 (cycle-1 per the anchoring decision) and QCF$ matching §8 except the classified items.
6. **Validation additions:** harness becomes a pytest-covered module; ARVOR-I validators extended with RTQC-on/RTQC-off golden checks; FileChecker re-run on RT products.

## 14. Validation status of this step

pytest **2,050 passed** (no source change; suite proves no regression) · ruff check + format clean (165 files, incl. the new `scripts/rtqc_harness.py`) · artifacts: `validation_rtqc_harness/{gdac_qcp_masks,fleet_summary,<wmo>_rtqc}.json` (5 files, preserved) · /tmp regenerables cleaned. **STOP — no production change; no RTQC enablement. Fixes await authorization per §13.**
