# `START_DATE` — focused final investigation before any fix

**Investigation only. No code changed.**

Question: what is the most correct behaviour for our decoder when the input is
a **partial mission archive**?

Sources: Argo User Manual v3.3 (`argo_user_manual_v3.3a.pdf`), the Coriolis
MATLAB chain, APF9A FormatNotes, raw ARGOS telemetry, and GDAC as cross-check
only.

---

## Headline

**The currently proposed fix (option B) is SAFE and is the right one — but my
earlier justification for it was wrong in one respect, and that matters.**

I previously said GDAC's `START_DATE` "is anchored on cycle 1, which agrees
with the manual". Deeper checking shows GDAC's value is **cycle 1's
`JULD_LOCATION`** — the first *surface fix after the first ascent* — which is
**not** the first descent the manual defines. So cycle-1 timing is a
**correlate, not a proxy**. Option B remains correct, but for the reason that
we cannot source the field, not because cycle 1 reproduces it.

---

## Q1 — What does `START_DATE` represent?

**SOURCE CONFIRMED.** Argo User Manual v3.3, §2.4 `meta.nc` (lines 3897-3906):

> `START_DATE:long_name = "Date (UTC) of the first descent of the float"`
> *"Date and time (UTC) of the first descent of the float."*
> `START_DATE:_FillValue = " "`

The manual defines **three separate deployment instants**, and their contrast
is the whole point:

| variable | manual definition | physical instant |
|---|---|---|
| `LAUNCH_DATE` | "Date (UTC) of the deployment" | float enters the water |
| `STARTUP_DATE` | "Date (UTC) of the activation of the float" | controller activated |
| **`START_DATE`** | **"Date (UTC) of the first descent"** | **float leaves the surface for the first time** |

So `START_DATE` is a **deployment property**, fixed for the life of the float,
and logically ordered `LAUNCH ≤ STARTUP ≤ START ≤ cycle-1 ascent`.

---

## Q2 — Is cycle-1 JULD a valid proxy, or only correlated?

**Only correlated. It is NOT a valid proxy.** *(SOURCE CONFIRMED)*

A profile `JULD` is an **ascent/surfacing** instant. The first descent happens
roughly one cycle *earlier*. Measured against GDAC:

| WMO | LAUNCH → START | cycle length | in cycle lengths |
|---|---|---|---|
| 2901339 | 263.0 h | 240 h | **1.10** |
| 2901350 | 264.0 h | 240 h | **1.10** |
| 2901328 | 152.3 h | 240 h | 0.63 |
| 2902222 | 19.7 h | 240 h | 0.08 |

On the DPF floats GDAC's `START_DATE` sits **1.10 cycle lengths after launch**.
A "first descent" cannot occur 11 days after the float was deployed when the
programmed prelude is 6 hours. Whatever GDAC publishes there, it is not
literally the first descent.

The spec-literal alternative also fails: `LAUNCH_DATE + CONFIG_MissionPreludeTime_hours`
misses GDAC by a **mean 78 h, max 258 h**, so it reproduces neither GDAC nor a
defensible independent value.

---

## Q3 — What causes the GDAC-vs-cycle-1-JULD difference?

**Reference-instant convention. SOURCE CONFIRMED — exact on 10/10 floats.**

`START_DATE` equals cycle 1's **`JULD_LOCATION`**, not its `JULD`:

| WMO | START_DATE | cyc1 `JULD` | cyc1 `JULD_LOCATION` |
|---|---|---|---|
| 2901305 | 20110215104040 | 20110215035238 (+6.80 h) | **20110215104040 (0.00)** |
| 2901328 | 20110904121919 | 20110904065218 (+5.45 h) | **20110904121919 (0.00)** |
| 2901339 | 20111227213055 | 20111227205434 (+0.61 h) | **20111227213055 (0.00)** |
| 2901350 | 20120208110937 | 20120208095208 (+1.29 h) | **20120208110937 (0.00)** |
| other 6 | — | 0.00 h | **0.00 h** |

**10/10 exact.** The 0.6–6.8 h residuals I previously could not explain are
simply the gap between the profile time and the first satellite fix — i.e.
the same profile-JULD/reference-instant question tracked as **C3**. It is
*not* telemetry loss, *not* first-descent timing, and *not* missing operator
metadata.

So GDAC's rule is **"first surface fix of cycle 1"**. That is a DAC
convention, and it **contradicts the manual's "first descent"** by about one
cycle. It is a reasonable practical stand-in — the first fix is the earliest
*observed* evidence the mission began — but it is not the specified quantity.

**Classification of the difference: E (reference/timestamp convention).**

---

## Q4 — How does Coriolis handle partial archives?

**It never derives `START_DATE` at all. SOURCE CONFIRMED.**

A grep across the whole chain for `START_DATE`, excluding variable
declarations and unrelated names (`STARTUP_`, `TRANSMISSION_START_`,
`DESCENT_START_`), returns **only 1:1 field mappings** — 20 of them, one per
`generate_json_float_meta_*` family, e.g. for APEX-Argos:

```matlab
% generate_json_float_meta_apx_argos_.m:1015
'START_DATE', 'START_DATE', ...
```

The value is copied from the operator database into the float's JSON
metadata, and `create_nc_meta_file_3_1.m:2974` merely reformats it beside
`LAUNCH_DATE` / `STARTUP_DATE` / `END_MISSION_DATE`.

Confirmed in real shipped metadata
(`decArgo_config_floats/json_float_meta_argos/6902687_meta.json`):

```
LAUNCH_DATE = '28/05/2016 12:54:00'
START_DATE  = '28/05/2016 21:45:00'     # +8.85 h, from the operator DB
```

**Consequence for partial archives:** Coriolis is completely insensitive to
which cycles are decoded. Decoding cycles 327-329 yields exactly the same
`START_DATE` as decoding cycles 1-329. **Our implementation is the only one of
the three that varies with the input set — that is the actual defect.**

---

## Q5 — Does the specification permit fill?

**Yes. SOURCE CONFIRMED, on three independent grounds.**

1. The manual declares `START_DATE:_FillValue = " "` — a fill is a defined,
   legal state.
2. Manual **§2.4.9 "Mandatory meta-data parameters"** lists the fields that
   were promoted from highly-desirable to mandatory. `START_DATE` is **not in
   that list** (verified: zero occurrences in the section). `LAUNCH_DATE` *is*.
3. Coriolis actively relies on this: `create_nc_meta_file_3_1.m:2968` guards
   the write with `if (~isempty(inputElt))`, so an empty source value leaves
   the variable at `_FillValue`. **2 of the 13 metadata JSONs shipped in the
   Coriolis repository carry an empty `START_DATE`.**

Emitting fill is therefore standard, spec-compliant behaviour — not a
degradation.

---

## Q6 — Can our 4-CSV backend supply it?

**No. SOURCE CONFIRMED.**

Scanned all four corrected sheets for any start/descent/activation column:

| file | columns | candidates |
|---|---|---|
| `meta.csv` | 31 | only `start marker` (a row delimiter, value `Column1`) |
| `sensor-info.csv` | 27 | only `start marker` |
| `config_params.csv` | 34 | `CONFIG_MissionPreludeTime_hours`, `CONFIG_DescentTo*TimeOut_hours` |
| `calib.csv` | 33 | only `start marker` |

There is no start-date field. The prelude/timeout columns are mission
*configuration*, and §Q2 shows `launch + prelude` does not reproduce a
defensible value (mean error 78 h).

---

## Recommendation

### **B — emit `START_DATE` only when the decoded run contains cycle 1; otherwise leave `_FillValue`.**

With one refinement, and one explicit caveat.

**Why B:**

* It removes the only actual defect: the value currently **changes with the
  archive window** (2902206: we publish 2025-12-31 for a float deployed in
  2016). No other decoder behaves this way; Coriolis is input-invariant.
* Fill is explicitly permitted (Q5) — `_FillValue` defined, not in the
  mandatory list, and used by Coriolis itself on 2 shipped floats.
* It never publishes a number we cannot justify, which is the standing rule
  for this project.
* Cycle 1 is the only cycle whose timing bounds the first descent at all; for
  any archive lacking it we genuinely have no evidence.

**Refinement:** when cycle 1 *is* present, use its **`JULD_LOCATION`** (first
surface fix) rather than its `JULD`. That is what the field already reduces to
for 6 of our floats, it matches all 10 GDAC values exactly, and — importantly
— it is defensible on its own terms as *the earliest observed evidence that
the mission had begun*. It should be documented as a **DAC convention that
approximates, but is not identical to, the manual's "first descent"**, since
we have proven it sits after the first ascent.

**Why not the others:**

* **A (derive from cycle 1 always)** — rejected. It would still be wrong
  whenever cycle 1 is absent, because there is nothing to derive from; and
  extrapolating backwards from cycle *N* would invent a deployment fact.
* **C (add `START_DATE` to the 4-CSV sheets, metadata only)** — this is the
  **correct long-term answer** and exactly what Coriolis does. Recommend
  requesting the column from the operator. It is not available today, so it
  cannot be this change.
* **D** — no better alternative found. `launch + prelude` fails by 78 h mean.

**Best combined path:** implement **B now** (correctness, no invented data),
and request the `start date` column so the backend can later move to **C**,
which supersedes B automatically — if the column is present, use it; else
fall back to cycle 1's `JULD_LOCATION`; else fill.

### Is the proposed fix safe to implement?

**Yes — safe, with the refinement above.** Evidence is sufficient:

* the defect is proven and unambiguous (input-dependent output);
* the remedy is spec-permitted (Q5, three independent confirmations);
* the behaviour on our two floats that already match (2901304, 2901305) is
  **unchanged**, because their archives contain cycle 1;
* it touches one metadata field and no science, QC, GROUNDED, C1 or RTQC code.

Expected effect: 2901304/2901305 unchanged and still exact; 2901328/2901339/
2901350 change from wrong-by-days to **correct** (they contain cycle 1, via
`JULD_LOCATION`); 2902201/2902203/2902206/2902222/2902223 change from
wrong-by-9-years to **fill**.

### One caveat to record

Adopting `JULD_LOCATION` makes us agree with GDAC 10/10, but the underlying
quantity still is not literally "the first descent". We should state that in
the code comment rather than imply spec-exactness. If C3 (the profile-JULD
anchor) is ever resolved, this field should be revisited with it.

---

## Correction to the previous report

`docs/SPEC_VS_CORIOLIS_INVESTIGATION.md` §1 states that GDAC's value "equals
the JULD of GDAC's own cycle 1 exactly on 6 floats and within 0.6–6.8 h on the
four DPF floats — consistent with the C3 anchor question". That is right in
direction but imprecise: the correct statement is that it equals cycle 1's
**`JULD_LOCATION`** exactly on **all 10**. The earlier text also implied
cycle-1 timing "agrees with the manual"; §Q2 here shows it does not, and the
justification for option B rests on Q4/Q5 instead.
