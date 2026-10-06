from datetime import datetime

from fastapi import HTTPException


def zoom_to_resolution(zoom: float) -> int:
    """
    Maps map zoom level to H3 resolution.
    Zoom <= 9   -> Res 6 (~3.2 km)
    Zoom 10-11  -> Res 7 (~1.2 km)
    Zoom 12-13  -> Res 8 (~460 m)
    Zoom >= 14  -> Res 9 (~175 m)
    """
    z = round(zoom)
    if z <= 9:
        return 6
    elif z <= 11:
        return 7
    elif z <= 13:
        return 8
    else:
        return 9

def choose_source_table(from_dt: datetime, to_dt: datetime) -> str:
    """
    Selects source table based on query window duration:
    <= 7 days: 'demand_cells' (hourly)
    > 7 days:  'demand_daily' (daily rollups)
    """
    delta = to_dt - from_dt
    if delta.total_seconds() > 7 * 86400:
        return "demand_daily"
    return "demand_cells"

def parse_and_validate_bbox(bbox_str: str, zoom: float) -> tuple[float, float, float, float]:
    """
    Parses 'w,s,e,n' bbox string and validates geographical bounds and scale limits.
    Raises HTTPException(422) if invalid.
    """
    parts = bbox_str.split(",")
    if len(parts) != 4:
        raise HTTPException(
            status_code=422,
            detail="bbox must be formatted as 'w,s,e,n' (western lng, southern lat, eastern lng, northern lat)"
        )
    try:
        w = float(parts[0])
        s = float(parts[1])
        e = float(parts[2])
        n = float(parts[3])
    except ValueError:
        raise HTTPException(status_code=422, detail="bbox coordinates must be valid numbers")

    if w < -180 or e > 180 or s < -90 or n > 90:
        raise HTTPException(status_code=422, detail="Coordinates out of bounds (-180..180, -90..90)")

    if w >= e:
        raise HTTPException(status_code=422, detail="Invalid bbox: west must be strictly less than east (antimeridian not supported)")

    if s >= n:
        raise HTTPException(status_code=422, detail="Invalid bbox: south must be strictly less than north")

    # Guard against bbox far larger than zoom justifies to prevent huge queries
    delta_lng = e - w
    delta_lat = n - s
    res = zoom_to_resolution(zoom)

    # Maximum degree spans allowed per resolution
    max_spans = {
        9: 0.8,   # Zoom >= 14
        8: 2.0,   # Zoom 12-13
        7: 6.0,   # Zoom 10-11
        6: 60.0   # Zoom <= 9
    }

    max_allowed = max_spans.get(res, 60.0)
    if delta_lng > max_allowed or delta_lat > max_allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Bounding box is too large for the requested zoom/resolution (res {res}). Please zoom in or expand at lower zoom."
        )

    return w, s, e, n
