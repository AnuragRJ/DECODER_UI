# PROVOR CTS4 (decoder 301) — Phase-2A Completion Report (2026-09-09)

## Objective

Decode SBD packets 250/252/253/254/255 per NKE 5.8, map fields to the
301 config/tech label tables, decode observed BGC measurement packets,
build raw→calibrated equations from authoritative sources, and
reverse-bootstrap coefficients from INCOIS GDAC evidence — then stop.

## Delivered

* **Decoders** (`platforms/provor_cts4_ir_sbd/`): 255 mission
  (PV/PM, dbar depths), 254 tech params (PT0–27), 253 vector tech
  (140-byte budget verified), 252 pressure samples, 251 sensor
  params, 250 sensor tech (CTD/Optode/FLBB free zones), O2 + FLBB
  BGC extraction, CTD/BGC association, 301 label maps.
* **Equations** (`equations.py`, pure math, explicit coefs): Aanderaa
  4330 DOXY chain, CHLA, BBP700, Zhang-2009 βsw. Validated vs INCOIS
  2902091 cycle 1: CHLA/BBP/βsw EXACT; DOXY meta.nc-literal with a
  documented +0.21-style publication gap (PUBLICATION-RTQC).
* **Reference CSV** (`config/metadata/provor_cts4_301_reference.csv`):
  1534 rows = 118 coefs × 13 GDAC floats, fully provenanced,
  88 family-generic / 30 float-specific by numeric-constancy audit.
  The four legacy CSV schemas are byte-untouched (frozen backend
  with an exact-join contract CTS4 rows cannot honestly join).
* **Corpus adjudication**: every 2A hypothesis pinned over 517 SBD
  files — minutes-hours, session-2 fill rule (0 breaks/270), bench
  rows, 250 pairing, per-group serials, BGC ranges, 378/378 cycle
  membership (+2 fragmented files explained).
* **Docs**: full record in
  `provor_bio_irsbd/PROVOR_CTS4_PHASE2A_DESIGN_NOTE.md`.

## Tests

27 unit + 16 corpus-integration (new); full suite 2216 passed /
1 pre-existing skip. Phase 1 untouched and green; no collateral.

## Forwarded (not 2A)

DOXY publication gap, PT26/27 semantics, tech-173 derivation rule,
253 rtc flag, 03530-c9 stab, Optode-pattern serial hypothesis
(supported, unproven), serial corroborations as Phase-2B leads.
No WMO assignment performed.

## Stop-list compliance

No NetCDF emission, R/BD publication, WMO assignment, CSV-schema
changes, final publication decisions, or broad refactor. No GitHub.
No fabrication: every coefficient carries WMO + file + variable +
interpretation; uncertain items are explicitly unresolved with
mismatch classes.
