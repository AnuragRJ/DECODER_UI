# Indian EEZ Monitoring — Final Implementation Report (spec §20)

**Date:** 2026-09-15 · **Scope:** `decoder-ui/` only · **Commits:** `8bbf6e2` → `75ee674` → `8267ecd` → `8ab6448` → `91ef0ef` → `a75313b` → current-state/pulse refinement → teal/cyan color refinement → bottom-left toggle-gated alert → smooth fade in/out (this commit)
**Companion evidence:** [`EEZ_VERIFICATION.md`](EEZ_VERIFICATION.md) (54-item checklist),
[`../data/geography/README.md`](../data/geography/README.md) (dataset provenance)

---

## 1. Dataset identity

| Field | Value |
|---|---|
| Name | Maritime Boundaries Geodatabase: Maritime Boundaries and Exclusive Economic Zones (200NM) |
| Publisher | Flanders Marine Institute (VLIZ) — marineregions.org |
| Version / release date | World EEZ v12 — 2023-10-25 (low-resolution variant) |
| Download URL | https://doi.org/10.5281/zenodo.16314546 (`World_EEZ_v12_20231025_LR.zip`) |
| Archive MD5 (verified) | `96f624b6a74bd08ac80d8894c4a61e09` — equals publisher checksum |
| Features retained | MRGID 8480 (Indian EEZ, mainland incl. Lakshadweep — 1,659,500 km²), MRGID 8333 (Indian EEZ, Andaman & Nicobar — 664,448 km²) |
| CRS | EPSG:4326 (WGS 84), `[lon, lat]` order |
| License | CC-BY-4.0 (license text retained in source archive; VLIZ citation in provenance doc) |
| Official status | **External scientific reference dataset. NOT an official Government of India / INCOIS product.** An official public Indian-government EEZ GIS download was searched for first and none was retrievable; VLIZ terms explicitly state the data has no legal value. |
| Artifact path | `decoder-ui/data/geography/india_eez.geojson` (2 features, ~578 KB) |
| Serving endpoint | `GET /api/geography/india-eez` — re-validates the artifact per load (exact MRGID set / India-only / Polygon|MultiPolygon), `503` if unprovisioned, refuses substituted geometry; headers declare provenance + `X-Dataset-Status: external-reference-not-official-incois` |

## 2. Implementation summary

### UI (map layer + control) — `frontend/src/components/FleetOceanMap.tsx`

The layer is painted **inside the map's pan/zoom world group**, i.e. it inherits
the same `view(tx,ty,k) · base` transform as the basemap and every marker — no
pixel offsets, no CSS shifts, no second projection:

```tsx
{eez?.layerOn && eezPaths ? (
  <g style={{ pointerEvents: "none" }} data-eez-layer>
    <path d={eezPaths.d} fill="rgba(20,160,150,0.11)" fillRule="evenodd" stroke="none" data-eez-fill />
    <path d={eezPaths.d} fill="none" fillRule="evenodd" stroke="rgba(103,232,249,0.22)"
          strokeWidth={3} vectorEffect="non-scaling-stroke" pointerEvents="none" />
    <path d={eezPaths.d} fill="none" fillRule="evenodd" stroke="rgba(103,232,249,0.85)"
          strokeWidth={1.15} strokeDasharray="5,4" vectorEffect="non-scaling-stroke" data-eez-boundary />
  </g>
) : null}
```

Region styling (teal/cyan GIS refinement): translucent deep-teal fill at 11%
(8–15% band, satellite basemap stays visible) + thin brighter cyan dashed
boundary strictly stronger than the fill + a soft under-stroke, so the Indian
EEZ reads as a geographic *region*, not a bare line — no neon, no opaque
fills, no red geography. Legend gains `float inside Indian EEZ` plus teal/cyan
`Indian EEZ boundary` / `Indian EEZ region` swatches only while ON. Red/orange
is reserved for the in-EEZ float pulse and the alert notification.

Current-state float distinction (pulse refinement): a float whose latest
valid decoded position is classified `INDIAN_EEZ` keeps its yellow marker, but
the marker core itself visibly scales (r 4 → 5.8 → 4, ×1.45, 1.2 s ease-in-out
SMIL loop with the `<animate>` living ON the rendered circle — declarative,
zero React re-renders, zero PIP recompute, no JS timers; zoom/pan/selection
only update cx/cy/fill so the animation never detaches), accompanied by a
restrained red/orange ring + soft secondary halo oscillation — all rendered
**only while the layer is ON**. It encodes **current geographic state only**,
is derived for exactly the backend-truth inside set (never hardcoded WMOs),
and stays centered on the real marker coordinates at every zoom level.
Entry/exit trajectory diamonds use the same red operational family as the
notification.

The `MAP LAYERS` floating control (dark/translucent, collapsible, one instance
shared by normal + Full Screen) holds the **Indian EEZ** toggle — OFF by default,
disabled in `unavailable` and `loading` states with honest status text, and an
`EEZ events (N)` history section. Toggle flips render flags only.

### Classification module — `frontend/src/utils/indiaEez.ts`

Exact even-odd ray casting over the union of both Indian features — the same
fill rule as the rendered SVG, so the map and classifier cannot disagree:

```ts
function ringContains(ring: number[][], lon: number, lat: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 2; i < ring.length - 1; j = i, i++) {
    const [xi, yi] = ring[i]; const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
```

Trajectory order enforced (`CYCLE_NUMBER`, `JULD` tiebreak); invalid positions
dropped (never classified elsewhere); transitions only on actual consecutive
flips; single neutral wording builder:

> “WMO 2901339 entered the Indian EEZ between Cycle 49 and Cycle 50 based on the available decoded positions”

### Alert logic — `frontend/src/store/useDecoderStore.ts` + `components/EezCombinedAlert.tsx`

Stable identity + append-only history + aggregate-before-render + dismiss-without-delete:

```ts
const have = new Set(get().eezTransitions.map((t) => t.id));
const fresh = transitions.filter((t) => !have.has(t.id)); // first occurrence wins
if (fresh.length > 0) set({ eezTransitions: [...get().eezTransitions, ...fresh] });
// combined dismiss: mark every current id dismissed atomically — history untouched,
// only genuinely NEW ids arriving later can re-surface the single panel
```

Cached classification → latest valid position per WMO → filter CURRENT
`INDIAN_EEZ` → unique sorted WMOs → drop dismissed (`inside|<wmo>`) → render
**ONE** panel. Title is exactly “Indian EEZ Alert” with
`N float(s) currently inside EEZ` + WMO-only rows — zero cycle numbers, zero
historical Entry/Exit content (transitions stay in MAP LAYERS history but
never populate the alert); banned enforcement wording absent everywhere
(asserted in tests). The panel wears a **restrained red operational-warning
family** — red warning glyph + `• WMO …` rows + dark translucent surface +
light text (`role="alert"`) — communicating current monitoring state, never a
decoder failure, crash or system error. It renders only when the Fleet Map is
expanded / Full Screen (the normal compact view renders no alert UI);
collapsing hides it without deleting classification, and
toggle/zoom/pan/resize/selection/rerender can never duplicate it (pure
derivation, verified by e2e #22/#23).

## 3. Verification results (all on REAL backend data — no mocks)

| Suite | Result | Highlights |
|---|---|---|
| `pytest decoder-ui/tests` | **54/54** | artifact truth, loader rejection matrix, endpoint honesty |
| `frontend vitest` | **83/83** | PIP parity vs production artifact, transitions, store lifecycle, EEZ visual SSR contracts (toggle-gated marker-scale pulse on the real core + secondary halo, teal/cyan region styling, teal/cyan legend, red event diamonds), combined-alert contract (toggle-ON + expanded single bottom-left current-state WMO panel, zero cycle/event content, toggle-OFF hides, dedupe, 6-row cap, dismiss-keeps-classification, newly-inside re-surface, wording safety) |
| EEZ layer e2e (`npm run test:eez`) | **27/27** | OFF-default, pristine OFF map (incl. zero halos/animations), transform invariance over zoom/pan, label-in-bbox registration, per-cycle truth == backend-derived, normal view never alerts, OFF→ON→OFF exact identity, single control in Full Screen + toggle-ON + expanded ONE bottom-left current-state alert with backend-identical inside-WMO rows (no-cycle regex), alert hidden on collapse/toggle-OFF, 300 ms fade in/out on toggle, 1 fetch/session; teal region fill 8–15% band + brighter cyan boundary, ON-only teal/cyan legend swatches, inside-float marker cores visibly scaling 4→5.8→4 on the real element (centered, 1.2 s SMIL + secondary halo), animations stop when OFF, current-state ≠ event, red alert family + `role="alert"`, zero banned wording page-wide, toggle-OFF-hides + select/zoom/pan/collapse no-duplicate matrix, dismiss-keeps-classification without resurrection |
| `fleetMap.e2e.mjs` | **14/14** | unchanged map contract preserved |
| `geoVerify.mjs` | **10/10** | basemap/geography invariants intact |
| `decodeAllGating.e2e.mjs` | **16/16** | Decode-All idempotency intact |
| `ingestionArrivals.e2e.mjs` | **17/17** | Task-3 ingestion contract intact |

Live proof on the real fleet: WMO 2901339's latest valid decoded position
(C71, 18.236 N / 69.731 E) classifies `INDIAN_EEZ` — exactly ONE combined
panel ("1 float currently inside EEZ · WMO 2901339") with zero cycle/event
content, and exactly one visibly scaling marker on the live map; every other
float correctly contributes no rows and no pulse, and the normal compact view
shows zero alert UI. (The float's 5 historical transitions remain in
MAP LAYERS → EEZ events history only.)

## 4. Constraints confirmation

- **`src/argo_decoder/` — untouched** (0 modified files; core decoder logic unchanged). ✅
- No map redesign: basemap, size, zoom controls, yellow markers, trajectory logic, WMO labels, colors and interaction preserved; layer OFF renders the byte-identical DOM structure. ✅
- No hardcoded WMOs/coordinates/cycles/membership/events anywhere in feature code; fixtures used only in unit tests. ✅
- EEZ status never merged into processing status; alerts never make compliance/legal claims; toggle never recomputes or destroys state. ✅
- Performance: one-time geometry fetch (exactly 1 per session), memoized classification, no refetch/recompute on toggle/zoom/pan/resize/Full Screen/remount. ✅
