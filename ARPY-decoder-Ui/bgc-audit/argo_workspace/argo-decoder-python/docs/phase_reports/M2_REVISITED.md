# M2 Revisited — Decoder Capability vs DAC Publication Policy

**Date:** 2026-07-28
**Trigger:** Review challenge to the M2 non-implementation decision.

---

## 0. The error in my original reasoning

In the APF9 Completion Report I withheld 16 parameters on this basis:

> All six references use the same fixed 14-name vocabulary … Emitting them
> would add rows the reference does not have, moving the product away from
> GDAC parity.

**That reasoning was wrong.** It treated one DAC's output as if it were the
specification. GDAC parity is a *regression reference* — a way to prove the
decoder is correct where comparison is possible. It is not a ceiling on what a
complete decoder may produce.

The reviewer's distinction is the right one, and acting on it turned up
evidence I had not looked for.

---

## 1. The decisive evidence I had missed

Two sources settle the question, both inside the material already available.

### 1.1 The decoder manual states the actual rule

`argo_coriolis_matlab_decoder_V1.10_20251112.pdf`, §14.2 "Technical label
management" (p. 37):

> The technical labels used in the TECHNICAL_PARAMETER_NAME variable of the
> NetCDF TECH file **should be allowed by the Argo project**. The approved list
> of labels can be found on the Argo data management web page. … The TECH
> labels used by the decoder are stored in the
> `DIR_INPUT_JSON_TECH_LABEL_FILE` directory. There is one file (named
> `_tech_param_name_decId.json`) **per decoder Id**.

So the constraint is **"drawn from the Argo-approved list"**, not "matches what
INCOIS chose to publish". My original criterion was not the specification's.

### 1.2 The machine-readable allow-list exists, per decoder id

`decArgo_soft/config/_techParamNames/_tech_param_name_1005.json` (41 entries)
and `_tech_param_name_1010.json` (42 entries) are the approved vocabularies for
**our exact decoder ids**. Checking all 16 candidates against them:

| Parameter | 1005 | 1010 |
|---|---|---|
| `NUMBER_ArgosPositions_COUNT` | ✅ id 10 | ✅ id 10 |
| `NUMBER_ArgosPositioningClass{0,1,2,3,A,B,Z}_COUNT` | ✅ ids 11–17 | ✅ ids 11–17 |
| `NUMBER_TransmissionFloatFramesComplete_COUNT` | ✅ id 18 | ✅ id 18 |
| `NUMBER_TransmissionFloatFramesCrcOk_COUNT` | ✅ id 19 | ✅ id 19 |
| `PRES_MaxDifferencePvsPTorPTSSamples_dbar` | ✅ id 1022 | ✅ id 1024 |
| `CLOCK_AscentInitiationFromDownTimeExpiryOffset_minutes` | ✅ id 1023 | ✅ id 1025 |
| `PRESSURE_InternalVacuumParkEnd_inHg` | ✅ id 1024 | ✅ id 1021 |
| `NUMBER_PRESSamplesDuringDescentToPark_COUNT` | ✅ id 1025 | ✅ id 1026 |
| `NUMBER_RepositionsDuringPark_COUNT` | ✅ id 1020 | ✅ id 1019 |
| `NUMBER_ParkSamples_COUNT` | ✅ id 1021 | ✅ id 1020 |

**All 16 are approved.** (My first automated check reported `CLOCK_Ascent…` as
"not listed" — a false negative: the JSON value carries a trailing space,
`'CLOCK_AscentInitiationFromDownTimeExpiryOffset_minutes '`. Three labels have
this quirk. Worth knowing for anyone matching these strings.)

The same files also revealed two labels I had not considered:

- **`FLAG_TelonicsPTTStatus_hex`** (1010, ids 101/1002) — an approved home for
  the `TELONICS` byte captured in M3 but never published.
- **`FLAG_CTDStatus_hex`** — an approved home for the SBE41 status word.

### 1.3 The container structurally does not constrain the vocabulary

`TECHNICAL_PARAMETER_NAME` carries **no `conventions` attribute**, and
`N_TECH_PARAM` is an **unlimited** dimension. The ADMT technical file is an open
name/value table by design.

---

## 2. Per-parameter answers to the five questions

Legend: **Q1** derivable from documented telemetry · **Q2** already decoded
internally · **Q3** representable within ADMT · **Q4** omitted *solely* because
the reference DAC declines to publish · **Q5** should we publish.

### Group A — ARGOS reception statistics (10)

| Parameter | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---|---|---|---|---|
| `NUMBER_ArgosPositions_COUNT` | ✅ count of parsed fixes | ✅ `n_argos_fixes` | ✅ approved id 10 | ✅ | **Publish** |
| `NUMBER_ArgosPositioningClass{0,1,2,3,A,B,Z}_COUNT` | ✅ `ArgosFix.location_class` | ✅ parsed | ✅ approved ids 11–17 | ✅ | **Publish** |
| `NUMBER_TransmissionFloatFramesComplete_COUNT` | ✅ frames per cycle | ✅ `n_argos_messages` | ✅ approved id 18 | ✅ | **Publish** |
| `NUMBER_TransmissionFloatFramesCrcOk_COUNT` | ✅ CRC verified | ✅ `n_crc_ok_messages` | ✅ approved id 19 | ✅ | **Publish** |

These derive from *received satellite data*, need no float telemetry, and were
already computed and attached as decoder attributes. Publishing them was purely
a matter of routing existing values to approved labels.

*Caveat honestly stated:* D2 labels the last two "PROVOR frames". For an APEX
float the natural reading is ARGOS message frames, which is what we count. The
counts are exact and reproducible; if Coriolis intends a different denominator
the label semantics — not our arithmetic — would differ.

### Group B — float engineering from messages 2/3 and the auxiliary block (6)

| Parameter | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---|---|---|---|---|
| `NUMBER_RepositionsDuringPark_COUNT` | ✅ `NADJ`, msg 2 (D2 row 124) | ✅ M4 | ✅ approved | ✅ | **Publish** |
| `NUMBER_ParkSamples_COUNT` | ✅ `PRKN`, msg 2 (D2 row 125) | ✅ M4 | ✅ approved | ✅ | **Publish** |
| `PRES_MaxDifferencePvsPTorPTSSamples_dbar` | ✅ `PDIVMAX` (D3 p.7) | ✅ M5 | ✅ approved | ✅ | **Publish** |
| `CLOCK_AscentInitiationFromDownTimeExpiryOffset_minutes` | ✅ `TPI` (D2 row 230) | ✅ M5 | ✅ approved | ✅ | **Publish** |
| `NUMBER_PRESSamplesDuringDescentToPark_COUNT` | ✅ `NPMK` (D2 row 233) | ✅ M5 | ✅ approved | ✅ | **Publish** |
| `NUMBER_AscendingCTDSamplesInternalCounter_COUNT` | ✅ `LEN`, msg 1 | ✅ since 6A.3 | ✅ approved | ✅ | **Publish** |

`TPI` deserves a note. In the completion report I withheld it because
`JULD_ASCENT_START` is 0/339 populated in every reference, so the *derived time*
cannot be validated. That reasoning holds for the trajectory field but **not**
for the technical file: `CLOCK_AscentInitiationFromDownTimeExpiryOffset_minutes`
is the raw signed-minute offset, which is directly decoded and needs no
external validation. Publishing the raw offset while continuing to withhold the
unvalidatable derived timestamp is the consistent position.

### Group C — newly identified approved labels (2)

| Parameter | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---|---|---|---|---|
| `FLAG_CTDStatus_hex` | ✅ SBE41 word (D4 p.20 / D5 p.21) | ✅ M3 | ✅ approved | ✅ | **Publish** |
| `FLAG_TelonicsPTTStatus_hex` | ✅ byte 9 on 1010 (D5 p.21) | ✅ M3 | ✅ approved id 1002 | ✅ | **Publish as raw hex** |

`TELONICS` bit meanings remain undocumented, so the raw byte is rendered as hex
with **no interpretation**. Publishing the observation is honest; inventing bit
names would not be.

### Group D — genuinely blocked (unchanged)

| Parameter | Q4 answer | Why still withheld |
|---|---|---|
| 3 × `VOLTAGE_*`, 3 × `CURRENT_*`, `PRESSURE_InternalVacuum_inHg` | ❌ **No** | Conversion published (D4 p.23) and verified, but the DAC's "store average of decoded values" rule is unresolved. Category **D**, not a policy choice. |
| `PRESSURE_AirBladder_COUNT` on 1010 | ❌ **No** | Source byte identified, but ±1 residual is the same averaging rule. |
| `PRESSURE_InternalVacuumParkEnd_inHg` | ❌ **No** | `VAC` **counts** are decoded (M5), but the inHg conversion needs the same unresolved rule. Counts retained internally; not published under an inHg label. |

The distinction that matters: Groups A–C were withheld because of *someone
else's publication policy*. Group D is withheld because of a *genuine gap in our
knowledge*. Only the first kind should have been reversed.

---

## 3. What changed

`TECH_PARAMETER_ORDER` grew from 7 to 25 approved labels; emitted parameters per
float went **7 → 24**. Example, WMO 2902222 cycle 327:

```
FLAG_ProfileTermination_hex                            = 801     <- verified
PRES_SurfaceOffsetNotTruncated_dbar                    = -0.4    <- verified
POSITION_PistonSurface_COUNT                           = 163     <- verified
TIME_PumpMotor_seconds                                 = 0       <- verified
POSITION_PistonProfile_COUNT                           = 30      <- verified
POSITION_PistonPark_COUNT                              = 83      <- verified
FLAG_CTDStatus_hex                                     = 00      <- new
FLAG_TelonicsPTTStatus_hex                             = 00      <- new
NUMBER_RepositionsDuringPark_COUNT                     = 1       <- new
NUMBER_ParkSamples_COUNT                               = 216     <- new
PRES_MaxDifferencePvsPTorPTSSamples_dbar               = 0.6     <- new
CLOCK_AscentInitiationFromDownTimeExpiryOffset_minutes = 0       <- new
NUMBER_PRESSamplesDuringDescentToPark_COUNT            = 6       <- new
NUMBER_AscendingCTDSamplesInternalCounter_COUNT        = 58      <- new
NUMBER_ArgosPositions_COUNT                            = 7       <- new
NUMBER_ArgosPositioningClass0..3/A/B/Z_COUNT           = 0,1,2,4,0,0,0
NUMBER_TransmissionFloatFramesComplete_COUNT           = 175     <- new
NUMBER_TransmissionFloatFramesCrcOk_COUNT              = 146     <- new
```

### Guarding against self-deception

Adding parameters must not let a real regression hide. Two safeguards:

1. **No name collisions.** The 18 new labels are provably disjoint from the
   14 reference labels; the 6 shared ones are unchanged. So the audit's
   name-matched comparison cannot be diluted.
2. **`GDAC_VERIFIED_TECH_PARAMETERS`** records the 7 labels proven against GDAC,
   with a test asserting the set stays at exactly 7.

### Independent verification

I re-derived the ARGOS statistics straight from the raw files and compared them
with the emitted rows: **308/312 exact**.

The 4 exceptions are all WMO 2901339 cycle 38, the one cycle assembled from two
raw files. The decoder keeps the richer observation (9 fixes / 139 frames over
1 fix / 19 frames); my verification script naively used the last file. **The
implementation is right and the check script was wrong** — the same class of
error, in the opposite direction, as my first run, which used the wrong cycle
mapping for decoder 1005 (`PRF − 1`, not `PRF + 256`) and produced 263 spurious
mismatches.

Two mutation tests confirm the new guards bite: remapping class 3 to the class-2
label, and omitting zero-valued classes, each fail targeted tests.

---

## 4. Regression

```
ruff check / ruff format / mypy --strict   clean
pytest -q                                  559 passed  (was 553)
audit_mono_profile_values                  1813/1813 bit-identical
audit_technical_admt                       531/531 (100.0%)
audit_mono_profile_admt                    pass: 11
audit_trajectory_admt / metadata           structural_parity: 4
audit_engineering_decode                   0 unexplained
```

Science untouched; GDAC-comparable agreement unchanged at 531/531.

---

## 5. Conclusion

| Question | Answer |
|---|---|
| Fully derivable from documented telemetry? | **16 of 16 yes** |
| Already decoded internally? | **16 of 16 yes** (10 as attributes, 6 from M3–M5) |
| Representable within ADMT? | **Yes** — all approved for decoders 1005/1010; the table is an open, unlimited name/value structure |
| Omitted solely due to DAC publication policy? | **Yes for 16** |
| Should we publish? | **Yes — now implemented (18 new labels)** |

The reviewer was right. I had used GDAC output as a specification when it is a
regression reference, and the approved-label files inside the container
contradicted my conclusion. Publishing these costs nothing in parity, is
standards-compliant by the manual's own criterion, and materially increases the
decoder's completeness.

Group D remains withheld — and that boundary is now sharper: **capability limits
are respected, policy limits are not.**
