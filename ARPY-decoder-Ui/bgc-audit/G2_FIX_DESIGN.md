# G2 backend fix — design proposal (NOT implemented, awaiting approval)

Read-only analysis of `src/argo_decoder/writer/nc.py`. No source file was
modified. Implementing this design requires explicit approval because it
touches `src/argo_decoder/`.

## 1. Defect restated (observed)

`BR2902086_103.nc`: N_PROF=3 with profile 2 labeling DOXY channels
(`PRES,C1PHASE_DOXY,C2PHASE_DOXY,TEMP_DOXY,DOXY`) while every labeled
channel is entirely fill — yet cycle 103 measured FL (fluorometer) data.
The UI flags it (`matches_g2_signature`) and refuses to plot it. The data
loss is in the WRITER, not the decoder: the samples exist upstream.

## 2. Root cause (code-located)

`write_profile_file()` in `src/argo_decoder/writer/nc.py`:

1. `template = BGC_STATION_PARAMETERS_TEMPLATE` (4 fixed rows: PRES-only,
   PRES-only, DOXY-row, FL-row), then for non-4 layouts:
   `template = [template[i % len(template)] for i in range(n_prof)]`
   → for N_PROF=3 the rows become [PRES, PRES, DOXY-row].
2. `_write_station_parameters(...)` writes STATION_PARAMETERS from
   `template[i][j]` — labels come from POSITION, not measurement.
3. Every data variable is masked by template membership:
   `if pname not in template[i]: arr[i,:] = FLOAT_FILL`.

Cycle 103's profile list order is [primary, near, FL]: real FL data sits
at index 2, but template row 2 is the DOXY row → FL params masked to fill,
DOXY params labeled but dataless. Labels and data are BOTH wrong, in
opposite directions. (`PARAMETER`, `PARAMETER_DATA_MODE`, and the calib
blocks use the same positional template and inherit the same defect.)

## 3. Fix design

Replace positional templating with measured-presence keying, in the writer
only (no decoder/RTQC changes):

1. Derive each profile row's parameter list from the profile dict's actual
   measured keys (map via the existing `_RTQC_SOURCE_KEY`-style key→param
   table), capped at N_PARAM per row as today.
2. Write STATION_PARAMETERS / PARAMETER / PARAMETER_DATA_MODE from those
   per-row lists instead of `template[i]`.
3. Mask each variable's row by whether the profile measured it, not by
   template membership (equivalently: keep `_prepare_2d` output, drop the
   template-mask loop for rows whose list contains the param).
4. Keep the 4-row templates as the N_PROF=4 fast path ONLY if byte-identical
   output can be proven (see §4); otherwise delete the positional path so
   the two cannot diverge again.

Out of scope: G3 (never reproduced — no fix can be designed without a
reproducing case; explicitly NOT bundled with this change).

## 4. Acceptance criteria (must all hold before merge)

1. Frozen-path decode of group 12170/2902086: `BR…_103.nc` has N_PROF=3
   with row 2 labeled `[PRES, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700,
   CHLA, CHLA_FLUORESCENCE, BBP700]` and non-fill FL series; C103 UI
   G2 flag clears while the cycle stays BGC-only (no R exists — unchanged).
2. Byte-parity: every previously-healthy R/BR file across all 10 staged
   groups is byte-identical before/after (proves the N_PROF=4 path is
   untouched). Any diff fails the change.
3. Full service E2E re-run: 301 batch + legacy parity (1902844 23/23/0),
   PDF/email text checks, UI bundle strings — same ledger as prior phases.
4. No changes outside `src/argo_decoder/writer/` (+ tests, if any exist
   for the writer). Decoder, RTQC, service, and frontend untouched.

## 5. Blast radius if approved

Writer behavior changes ONLY for files where the profile order/content
deviates from the 4-row assumption — today exactly one file in the corpus
(`BR2902086_103.nc`). All other outputs must be byte-identical per §4.2.
