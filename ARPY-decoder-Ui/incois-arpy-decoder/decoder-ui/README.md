# Euro-Argo Float Decoder Workstation

A web-based operational monitoring and execution UI for the Euro-Argo / decArgo Python float decoding pipeline.

## Features & Implementation

### 1. Single Float Execution (`[ DECODE FLOAT ]`)
- Decodes the currently selected float via the real Python backend pipeline.
- Complete 18-stage execution: Input Ingestion, Metadata Loading, Cycle Grouping, Platform Decoding, Sensor Calibration, Derived Parameter Synthesis, Real-Time Quality Control (RTQC 15-test suite), Product Generation (ADMT v3.1 NetCDF), Output Verification.
- Real-time event streaming over WebSocket / SSE with sub-millisecond latency.

### 2. Fleet Batch Execution (`[ DECODE ALL TODAY'S FLOATS ]`)
- Automatic discovery of all input floats across ARGOS and Iridium SBD telemetry archives.
- Sequential fleet ingestion using the identical real Python decoding engine.
- Fleet progress banner tracking Total Floats, Completed, Running, Pending, Failed, and Stopped counts.
- Live pipeline view streams the current executing float in real-time.

### 3. Cooperative Cancellation (`[ STOP DECODE ]`)
- Safe, non-corrupting cooperative cancellation for both single float runs and fleet batch executions.
- Immediately stops active decoder processing and cancels remaining queued batch floats.
- Preserves all generated logs, stage histories, and generated NetCDF products on disk.
- Sets run status to `STOPPED` with exact duration and timestamp.

### 4. Persistent Run & Batch History
- Every run and batch execution is saved atomically to disk (`decoder-ui/data/runs/` and `decoder-ui/data/batches/`).
- Survives browser refreshes, server restarts, and system reboots.
- Persistent searchable history modal (`[ HISTORY ]`).

### 5. Fleet Decode Summary / Results (`[ VIEW DECODE RESULTS ]`)
- Comprehensive overview of fleet execution:
  - Total Floats, Successful, Failed, Stopped.
  - Profiles Generated, Profiles Missing, Total NetCDF Products, Batch Duration.
  - Interactive table of all floats with statuses, cycle counts, profile counts, output files, duration, and error diagnostics.

### 6. Interactive Clickable Diagnostics
- Any error message in the Batch Summary or Run History is highlighted and clickable.
- Clicking an error navigates directly to the exact run, restores historical logs, and auto-scrolls to the exact error event with full pre/post event context and Python traceback details.

### 7. Historical Run Replay (`[ VIEW RUN ]`)
- Instant one-click replay that reconstructs the complete workstation state (18-stage pipeline, RTQC metrics, cycle navigator, center log, generated NetCDF products) from saved real events.

## Architecture & Layout
- **Left Panel (~20%)**: Configuration, Float Selection, Directory Paths, Pipeline Execution Controls, System Status.
- **Center Panel (~51%)**: 18-Stage Interactive Circular Pipeline Canvas (`@xyflow/react`), Live Operation Badges, Dual Execution / Historical Center Log with Level Filtering, Search, and Clickable Diagnostic Inspect.
- **Right Panel (~29%)**: Real-Time Telemetry & Float Summary, Cycle Navigator, Live RTQC Matrix with Test Indicators, Generated NetCDF Product Directory Inspector.

### 8. Fleet Ocean Map (`Results → FLEET POSITIONS`, `[ Expand Fleet ]`)
- Real satellite/terrain Earth basemap (bundled asset `frontend/src/assets/fleet_basemap.jpg`, preloaded at app start) with a crisp Natural Earth coastline overlay — fully offline, no map tiles are ever requested at runtime.
- The map paints immediately and independently of decoded data: imagery, coastlines and graticule render as soon as the view opens; float markers simply appear on top as positions hydrate. Empty batches show an honest caption instead of a skeleton.
- Every marker sits exactly on its float's latest real decoded cycle position; trajectories render ALL real cycle points chronologically with unmodified coordinates, painted above markers so the selected float's highlight (small core + open ring) can never cover nearby cycle dots.
- Interaction: cursor-anchored wheel zoom, drag pan, animated button/double-click zoom, FIT frames the whole fleet. Selecting a float auto-frames its real trajectory (density-aware so piled-up cycles separate; re-clicking it reframes). The same map instance is shared between the normal-page band and full-screen mode, so view and selection survive Expand/Exit.

### 10. Incoming-data ingestion (NEW DATA, FTP-ready)

Phase-1 milestone: new incoming float data is detected → normalized → the float appears in the Fleet UI as **🟡 NEW DATA**. Detection is purely observational — it **never** starts decoding (the explicit Decode workflow is unchanged).

```
INCOIS FTP/SFTP/API (later)           Existing local raw stores + landing zone (today)
                │                                        │
                ▼                                        ▼
         DataSource interface  ─────────────────────────────────
         │ LocalDataSource                          FTPDataSource (connector shell)
         ▼
 normalized IngestArrival records (WMO when resolvable from real metadata, platform,
 cycle/JULD/coords only when the source genuinely carries them — nothing invented)
         ▼
 IngestionRegistry (fingerprint dedupe, silent first-scan baseline, append-only state,
 ack lifecycle, persisted under ARGO_UI_DATA_DIR/ingestion.json)
         ▼
 Fleet UI: header source pill (LOCAL / FTP truthfully) + NEW DATA count,
 Incoming-data arrivals panel, fleet-table row badges
         ▼
            User chooses Decode  →  existing ARPY decoder (untouched)
```

* **Sources** (`service/datasources/`): `LocalDataSource` watches the same raw input roots as the decoder plus a landing zone (`LOCAL_INGEST_DIR`, default `<ARGO_UI_DATA_DIR>/incoming`; one subdirectory per float association, named by WMO/PTT/IMEI). `FTPDataSource` is env-configured only, treats remote objects as opaque until the real INCOIS format spec/parser is supplied, and can only report `connected` after a real successful FTP session. No file-format, filename or packaging assumptions are made anywhere; one-file-one-float and one-file-many-floats both plug in via the same parser hook.
* **Configuration (env only, never in code/logs):** `DATA_SOURCE=local|ftp`, `FTP_HOST/PORT/USER/PASSWORD/ROOT`, `FTP/INGESTION_POLL_INTERVAL` (default 60 s), `LOCAL_INGEST_DIR`. Local/dev mode is always labelled `DEV SOURCE` in the UI; simulated data is never presented as INCOIS data.
* **REST:** `GET /api/ingestion/status` (honest source status, `test_mode` flag), `GET /api/ingestion/arrivals[?state=new]`, `POST /api/ingestion/ack` (clears the badge, history kept), `POST /api/ingestion/scan` (on-demand scan). Runtime state stays out of git (`data/ingestion.json`, `data/incoming/`).

### 11. Indian EEZ geographic monitoring (MAP LAYERS → Indian EEZ)

Optional geographic reference layer on the Fleet map plus derived per-cycle EEZ state, per-float trajectory analysis, and neutral notifications. **Decoder logic, processing status and the batch/ingestion workflows are untouched** — EEZ state is a separate, independent dimension.

* **Verified dataset (acquired first, provenance documented in [`data/geography/README.md`](data/geography/README.md)):** Marine Regions World EEZ v12 (2023-10-25), publisher Flanders Marine Institute (VLIZ) — Indian features MRGID 8480 (mainland incl. Lakshadweep) + MRGID 8333 (Andaman & Nicobar), extracted verbatim from the VLIZ-published Zenodo archive (DOI 10.5281/zenodo.16314546, MD5 verified), stored at `data/geography/india_eez.geojson` (EPSG:4326, MultiPolygon, CC-BY 4.0). This is an **external scientific reference — not an official INCOIS / Government of India dataset** (no public official download was retrievable at acquisition time). No official Indian-government geometry is served or implied anywhere. The endpoint `GET /api/geography/india-eez` re-validates the artifact on every load and refuses to serve substituted or malformed geography (503 + honest error).
* **MAP LAYERS control:** compact dark/translucent GIS-style floating panel (shared single implementation in normal and Full Screen — the live control is one instance, no duplicates). The **Indian EEZ toggle is OFF by default** and purely visual: switching it never recomputes data, destroys state, or re-fires alerts. When the geometry is unavailable the control disables the row and says so honestly (no approximate outline is ever drawn).
* **CRS-true rendering:** the region fill + boundary are built in the map's world coordinate frame and painted *inside* the pan/zoom world group, so the layer inherits the exact transform of the basemap across zoom, pan, wheel, FIT, resize and Full Screen. No pixel offsets, no CSS shifts, no separate projection. With the layer OFF the map is structurally identical to the original (verified by exact string equality in e2e).
* **EEZ as a teal/cyan maritime region (not a bare line):** smooth 300 ms fade in/out on toggle; translucent deep-teal fill at 11% opacity (inside the 8–15% band, so the satellite basemap stays visible), a thin brighter cyan dashed non-scaling boundary strictly stronger than the fill, plus a subtle soft under-stroke so the zone reads as an actual geographic region; the `INDIAN EEZ` label (cyan, matching the region) projects inside the polygon interior via the same world pipeline. No neon, no opaque fills, no red geography — floats and trajectories always stay the visual priority, with red/orange reserved for the in-EEZ pulse and the alert.
* **Current-state float distinction:** a float whose **latest valid decoded position** is inside the Indian EEZ keeps its yellow marker, but the marker core itself visibly scales (r 4 → 5.8 → 4, ×1.45, 1.2 s ease-in-out SMIL loop on the rendered circle — browser-driven, zero React re-renders, zero classification recompute, no JS timers), accompanied by a restrained red/orange ring + soft secondary halo oscillation, rendered **only while the Indian EEZ layer is ON** (layer OFF restores pristine markers instantly). This expresses *current geographic state only* — it is never tied to entry events, fires for exactly the backend-verified inside set, and stays centered on the true float coordinates at any zoom/pan.
* **Legend (compact, ON-only additions):** `float inside Indian EEZ`, `Indian EEZ boundary`, `Indian EEZ region` appear only while the layer is ON; the base `float position` / `trajectory` entries never change.
* **Per-cycle classification:** each real decoded cycle position (only valid LAT/LON) is classified with exact even-odd point-in-polygon against the Indian EEZ union (the same fill rule the SVG uses) → `INDIAN_EEZ` / `OUTSIDE_INDIAN_EEZ`. Classification is memoized; geometry is fetched exactly once per session and never re-requested (not on toggle, zoom, pan, resize, Full Screen or re-mount).
* **Trajectory analysis:** the selected float's trajectory keeps its real order (CYCLE_NUMBER, JULD tiebreak); per-cycle EEZ state rides along as attributes, and EEZ entry/exit diamonds mark the positions where consecutive *valid* positions genuinely flip sides. Descriptions are strictly neutral: “WMO 2901339 entered the Indian EEZ between Cycle 49 and Cycle 50 based on the available decoded positions” — never an invented crossing location or timestamp.
* **Alerts:** exactly **ONE combined red operational-warning panel** answering only “which floats are currently inside?” — “Indian EEZ Alert” + `N float(s) currently inside EEZ` + one compact row per inside WMO (`• WMO …`), capped at 6 rows — red accent + warning glyph, dark translucent surface, readable light text. No cycle numbers, no `Cfrom → Cto` pairs, no historical Entry/Exit content: a WMO appears iff its latest valid real position classifies inside right now (deduped WMOs, derived from cached classification — never recomputed for the alert — and cannot duplicate across toggle/zoom/pan/resize/selection/Full Screen/re-render). The panel is visible **only in the expanded / Full Screen Fleet Map** (normal compact view shows no alert UI at all); collapsing hides it without deleting classification, and a single dismiss snapshots the inside set while classification + MAP LAYERS → EEZ events history stay intact (only a newly-inside WMO can re-surface it). Entry/exit trajectory diamonds on the map use the same restrained red family.
* **Selected float compact info:** the header adds `EEZ: Indian EEZ` / `EEZ: Outside Indian EEZ` next to — never merged with — the processing status badge.
* **Wording & boundaries:** entry/exit wording is neutral and scientific everywhere (no legal/enforcement terms); the layer marks geography, it never implies compliance claims.

## Verification

From `decoder-ui/frontend/`:

| Command | What it verifies |
|---|---|
| `npm test` | 83 unit/SSR tests: EEZ core (`utils/indiaEez.test.ts` — strict artifact parsing/anti-substitution guards, exact PIP on fixtures AND the production file, per-cycle classification, stable-id transitions, neutral wording, interior anchor) + EEZ store slice (`store/eez.test.ts` — one-time truthful loading/unavailable path, classification as a separate dimension, append-only history dedupe, dismiss-keeps-classification + newly-inside re-surface) and the previously existing suites: map math invariants (`mapProjection.test.ts` — projection roundtrips, anchored zoom, clamp laws, bbox fitting, browser-resize view preservation), render contracts (`FleetOceanMap.ssr.test.tsx` — immediate world paint, no skeleton on empty data, small selection highlight, full chronological trajectory above markers), EEZ visual contracts (`FleetOceanMap.eez.ssr.test.tsx` — visibly scaling marker cores (r 4→5.8→4 SMIL on the rendered circle) + secondary halo on exactly the classified set, current-state ≠ event separation, teal-region/cyan-boundary styling with the 8–15% opacity band, ON-only legend additions, red entry/exit diamonds, OFF-state pristine markers), combined-alert contract (`EezCombinedAlert.test.tsx` — normal view renders nothing, toggle OFF renders nothing, expanded + layer-ON renders exactly one bottom-left current-state WMO panel (300 ms fade) with zero cycle/event content, dedupe, 6-row cap, dismiss-keeps-classification, newly-inside re-surface, wording safety), Decode-All gating state handling (`store/decodeAllGating.test.ts` — "already_complete" notice surfaced without entering a running state; notice cleared on any new start/Re-run All), and ingestion arrival handling (`store/ingestionArrivals.test.ts` — status/arrivals stored verbatim, discovery never enters a running state, ack refreshes). |
| `npm run test:e2e` | 15-check Playwright harness (`e2e/fleetMap.e2e.mjs`) driving the real built app in headless Chromium against a live backend with real decoded data: live Esri satellite basemap (200 tiles, 0 fails; Expand Fleet reparents the same view), marker == latest real cycle lat/lon, smooth zoom/wheel/drag, FIT framing, WMO labels hidden until hover/click (persistent: selected float only), selection auto-frame with zero covered cycle dots (genuine world-coincident cycles reported, not failed), trajectory swap, state persistence. Drives the real Decode-All button and handles both backend outcomes (fresh batch OR "already complete" notice). Requires `npx playwright install chromium` once and the backend serving a completed batch (≥2 floats with positions); override target via `MAP_E2E_BASE`, screenshots via `MAP_E2E_SHOTS`. |
| `node e2e/geoVerify.mjs` | 10 geographic-registration checks (`e2e/geoVerify.mjs`): served basemap is the genuine Esri imagery + reference service (200 tiles, 0 fails), no antimeridian seam breakage (cross-dateline view settles, all markers project finite), world view + 6 zoomed regions (India, W Africa, Europe, E Asia, S. America, N. America) + polar edges, fullscreen exit, and browser-resize state preservation (centre drift 0.00°, no off-world blank map, camera zoom preserved). Same backend/env conventions as `test:e2e`. |
| `npm run test:gating` | Decode-All idempotency contract (`e2e/decodeAllGating.e2e.mjs`, real backend + real browser): already-complete sessions never append a duplicate batch (API + rapid clicks + second tab), exact user message, [ View Results ] opens the existing completed batch, failed/incomplete floats keep the existing pending-only rules (cached floats never reprocessed), and the UI duplicates nothing. Works on any real dataset state (already-complete OR partially-failed). |
| `npm run test:eez` | 27-check Indian EEZ layer harness (`e2e/eezLayer.e2e.mjs`, real backend + real browser, no mocks): verified-dataset endpoint + provenance headers, MAP LAYERS control OFF by default, pristine OFF state, boundary/fill/label/legend rendering, **transform invariance across zoom/pan** (identical rings; label projects inside the boundary extent via the shared world pipeline — true geographic registration), selected-float `EEZ:` info line, per-cycle EEZ statuses reproduced from backend truth, **toggle-ON + expanded single current-state alert (bottom-left)** (rows ≡ backend-derived inside set, zero cycle/event content), structural identity of the map after toggling OFF, single control + state persistence across Full Screen entry/exit, geometry fetched **exactly once**, zero page errors. Visual-refinement checks on top of that: region fill opacity inside the 8–15% band with a strictly brighter boundary (no neon/opaque/red region), ON-only legend additions (inside-float + region), **inside-float halo matches exactly the backend-derived currently-inside set** (red ring centered on the real core), current state vs entry event kept separate, ON-only teal/cyan legend swatches (no red geography), inside-float markers wear a red halo ring on the real marker core (backend-truth set), current-state ≠ event separation, red current-state alert family enforced (dark surface, red accent/icon, `role="alert"`, single “Indian EEZ Alert” title, WMO rows only), zero banned wording anywhere on the page, and the combined-alert lifecycle: normal-view silence, toggle-ON + expanded single-panel aggregation (bottom-left) with backend-identical inside-WMO rows, toggle-gated pulse symmetry (ON pulses / OFF pristine), a toggle-OFF-hides + select/zoom/pan/collapse no-duplicate matrix, and dismiss-keeps-classification without resurrection. |
| `node e2e/ingestionArrivals.e2e.mjs` | 17-check ingestion flow (real backend + real browser): a fresh real-file drop in the landing zone is detected, the WMO resolved via real metadata (PTT), the float appears as NEW DATA in the panel + fleet-table row, the header pill stays honest (`LOCAL (DEV SOURCE)`, never "FTP CONNECTED"), and NO batch is auto-started anywhere; [ View float ] selects the float in the Decoder, [ Mark seen ] acknowledges the arrival (history kept). `INGEST_ZONE` overrides the drop location. |

Decode All Today’s Floats is idempotent by design: when every currently eligible float already has a genuinely successful decode from today, `POST /api/batch/decode-all` answers `status="already_complete"` (no batch created — history stays append-only) and the UI offers "Today's fleet decoding is already complete…" with `[ View Results ]` / `[ Re-run All ]`. An active batch still wins with HTTP 409.

Basemap asset provenance/calibration/regeneration: see `frontend/tools/basemap/README.md` (the committed asset regenerates byte-identically from `tools/basemap/rebuild_basemap.py`).

Backend: `PYTHONPATH=decoder-ui/service python3 -m pytest decoder-ui/tests -q` (54 tests, incl. `tests/test_geography.py`: EEZ artifact is the exact two verified Indian features with closed-ring WGS84 India-only geometry, provenance README completeness, loader rejection of missing/malformed/substituted artifacts, honest 503 + headers on the serving endpoint — plus `tests/test_ingestion.py`: DataSource contract, content-based dedupe (identical re-materialized payloads are NOT rebadged), ack/persistence, state migration, and FTP honesty — never claims a connection, never fabricates floats, credentials never leak into status/log output).
