from datetime import datetime, timedelta, timezone

import h3
import pytest
from fastapi import HTTPException

from api.zoom import choose_source_table, parse_and_validate_bbox, zoom_to_resolution


def test_h3_consistency():
    lat, lng = 12.9716, 77.5946
    cell1 = h3.latlng_to_cell(lat, lng, 9)
    cell2 = h3.latlng_to_cell(lat, lng, 9)
    assert cell1 == cell2, "Same coordinate must produce identical H3 cell"
    assert h3.is_valid_cell(cell1)

def test_h3_parent_hierarchy():
    lat, lng = 12.9716, 77.5946
    cell9 = h3.latlng_to_cell(lat, lng, 9)
    parent8 = h3.cell_to_parent(cell9, 8)
    parent7 = h3.cell_to_parent(cell9, 7)
    parent6 = h3.cell_to_parent(cell9, 6)

    assert h3.cell_to_parent(parent8, 7) == parent7
    assert h3.cell_to_parent(parent7, 6) == parent6

def test_zoom_to_resolution_mapping():
    assert zoom_to_resolution(8.0) == 6
    assert zoom_to_resolution(9.0) == 6
    assert zoom_to_resolution(10.0) == 7
    assert zoom_to_resolution(11.0) == 7
    assert zoom_to_resolution(12.0) == 8
    assert zoom_to_resolution(13.0) == 8
    assert zoom_to_resolution(14.0) == 9
    assert zoom_to_resolution(16.0) == 9

def test_source_table_selection():
    now = datetime.now(timezone.utc)
    # <= 7 days -> demand_cells
    short_window = now + timedelta(days=6)
    assert choose_source_table(now, short_window) == "demand_cells"

    # exactly 7 days -> demand_cells
    seven_days = now + timedelta(days=7)
    assert choose_source_table(now, seven_days) == "demand_cells"

    # > 7 days -> demand_daily
    long_window = now + timedelta(days=8)
    assert choose_source_table(now, long_window) == "demand_daily"

def test_bbox_validation():
    # Valid bbox
    w, s, e, n = parse_and_validate_bbox("77.5,12.9,77.7,13.1", zoom=12)
    assert (w, s, e, n) == (77.5, 12.9, 77.7, 13.1)

    # Inverted longitude (w >= e)
    with pytest.raises(HTTPException) as exc:
        parse_and_validate_bbox("77.7,12.9,77.5,13.1", zoom=12)
    assert exc.value.status_code == 422

    # Inverted latitude (s >= n)
    with pytest.raises(HTTPException) as exc:
        parse_and_validate_bbox("77.5,13.1,77.7,12.9", zoom=12)
    assert exc.value.status_code == 422

    # Too large for zoom 14
    with pytest.raises(HTTPException) as exc:
        parse_and_validate_bbox("70.0,10.0,80.0,20.0", zoom=15)
    assert exc.value.status_code == 422
