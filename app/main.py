import os
import json
import uuid
import time
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, desc

from app.config import settings
from app.database import get_db, SessionLocal, engine, Base
from app.models import RoadEvent, RideStatus, BulbState
from app.schemas import (
    EventMetadataSchema, EventUploadResponse,
    RideStatusUpdateRequest, RideStatusResponse,
    RoadEventDetail
)
from app.storage import storage_service
from app.bulb_service import get_bulb_adapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

# Auto-create tables on startup (creates PostGIS and app tables)
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    logger.warning(f"Note on DB schema init: {e}")

# Global flag for bulb controller background loop
_loop_running = True

async def bulb_controller_loop():
    """
    Background loop serializing smart bulb control:
    - Applies desired state to bulb
    - Handles dazzling 1s ON / 1s OFF pulse for 60 seconds
    - Recovers pulse deadline from PostgreSQL after server restarts
    - Handles speed timeouts (>15s)
    """
    global _loop_running
    bulb = get_bulb_adapter()
    logger.info("Bulb controller background loop started.")

    while _loop_running:
        try:
            db = SessionLocal()
            try:
                bulb_state = db.query(BulbState).filter_by(id=1).first()
                if not bulb_state:
                    bulb_state = BulbState(id=1, desired_mode="restore_off", desired_version=1)
                    db.add(bulb_state)
                    db.commit()
                    db.refresh(bulb_state)

                now = datetime.now(timezone.utc)

                # Check stale speed for active ride
                if bulb_state.controlling_ride_id:
                    ride = db.query(RideStatus).filter_by(ride_id=bulb_state.controlling_ride_id).first()
                    if ride and ride.ride_state == "active":
                        # Speed stale timeout: 15 seconds
                        speed_stale = False
                        if ride.last_valid_speed_at:
                            speed_stale = (now - ride.last_valid_speed_at).total_seconds() > settings.STALE_SPEED_TIMEOUT_SEC

                        # Stale condition only resets if NO unresolved incident exists
                        has_active_incident = (ride.alert_state == "active")
                        if speed_stale and not has_active_incident:
                            if bulb_state.desired_mode != "restore_off":
                                logger.info(f"Ride {ride.ride_id} speed went stale. Switching bulb to restore_off.")
                                bulb_state.desired_mode = "restore_off"
                                bulb_state.desired_version += 1
                                db.commit()

                desired = bulb_state.desired_mode

                if desired == "alert_pulse":
                    # Check pulse deadline
                    if bulb_state.pulse_deadline and now <= bulb_state.pulse_deadline:
                        # 1 second ON, 1 second OFF
                        if int(time.time()) % 2 == 0:
                            bulb.set_color("red")
                        else:
                            bulb.set_power(False)
                        bulb_state.applied_mode = "alert_pulse"
                    else:
                        # 60s pulse finished -> transition to solid red until explicitly cleared
                        bulb.set_color("red")
                        bulb_state.applied_mode = "red_solid"
                    db.commit()

                elif desired != bulb_state.applied_mode or bulb_state.applied_version < bulb_state.desired_version:
                    success = False
                    if desired == "green":
                        success = bulb.set_color("green")
                    elif desired == "yellow":
                        success = bulb.set_color("yellow")
                    elif desired == "red":
                        success = bulb.set_color("red")
                    elif desired == "restore_off":
                        snapshot = {
                            "power": bulb_state.pre_ride_power,
                            "brightness": bulb_state.pre_ride_brightness,
                            "color": bulb_state.pre_ride_color
                        }
                        success = bulb.restore(snapshot)
                    else:
                        success = bulb.turn_off()

                    if success:
                        bulb_state.applied_mode = desired
                        bulb_state.applied_version = bulb_state.desired_version
                        bulb_state.last_error = None
                    else:
                        bulb_state.last_error = "Failed to communicate with bulb"
                    db.commit()

            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in bulb controller loop: {e}", exc_info=False)

        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop_running
    _loop_running = True
    bg_task = asyncio.create_task(bulb_controller_loop())
    yield
    _loop_running = False
    bg_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Road Events API",
    version="1.0.0",
    description="FastAPI Backend for Road-Event Capture App & Smart Bulb Automation",
    lifespan=lifespan
)

def verify_token(authorization: Optional[str] = Header(None)) -> str:
    """Validates the Bearer token configured for mobile client authorization."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected 'Bearer <token>'"
        )
    token = authorization.split("Bearer ")[1].strip()
    if token != settings.DEVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device token"
        )
    return token


@app.get("/healthz", tags=["Diagnostics"])
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint for Kubernetes liveness & readiness probes."""
    db_ok = False
    try:
        db.execute(text("SELECT 1")).scalar()
        db_ok = True
    except Exception as e:
        logger.error(f"DB health check error: {e}")

    return {
        "status": "healthy" if db_ok else "unhealthy",
        "database": "connected" if db_ok else "disconnected",
        "storage_backend": settings.STORAGE_BACKEND,
        "bulb_adapter": settings.BULB_ADAPTER
    }


@app.post("/api/v1/events", response_model=EventUploadResponse, tags=["Events"])
async def upload_event(
    metadata: str = Form(...),
    photo: UploadFile = File(...),
    token: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Ingests road event photos and telemetry:
    - Multipart validation (metadata JSON + JPEG up to 5 MiB)
    - SHA-256 verification of image bytes
    - Atomic storage persistence (MinIO S3 or local volume)
    - PostGIS geography insertion (longitude first, latitude second)
    - Idempotent deduplication (201 Created for new, 200 OK for retry, 409 for conflict)
    """
    # 1. Parse metadata JSON
    try:
        data = json.loads(metadata)
        meta = EventMetadataSchema(**data)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid metadata JSON: {e}")

    # 2. Read and validate photo bytes
    photo_bytes = await photo.read()
    if len(photo_bytes) > settings.MAX_PHOTO_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Photo size ({len(photo_bytes)} bytes) exceeds 5 MiB limit."
        )

    # 3. Check for existing event (Idempotency)
    existing_event = db.query(RoadEvent).filter_by(event_id=meta.event_id).first()
    if existing_event:
        if existing_event.photo_sha256.lower() == meta.photo_sha256.lower():
            # Idempotent replay: return 200 OK
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "event_id": str(meta.event_id),
                    "status": "stored",
                    "photo_sha256": meta.photo_sha256
                }
            )
        else:
            # Same UUID but different content
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Event {meta.event_id} already exists with different photo SHA-256"
            )

    # 4. Save photo (MinIO S3 or filesystem) and verify SHA-256
    try:
        photo_path = storage_service.save_photo(meta.event_id, photo_bytes, meta.photo_sha256)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error(f"Storage save error: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to persist image")

    # 5. Insert PostGIS row
    wkt_location = f"SRID=4326;POINT({meta.longitude} {meta.latitude})"
    new_event = RoadEvent(
        event_id=meta.event_id,
        detected_at=meta.detected_at,
        latitude=meta.latitude,
        longitude=meta.longitude,
        location=wkt_location,
        gps_accuracy_m=meta.gps_accuracy_m,
        speed_before_kmh=meta.speed_before_kmh,
        speed_after_kmh=meta.speed_after_kmh,
        acceleration_peak_mps2=meta.acceleration_peak_mps2,
        photo_sha256=meta.photo_sha256.lower(),
        photo_path=photo_path
    )
    db.add(new_event)
    db.commit()

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "event_id": str(meta.event_id),
            "status": "stored",
            "photo_sha256": meta.photo_sha256
        }
    )


@app.put("/api/v1/rides/{ride_id}/status", response_model=RideStatusResponse, tags=["Rides"])
def update_ride_status(
    ride_id: uuid.UUID,
    payload: RideStatusUpdateRequest,
    token: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Processes real-time ride telemetrics and incident alerts:
    - Monotonic sequence enforcement
    - Clock skew tolerance (20s past / 5s future)
    - Incident alert priority & dazzling pulse timing
    - Atomic ride state & bulb state synchronization
    """
    now = datetime.now(timezone.utc)
    obs_time = payload.observed_at

    # Clock skew validation for live status (allow up to 25s past and 10s future skew)
    time_diff = (now - obs_time).total_seconds()
    clock_skew_valid = (-10.0 <= time_diff <= 25.0)

    # 1. Lookup or create RideStatus record
    ride = db.query(RideStatus).filter_by(ride_id=ride_id).first()
    if ride:
        if payload.sequence < ride.sequence:
            # Stale sequence: ignore update but return current acknowledged state
            bulb_state = db.query(BulbState).filter_by(id=1).first()
            return RideStatusResponse(
                accepted_sequence=ride.sequence,
                bulb_status=bulb_state.applied_mode if (bulb_state and bulb_state.applied_mode) else "pending",
                desired_mode=bulb_state.desired_mode if bulb_state else "restore_off"
            )
        elif payload.sequence == ride.sequence:
            # Identical retry vs Conflict
            if ride.ride_state == payload.ride_state and ride.motion_state == payload.motion_state:
                bulb_state = db.query(BulbState).filter_by(id=1).first()
                return RideStatusResponse(
                    accepted_sequence=ride.sequence,
                    bulb_status=bulb_state.applied_mode if (bulb_state and bulb_state.applied_mode) else "pending",
                    desired_mode=bulb_state.desired_mode if bulb_state else "restore_off"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Sequence {payload.sequence} already processed with divergent content"
                )
    else:
        # First update for this ride
        ride = RideStatus(ride_id=ride_id, sequence=payload.sequence, observed_at=obs_time, ride_state=payload.ride_state, motion_state=payload.motion_state)
        db.add(ride)

    # 2. Update ride record fields
    ride.sequence = payload.sequence
    ride.observed_at = obs_time
    ride.ride_state = payload.ride_state
    ride.speed_kmh = payload.speed_kmh
    ride.motion_state = payload.motion_state
    if payload.last_valid_speed_at:
        ride.last_valid_speed_at = payload.last_valid_speed_at

    # Handle incident payload if present
    if payload.incident:
        ride.alert_id = payload.incident.alert_id
        ride.alert_state = payload.incident.state
        ride.alert_detected_at = payload.incident.detected_at
        ride.alert_source = payload.incident.source
        ride.alert_cleared_at = payload.incident.cleared_at

    # 3. Compute desired bulb state
    bulb_state = db.query(BulbState).filter_by(id=1).first()
    if not bulb_state:
        bulb_state = BulbState(id=1, desired_mode="restore_off", desired_version=1)
        db.add(bulb_state)

    # Take ownership of bulb if no current controlling ride or this is the controlling ride
    if bulb_state.controlling_ride_id is None or bulb_state.controlling_ride_id == ride_id:
        bulb_state.controlling_ride_id = ride_id

        # Determine target mode
        if ride.alert_state == "active":
            # Active incident overrides all colors
            if bulb_state.desired_mode != "alert_pulse":
                bulb_state.desired_mode = "alert_pulse"
                bulb_state.desired_version += 1
                # If alert arrived within 2 minutes of detection, set 60s pulse; else solid red directly
                alert_age = (now - ride.alert_detected_at).total_seconds() if ride.alert_detected_at else 0
                if alert_age <= 120.0:
                    bulb_state.pulse_deadline = now + timedelta(seconds=settings.INCIDENT_PULSE_DURATION_SEC)
                else:
                    bulb_state.pulse_deadline = now  # Immediate solid red
        elif ride.ride_state == "ended":
            bulb_state.desired_mode = "restore_off"
            bulb_state.desired_version += 1
            bulb_state.controlling_ride_id = None
        else:
            # Normal ride state: only apply if clock skew is valid
            if clock_skew_valid:
                target_mode = "green"
                if ride.motion_state in ["starting", "moving"]:
                    target_mode = "green"
                elif ride.motion_state == "slow":
                    target_mode = "yellow"
                elif ride.motion_state == "stopped":
                    target_mode = "red"
                elif ride.motion_state == "unknown":
                    target_mode = bulb_state.desired_mode  # Retain previous

                if bulb_state.desired_mode != target_mode:
                    bulb_state.desired_mode = target_mode
                    bulb_state.desired_version += 1

    db.commit()
    db.refresh(ride)
    db.refresh(bulb_state)

    return RideStatusResponse(
        accepted_sequence=ride.sequence,
        bulb_status=bulb_state.applied_mode or "pending",
        desired_mode=bulb_state.desired_mode
    )


@app.get("/api/v1/events/nearby", response_model=List[RoadEventDetail], tags=["Spatial Queries"])
def get_nearby_events(
    latitude: float,
    longitude: float,
    radius_meters: float = 500.0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Spatial radius search:
    - Finds all road events within `radius_meters` of given (latitude, longitude)
    - Uses index-accelerated ST_DWithin and ST_Distance
    - Returns results ordered by distance
    """
    dialect = db.bind.dialect.name if db.bind else "postgresql"
    if dialect == "postgresql":
        query = text("""
            SELECT event_id, detected_at, latitude, longitude,
                   gps_accuracy_m, speed_before_kmh, speed_after_kmh,
                   acceleration_peak_mps2, photo_sha256,
                   ST_Distance(location, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS distance_meters
            FROM road_events
            WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius_m)
            ORDER BY distance_meters ASC
            LIMIT :lim
        """)
        rows = db.execute(query, {
            "lat": latitude,
            "lon": longitude,
            "radius_m": radius_meters,
            "lim": limit
        }).fetchall()

        results = []
        for r in rows:
            results.append(RoadEventDetail(
                event_id=r.event_id,
                detected_at=r.detected_at,
                latitude=r.latitude,
                longitude=r.longitude,
                gps_accuracy_m=r.gps_accuracy_m,
                speed_before_kmh=r.speed_before_kmh,
                speed_after_kmh=r.speed_after_kmh,
                acceleration_peak_mps2=r.acceleration_peak_mps2,
                photo_sha256=r.photo_sha256,
                distance_meters=round(r.distance_meters, 2)
            ))
        return results
    else:
        # SQLite fallback for unit tests
        events = db.query(RoadEvent).limit(limit).all()
        return [
            RoadEventDetail(
                event_id=e.event_id,
                detected_at=e.detected_at,
                latitude=e.latitude,
                longitude=e.longitude,
                gps_accuracy_m=e.gps_accuracy_m,
                speed_before_kmh=e.speed_before_kmh,
                speed_after_kmh=e.speed_after_kmh,
                acceleration_peak_mps2=e.acceleration_peak_mps2,
                photo_sha256=e.photo_sha256,
                distance_meters=0.0
            ) for e in events
        ]


@app.get("/api/v1/events/bbox", response_model=List[RoadEventDetail], tags=["Spatial Queries"])
def get_bbox_events(
    min_latitude: float,
    min_longitude: float,
    max_latitude: float,
    max_longitude: float,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Spatial bounding-box viewport query:
    - Finds events within the rectangle [min_lon, min_lat, max_lon, max_lat]
    - Uses PostGIS spatial bounding box operator '&&'
    """
    dialect = db.bind.dialect.name if db.bind else "postgresql"
    if dialect == "postgresql":
        query = text("""
            SELECT event_id, detected_at, latitude, longitude,
                   gps_accuracy_m, speed_before_kmh, speed_after_kmh,
                   acceleration_peak_mps2, photo_sha256
            FROM road_events
            WHERE location && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)::geography
            ORDER BY detected_at DESC
            LIMIT :lim
        """)
        rows = db.execute(query, {
            "min_lon": min_longitude,
            "min_lat": min_latitude,
            "max_lon": max_longitude,
            "max_lat": max_latitude,
            "lim": limit
        }).fetchall()

        return [
            RoadEventDetail(
                event_id=r.event_id,
                detected_at=r.detected_at,
                latitude=r.latitude,
                longitude=r.longitude,
                gps_accuracy_m=r.gps_accuracy_m,
                speed_before_kmh=r.speed_before_kmh,
                speed_after_kmh=r.speed_after_kmh,
                acceleration_peak_mps2=r.acceleration_peak_mps2,
                photo_sha256=r.photo_sha256,
                distance_meters=None
            ) for r in rows
        ]
    else:
        # SQLite fallback
        events = db.query(RoadEvent).filter(
            RoadEvent.latitude >= min_latitude,
            RoadEvent.latitude <= max_latitude,
            RoadEvent.longitude >= min_longitude,
            RoadEvent.longitude <= max_longitude
        ).limit(limit).all()

        return [
            RoadEventDetail(
                event_id=e.event_id,
                detected_at=e.detected_at,
                latitude=e.latitude,
                longitude=e.longitude,
                gps_accuracy_m=e.gps_accuracy_m,
                speed_before_kmh=e.speed_before_kmh,
                speed_after_kmh=e.speed_after_kmh,
                acceleration_peak_mps2=e.acceleration_peak_mps2,
                photo_sha256=e.photo_sha256,
                distance_meters=None
            ) for e in events
        ]
