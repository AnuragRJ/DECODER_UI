# handoff.md — Argo APEX APF9 decoder, current state

Prepared 2026-08-12. For a new coding agent taking over without reading the
prior conversation.

Everything below was verified against the working tree on the date above, not
recalled. Where something is uncertain it says so.

---

## 1. Project purpose

Migrate the Coriolis MATLAB Argo float decoder to Python. The decoder reads
raw satellite telemetry from Argo profiling floats and writes the four
standard Argo NetCDF products, which must match what the official GDAC
publishes.

Current focus: **APEX floats with an APF9 controller board transmitting over
ARGOS**, decoder families **1005** and **1010**.

Output products per float:

| file | contents |
|---|---|
| `<wmo>_meta.nc` | float metadata, sensors, calibration, configuration |
| `<wmo>_tech.nc` | per-cycle technical/engineering values |
| `<wmo>_Rtraj.nc` | trajectory: positions, timestamps, park measurements |
| `profiles/R<wmo>_NNN.nc` | one mono-profile per cycle (PRES/TEMP/PSAL + QC) |
| `<wmo>_prof.nc` | multi-profile aggregate |

---

## 2. Current architecture

Layered Python package under `src/argo_decoder/` (71 source files):

```
cli/         Typer CLI (argo-decoder)
config/      Pydantic settings; decoder table; RTQC reference-file paths
metadata/    float registry loaders (two backends), builder, models
io/          rsync/archive discovery, raw file reading
domain/      core types: CycleData, RawFrame, QcFlag
platforms/   per-platform decoders; apex_argos/ is the active one
sensors/     CTD profile -> xarray dataset, RTQC provenance masks
derived/     CNDC, density (TEOS-10 via gsw)
rtqc/        real-time QC tests
nc/          NetCDF writers (metadata_file, technical, trajectory, mono_profile)
pipeline/    runner that wires the stages; dual_run harness
trajectory/  trajectory helpers
util/        logging
```

Data flow:

```
raw ARGOS .txt
  -> frames.py        split transmissions, CRC, redundancy selection
  -> profile.py       decode profile id + PRES/TEMP/PSAL by layout
  -> engineering.py   decode technical/engineering block
  -> rtqc/            per-profile then cross-cycle QC
  -> nc/              write the four products
```

---

## 3. Implementation status

### Implemented and verified

- **ARGOS frame handling** — transmission splitting, CRC checking, redundancy
  voting, per-byte majority selection for re-sampled analogue channels.
- **Profile decoding** for decoder 1005 (`apf9_ctd_23`) and 1010
  (`apf9_ctd_19`) layouts.
- **Cycle numbering** — telemetered profile id + derived 8-bit counter
  roll-over + registry deployment offset. See `docs/CYCLE_NUMBERING.md`.
- **All four NetCDF writers**, format 3.1.
- **RTQC: 14 tests** — 1, 2, 3, 5, 6, 8, 9, 11, 12, 13, 14, 16, 18, 19,
  including cross-cycle 5/16/18 in a second pass.
- **Two metadata backends** (see §7 — this distinction matters a lot).
- **Reference-free self-check** (`scripts/selfcheck_output.py`) that catches
  structural decode errors with no GDAC file present.
- **690 tests pass**; `ruff`, `ruff format` (125 files) and `mypy --strict`
  (71 files) all clean.
- **`END_MISSION_DATE`** is copied from the four-CSV `end mission date`
  column (operator fact, not last-message). 2901304/2901305 match GDAC;
  live floats stay empty.
- **`GROUNDED`** is derived from float performance on APEX/ARGOS:
  `'Y'` when the ascending profile stops more than 100 dbar short of
  `CONFIG_ProfilePressure_dbar`, `'N'` when it reaches it, `'U'` when
  either input is missing. **23/23 on 2901304** (Y×5, N×15, U×3).
  Nothing to do with GEBCO — reference table 20 reserves `B`/`C` for the
  bathymetry route and INCOIS publishes `Y`/`N`. See
  `docs/GROUNDED_INVESTIGATION.md`.

### Partially implemented
- **Trajectory schedule chain** — modelled only when the archive contains
  cycle 1. Archives that start mid-life get empty `JULD_DESCENT_START`,
  `JULD_PARK_*`, `JULD_TRANSMISSION_END`.
- **Technical parameters on decoder 1010** — 12 of 14 published labels;
  `PRESSURE_AirBladder_COUNT` and `PRESSURE_InternalVacuum_inHg` are not
  located in that firmware's layout.

### Planned (not started)

- **RTQC TEST004** (position on land) — needs GEBCO; config slot already
  exists (`TEST004_GEBCO_FILE`).
- **Profile `JULD` anchored on ascent end** instead of first satellite fix.
- **Layout selection by raw-byte plausibility** instead of the firmware table.

### Deferred (explicit decisions, do not restart without asking)

- **Phase 7 Buffer Manager** — out of scope.
- **Docker / CI / packaging work** — out of scope for the current phase.
- **Iridium and APF11 platforms** — code paths exist but are not the focus.
- **Reproducing known GDAC defects** — see §12.

---

## 4. Completed milestones

From `IMPLEMENTATION_PROGRESS.md` (append-only, 8,399 lines — the primary
source of truth). Most recent phases, newest last:

1. Sea-Bird calibration coefficients for the 2901304/2901305 pair
2. GDAC parity for `tech.nc` and `Rtraj.nc`
3. Three CLI defects behind a file-checker rejection
4. RTQC conformance: cross-parameter leak, mis-specified Test 13, three
   missing tests
5. Cross-cycle RTQC: TEST005/016/018
6. Multi-burst raw files: two splitter defects affecting every APF9 float
7. Fleet-wide QC audit **plus a correction** — 98 of 2901304's QC differences
   turned out to be a delayed-mode artefact, not a real disagreement
8. Three generic defects behind the 2901328/2901350 differences
9. Fleet check of the 480 h schedule chain — a single-file GDAC defect
10. GEBCO bathymetry decision + making the fleet reproducible offline
11. Submission-facing meta/traj/tech gaps: `END_MISSION_DATE` CSV column,
    `GROUNDED='U'`; R4/R5/cycle-20 FLAG investigated and left alone
12. `GROUNDED` Y/N derived from float performance — the earlier "not
    derivable" conclusion falsified and superseded

---

## 5. Current phase

**GDAC parity hardening across all APF9 floats**, with a deliberate shift away
from per-float patching toward generic, self-validating behaviour.

Immediately preceding work: `END_MISSION_DATE` via four-CSV and
`GROUNDED='U'`. Prefer four-CSV (`config/metadata/`) for all decode work.

---

## 6. What currently works

All nine floats decode from the repository alone — no network, no `/tmp`:

```bash
python scripts/generate_apex_argos_nc.py \
  --raw-root phase4_reference/raw/raw-files \
  --registry config/registry_apf9.csv \
  --output-root /tmp/out \
  --wmo 2901304 --wmo 2901328 --wmo 2901339 --wmo 2901350 \
  --wmo 2902201 --wmo 2902203 --wmo 2902206 --wmo 2902222 --wmo 2902223
```

All report `status=ok`.

Measured parity (2026-08-11, full detail in `APF9_PARITY_STATE.md`):

| measure | result |
|---|---|
| science values, all floats | **14 807 / 14 812 levels bit-identical (99.97 %)** |
| QC flags | 44 277 / 44 436 (99.64 %) |
| `meta.nc` (four-CSV backend) | **63 / 65** (2901304; remaining two are run-time stamps) |
| `tech.nc` 2901339 / 2901350 | **100 %** |
| `tech.nc` 2901304 | 321 / 322 |
| `Rtraj.nc` 2901304 N_CYCLE | 800 / 920 (87 %) |

The 5 "mismatched" science levels are cases where GDAC published a fill value
and we recovered a real measurement. Science parity is effectively complete.

---

## 7. Important modules and files

### Source

| file | why it matters |
|---|---|
| `platforms/apex_argos/profile.py` | layout table, `decode_profile`, `cycle_number_wrap_for` |
| `platforms/apex_argos/frames.py` | transmission splitting, CRC, majority bytes |
| `platforms/apex_argos/decoder.py` | orchestration, sentinel cycles, roll-over wiring |
| `platforms/apex_argos/engineering.py` | technical/engineering block |
| `platforms/apex_argos/trajectory.py` | schedule model, MC tables |
| `rtqc/cross_cycle.py` | TEST005/016/018 (016 rewritten — see §10) |
| `rtqc/non_density.py`, `density_inversion.py` | per-profile tests |
| `nc/{metadata_file,technical,trajectory,mono_profile}.py` | writers |
| `metadata/builder.py` | builds `FloatMeta`; `END_MISSION_DATE` from the four-CSV extra |
| `config/models.py` | `RtqcReferenceFiles.gebco_file`, `position_on_land` flag |

### Data

| path | contents |
|---|---|
| `phase4_reference/raw/raw-files/` | raw ARGOS telemetry, 9 APF9 floats + others |
| `config/metadata/*.csv` | four-CSV backend (5 floats) |
| `config/registry.csv` | single-registry backend |
| `config/registry_apf9.csv` | **all 9 APF9 floats**, decoder ids verified empirically |
| `phase4_reference/gdac_profiles/`, `phase5_reference/` | GDAC fixtures used by audit scripts |

### Documentation — read in this order

| doc | purpose |
|---|---|
| **`APF9_PARITY_STATE.md`** | **start here** — full fleet state, every open issue, ranked next steps |
| `IMPLEMENTATION_PROGRESS.md` | append-only engineering log, primary source of truth |
| `OPEN_ISSUES_2901304.md` | per-issue detail for the reference float |
| `docs/DECODE_LOCALLY.md` | how to run the decoder; backend selection; traps |
| `docs/CYCLE_NUMBERING.md` | how cycle numbers are derived; Coriolis comparison |
| `docs/BATHYMETRY_SETUP.md` | GEBCO download decision and wiring |
| `docs/END_MISSION_DATE.md` | why that field cannot be computed |
| `QC_DIFF_REPORT.md` | supporting QC analysis across the fleet |

**Setup / environment / Docker docs specifically:**

| doc | when to read |
|---|---|
| `docs/DECODE_LOCALLY.md` | **first, before running anything** — venv, install, both backends, the filename trap |
| `docs/RUN_LOCALLY_WINDOWS.md` | Windows-specific paths |
| `deploy/README.md` + `deploy/Dockerfile` + `deploy/compose.python-shadow.yaml` | container image and the shadow-deployment overlay (Docker work is deferred) |
| `docs/PROJECT_STATUS.md` | older status snapshot; superseded by `APF9_PARITY_STATE.md` |

**This file (`handoff.md`) is the only current handoff.** The earlier
per-phase handoffs (`HANDOFF.md`, `PHASE3_HANDOFF.md`, `PHASE4_HANDOFF.md`,
`PHASE5_MIGRATION_HANDOFF.md`) and `NEW_FLOATS_COMPARISON.md` were deleted on
2026-08-12 to keep the root clean for migration. Nothing was lost: their
substance lives in `IMPLEMENTATION_PROGRESS.md` (append-only, the historical
record) and in `APF9_PARITY_STATE.md` (current state). Some older documents
under `docs/` still cite them by name — those citations are now dangling and
should be read as pointers into `IMPLEMENTATION_PROGRESS.md`.

---

## 8. Execution workflow

```bash
cd argo-decoder-python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,gsw]"        # MUST be re-run in a fresh sandbox
```

`gsw` is effectively required — it computes CNDC and drives TEST014.

Decode (preferred, four-CSV backend — pass a **directory**):

```bash
python scripts/generate_apex_argos_nc.py \
  --raw-root phase4_reference/raw/raw-files \
  --registry config/metadata \
  --output-root output/local --wmo 2902222
```

Decode all nine APF9 floats (single-registry backend, pass a **file**):

```bash
python scripts/generate_apex_argos_nc.py \
  --raw-root phase4_reference/raw/raw-files \
  --registry config/registry_apf9.csv \
  --output-root output/all --wmo 2901304   # ...etc
```

Via CLI (single-registry only — see §11 issue 3):

```bash
argo-decoder decode-float 2902222 \
  -i phase4_reference/raw/raw-files -o output/cli \
  --metadata-backend csv --registry config/registry.csv
```

---

## 9. Validation and oracle workflow

```bash
ruff check src tests scripts && ruff format --check src tests scripts
mypy --strict src
pytest -q                                   # baseline: 690 passed
```

Whole-archive audits (compare against committed GDAC fixtures):

```bash
python scripts/audit_mono_profile_values.py   # 1813/1813 bit-identical
python scripts/audit_technical_admt.py        # 817/817
python scripts/audit_trajectory_admt.py
python scripts/audit_metadata_admt.py
python scripts/audit_engineering_decode.py
```

Ad-hoc QC comparison against any GDAC tree:

```bash
python scripts/audit_qc_diffs.py --float "2902222=<our_nc_dir>=<gdac_dir>"
```

Reference-free self-check — **no GDAC needed**, gate a decode with this:

```bash
python scripts/selfcheck_output.py --nc-dir output/all/nc/2901328 \
  --wmo 2901328 --registry config/registry_apf9.csv
```

Exit code 1 on error. It catches wrong layouts, bogus cycle offsets and RTQC
misfires from internal consistency alone. It caught two of the three defects
fixed in milestone 8 before any reference was consulted.

**MATLAB oracle:** `argo-decoder dual-run` / `shadow` exist and
`Coriolis-data-processing-chain-for-Argo-floats-container/` is present in the
parent directory. `tests/conftest.py` resolves `DEMO_ROOT` from that directory
name — **do not rename or delete it**. The MATLAB code must never be modified.

---

## 10. Reference GDAC dataset and how it is used

Official source: `https://data-argo.ifremer.fr/dac/incois/<wmo>/`

Downloaded on demand for comparison; **only small curated fixtures are
committed** (`phase4_reference/gdac_profiles/`, `phase5_reference/`).

**Critical caveat — D-files vs R-files.** For 2901304, 2901328, 2901339 and
2901350 the GDAC serves **delayed-mode (D) files**. Comparing our real-time
output directly against those inflates QC differences: 2901304 shows 98 QC
cell differences, of which **90 are Coriolis delayed-mode re-flagging from
2013**, not real-time disagreement. Reconstruct real-time state by replaying
`HISTORY` rows with `HISTORY_STEP == 'ARSQ'` backwards using
`HISTORY_PREVIOUS_VALUE`. Against real-time state the 98 collapse to **8**.
This mistake was made once already — do not repeat it.

---

## 11. Design decisions already made

1. **Firmware version, not `DAC_FORMAT_ID`, selects the decoder.** GDAC reports
   `1010`/`1021` for all eleven INCOIS floats; four of them only decode
   correctly as **1005**. Wrong layout shifts fields one place — pressure lands
   in the temperature slot and PRES comes out empty.
2. **The 8-bit counter roll-over is derived, never tabulated.** It depends on
   how long the float has been deployed, not on firmware. A hardcoded `+256`
   previously mislabelled 2901328 as cycles 257–355 against GDAC's 1–98.
3. **TEST016 compares a common depth band with both casts interpolated onto
   one grid**, and requires the band below 500 dbar. Averaging each profile's
   own deepest 100 dbar produced **358 false positives** on 2901328 when dives
   were truncated.
4. **"Not run" is not "run and passed"** — RTQC tests report a distinct
   did-not-run state so `HISTORY_QCTEST` stays truthful.
5. **Never fabricate metadata.** Fields we cannot derive stay empty rather
   than being guessed.
6. **We decline to reproduce GDAC defects** (§12).
7. **`IMPLEMENTATION_PROGRESS.md` is append-only.** Corrections go in a new
   entry; never rewrite history.

---

## 12. Known issues and limitations

### Ours to fix

| # | issue | effort | notes |
|---|---|---|---|
| 1 | CLI cannot use the four-CSV backend | one line | `--registry` is declared `dir_okay=False`, so the documented entry point is stuck on the weaker backend. |
| 2 | Only 5 of 9 floats in four-CSV backend | data entry | worth ~17 metadata variables each, and switches TEST019 on. |
| 3 | Profile `JULD` uses first fix, not ascent end | real work | we agree with GDAC on **1 of 230** profiles across 2901328/39/50. Matches on 2901304 only by luck. |
| 4 | Schedule chain empty without cycle 1 | real work | all `JULD_*` score 0/3 on every 1010 float. |
| 5 | Vacuum sign error on 2901328 | needs docs | we emit `44.655`, GDAC `-25.665` on 6 cycles. |
| 6 | Two technical labels missing on 1010 | needs docs | `PRESSURE_AirBladder_COUNT`, `PRESSURE_InternalVacuum_inHg`. |

### Blocked

- ~~**TEST004 + `GROUNDED` detection**~~ — both done. TEST004 needs GEBCO
  (§14); `GROUNDED` turned out to be unrelated to bathymetry and is closed.
- **TEST014 sensitivity** (4 cells on 2901304) — GDAC flags a 0.005 kg/m³
  inversion against the manual's 0.03. A threshold sweep showed matching it
  costs 18 new false positives fleet-wide, so their rule is something else.

### Not comparable (external)

- **2901328** — GDAC trajectory is **format 2.2**, no `MEASUREMENT_CODE`.
- **2901339 / 2901350** — GDAC trajectory covers only later cycles; **zero
  overlap** with our raw archive.
- **2902201 / 2902206** — GDAC has not published the cycles we hold.

### GDAC defects we deliberately do not copy

- **480 h schedule chain on 2901304** — verified across all 11 INCOIS floats:
  2901304 is the **only** one affected; the other 8 step at exactly 240.0 h.
  Its own observed telemetry steps at 240.1 h and its config says 240. Costs
  46 N_MEAS rows and 4 N_CYCLE fields.
- **MC 0 stores an un-subtracted Julian Day** — offset is exactly `2433282.5`
  (the 1950 epoch as an astronomical JD). Present on **all nine** format-3.1
  floats, each decoding to that float's `LAUNCH_DATE`. Inert: the row carries
  `CYCLE_NUMBER = -1` so nothing downstream reads it. Costs 1 row per float.
- **Delayed-mode QC flags** — see §10.
- **`tech.nc` cycle 20 `FLAG_ProfileTermination_hex`** — GDAC has `61`; the 11
  CRC-valid copies hold only `0x0001` and `0x0601`. Unreachable.
- **We hold telemetry GDAC does not** — 5 cycles on 2901304 where our
  `JULD_FIRST_MESSAGE` is earlier by 11–91 min, verified present in the raw
  file. More data, not wrong data.

---

## 13. Exact next recommended task

**Allow a directory for CLI `--registry`** so `argo-decoder decode-float`
can use the four-CSV backend (currently `dir_okay=False`). Then add the
remaining APF9 floats to `config/metadata/`.

Doing so also switches `GROUNDED` on for the remaining floats: it needs
`CONFIG_ProfilePressure_dbar`, which only the four-CSV backend carries, so
2901339 and friends currently report `'U'` on every cycle. **Do not work
around that by inferring the target from the data.**

Do **not** invent cycle-20 `FLAG=61`. Do **not** copy the 480 h chain or
MC 0 astronomical JD.

---

## 14. GEBCO / bathymetry

Decision made, not yet downloaded. Read `docs/BATHYMETRY_SETUP.md`.

Short version: **GEBCO_2026 Grid (ice surface elevation), netCDF, global
file** — 4 GB zipped, 7.0 GB uncompressed. netCDF because Coriolis reads
`lon`/`lat`/`elevation` and sub-sets by window; the Esri ASCII product is
18.2 GB of text. Global rather than tiles because the fleet spans longitude
−180 to +180.

Install is download, unzip, then set `TEST004_GEBCO_FILE` — the config slot
already exists. **Do not commit the grid**; treat it as an external dependency
by path, as Coriolis does.

**`GROUNDED` does not need GEBCO** and no longer belongs in this section.
It is derived from float performance (profile shortfall vs
`CONFIG_ProfilePressure_dbar`), verified on 8 floats / 2 315 cycles. The
earlier crude max-pressure heuristic scored 13/16 on 2902222 because it
compared *park* pressure; against the *ascending profile* the same idea is
exact. See `docs/GROUNDED_INVESTIGATION.md`.

---

## 15. Runtime requirements and constraints

- **Python 3.13** (verified 3.13.14). Dependencies in `pyproject.toml`:
  pydantic 2, typer, structlog, xarray, netCDF4, numpy 2, scipy, lxml,
  cf-xarray, rich, pyyaml; `gsw` via the `gsw` extra.
- **Docker is not required** for development. `deploy/Dockerfile` and
  `deploy/compose.python-shadow.yaml` exist for the shadow deployment, but
  Docker/CI/packaging work is **deferred**.
- **`Coriolis-data-processing-chain-for-Argo-floats-container/`** must remain
  in the parent directory under that exact name — `tests/conftest.py` resolves
  `DEMO_ROOT` from it. Its MATLAB code is read-only reference; never modify it.
- No network is needed for tests or for decoding the nine committed floats.

### Sandbox constraints (learned the hard way)

- **`pip install -e ".[dev,gsw]"` must be re-run every fresh session** —
  installed packages do not persist.
- **`/tmp` is cleared between sessions.** Never leave anything needed there.
  All nine floats' raw telemetry is now committed under
  `phase4_reference/raw/raw-files/` precisely so this stops mattering.
- **Workspace storage is capped** (~128 MB / 10,000 files). Do not copy
  reference datasets or extracted archives into the workspace. See §17.

### Raw filename trap

| form | cycle taken from |
|---|---|
| `<ptt>_<YYYY-MM-DD>.txt` | telemetry |
| `<ptt>_<YYYY-MM-DD>_<wmo>_<NNN>.txt` | the filename |

For 2901304 the short form is required. With the long form two files both
parse to cycle `000`, collide, and yield cycles `[2,3,16]` instead of
`[1,2,3]`.

---

## 16. Workspace / sandboxing reference

A workspace/reference dataset link may be supplied separately by the user.
**Treat it as a reference link only** — do not download or copy its contents
into the workspace. Doing exactly that is what pushed this workspace over
budget once already.

If reference data is needed, fetch it to a path outside the repository
(`/tmp/...`), use it, and let it be discarded. Only small curated fixtures
belong in the repo.

For sandboxing and local setup, read `docs/DECODE_LOCALLY.md` first, then
`docs/RUN_LOCALLY_WINDOWS.md` if on Windows, then `deploy/README.md` if
containerisation becomes relevant.

---

## 17. Workspace hygiene

Cleanup performed 2026-08-11: removed ~21 MB / 152 files of downloaded
archives, byte-identical duplicates and regenerable outputs. Details in the
session summary; the short rule is:

- **Do not** copy Google Drive datasets or extracted archives into the repo.
- **Do not** commit decoder output — it is regenerable.
- **Do** keep `phase4_reference/`, `phase5_reference/`, `phase4_outputs/`,
  `output/`, `tests/` — all are referenced by tests or audit scripts.

Verify a clean state with `pytest -q` (690) plus a decode of 2901304.
