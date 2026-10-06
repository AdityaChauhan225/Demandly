from pydantic import BaseModel, ConfigDict, Field


class CellCount(BaseModel):
    h3: str
    count: int

class CellsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    res: int
    source: str
    from_: str = Field(..., alias="from", validation_alias="from", serialization_alias="from")
    to: str
    cells: list[CellCount]
    suppressed: bool
    k: int

class TimeWindow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(..., alias="from", validation_alias="from", serialization_alias="from")
    to: str

class ZoneRank(BaseModel):
    rank: int
    h3: str
    center: tuple[float, float]
    count: int
    previous: int
    growth_pct: float

class TopZonesResponse(BaseModel):
    window: TimeWindow
    previous_window: TimeWindow
    zones: list[ZoneRank]

class HourCount(BaseModel):
    hour: int
    count: int

class ZoneHourlyResponse(BaseModel):
    h3: str
    hours: list[HourCount]
    peak_hours: list[int]

class ResolutionInfo(BaseModel):
    zoom_range: str
    res: int
    approx_edge: str

class MetaResponse(BaseModel):
    categories: list[str]
    time_range: dict[str, str | None]
    k: int
    epsilon: float
    resolutions: list[ResolutionInfo]
    total_cells: int
    total_events: int

class RawEventInput(BaseModel):
    lat: float | None = None
    lng: float | None = None
    ts: str | None = None
    category: str | None = None

class BatchIngestRequest(BaseModel):
    batch_id: str
    events: list[RawEventInput]

class BatchIngestResponse(BaseModel):
    accepted: int
    rejected: int
    duplicate_batch: bool

class HealthResponse(BaseModel):
    status: str
    postgres: bool
    redis: bool
    backend_mode: str
