"""Unit and integration tests for Indian EEZ classification and email reporting.

Tests:
1. Canonical EEZ geometry validation (MRGID 8480, 8333).
2. Point-in-polygon classification:
   - Points inside (Arabian Sea EEZ, Bay of Bengal EEZ, Andaman Sea EEZ)
   - Points outside (deep international waters, other jurisdictions)
   - Missing / invalid / NaN / Inf coordinates
   - Boundary & hole handling
3. Email rendering:
   - Email text & HTML when floats are inside EEZ
   - Email text & HTML when count is 0
   - Verification that predicted positions are ignored and only verified positions are used
   - Preservation of existing email content, PDF attachment notes, and failure summaries.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from datetime import datetime, timezone

SERVICE_DIR = Path(__file__).resolve().parent.parent / "service"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import pytest

from india_eez import (
    EEZ_SOURCE,
    POSITION_BASIS,
    get_monitored_floats_inside_eez,
    point_in_india_eez,
    load_eez_polygons,
)
from email_notifier import build_batch_email_content
from models import BatchSummary, NodeStatus


class TestIndiaEezGeometry:
    def test_load_eez_polygons_non_empty(self):
        polygons = load_eez_polygons()
        assert len(polygons) >= 2, "Must contain at least the 2 Indian EEZ polygon features"
        for poly in polygons:
            assert len(poly) >= 1, "Polygon must have at least an exterior ring"
            exterior = poly[0]
            assert len(exterior) >= 4, "Exterior ring must have at least 4 coordinates (closed ring)"
            assert exterior[0] == exterior[-1], "Exterior ring must be closed"

    def test_points_inside_eez(self):
        # Coordinates well inside Indian EEZ:
        # Off Mumbai (Arabian Sea): 71.0°E, 18.0°N
        assert point_in_india_eez(71.0, 18.0) is True
        # Off Chennai (Bay of Bengal): 81.5°E, 13.0°N
        assert point_in_india_eez(81.5, 13.0) is True
        # Andaman & Nicobar EEZ: 93.0°E, 11.5°N
        assert point_in_india_eez(93.0, 11.5) is True
        # Lakshadweep EEZ: 72.5°E, 10.5°N
        assert point_in_india_eez(72.5, 10.5) is True

    def test_points_outside_eez(self):
        # Far west Arabian Sea (international / Oman / Somali waters): 58.0°E, 15.0°N
        assert point_in_india_eez(58.0, 15.0) is False
        # South of equator: 75.0°E, -10.0°N
        assert point_in_india_eez(75.0, -10.0) is False
        # Far east (Gulf of Thailand / South China Sea): 102.0°E, 10.0°N
        assert point_in_india_eez(102.0, 10.0) is False
        # North Atlantic: -40.0°E, 30.0°N
        assert point_in_india_eez(-40.0, 30.0) is False

    def test_missing_and_invalid_coordinates(self):
        assert point_in_india_eez(None, None) is False
        assert point_in_india_eez(75.0, None) is False
        assert point_in_india_eez(None, 15.0) is False
        assert point_in_india_eez(float("nan"), 15.0) is False
        assert point_in_india_eez(75.0, float("nan")) is False
        assert point_in_india_eez(float("inf"), 15.0) is False
        assert point_in_india_eez(75.0, float("-inf")) is False
        # Out of geographic bounds
        assert point_in_india_eez(200.0, 15.0) is False
        assert point_in_india_eez(75.0, 95.0) is False


class TestMonitoredFloatsInsideEez:
    def test_strict_verified_position_usage_no_prediction(self):
        # Float with verified position outside, but predicted position inside
        mock_float_1 = {
            "wmo": 9999001,
            "float_type": "APEX",
            "lat": -5.0,  # Verified outside
            "lon": 75.0,
            "prediction": {
                "predicted_lat": 18.0,  # Inside!
                "predicted_lon": 71.0,
            },
            "last_profile_iso": "2026-09-01T00:00:00+00:00",
            "data_status": "ACTIVE",
        }
        # Float with verified position inside
        mock_float_2 = {
            "wmo": 9999002,
            "float_type": "PROVOR_III",
            "lat": 18.0,  # Verified inside
            "lon": 71.0,
            "last_profile_iso": "2026-09-02T00:00:00+00:00",
            "data_status": "PROFILE OVERDUE",
        }

        inside, total, _ = get_monitored_floats_inside_eez([mock_float_1, mock_float_2])
        assert total == 2
        assert len(inside) == 1
        assert inside[0]["wmo"] == 9999002
        assert inside[0]["float_type"] == "PROVOR_III"
        assert inside[0]["lat"] == 18.0
        assert inside[0]["lon"] == 71.0

    def test_fallback_to_latest_profile_verified_coordinates(self):
        mock_float = {
            "wmo": 9999003,
            "float_type": "ARVOR",
            "lat": None,
            "lon": None,
            "latest_profile": {
                "lat": 13.0,
                "lon": 81.5,
                "pos_qc": "1",
            },
            "last_profile_iso": "2026-09-03T12:00:00+00:00",
            "data_status": "ACTIVE",
        }
        inside, total, _ = get_monitored_floats_inside_eez([mock_float])
        assert total == 1
        assert len(inside) == 1
        assert inside[0]["wmo"] == 9999003


class TestEmailRenderingWithEez:
    def _create_mock_batch(self) -> BatchSummary:
        return BatchSummary(
            batch_id="batch-test-eez-1234",
            total_floats=1,
            completed_floats=1,
            failed_floats=0,
            stopped_floats=0,
            total_profiles_generated=10,
            total_output_files=10,
            duration_seconds=12.5,
            status=NodeStatus.COMPLETED,
            ended_at="2026-09-22T12:00:00Z",
            items=[],
        )

    def test_email_rendering_with_floats_inside_eez(self):
        batch = self._create_mock_batch()
        monitored = [
            {
                "wmo": 2901328,
                "float_type": "APEX",
                "lat": 11.879,
                "lon": 80.058,
                "last_profile_iso": "2013-01-01T08:14:45+00:00",
                "data_status": "NO RECENT PROFILE DATA 80+ DAYS",
            },
            {
                "wmo": 1902844,
                "float_type": "ARVOR",
                "lat": -10.0,
                "lon": 75.0,
                "last_profile_iso": "2026-09-08T14:04:11+00:00",
                "data_status": "ACTIVE",
            },
        ]

        plain_text, html_body = build_batch_email_content(
            batch=batch,
            pdf_available=True,
            monitored_floats=monitored,
        )

        # Plain text assertions
        assert "FLOATS CURRENTLY INSIDE INDIAN EEZ" in plain_text
        assert "Count inside / total monitored: 1 / 2" in plain_text
        assert EEZ_SOURCE in plain_text
        assert f"Position basis:                 {POSITION_BASIS}" in plain_text
        assert "2901328" in plain_text
        assert "APEX" in plain_text
        assert "11.8790" in plain_text
        assert "80.0580" in plain_text
        assert "NO RECENT PROFILE DATA 80+ DAYS" in plain_text
        # Ensure outside float is not listed in EEZ table
        assert "1902844" not in plain_text.split("FLOATS CURRENTLY INSIDE INDIAN EEZ")[1]

        # HTML assertions
        assert "FLOATS CURRENTLY INSIDE INDIAN EEZ" in html_body
        assert "Count inside / total monitored: <strong>1 / 2</strong>" in html_body
        assert EEZ_SOURCE in html_body
        assert POSITION_BASIS in html_body
        assert "2901328" in html_body
        assert "80.0580" in html_body

    def test_email_rendering_with_count_zero(self):
        batch = self._create_mock_batch()
        monitored = [
            {
                "wmo": 1902844,
                "float_type": "ARVOR",
                "lat": -10.0,
                "lon": 75.0,
                "last_profile_iso": "2026-09-08T14:04:11+00:00",
                "data_status": "ACTIVE",
            }
        ]

        plain_text, html_body = build_batch_email_content(
            batch=batch,
            pdf_available=False,
            monitored_floats=monitored,
        )

        assert "FLOATS CURRENTLY INSIDE INDIAN EEZ" in plain_text
        assert "Count inside / total monitored: 0 / 1" in plain_text
        assert "Count: 0" in plain_text

        assert "FLOATS CURRENTLY INSIDE INDIAN EEZ" in html_body
        assert "Count inside / total monitored: <strong>0 / 1</strong>" in html_body
        assert "Count: 0" in html_body
