"""Unit tests for the Indian EEZ reference-geometry endpoint (``/api/geography/india-eez``).

Contract under test:

* The endpoint serves the VERIFIED dataset artifact at
  ``decoder-ui/data/geography/india_eez.geojson`` — the exact two Indian
  features (MRGID 8480 mainland+Lakshadweep, MRGID 8333 Andaman & Nicobar)
  from Marine Regions World EEZ v12, unchanged.
* Served payloads are WGS84 Polygon/MultiPolygon GeoJSON with closed rings
  and an India-only extent suitable for point-in-polygon classification.
* ``_load_india_eez`` refuses malformed/missing/substituted artifacts
  (never silently serving a different geography).
* Response headers declare honest provenance (external reference, CC-BY-4.0)
  and stable caching (one-time geometry load on the client).

Run with:
    cd decoder-ui && PYTHONPATH=service python -m pytest tests/test_geography.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient  # noqa: E402

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))

import api  # noqa: E402
from main import app  # noqa: E402

REPO_GEOJSON = Path(__file__).resolve().parents[1] / "data" / "geography" / "india_eez.geojson"
README = Path(__file__).resolve().parents[1] / "data" / "geography" / "README.md"


def _rings(geom: dict) -> list[list[list[float]]]:
    coords = geom["coordinates"]
    if geom["type"] == "Polygon":
        return coords
    assert geom["type"] == "MultiPolygon"
    out: list[list[list[float]]] = []
    for poly in coords:
        out.extend(poly)
    return out


# ---------------------------------------------------------------------------
# Artifact-on-disk verification (committed dataset is always consistent)
# ---------------------------------------------------------------------------

def test_geojson_artifact_exists_and_matches_exact_indian_feature_set() -> None:
    assert REPO_GEOJSON.is_file(), "verified dataset artifact missing"
    payload = json.loads(REPO_GEOJSON.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 2
    mrgids = sorted(f["properties"]["MRGID"] for f in payload["features"])
    assert mrgids == [8333, 8480]
    assert all(f["properties"]["SOVEREIGN1"] == "India" for f in payload["features"])
    assert all(f["properties"]["POL_TYPE"] == "200NM" for f in payload["features"])


def test_geojson_artifact_is_wgs84_closed_ring_india_only_geometry() -> None:
    payload = json.loads(REPO_GEOJSON.read_text(encoding="utf-8"))
    crs_name = payload.get("crs", {}).get("properties", {}).get("name", "")
    assert "4326" in crs_name
    all_lons: list[float] = []
    all_lats: list[float] = []
    for f in payload["features"]:
        assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
        for ring in _rings(f["geometry"]):
            assert len(ring) >= 4
            assert ring[0] == ring[-1], "ring must be closed"
            for c in ring:
                assert len(c) == 2
                lon, lat = c
                assert isinstance(lon, (int, float)) and isinstance(lat, (int, float))
                assert -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0
            all_lons.extend(c[0] for c in ring)
            all_lats.extend(c[1] for c in ring)
    # India-only extent (mainland + Lakshadweep + Andaman & Nicobar union)
    assert 63.0 < min(all_lons) < 70.0
    assert 94.0 < max(all_lons) < 100.0
    assert 2.0 < min(all_lats) < 9.0
    assert 23.0 < max(all_lats) < 25.0


def test_provenance_readme_documents_source_version_license() -> None:
    text = README.read_text(encoding="utf-8")
    for needle in (
        "World EEZ v12",
        "2023-10-25",
        "Flanders Marine Institute",
        "marineregions.org",
        "zenodo.16314546",
        "CC BY 4.0",
        "EPSG:4326",
        "8480",
        "8333",
        "NOT an official Government of India / INCOIS product",
        "96f624b6a74bd08ac80d8894c4a61e09",
    ):
        assert needle in text, f"provenance README must state {needle!r}"


# ---------------------------------------------------------------------------
# Loader validation (never serve malformed/substituted geography)
# ---------------------------------------------------------------------------

def test_loader_accepts_committed_artifact() -> None:
    payload = api._load_india_eez()
    assert len(payload["features"]) == 2


def test_loader_rejects_missing_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "INDIA_EEZ_GEOJSON", tmp_path / "absent.geojson")
    with pytest.raises(FileNotFoundError):
        api._load_india_eez()


@pytest.mark.parametrize(
    "mutator,desc",
    [
        (lambda p: p.pop("type"), "missing collection type"),
        (lambda p: p.update(features=[]), "no features"),
        (lambda p: p["features"].pop(), "incomplete feature set"),
        (
            lambda p: p["features"][0].update(properties={"MRGID": 9999, "SOVEREIGN1": "India", "POL_TYPE": "200NM"}),
            "wrong MRGID",
        ),
        (
            lambda p: p["features"][0].update(properties={"MRGID": 8480, "SOVEREIGN1": "Maldives", "POL_TYPE": "200NM"}),
            "non-India sovereign",
        ),
        (lambda p: p["features"][0]["geometry"].update(type="LineString"), "non-area geometry"),
    ],
)
def test_loader_rejects_malformed_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutator, desc: str) -> None:
    payload = json.loads(REPO_GEOJSON.read_text(encoding="utf-8"))
    mutator(payload)
    target = tmp_path / "india_eez.geojson"
    target.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(api, "INDIA_EEZ_GEOJSON", target)
    with pytest.raises((ValueError, KeyError)):
        api._load_india_eez()


# ---------------------------------------------------------------------------
# REST surface
# ---------------------------------------------------------------------------

@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_endpoint_serves_verified_geometry_with_honest_headers(client: TestClient) -> None:
    r = client.get("/api/geography/india-eez")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "max-age" in r.headers.get("cache-control", "")
    assert "Marine Regions" in r.headers.get("x-dataset-source", "")
    assert "external" in r.headers.get("x-dataset-status", "")
    payload = r.json()
    assert payload["type"] == "FeatureCollection"
    assert sorted(f["properties"]["MRGID"] for f in payload["features"]) == [8333, 8480]


def test_endpoint_reports_unavailable_geometry_honestly(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "INDIA_EEZ_GEOJSON", tmp_path / "absent.geojson")
    r = client.get("/api/geography/india-eez")
    assert r.status_code == 503
    assert "not provisioned" in r.json()["detail"]
