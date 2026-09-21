/**
 * Real geographic basemap data — Natural Earth 110m (public domain),
 * published as TopoJSON by the `world-atlas` npm package and decoded with
 * `topojson-client` (the same data stack used by d3-geo / Observable).
 *
 * The TopoJSON is imported with `?raw` so it is BUNDLED into the app:
 * the map renders offline, in sandboxed previews, and from `file://` —
 * no CDN or network request is ever made for the basemap.
 */
import { feature } from "topojson-client";
import landRaw from "world-atlas/land-110m.json?raw";
import countriesRaw from "world-atlas/countries-110m.json?raw";

export interface WorldGeo {
  /** GeoJSON FeatureCollection of land polygons (continents + islands). */
  land: any;
  /** GeoJSON FeatureCollection of admin-0 countries (borders + land). */
  countries: any;
}

let cached: WorldGeo | null = null;

export function getWorldGeo(): WorldGeo {
  if (!cached) {
    const landTopo = JSON.parse(landRaw);
    const countriesTopo = JSON.parse(countriesRaw);
    cached = {
      land: feature(landTopo, landTopo.objects.land) as any,
      countries: feature(countriesTopo, countriesTopo.objects.countries) as any,
    };
  }
  return cached;
}
