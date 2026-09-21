# Indian EEZ Geographic Monitoring — Verification Report

**Feature:** Indian EEZ map layer, per-cycle EEZ classification, trajectory
entry/exit analysis and neutral notifications in the Argo Float Decoder UI.
**Scope enforcement:** decoder-ui only; `src/argo_decoder/` untouched
(confirmed below). **Date:** 2026-09-15. **Commits:** dataset+core `8bbf6e2`,
UI+alerts `75ee674`, docs `8267ecd`/`8ab6448`, visual refinement `91ef0ef`,
combined-alert refinement this file.

---

## 1 — Dataset verification (spec §1–§3)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Acquired an authentic, verifiable Indian EEZ dataset BEFORE UI work | ✅ | Marine Regions **World EEZ v12 (2023-10-25)**, publisher Flanders Marine Institute (VLIZ), via the VLIZ-owned Zenodo record `10.5281/zenodo.16314546` |
| 2 | Official Government of India / INCOIS source sought first | ✅ | Web search performed: no publicly downloadable official Indian EEZ boundary GIS artifact retrievable (documented in `data/geography/README.md`); sanctioned external fallback adopted per spec |
| 3 | Dataset is documented as **external reference — NOT official INCOIS** | ✅ | `data/geography/README.md` provenance table; backend headers `X-Dataset-Status: external-reference-not-official-incois`; UI wording never claims official status |
| 4 | Authenticity proven (publisher checksum) | ✅ | Archive MD5 `96f624b6a74bd08ac80d8894c4a61e09` == publisher-declared md5 at download time |
| 5 | India-only feature set | ✅ | Exactly MRGID 8480 + MRGID 8333 (`SOVEREIGN1 = 'India'`); loader + parser reject any other feature set |
| 6 | Valid GeoJSON, Polygon/MultiPolygon | ✅ | pytest `test_geography.py`; TS `parseIndiaEez` structural validation |
| 7 | CRS declared + WGS84 lon/lat | ✅ | EPSG:4326 in artifact `crs`, ring coordinate ranges enforced |
| 8 | Closed rings / hole semantics | ✅ | every ring closed (validated backend + frontend) |
| 9 | India-only extent guard | ✅ | union lon [65.639, 95.697], lat [3.841, 24.059]; parser throws on non-India extents |
| 10 | PIP-suitable geometry (topologically valid, correct inside/outside) | ✅ | GEOS `is_valid` on union; PIP battery on ARAB/BAY/ANDAMAN/foreign points (python + TS, 3 independent extractions agree) |
| 11 | No invention/approximation/manual drawing | ✅ | coordinates extracted verbatim; no simplify/reproject/edits whatsoever |
| 12 | Provenance recorded in project docs | ✅ | name, source URL, version, release date, checksum, license (CC-BY-4.0), terms-of-use, official status disclaimer, extraction rule, dead ends |
| 13 | License compatible + attribution | ✅ | CC-BY-4.0 with VLIZ citation recorded; license text retention noted |

## 2 — Layer control & visualization (spec §5–§6, §14)

| # | Check | Result | Evidence |
|---|---|---|---|
| 14 | `MAP LAYERS` floating control exists, dark/translucent, compact, subordinate | ✅ | `FleetOceanMap.tsx` control; screenshots `/tmp/eezshots/eez-normal.png` |
| 15 | `Indian EEZ` toggle **OFF by default** | ✅ | store default `false`; e2e #2 |
| 16 | OFF state renders NO layer nodes (boundary/fill/label/legend) | ✅ | e2e #3 counts 0/0/0/0/0 |
| 17 | Layer OFF = original map preserved exactly | ✅ | e2e #12 exact svg **string identity** across OFF→ON→OFF |
| 18 | ON state: professional teal/cyan GIS REGION treatment — translucent deep-teal fill `rgba(20,160,150,0.11)` (inside 8–15% band, basemap stays visible), thin brighter cyan dashed boundary `rgba(103,232,249,0.85)` strictly stronger than fill, soft under-stroke, compact cyan `INDIAN EEZ` label | ✅ | non-scaling strokes; e2e #5/#17 (band + hierarchy + no-neon/no-red-geography assertions) |
| 19 | Legend: OFF → float/trajectory only (compact); ON adds `float inside Indian EEZ` + teal/cyan `Indian EEZ boundary`/`Indian EEZ region` swatches (same treatment as the polygon), removed again when OFF | ✅ | e2e #3/#5/#18/#18b + SSR tests; no non-map info in legend (legend order can vary) |
| 20 | Toggle = visualization-only | ✅ | toggle flips render flags only; classification/history untouched (store tests + e2e #12) |
| 21 | No geometry refetch/remount/recompute on toggle | ✅ | memoized parse + one-time fetch; e2e #15 (exactly 1 request/session) |
| 22 | Unavailable geometry → control disables row + honest note, nothing approximated | ✅ | `loadEezGeometry` unavailable path; vitest `eez.test.ts` |

## 3 — CRS / geographic alignment (spec §16–§18)

| # | Check | Result | Evidence |
|---|---|---|---|
| 23 | Boundary painted in the map's real world transform (inside pan/zoom group) | ✅ | rendered inside `<g data-world-transform>`; no pixel offsets/CSS shifts anywhere |
| 24 | Same path `d` across zoom and pan (geometry never rebuilt/shifted) | ✅ | e2e #6 + #8 (`d` identical) |
| 25 | Label anchored to a REAL interior lon/lat, projected via map transform | ✅ | `findInteriorAnchor` (deterministic, inside-tested), toScreen projection; e2e #7 label-in-bbox |
| 26 | even-odd fill rule == classifier PIP rule | ✅ | both use even-odd parity on identical rings |
| 27 | Aligned across zoom/pan/resize/Full Screen | ✅ | e2e #6/#8/#13/#14; geoVerify resize suite still 10/10 |

## 4 — Per-float & trajectory analysis (spec §7–§10)

| # | Check | Result | Evidence |
|---|---|---|---|
| 28 | Per-cycle status `INDIAN_EEZ`/`OUTSIDE_INDIAN_EEZ` from real decoded LAT/LON only | ✅ | classifier runs on valid WGS84 coords only; invalid positions dropped, never forced |
| 29 | Status strictly separate from processing status | ✅ | store fields `eez*` only; `RunStatusBadge` untouched; vitest asserts no batch/run mutation |
| 30 | Float compact info adds `EEZ: Indian EEZ` / `EEZ: Outside Indian EEZ` | ✅ | header line; e2e #9 verified live |
| 31 | Trajectory order = CYCLE_NUMBER, JULD tiebreak | ✅ | `classifyTrajectory` enforces the same ordering the map uses |
| 32 | Entry/exit only on actual consecutive valid-position flips | ✅ | diff over consecutive classified cycles only; fixture + real artifact tests |
| 33 | Neutral wording exactly: "entered the Indian EEZ between Cycle N and N+1 based on the available decoded positions" | ✅ | single wording builder; vitest string assertions; live e2e cards verified |
| 34 | Never claims exact crossing location/time | ✅ | no interpolated geometry/timestamps in events; tests grep for absence |
| 35 | Per-cycle state visible on trajectory points + transition diamonds at real to-cycle positions | ✅ | `data-eez` attrs (e2e #10: 23 dots == backend truth) + event diamonds with `<title>` wording |

## 5 — Alerts (spec §11–§13)

| # | Check | Result | Evidence |
|---|---|---|---|
| 36 | Exactly ONE combined CURRENT-STATE professional alert "Indian EEZ Alert" (`N float(s) currently inside EEZ` + one row per inside WMO, zero cycle/event content), visible only in expanded / Full Screen Fleet Map | ✅ | `EezCombinedAlert`; live panel in screenshot `/tmp/eezshots/eez-combined-alert.png`; e2e #11 (normal view: zero alert UI) / #13b / #21 |
| 37 | Stable identity WMO+prevCycle+curCycle+eventType; dedupe across toggle/zoom/pan/resize/FullScreen/rerender | ✅ | id `eez|wmo|from|to|type`; append-only-first-win in store; idempotency tests; e2e #14 |
| 38 | Dismissible without deleting history | ✅ | dismiss sets flag; history list in control; store test |
| 39 | Combined alert lists CURRENTLY-INSIDE WMOs only (no cycles/events); normal view never alerts; zero panels when none inside | ✅ | e2e #11 (normal: 0 panels with a float inside) + #13b/#21: rows ≡ backend-derived inside set (WMO 2901339) with no-cycle regex; empty-set case asserted too |
| 40 | Banned wording absent (illegal/violation/unauthorized/intrusion/breach) | ✅ | neutral copy only; vitest regex assertions |
| 41 | Derived events only — no core-decoder changes, no duplicated persisted events | ✅ | events derived in the UI session from real data; nothing written back to any store of record |
| 42 | Same single implementation in normal + Full Screen; toggle/select/zoom/pan/collapse/re-expand never duplicate (≤1 panel, identical rows) | ✅ | one combined panel at workspace root gated on expansion state; one control instance; e2e #13/#13b/#14/#22/#23 |
| 43 | Performance: one-time geometry load, memoized PIP/cache, no refetch on interaction | ✅ | module singleton + fingerprint memo; e2e #15 exactly-1 fetch; steady interaction-time behavior verified in all suites (no page errors) |

## 5b — Visual refinement (current-state halo, red operational alerts, region treatment)

| # | Check | Result | Evidence |
|---|---|---|---|
| 44 | Floats currently **inside** the EEZ visually distinguished, **only while the layer is ON**: the REAL yellow marker core visibly scales (r 4 → 5.8 → 4, ×1.45, 1.2 s ease-in-out SMIL on the rendered circle) + restrained red/orange ring + soft secondary halo oscillation; base marker never permanently enlarged, no hidden cycle data; OFF removes every animation instantly | ✅ | `FleetOceanMap.tsx` marker group + `data-eez-marker-pulse`/`data-eez-halo`/`data-eez-pulse`; SSR tests + e2e #3/#19/#19b |
| 45 | Halo set ≡ backend-derived currently-inside set exactly (no hardcoded WMOs/coords, DOM→backend truth comparison), centered on real marker coords, SMIL-driven (zero React rerenders, zero PIP recompute) | ✅ | e2e #19 (`dom=2901339 truth=2901339 centered=true smil=2`), `currentStatus` memo in `ResultsWorkspace` |
| 46 | Current geographic state ≠ entry/exit event — pulse never fires from events, events never depend on current-state alone | ✅ | e2e #20 + SSR "halo without any transitions present" test |
| 47 | ONE combined CURRENT-STATE panel: restrained red operational family (red accent glyph, dark translucent `#230d12·95` surface, light text, `role="alert"`, exact title "Indian EEZ Alert", `N float(s) currently inside EEZ` + WMO-only rows); zero cycle/event content; never decoder-error/styled enforcement; capped at 6 rows + overflow line | ✅ | `EezCombinedAlert.tsx`; e2e #13b/#21 (rows ≡ inside set, no-cycle regex) + #21b banned-wording scan page-wide; vitest content/cap/dedupe/wording tests |
| 48 | EEZ region: 8–15% fill opacity band, boundary strictly brighter than fill, no neon/opaque/red region | ✅ | e2e #17 RGBA assertions + SSR styling contract |
| 49 | Legend stays compact: inside-item + region swatch ON-only, removed OFF | ✅ | e2e #18/#18b |
| 50 | Layer control unchanged (no event-dashboard creep; history line retained per prior explicit decision) | ✅ | control markup untouched apart from red family history badges |

## 5c — Combined alert aggregation (ONE panel, expanded + toggle-ON, bottom-left)

| # | Check | Result | Evidence |
|---|---|---|---|
| 51 | Cached classification → latest position per WMO → inside filter → unique WMOs → render ONE panel; no per-float / per-event components; zero cycle/event content | ✅ | `EezCombinedAlert.tsx` memos; vitest content/dedupe/single-panel tests; e2e #13b rows ≡ backend inside set (each once) + no-cycle regex |
| 52 | Normal compact view: zero alert UI; toggle OFF: zero alert UI; expanded / Full Screen + layer ON: single bottom-left panel; collapse hides without classification loss; re-expand shows the same panel (no duplicates) | ✅ | `expanded={fleetFullScreen}` prop gate; e2e #11/#13b/#14/#22 |
| 53 | Toggle governs ALL map highlighting: ON → teal region + cyan boundary + legend + bottom-left alert + visibly scaling inside markers (boundary/fill/label/alert fade smoothly over 300 ms); OFF → pristine markers/map instantly (no scale/halo/pulse/fill/boundary/legend) | ✅ | marker `<animate>` + halo gated on `layerOn`; 1.2 s ×1.45 SMIL core scale; e2e #3/#19/#19b + SSR ON/OFF tests |
| 54 | Single dismiss snapshots the inside set but keeps classification + MAP LAYERS history; collapse/expand/toggle/select/zoom/pan never resurrect it; only newly-inside WMOs re-surface the alert | ✅ | atomic `dismissAllEezNotices` (`inside|<wmo>` keys); e2e #23; vitest dismissal tests |

## 6 — Regression & overall evidence

| Suite | Result |
|---|---|
| `pytest decoder-ui/tests` | **54/54** (41 baseline + 13 geography) |
| `vitest` (frontend unit/SSR) | **83/83** (36 baseline + 16 EEZ util + 11 EEZ store + 7 EEZ visual SSR + 13 combined-alert) |
| `e2e/eezLayer.e2e.mjs` | **27/27** on REAL backend data |
| `fleetMap.e2e.mjs` | **14/14** (check 7 rewritten honestly for cover-clamped global fleets — see commit notes) |
| `geoVerify.mjs` | **10/10** |
| `decodeAllGating.e2e.mjs` | **16/16** |
| `ingestionArrivals.e2e.mjs` | **17/17** |
| `src/argo_decoder/` modified? | **NO — unchanged** (`git status` clean for that path; only `decoder-ui/` touched) |
| Live real-data proof | WMO 2901339 latest valid position (C71, 18.236 N / 69.731 E) classified `INDIAN_EEZ` → exactly ONE current-state panel ("1 float currently inside EEZ · WMO 2901339", zero cycle content) + exactly one visibly scaling marker (r 4→5.8→4) on the live teal region; its 5 historical transitions stay in MAP LAYERS history only |
