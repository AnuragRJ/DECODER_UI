# Running the decoder locally on ARVOR-I floats

A short, tested runbook for decoding an ARVOR-I (NKE Arvor, Iridium SBD, SBE41CP)
float from raw telemetry to GDAC-shaped NetCDF.

Every command below was executed end-to-end on 2026-09-08 against float **6990711**
and produced the 10 NetCDF products shown in §5.

---

## 1. Install

Python **3.11+** required.

```bash
cd argo-decoder-python
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -e .
pip install gsw          # needed for density / DOXY / RTQC test 14
```

> `gsw` is an optional extra (`pip install -e '.[gsw]'` also works). **Install it** —
> without it 16 tests fail and the density-inversion RTQC test cannot run.

Check the install:

```bash
python3 -m argo_decoder.cli.main version
python3 -m argo_decoder.cli.main decode-float --help
```

The console script `argo-decoder` is equivalent to `python3 -m argo_decoder.cli.main`.

## 2. Input layout (the part that trips people up)

The pipeline discovers files under **`<input-root>/archive/cycle/<transmitter-id>/`**,
*not* directly in the directory you pass to `-i`. Each Iridium session needs **both**
files:

```
<input-root>/
└── archive/
    └── cycle/
        └── 664170/                        <- transmitter id (see table below)
            ├── redacted_imei_170_000067.eml   <- session header
            ├── redacted_imei_170_000067.sbd   <- binary payload  (REQUIRED)
            ├── redacted_imei_170_000068.eml
            ├── redacted_imei_170_000068.sbd
            └── ...
```

- The directory name is the **transmitter id**, taken from the `Argos number` column of
  `config/metadata/meta.csv`. It is not the WMO.
- `.eml` alone is not enough. Without the matching `.sbd` the run fails with
  `no Tech#1 packet found: cannot resolve decoder id`.
- `.eml` filenames follow `redacted_imei_<prefix>_<momsn>.eml`.

Validation floats in this workspace:

| WMO | transmitter id (dir name) | raw telemetry location |
|---|---|---|
| 1902844 | `123230` | `arvor_raw/harness_bundle/more-raw-files-and-manuals/1902844/` |
| 2904082 | `124250` | `arvor_raw/harness_bundle/more-raw-files-and-manuals/2904082/` |
| 6990711 | `664170` | `arvor_raw/ARVOR-I-raw-files/20260819/6990711/` |
| 7902408 | `339490` | `arvor_raw/ARVOR-I-raw-files/20260819/7902408/` |

## 3. Metadata: the four CSVs

ARVOR-I metadata comes **only** from the four authoritative CSVs in
`config/metadata/`:

```
meta.csv   sensor-info.csv   calib.csv   config_params.csv
```

Select them with `--metadata-backend csv4 --registry config/metadata`
(`--registry` points at the **directory**, not a file).

> `registry.csv` is **not** used for ARVOR-I metadata or decoder routing. Routing is
> family-generic: the CSV signature (NKE hull + SBE41CP + non-ARGOS comms) resolves to
> `PROFILE_CLASS "arvor_i_sbe41cp"` → `ArvorISbdDecoder`.

## 4. Decode

```bash
cd argo-decoder-python

WMO=6990711
PTT=664170
RAW=../arvor_raw/ARVOR-I-raw-files/20260819/$WMO

# stage the input tree
mkdir -p /tmp/run/in/archive/cycle/$PTT /tmp/run/out
cp $RAW/*.eml $RAW/*.sbd /tmp/run/in/archive/cycle/$PTT/

# decode
python3 -m argo_decoder.cli.main -l WARNING decode-float $WMO \
    --metadata-backend csv4 \
    --registry config/metadata \
    --rtqc \
    -i /tmp/run/in \
    -o /tmp/run/out
```

### `--rtqc` is not optional in practice

Real-time QC is **off by default**. Without it every published `<PARAM>_QC`
stays `'0'` ("no QC performed") and `PROFILE_<PARAM>_QC` stays blank, which the
GDAC FileChecker **rejects**. Measured on 6990711 cycle 1:

| | `PRES_QC` zeros | `PROFILE_PRES_QC` | `N_HISTORY` |
|---|---|---|---|
| `--rtqc` | **0 / 102** | `'A'` | 4 (adds `QCP$`/`QCF$`) |
| default | 102 / 102 | `' '` | 2 |

Tests that cannot run stay truthfully skipped — TEST004 without a bathymetry
grid is recorded as skipped, never as passed.

Useful flags: `-l INFO|DEBUG` for verbosity, `--json-logs` for machine-readable logs
(both go **before** the sub-command), `--xml-name` to set the report filename,
`--ref <dir>` to supply RTQC reference data (a `gebco.nc` there enables TEST004).

## 5. Output

```
/tmp/run/out/
├── nc/6990711/
│   ├── 6990711_meta.nc              metadata
│   ├── 6990711_tech.nc              technical
│   ├── 6990711_Rtraj.nc             trajectory (RTQC applied)
│   └── profiles/R6990711_001.nc …   mono-profiles, one per cycle
├── xml/co041404_<timestamp>_6990711.xml    run report
├── csv/   log/   iridium/
```

For 6990711 this is 3 float-level files + 7 mono-profiles = **10 NetCDF files**.

Quick look:

```bash
python3 -c "
import netCDF4, numpy as np
d = netCDF4.Dataset('/tmp/run/out/nc/6990711/6990711_meta.nc'); d.set_auto_mask(False)
g = lambda n: ''.join(x.decode('latin1') for x in np.asarray(d[n][:]).reshape(-1)).strip()
print({k: g(k) for k in ['PLATFORM_NUMBER','PLATFORM_TYPE','POSITIONING_SYSTEM','TRANS_SYSTEM']})
"
# {'PLATFORM_NUMBER': '6990711', 'PLATFORM_TYPE': 'ARVOR',
#  'POSITIONING_SYSTEM': 'GPS', 'TRANS_SYSTEM': 'IRIDIUM'}
```

## 6. Checking the result

**Against the GDAC references** (in `gdac_arvor_i_ref/`):

```bash
python3 scripts/validate_arvor_i_meta.py         # 116/116
python3 scripts/validate_arvor_i_rtraj_gdac.py   #  84/84
python3 scripts/validate_arvor_i_rtraj.py        #  64/64
python3 scripts/validate_arvor_i_tech_gdac.py    #  32/32
python3 scripts/validate_arvor_i_tech.py         #  56/56
```

**Format + consistency compliance** (official Argo FileChecker, needs Java):

```bash
# latest release (v3.0.5) - format AND consistency/NVS checks
curl -sLO https://github.com/OneArgo/ArgoFormatChecker/releases/download/v3.0.5/file_checker_exec-3.0.5.jar
curl -sL https://github.com/OneArgo/ArgoFormatChecker/archive/refs/heads/main.tar.gz | tar -xz

mkdir -p data results
cp /tmp/run/out/nc/*/*.nc /tmp/run/out/nc/*/profiles/*.nc data/
java -jar file_checker_exec-3.0.5.jar incois \
     ./ArgoFormatChecker-main/file_checker_spec ./results ./data
grep -h "<status>" results/*.filecheck | sort | uniq -c
# 81 <status>FILE-ACCEPTED</status>
```

All four products are **FILE-ACCEPTED with zero errors** (81/81 verified). The only
warning is `PI_NAME : 'M Ravichandran' Status: Invalid (not in NVS R40 table)`, which is
**identical in GDAC's own published files** — an INCOIS PI-registration matter, not a
decoder issue.

> ⚠️ Use the **release jar**, not the older `format_control_1-17` package. That one runs
> the **format layer only** and silently skips every consistency/NVS rule, so it will
> report "compliant" on files the real GDAC checker rejects.

**Test suite:**

```bash
python3 -m pytest -q        # 2112 passed, 1 skipped
ruff check src/ tests/ scripts/
```

The one skip (`test_structural_parity`) needs a golden tree; regenerate it with
`python3 scripts/bootstrap_golden.py` if you want it green.

## 7. Expected differences vs GDAC

A correct ARVOR-I run does **not** match INCOIS GDAC byte-for-byte. Meta reaches
**62 of 65** value fields exact; the rest are deliberate and documented:

| Field | Why it differs |
|---|---|
| `DATE_CREATION`, `DATE_UPDATE` | file generation timestamps |
| `START_DATE` | we publish the **decoded first descent** (earliest DST / MC 100), per Argo User's Manual 3.44.0 §2.4.5. GDAC's four values follow three mutually incompatible derivations, two of them *later* than the actual first descent |

`START_DATE_QC` now matches GDAC (`'1'`), derived from the value rather than hardcoded:
`'1'` once a start date is published, `'9'` ("Missing value", reference table 2) if the
telemetry carries no dated descent.

Rtraj also diverges where GDAC is demonstrably wrong (legacy integer-day clock drift,
a missing ascent-end correction, ARGOS accuracy codes on an Iridium float). See
`validation_arvor_i_products/RTRAJ_STANDARDS_ADJUDICATION_2026-09-08.md` and
`META_PARITY_ANALYSIS_2026-09-08.md` for the standards-based reasoning behind each one.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `no input files found for WMO … under <path>/archive/cycle` | Input tree is flat. Files must be in `<input>/archive/cycle/<transmitter-id>/`. |
| `no Tech#1 packet found: cannot resolve decoder id` | `.sbd` payloads missing — copy them next to the `.eml` files. |
| `no ARVOR-I messages parsed` | Wrong transmitter-id directory name, or the raw files are for a different float. |
| `DECODER_ID missing/zero` (warning) | **Harmless.** ARVOR-I routes by CSV signature, not by a numeric decoder id. |
| 16 failures in `test_derived_density` / `test_derived_doxy` / `test_rtqc_density_inversion` | `gsw` not installed → `pip install gsw`. |
| RTQC test 4 always skipped | No GEBCO bathymetry grid. Expected; the result is never fabricated. Pass `--ref <dir>` containing `gebco.nc` to enable it. |
| FileChecker rejects mono: `PRES_QC[1]: QC code '0' at N levels` | RTQC did not run — add **`--rtqc`** (see §4). |
| FileChecker rejects meta: `START_DATE_QC: ' ' Status: Invalid` | Stale build. Current code emits `'1'`/`'9'`, never blank. |
| Older `format_control_1-17` says "compliant" but the GDAC checker rejects | That package runs the **format layer only**. Use the v3.0.5 release jar (§6). |
| Blank PET/AST/AET (MC 300/400/500) | The float never transmitted a Param#1 mission-config packet. Genuine data coverage limit, not a bug. |
