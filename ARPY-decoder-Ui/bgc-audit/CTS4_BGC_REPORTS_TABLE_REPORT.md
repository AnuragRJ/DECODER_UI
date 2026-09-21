# CTS4 BGC reports + measurement table — continuation report (2026-09-16)

Completes the remaining approval-free §G items from `CTS4_BGC_UI_REPORT.md`.
Commit: `07534b6` in `/home/user/incois-arpy-decoder`. Server left running
on :8000 with the rebuilt frontend. Still parked (need explicit approval):
`src/argo_decoder/` G2/G3 fixes, concurrency guard, RTQC modal catalogue
for BGC tests.

## A. What was built

**Reports (all values from the run's own cycle records — the same evidence
the Results page renders; legacy floats render exactly as before):**
- `report_data.py`: new `FloatBgcReport` per float — BR files, cycles with
  BGC, series points (non-fill sensor measurements), N_PROF values, sensor
  params, BGC-only + flagged cycles — plus `summary_line()` shared by PDF
  and email. Feeds the per-float narrative (BGC sentences) and the
  assessment ("BGC findings").
- `pdf_report.py`: per-float BGC line in Section 4 (model-composed; the
  renderer still derives nothing).
- `email_notifier.py`: "BGC Summary" section in plain text + HTML, shown
  only when the report model carries BGC evidence (no model → no claim).

**Frontend:**
- `ResultsWorkspace`: "BGC measurement records" block after the BGC charts —
  one level-by-level table per data-bearing profile, columns in file order
  with file units, span-adaptive decimals, QC chips, hover-linked to the
  charts via the same composite level ids. All-fill profiles excluded (they
  stay as missing-data notices, never tabulated as fake data).
- `ScientificProfileChart`: `decimalsForSpan` exported and shared by chart
  + table so both format identical values.

In-repo doc `decoder-ui/docs/CTS4_BGC_SUPPORT.md` updated (Reports section,
table paragraph, scope list).

## B. E2E verification ledger (real APIs, real data)

| Check | Result |
|---|---|
| Forced batch `batch-1789554959-8a1c` (2902086 + 1902844) | 2/2 completed: 2902086 16/15/1/34, 1902844 23/23/0/27, email sent, PDF generated |
| 2902086 run cycles | 16 sorted; C103 BR-only + G2; C99 4 BGC profiles + 141 CTD samples |
| PDF text extraction (`pypdf`, 6 pp.) | "BGC findings — 16 BR … 18601 measurement(s) … C103 flagged … C103 BGC-only"; per-float narrative + BGC line present |
| Email content (direct model call) | Plain "BGC SUMMARY" + HTML "BGC Summary" both carry the full line incl. `N_PROF 3/4`, 9 params, C103 flags |
| Legacy float in reports | 1902844 `has_bgc=False`, zero BGC text anywhere |
| `tsc --noEmit` + production build | Clean; bundle contains "BGC measurement records", "BGC-ONLY CYCLE", "SUSPECTED WRITER ARTIFACT" |
| Pre-commit audit | Every marker in all 12 touched files grep-verified present (see §C) |

## C. Process lessons (important for future sessions)

1. **Same-file parallel edits are lossy.** Multiple `edit_file` calls to
   one file inside a single tool block report success but only a subset
   persists (last write wins). Lost-and-restored this turn: the `bgc` model
   field, the assessment "BGC findings" block, the email HTML placeholder,
   the chart's `decimalsForSpan` export + span guard. Rule: ONE edit per
   file per message; always grep-verify after.
2. **Turn-end snapshots keep dropping the commit** (second occurrence:
   `8bf3455` gone, HEAD back at `838eb4b`) while the working tree survives.
   Mitigation used: re-commit at turn end + full marker audit before it.
   Snapshot also wipes `:8000`, `frontend/dist`, `node_modules`, pip
   packages — recovery each restore: pip reinstall, `npm ci` + build,
   server restart. `data/runs`, `data/batches`, `output/` persist.
3. **"Run not found" for old batch items** is the known pre-restore async-
   persist loss (daemon threads killed at turn end), not a regression;
   fresh batches persist correctly.

## D. How to view

:8000 preview → Results workspace → any 2902086 cycle: BGC cards +
measurement tables; C103: BR-only + G2 notice. Batch email/PDF carry the
same BGC evidence in prose.
