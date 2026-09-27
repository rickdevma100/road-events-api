import uuid
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import TypeDecorator, String as SAString
from geoalchemy2 import Geography
from app.database import Base

class SafeGeographyPoint(TypeDecorator):
    """
    TypeDecorator that produces native PostGIS Geography(POINT, 4326) on PostgreSQL,
    and falls back to String on SQLite for unit tests.
    """
    impl = Geography
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect is not None and dialect.name == "sqlite":
            return dialect.type_descriptor(SAString(100))
        if dialect is not None:
            return dialect.type_descriptor(Geography(geometry_type="POINT", srid=4326))
        return SAString(100)


class RoadEvent(Base):
    __tablename__ = "road_events"

    # UUID primary key
    event_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    detected_at = Column(DateTime(timezone=True), nullable=False, index=True)

    # Scalar coordinates for rapid serialization and non-GIS queries
    latitude = Column(Float, nullable=False)   # WGS84 Latitude (-90 to +90)
    longitude = Column(Float, nullable=False)  # WGS84 Longitude (-180 to +180)

    # Spatial PostGIS point: Longitude first, Latitude second (ST_MakePoint(lon, lat))
    location = Column(SafeGeographyPoint, nullable=False)

    gps_accuracy_m = Column(Float, nullable=False)
    speed_before_kmh = Column(Float, nullable=False)
    speed_after_kmh = Column(Float, nullable=False)
    acceleration_peak_mps2 = Column(Float, nullable=False)
    photo_sha256 = Column(String(64), nullable=False)
    photo_path = Column(String(512), nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RideStatus(Base):
    __tablename__ = "ride_status"

    ride_id = Column(PG_UUID(as_uuid=True), primary_key=True)
    sequence = Column(Integer, nullable=False, default=0)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    ride_state = Column(String(32), nullable=False)  # active, suspended, ended
    speed_kmh = Column(Float, nullable=True)
    last_valid_speed_at = Column(DateTime(timezone=True), nullable=True)
    motion_state = Column(String(32), nullable=False)  # starting, moving, slow, stopped, unknown

    # Incident information
    alert_id = Column(PG_UUID(as_uuid=True), nullable=True)
    alert_state = Column(String(32), nullable=True)  # active, cleared
    alert_detected_at = Column(DateTime(timezone=True), nullable=True)
    alert_source = Column(String(16), nullable=True)  # automatic, manual
    alert_cleared_at = Column(DateTime(timezone=True), nullable=True)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BulbState(Base):
    __tablename__ = "bulb_state"

    id = Column(Integer, primary_key=True, default=1)  # Singleton row (id=1)
    controlling_ride_id = Column(PG_UUID(as_uuid=True), nullable=True)
    desired_mode = Column(String(32), nullable=False, default="restore_off")  # green, yellow, red, alert_pulse, restore_off
    desired_version = Column(Integer, nullable=False, default=1)
    pulse_deadline = Column(DateTime(timezone=True), nullable=True)

    # Pre-ride state snapshot for restoration
    pre_ride_power = Column(Boolean, nullable=True)
    pre_ride_brightness = Column(Integer, nullable=True)
    pre_ride_color = Column(String(64), nullable=True)

    applied_mode = Column(String(32), nullable=True)
    applied_version = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
