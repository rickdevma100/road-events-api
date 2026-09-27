import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class EventMetadataSchema(BaseModel):
    event_id: uuid.UUID
    detected_at: datetime
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    gps_accuracy_m: float = Field(..., ge=0.0)
    speed_before_kmh: float = Field(..., ge=0.0)
    speed_after_kmh: float = Field(..., ge=0.0)
    acceleration_peak_mps2: float = Field(..., ge=0.0)
    photo_sha256: str = Field(..., min_length=64, max_length=64)


class EventUploadResponse(BaseModel):
    event_id: uuid.UUID
    status: str
    photo_sha256: str


class IncidentSchema(BaseModel):
    alert_id: uuid.UUID
    state: str = Field(..., pattern="^(active|cleared)$")
    detected_at: datetime
    source: Optional[str] = "automatic"
    cleared_at: Optional[datetime] = None


class RideStatusUpdateRequest(BaseModel):
    sequence: int = Field(..., ge=0)
    observed_at: datetime
    ride_state: str = Field(..., pattern="^(active|suspended|ended)$")
    speed_kmh: Optional[float] = None
    last_valid_speed_at: Optional[datetime] = None
    motion_state: str = Field(..., pattern="^(starting|moving|slow|stopped|unknown)$")
    incident: Optional[IncidentSchema] = None


class RideStatusResponse(BaseModel):
    accepted_sequence: int
    bulb_status: str
    desired_mode: str


class RoadEventDetail(BaseModel):
    event_id: uuid.UUID
    detected_at: datetime
    latitude: float
    longitude: float
    gps_accuracy_m: float
    speed_before_kmh: float
    speed_after_kmh: float
    acceleration_peak_mps2: float
    photo_sha256: str
    distance_meters: Optional[float] = None
