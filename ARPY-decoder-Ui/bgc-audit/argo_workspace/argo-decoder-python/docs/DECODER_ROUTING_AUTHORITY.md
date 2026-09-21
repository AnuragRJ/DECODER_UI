# Decoder routing — the authoritative table

**What selects the decoder for an APEX APF9/ARGOS float, and what must
never be used to select it.**

Verified 2026-08-17 against the INCOIS four-CSV metadata, the Coriolis
MATLAB source, and runtime decode output. Read-only investigation; no
behaviour was changed to produce this document.

---

## The rule

> ### ⛔ Never use `Float subtype` as the Coriolis decoder selector merely because its numeric value equals a Coriolis decoder ID.
>
> `Float subtype` is the Argo **`DAC_FORMAT_ID`** (`PR_VERSION`). Its
> values (`1010`, `1021`) collide numerically with Coriolis decoder IDs
> while meaning something entirely different.
>
> **The routing key is `sensor-info.csv` → `firmware revision number`.**

---

## The table

| INCOIS field | Value | Semantic meaning | Python routing | Coriolis evidence |
|---|---|---|---|---|
| `Float subtype` | `1010` | Argo `DAC_FORMAT_ID` / `PR_VERSION` | **not a routing key** | confirmed — see §3 |
| `Float subtype` | `1021` | Argo `DAC_FORMAT_ID` / `PR_VERSION` | **not a routing key** | confirmed — see §3 |
| `firmware revision number` | `061810` | APF9 firmware revision | **1005** | **DIRECT** |
| `firmware revision number` | `110613` | APF9 firmware revision | **1010** | **DIRECT** |
| `firmware revision number` | `091615` | APF9 firmware revision | **1010** | **DERIVED + RUNTIME VERIFIED** |

Evidence grades: **DIRECT** = the firmware string appears verbatim in the
Coriolis dispatch. **DERIVED** = not present in Coriolis; binding rests on
byte-layout identity. **RUNTIME VERIFIED** = decoded values at
layout-discriminating offsets reproduce the GDAC reference.

---

## 1. Why `Float subtype` is not the selector

It **disagrees with the true decoder on 11 of 11 floats** — there is no
float for which taking it at face value gives the right answer:

| WMO | `Float subtype` | firmware | true decoder | agree? |
|---|---|---|---|---|
| 2901304, 2901305, 2901328, 2901339, 2901350 | `1010` | `061810` | **1005** | ✗ |
| 2902201, 2902203, 2902206 | `1021` | `110613` | **1010** | ✗ |
| 2902222, 2902223, 2902224 | `1021` | `091615` | **1010** | ✗ |

**The 2901304 trap.** The sheet says `Float subtype = 1010` and GDAC
publishes `DAC_FORMAT_ID = 1010`. Both numbers equal a real Coriolis
decoder ID. The float nevertheless decodes with Coriolis **1005**.
Routing on that number selects a decoder whose byte layout diverges from
byte 7 onward, and the profile decodes to physically impossible pressures.

## 2. There is no `decoder_id` column

All **126 columns** across `meta.csv`, `sensor-info.csv`, `calib.csv` and
`config_params.csv` were enumerated. None carries a decoder id under any
spelling (`decoder_id`, `dec_id`, …). The only decoder-bearing field is
`firmware revision number`.

Related fields that are **not** routing keys:

| field | file | value | what it is |
|---|---|---|---|
| `format standard number` | config_params | `1020` (all floats) | Argo `STANDARD_FORMAT_ID` |
| `firmware date/software date` | config_params | varies | the *published* `FIRMWARE_VERSION`, **not** the format revision |

`firmware date/software date` deserves its own warning: on the 1005
family it reads `020811` while the format revision is `061810`. Routing
on the published label maps to 1010 and mis-decodes the hull.

## 3. Coriolis evidence, with line references

`/tmp/corio` = `github.com/euroargodev/Coriolis-data-processing-chain-for-Argo-floats`

**Dispatch — `decArgo_soft/soft/sub/decode_apx_argos.m`**

```matlab
 76:   case {1001} % 071412
124:   case {1005} % 061810          <- DIRECT evidence for 061810
184:   case {1010} % 110613&090413   <- DIRECT evidence for 110613
```

The `switch` is on `a_decoderId`, and each `case` carries the firmware
revision it serves as an inline comment. `1005` dispatches to
`decode_data_apx_1_5.m`; `1010` dispatches to `decode_data_apx_10.m`.

**`DAC_FORMAT_ID` semantics — `.../util/sub/generate_json_float_meta_apx_argos_.m`**

```matlab
994:   'DAC_FORMAT_ID', 'PR_VERSION', ...
```

and the list of values it accepts (line 171):

```matlab
{'071412'} {'061810'} {'082213'} {'032213'} {'110613'} {'090413'} ...
```

Coriolis's own `DAC_FORMAT_ID` values are **firmware strings**, never
`1005`/`1010`. INCOIS populates the same field with `1010`/`1021`, which
is a DAC-local convention that happens to collide with Coriolis's decoder
numbering. That collision is the entire hazard.

**No explicit mapping file exists.** `get_decoder_id.m` maps PROVOR DAC
format versions only (`'4.2'→1` … `'5.9'→105`); it contains no APEX
entries. The dispatch comments above are the only firmware↔ID binding in
the source.

## 4. Why `091615` is DERIVED, not DIRECT

`091615` (and `091515`) appear **nowhere** in the Coriolis tree — no
`.m`, `.json`, `.csv` or `.txt` match. Coriolis has no case for them.

The binding to 1010 rests on:

1. **Byte-layout identity.** Our `APF9_CTD_19` field-width table is
   byte-for-byte identical to `decode_data_apx_10.m:126`:

   ```
   [1 2 1 1 2 1 2 1 1 1 1 4 1 1 1 1 1 1 1 1 1 2] * 8
   ```

   and `APF9_CTD_23` matches `decode_data_apx_1_5.m:120`. The two tables
   are mutually distinct, diverging from field index 5 (offset `1@7` vs
   `2@7`).
2. **Same hull class** — APEX / APF9 / ARGOS / SBE41, 31-byte frames.
3. **Successful decode** — PRES 4.2 → 1999.8 dbar on 2902223.

**Honest limit:** a `091615`-specific decoder could exist in a Coriolis
version we do not hold. Recorded as DERIVED for that reason.

## 5. Runtime verification method

Numeric equality proves nothing; the layouts must be discriminated on
bytes where they actually differ. Fields 0–4 are identical in both
tables, so a test on those cannot distinguish them.

Testing at **diverging** offsets on 2901304 (routed to 1005):

| technical field | ours | GDAC |
|---|---|---|
| `PRESSURE_InternalVacuum_inHg` | 44.655, 44.655, 44.069, 43.776 | identical |
| `TIME_PumpMotor_seconds` | 11972, 23492, 35012, 27844 | identical |
| `POSITION_PistonPark_COUNT` | 15, 16, 17, 16 | identical |

Under the 1010 layout these bytes sit at different offsets and cannot
reproduce those values. This is what upgrades `061810 → 1005` from a
source comment to **RUNTIME VERIFIED**.

## 6. Where routing happens in the Python code

`src/argo_decoder/metadata/multi_csv_loader.py`

```python
626:  decoder_revision = _zero_padded_firmware(sensor.get("firmware revision number", ""))
627:  decoder_id       = FIRMWARE_TO_DECODER.get(decoder_revision, 0)
```

Zero-padding is load-bearing: the sheets store the revision numerically,
so `061810` arrives as `61810` and `091615` as `91615`.

`Float subtype` is read once, at line 703, and reaches **only** the
`DAC_FORMAT_ID` output field:

```python
703:  payload["dac_format_id"] = _int_str(meta.get("Float subtype", ""))
```

Verified by grep: `dac_format_id` appears in `builder.py:257`,
`models.py:168` and `nc/metadata_file.py:410` — all output paths. **It is
never consulted for routing.** An unknown firmware yields `decoder_id =
0` (fail closed) rather than a guess.

## 7. Regression guard

If a future change makes routing depend on `Float subtype`,
`DAC_FORMAT_ID`, or `firmware date/software date`, every 1005-family
float silently mis-decodes. The cheapest detection is the
layout-discriminating check in §5: decode 2901304 and compare
`PRESSURE_InternalVacuum_inHg` / `TIME_PumpMotor_seconds` /
`POSITION_PistonPark_COUNT` against the GDAC reference. Those fields sit
at offsets where the 1005 and 1010 tables disagree, so they fail loudly
under a wrong routing key.

---

## Summary

| Question | Answer |
|---|---|
| Is there a `decoder_id` column in the INCOIS CSVs? | **No** — 126 columns checked |
| Is `Float subtype` the decoder id? | **No** — it is `DAC_FORMAT_ID`; wrong on 11/11 floats |
| What is the routing key? | `sensor-info.csv` → `firmware revision number`, zero-padded |
| Does an explicit Coriolis mapping file exist? | **No** — only inline `case` comments in `decode_apx_argos.m` |
| `061810 → 1005` | DIRECT + RUNTIME VERIFIED |
| `110613 → 1010` | DIRECT |
| `091615 → 1010` | DERIVED + RUNTIME VERIFIED (absent from Coriolis) |
