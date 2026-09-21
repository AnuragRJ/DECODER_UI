# CTS4 BGC support in decoder-ui — phase report (2026-09-16)

Continues `CTS4_SERVICE_INTEGRATION_REPORT.md` §H (items H.1–H.3, H.7).
Commit: `8bf3455` in `/home/user/incois-arpy-decoder` (also re-creates the
pre-restore tree whose commit hash was lost when the turn-end snapshot
failed). Server left running on :8000 with the rebuilt frontend.

Standing constraints honored: `src/argo_decoder/` untouched, no G2/G3
backend fix, no concurrency guard, no BGC invention of any kind (no
hardcoded params/units/scales, all-fill channels never plotted).

## A. Service: N_PROF-aware BR reader (`service/bgc_reader.py`, new)

`read_br_file()` parses one `BR<wmo>_<cyc>.nc` profile-by-profile: own
`STATION_PARAMETERS`, pressure grid, per-parameter series with level QC,
plus the file's own `units`/`long_name` per channel. Rules:

- Fill → `None`; values never rounded (BGC spans 1e-7…1e2).
- Masked QC element → `"9"` (missing); a wholly absent `<PARAM>_QC`
  variable → `"0"` (not assessed — the true statement).
- Core `PRES/TEMP/PSAL` excluded from sensor channels by rule (never by name
  list of BGC params, so future channels can't be mislabeled).
- Returns the file header too (cycle, lat/lon, JULD, POSITION_QC).

Unit-verified on real files: healthy `BR2902130_001.nc` (N_PROF=4, DOXY
prof 428 pts + FL prof 535 pts, units `micromole/kg`, `mg/m3`, `m-1`,
`degree`, `count`, …) and G2 `BR2902086_103.nc` (N_PROF=3, prof2
all-fill, header recovered: 13.7035/86.5382, JULD 23447.1514).

## B. Cycle integration (`cts4_runner.py`, `models.py`)

- `CycleRecord` gains `bgc_profiles: list[BgcProfile]`, `bgc_source_file`,
  `bgc_n_prof`, `matches_g2_signature`, `has_core` — all defaulted, so
  legacy cycles and old run JSONs are unaffected.
- Every R cycle gets its matching BR attached; cycles are sorted by number.
- **BR-only cycles** (BR exists, no R) become honest records
  (`has_core=False`, `levels_count=0`, empty `ctd_samples`, real
  position/time) instead of `GET /cycles/103 → 404`.
- Verification event now reports R/BR/BGC-only counts; shared `_qc_char`
  moved into `bgc_reader.py` (single definition).

## C. G2 flagging (observational only)

`matches_g2_signature` = `N_PROF != 4` AND a profile whose labeled sensor
channels are entirely fill. A statement about file contents, verifiable by
inspection — the causal writer explanation stays in the audit report.
Corpus check: exactly 1 file matches (`BR2902086_103.nc`); no false
positives (no healthy N_PROF≠4 file exists to trip it).

## D. Frontend (additive; CTD/map/legacy paths behavior-identical)

- `ResultsWorkspace`: BGC section under the CTD charts, shown only with BR
  data — one `ScientificProfileChart` card per sensor parameter actually
  carrying measurements (file-true long names + units); all-fill channels
  listed as "no measurements in file — not plotted". Amber notice on
  G2-matching cycles; `BGC-ONLY` badge + cycle-button `BGC` tag on BR-only
  cycles. `tsc --noEmit` clean; production build succeeds.
- `ScientificProfileChart`: optional `genericParam` mode (composite hover
  ids `profile×100000+level`, span-adaptive decimals 2–7, generic hover
  readout, restrained palette). TEMP/PSAL props/rendering untouched.
- `CycleDetailModal`: BGC provenance strip (filename, N_PROF, profile
  count, G2/BGC-only badges); empty-CTD text distinguishes BGC-only cycles.
- Served bundle verified to contain the new UI strings; the card-derivation
  contract was replayed in Node against the real run payload: cycle 99 →
  9 cards (140/141 pts each), cycle 103 → 0 cards + notices.

## E. Data growth (§H.7)

Live-fetched `incois_2902130_meta.nc` + `incois_2902131_meta.nc` from GDAC
(verified: PLATFORM_NUMBER match, PROVOR_III/836, N_PARAM 11) →
`data/cts4/ref/gdac_incois_301/` now 15 files; **all 10 staged SBD groups
decode** (was 8/10). Frozen-path check: 2902130 → 14 R + 14 BR, 2902131 →
13 R + 13 BR, all N_PROF=4. README coverage updated.

## F. E2E verification ledger (real APIs, real data)

| Run | Result |
|---|---|
| `POST /api/decode {2902086}` → `run-2902086-7854e9` | completed, 16 cycles (15 R + BR-only 103), profiles 15, missing 1 (honest), G2 only on 103, msg "15 R … 16 BR … 1 BGC-only cycle(s)" |
| `POST /api/decode {1902844}` → `run-1902844-9d2137` | completed 23/23/0 — legacy parity exact, BGC fields default clean |
| `POST /api/batch/decode-all {wmos, force:true}` → `batch-1789551586-4713` | 2/2 fresh (1902844 23/23/0/27; 2902086 16/15/1/34), email sent, PDF 26,167 B |
| `GET /` | 200, rebuilt frontend served; batch runs persisted + servable |

One service bug found and fixed during E2E: `n_r`/`n_br_only` definitions
missing from the verification block (NameError → error status on first
attempt); fixed, syntax-checked, re-verified green.

Incidental finding (pre-existing, not caused here): the pre-restore mixed
batch references run JSONs lost when the turn-end snapshot failed (async
persist threads killed; batch JSON persisted synchronously and survived).
A fresh forced batch now provides a fully consistent Results view. The
non-forced `decode-all` correctly returns `already_complete` when today's
runs exist.

## G. Not done (still needs explicit approval)

`src/argo_decoder/` G2/G3 backend fixes; concurrency guard; RTQC modal
catalogue for tests 57/62/63 (no per-test evidence in 301 files);
PDF/report BGC wording; BGC measurement table (charts + hover readouts
cover verification for now).

## H. How to view

Open the :8000 preview → decode/batch 2902086 → Results workspace →
select any cycle (BGC cards) and C103 (BR-only + G2 notice). In-repo doc:
`decoder-ui/docs/CTS4_BGC_SUPPORT.md`.
