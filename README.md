# Road Events API

FastAPI backend service for road-event capture and smart bulb automation on MicroK8s with PostGIS and MinIO.

## Features
- **Road Event Ingestion**: Multipart JPEG upload, SHA-256 byte validation, and atomic storage in MinIO S3 object storage.
- **Spatial Indexing & Queries**: PostGIS `geography(Point, 4326)` storage with GiST indexing for fast radius (`ST_DWithin`) and bounding-box (`&&`) queries.
- **Ride Monitoring & Bulb State Machine**: Monotonic sequence tracking, debounced motion state (Green / Yellow / Red / Restore-Off), and restart-resilient 60-second dazzling red pulse for incidents.
- **Smart Bulb Adapter**: Modular adapter supporting physical Tuya / Wipro 9W RGB bulbs (via TinyTuya protocol 3.5) and Mock adapter for testing.

## Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/events` | Upload photo (JPEG max 5 MiB) and telemetry metadata |
| `PUT` | `/api/v1/rides/{ride_id}/status` | Synchronize real-time ride sequence, motion state, and incident alerts |
| `GET` | `/api/v1/events/nearby` | Spatial radius query (`latitude`, `longitude`, `radius_meters`) |
| `GET` | `/api/v1/events/bbox` | Spatial bounding box query (`min_lat`, `min_lon`, `max_lat`, `max_lon`) |
| `GET` | `/healthz` | Liveness and readiness probe |

## Quick Start (Local Development)

### 1. Set Up Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run Test Suite
```bash
pytest -v
```

### 3. Start Local Development Server
```bash
uvicorn app.main:app --reload --port 8000
```

## Docker Build
```bash
docker build -t road-events-api:latest .
```