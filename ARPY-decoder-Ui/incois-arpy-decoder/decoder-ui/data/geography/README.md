# Geography reference data — Indian EEZ

`india_eez.geojson` — verified reference geometry of the Indian Exclusive Economic Zone used for
the map overlay and the point-in-polygon (PIP) classification `INDIAN_EEZ` / `OUTSIDE_INDIAN_EEZ`.

## Provenance

| Field | Value |
|---|---|
| Dataset | Maritime Boundaries Geodatabase: Maritime Boundaries and Exclusive Economic Zones (200NM) |
| Publisher | Flanders Marine Institute (VLIZ), Marine Regions (`marineregions.org`) |
| Version | World EEZ v12 (released 2023-10-25), low-resolution variant (`World_EEZ_v12_20231025_LR`) |
| Download URL | Zenodo mirror published by VLIZ: <https://doi.org/10.5281/zenodo.16314546> (`World_EEZ_v12_20231025_LR.zip`) |
| Archive checksum (MD5) | `96f624b6a74bd08ac80d8894c4a61e09` — verified byte-for-byte against the publisher’s checksum at acquisition time |
| License | CC BY 4.0 (<https://creativecommons.org/licenses/by/4.0/>); license text bundled in the source archive (`LICENSE_EEZ_v12.txt`) |
| Citation | Flanders Marine Institute (2023). Maritime Boundaries Geodatabase: Maritime Boundaries and Exclusive Economic Zones (200NM), version 12. <https://doi.org/10.14284/632> |
| CRS | EPSG:4326 (WGS 84 geographic, `[lon, lat]` axis order) |
| Official status | **External scientific reference dataset — NOT an official Government of India / INCOIS product.** No authoritative Indian-government downloadable EEZ boundary was publicly retrievable at acquisition time; per the feature specification, Marine Regions World EEZ v12 is the sanctioned fallback reference. VLIZ states the data is for scientific/educational/research use and has no legal value. |

## Extraction rule (exactly reproducible)

Source table `eez_v12_lowres` (285 world features) filtered by attribute
`SOVEREIGN1 = 'India'`, yielding the two Indian features retained verbatim:

| MRGID | GEONAME | POL_TYPE | AREA_KM2 |
|---|---|---|---|
| 8480 | Indian Exclusive Economic Zone (mainland incl. Lakshadweep) | 200NM | 1,659,500 |
| 8333 | Indian Exclusive Economic Zone (Andaman and Nicobar Islands) | 200NM | 664,448 |

No coordinates were edited, simplified, densified, or re-projected. Attribute values are
preserved; property keys were uppercased from the shapefile for JSON ergonomics only.
A membership query is answered against the **union** of the two features.

## Validation performed at acquisition time

- GeoJSON structure: `FeatureCollection` with 2 features, geometries `MultiPolygon`/`Polygon`,
  all rings closed, all coordinates 2-D `[lon, lat]` within WGS 84 ranges — **PASS**.
- India-only extent: union bounds lon [65.639, 95.697], lat [3.841, 24.059] — **PASS**.
- Topological validity via GEOS (`shapely` union `is_valid = true`) — **PASS**.
- PIP suitability smoke battery: inside/outside sample points across Arabian Sea, Bay of Bengal,
  Andaman Sea, coastal margins, and foreign waters — **PASS** (raster sanity check shows the
  correct Indian EEZ wedge shape with Lakshadweep envelope and Andaman lobe).
- Archive MD5 equals the publisher-declared checksum — **PASS** (authentic, untampered).

### Acquisition notes / dead ends (documented for audit)

- The Marine Regions GeoServer WFS layer `MarineRegions:eez` returned geometrically degenerate
  output for MRGID 8480 (thin coastal ribbons instead of the full solid polygon; reproduced
  identically through both GeoJSON and SHAPE-ZIP exports, while other countries such as Belgium
  exported correctly). That served-layer artifact was rejected; the published low-res archive on
  the VLIZ-owned Zenodo record was used instead and validates cleanly.
- An official Indian-government (INCOIS / Survey of India) EEZ boundary GIS download was searched
  for first; none was publicly retrievable, so the sanctioned external fallback above is used and
  is documented as external, never as an official INCOIS dataset.
