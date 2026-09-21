# `END_MISSION_DATE` and the other end-of-mission fields

## Verdict

**Coriolis does not calculate it. It is a database lookup, and it cannot be
replicated from telemetry.** Adding a column is the correct answer, and for
`END_MISSION_STATUS` we already do the right thing.

---

## 1. What the MATLAB actually does

The only place `END_MISSION_DATE` appears in the decoder is a name-to-name
mapping table in `generate_json_float_meta_apx_argos_.m`:

```matlab
function [o_metaStruct] = get_meta_bdd_struct()
o_metaStruct = struct( ...
   ...
   'END_MISSION_DATE',   'END_MISSION_DATE', ...
   'END_MISSION_STATUS', 'END_MISSION_STATUS', ...
```

`BDD` is the Coriolis relational database. The left side is the NetCDF
variable, the right side is the **database column name**. The value is then
copied verbatim:

```matlab
idF = find(strcmp(metaData(idForWmo, 5), metaBddStructValue) == 1, 1);
if (~isempty(idF))
   metaStruct.(metaBddStructField) = metaData{idForWmo(idF), 4};
```

Confirming there is no derivation anywhere in the codebase:

```
$ grep -rn "END_MISSION_DATE\s*=" --include=*.m .
(no matches)
```

Zero computed assignments across all 523 `.m` files. It is also **absent from
both mandatory lists** (`mandatoryList1` / `mandatoryList2`), so when the
database has no value the field is simply left empty — it is never filled with
`n/a` or `UNKNOWN`, and never estimated.

Every sample `_meta.json` shipped in the container carries:

```json
"END_MISSION_DATE" : "",
"END_MISSION_STATUS" : "",
```

So the value originates from a human operator recording that a float died. It
is an **operational fact, not a measurement.**

---

## 2. Can it be derived from telemetry? No — tested

Checked the three INCOIS floats that have a populated date against the last
timestamp in their own trajectory files:

| WMO | `END_MISSION_DATE` | last telemetry | delta | match |
|---|---|---|---|---|
| 2901304 | 2011-09-22 05:14:40 | 2011-09-22 05:14:39 | **0.000 d** | **exact** |
| 2901305 | 2013-08-13 14:49:56 | 2012-08-28 17:15:23 | **+349.9 d** | no |
| 2901328 | 2013-06-05 07:37:45 | 2012-12-27 20:55:53 | **+159.4 d** | no |

1 of 3. And the two misses are not an artefact of our archive being short —
they are beyond **all published GDAC data**:

| WMO | last published profile | `END_MISSION_DATE` | gap |
|---|---|---|---|
| 2901305 | 2011-11-02 (cycle 27) | 2013-08-13 | **+650 days** |
| 2901328 | 2013-01-01 (cycle 98) | 2013-06-05 | **+154 days** |

A date 650 days after the float's final transmission cannot be computed from
anything the float sent. It records when the operator *declared* the mission
over — plausibly after a grace period, a recovery attempt, or an annual
housekeeping review. There is no formula.

Deriving it as "last message" would be right once and wrong twice, and would
silently fabricate a provenance claim. That fails the project's rule against
inventing metadata.

---

## 3. `END_MISSION_STATUS` — already solved, and it is the useful signal

Across all 11 INCOIS APEX floats:

| WMO | `END_MISSION_STATUS` | `END_MISSION_DATE` |
|---|---|---|
| 2901304, 2901305, 2901328 | **`T`** | populated |
| the other 8 | **`0`** | empty |

The correspondence is exact: `T` (terminated) ⇔ a date exists; `0` (active)
⇔ empty. Reference table 19 of the Argo user manual defines the code list;
the field is one character wide (`check_json_meta_data.m` line 128).

**We already emit this correctly.** `builder.py` reads it from the registry,
and `meta.csv` already carries a `Status` column that maps one-to-one:

| WMO | `meta.csv` `Status` | GDAC `END_MISSION_STATUS` |
|---|---|---|
| 2902222/23/24 | `live` | `0` |
| 2901304, 2901305 | `Dead` | `T` |

5/5. Verified on our own output:

```
OURS 2901304: END_MISSION_DATE='' END_MISSION_STATUS='T'
GDAC 2901304: END_MISSION_DATE='20110922051440' END_MISSION_STATUS='T'
```

So the status is right today; only the date is blank.

---

## 4. Recommendation

Add an `end_mission_date` column to `config/metadata/meta.csv` (and the
equivalent to `registry.csv`). This is **data entry of an operational fact**,
exactly what Coriolis does, not fabrication.

The plumbing is already in place — `FloatMeta.end_mission_date` exists
(`models.py` line 203) and `metadata_file.py` already writes the variable with
the correct `YYYYMMDDHHMISS` convention. The single change needed is in
`builder.py`:

```python
"END_MISSION_DATE": "",                                    # today
"END_MISSION_DATE": _row_extra(row, "end_mission_date"),   # proposed
```

which mirrors the line directly beneath it for `END_MISSION_STATUS`.

Values to enter, taken from the official GDAC files (not invented):

| WMO | value |
|---|---|
| 2901304 | `20110922051440` |
| 2901305 | `20130813144956` |
| 2901328 | `20130605073745` |
| all others | leave empty |

Leaving it empty for a live float is correct, not a gap: 8 of 11 INCOIS floats
have it empty in GDAC, and the Argo format does not require it.

### Why not derive it

| option | verdict |
|---|---|
| copy last message time | wrong on 2/3 floats, by 159 and 350 days |
| last message + fixed grace period | the two gaps differ by 191 days; no constant fits |
| leave blank always | loses a field GDAC publishes for dead floats |
| **CSV column** | **matches Coriolis exactly; no invention** |
