import json
import uuid
import hashlib
from datetime import datetime, timezone
import pytest

def get_auth_headers():
    return {"Authorization": "Bearer test-secret-token"}

def test_spatial_query_endpoints(client):
    # Insert two test events
    for i in range(2):
        event_id = str(uuid.uuid4())
        data = f"sample-bytes-{i}".encode()
        sha = hashlib.sha256(data).hexdigest()
        meta = {
            "event_id": event_id,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "latitude": 17.4123 + (i * 0.001),
            "longitude": 78.4231 + (i * 0.001),
            "gps_accuracy_m": 3.0,
            "speed_before_kmh": 40.0,
            "speed_after_kmh": 15.0,
            "acceleration_peak_mps2": 7.0,
            "photo_sha256": sha
        }
        res = client.post(
            "/api/v1/events",
            headers=get_auth_headers(),
            data={"metadata": json.dumps(meta)},
            files={"photo": ("photo.jpg", data, "image/jpeg")}
        )
        assert res.status_code == 201

    # 1. Test /api/v1/events/nearby
    res_nearby = client.get("/api/v1/events/nearby?latitude=17.4123&longitude=78.4231&radius_meters=1000")
    assert res_nearby.status_code == 200
    events = res_nearby.json()
    assert len(events) >= 2

    # 2. Test /api/v1/events/bbox
    res_bbox = client.get("/api/v1/events/bbox?min_latitude=17.40&min_longitude=78.40&max_latitude=17.45&max_longitude=78.45")
    assert res_bbox.status_code == 200
    bbox_events = res_bbox.json()
    assert len(bbox_events) >= 2
