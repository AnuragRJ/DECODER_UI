# G2 fix — completion record (2026-09-17)

Design: `G2_FIX_DESIGN.md` §3 (as-written final rule). Approval: user `ask_user`
`g2_fix` (G2 backend fix only; G3 / concurrency guard / RTQC-status still parked).

## Change (writer-only, one file)

`incois-arpy-decoder/src/argo_decoder/writer/nc.py` (+115/−26):

- New helpers: `_PROFILE_KEY_TO_PARAM`, `_CORE/_BGC_PARAM_ORDER`,
  `_OPTODE/_FLBB_SENSOR_KEYS`, `_key_measured` (present + non-empty + any
  non-fill, fill = NaN or >= 90000), `_measured_row_params` (canonical-order
  filter; core keys for R, BGC keys for BR; DOXY/BBP700 sensor completion;
  PRES forced; padded/truncated to N_PARAM).
- `write_profile` builds `measured` per row from profile content; the positional
  `template[i % 4]` path is deleted.
- `_write_station_parameters` / `_write_parameter_calib` take `measured_rows`;
  `PARAMETER_DATA_MODE` defaults = "R" exactly where the row labels a param;
  all 9 data/QC mask sites key on `measured[i]`.

No decoder, RTQC, service, or frontend change. No N_PROF/N_PARAM/dims/attrs change.

## Layout forensics (decisive, from row-1 PRES values)

- 103/144/046/050 = `[primary, near-surface (0–5 dbar), FL]` → row 2 was
  labeled/masked as a DOXY row (silent FL loss).
- 017/033 = `[primary, single optode record (809.8/1063.4 dbar), FL]` → row 1
  was labeled/masked as a DOXY row AND wiped by `doxy_missing` (one-sided);
  R017/033 row 1 additionally OVER-claimed TEMP/PSAL (labels claimed params
  with no data — the R diffs are this over-claim removal, zero data bytes).

## Acceptance ledger (§4)

1. **C103 fixed**: BR row 2 =
   `[PRES, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700, CHLA, CHLA_FLUORESCENCE,
   BBP700]`; `matches_g2_signature: False`; stays BGC-only (no R file);
   FLUO/BETA/CHLA/CHLA_F recovered 143/143 (QC 0/0/3/1); BBP700 labeled but
   fill (no CTD — honest); PROFILE_CHLA_QC `  F` matches healthy-file semantics.
2. **Byte-parity**: pre/post decode of all 10 staged groups → 266/274 identical
   modulo 4 timestamp vars; the 8 diffs are EXACTLY the predicted set
   (6 BR data+label recovery, 2 R label-only). Synthetic fixtures 6/6 identical
   incl. `doxy_missing` and `INCOIS_CORRECTED` branches. Service output for
   2902086 ≡ harness output 31/31.
3. **Service E2E**: 2902086 completed (C103 evidence above); 1902844 23/23/0
   with identical cycles and identical content (only run-stamped
   history/XML timestamps advance); forced 2-float batch 2/2, PDF 6 pp
   ("19173 measurement(s)" = 18601 + 572 recovered; C103 "BGC-only" wording,
   no flag language), email sent with the same BGC summary line; bundle
   strings present; pytest 54/54, vitest 83/83.
4. **Writer-only**: single-file diff; decoder/RTQC/service/frontend untouched.

Harness (scratch, not committed): `/tmp/g2/` (`decode_all.py`, `compare.py`,
`synth.py`, `patch_writer.py`, trees `A/Aprime/B`, `SA/SB`, `VA/VB`).
Pre-fix oracle: `/tmp/g2/A` (+ `Aprime` determinism twin).
Observed honest signal (RTQC verdict on recovered data, not a defect):
BR2902114_017 BBP700 single level QC 4 (value 2.53e-4, positive).
