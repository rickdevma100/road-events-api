import json
import uuid
import hashlib
from datetime import datetime, timezone
import pytest

def get_auth_headers():
    return {"Authorization": "Bearer test-secret-token"}

def test_upload_event_success(client):
    event_id = str(uuid.uuid4())
    photo_data = b"fake-jpeg-image-bytes-12345"
    photo_sha256 = hashlib.sha256(photo_data).hexdigest()

    meta = {
        "event_id": event_id,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "latitude": 17.4123,
        "longitude": 78.4231,
        "gps_accuracy_m": 4.5,
        "speed_before_kmh": 45.0,
        "speed_after_kmh": 18.0,
        "acceleration_peak_mps2": 8.5,
        "photo_sha256": photo_sha256
    }

    response = client.post(
        "/api/v1/events",
        headers=get_auth_headers(),
        data={"metadata": json.dumps(meta)},
        files={"photo": ("photo.jpg", photo_data, "image/jpeg")}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["event_id"] == event_id
    assert body["status"] == "stored"
    assert body["photo_sha256"] == photo_sha256

def test_upload_event_idempotency_same_content(client):
    event_id = str(uuid.uuid4())
    photo_data = b"idempotent-photo-bytes"
    photo_sha256 = hashlib.sha256(photo_data).hexdigest()

    meta = {
        "event_id": event_id,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "latitude": 17.4123,
        "longitude": 78.4231,
        "gps_accuracy_m": 4.5,
        "speed_before_kmh": 45.0,
        "speed_after_kmh": 18.0,
        "acceleration_peak_mps2": 8.5,
        "photo_sha256": photo_sha256
    }

    # First request -> 201 Created
    res1 = client.post(
        "/api/v1/events",
        headers=get_auth_headers(),
        data={"metadata": json.dumps(meta)},
        files={"photo": ("photo.jpg", photo_data, "image/jpeg")}
    )
    assert res1.status_code == 201

    # Second identical request -> 200 OK
    res2 = client.post(
        "/api/v1/events",
        headers=get_auth_headers(),
        data={"metadata": json.dumps(meta)},
        files={"photo": ("photo.jpg", photo_data, "image/jpeg")}
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "stored"

def test_upload_event_conflict_different_content(client):
    event_id = str(uuid.uuid4())
    photo_data1 = b"photo-bytes-one"
    photo_sha256_1 = hashlib.sha256(photo_data1).hexdigest()

    meta1 = {
        "event_id": event_id,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "latitude": 17.4123,
        "longitude": 78.4231,
        "gps_accuracy_m": 4.5,
        "speed_before_kmh": 45.0,
        "speed_after_kmh": 18.0,
        "acceleration_peak_mps2": 8.5,
        "photo_sha256": photo_sha256_1
    }

    res1 = client.post(
        "/api/v1/events",
        headers=get_auth_headers(),
        data={"metadata": json.dumps(meta1)},
        files={"photo": ("photo.jpg", photo_data1, "image/jpeg")}
    )
    assert res1.status_code == 201

    # Re-upload with same event_id but different image content -> 409 Conflict
    photo_data2 = b"different-photo-bytes-two"
    photo_sha256_2 = hashlib.sha256(photo_data2).hexdigest()
    meta2 = dict(meta1)
    meta2["photo_sha256"] = photo_sha256_2

    res2 = client.post(
        "/api/v1/events",
        headers=get_auth_headers(),
        data={"metadata": json.dumps(meta2)},
        files={"photo": ("photo.jpg", photo_data2, "image/jpeg")}
    )
    assert res2.status_code == 409

def test_upload_event_unauthorized(client):
    res = client.post(
        "/api/v1/events",
        headers={"Authorization": "Bearer bad-token"},
        data={"metadata": "{}"},
        files={"photo": ("photo.jpg", b"abc", "image/jpeg")}
    )
    assert res.status_code == 401

def test_upload_event_sha_mismatch(client):
    event_id = str(uuid.uuid4())
    photo_data = b"photo-bytes-correct"
    wrong_sha256 = "a" * 64

    meta = {
        "event_id": event_id,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "latitude": 17.4123,
        "longitude": 78.4231,
        "gps_accuracy_m": 4.5,
        "speed_before_kmh": 45.0,
        "speed_after_kmh": 18.0,
        "acceleration_peak_mps2": 8.5,
        "photo_sha256": wrong_sha256
    }

    res = client.post(
        "/api/v1/events",
        headers=get_auth_headers(),
        data={"metadata": json.dumps(meta)},
        files={"photo": ("photo.jpg", photo_data, "image/jpeg")}
    )
    assert res.status_code == 422

def test_swagger_docs_and_openapi(client):
    # Test root redirect to /docs
    res_root = client.get("/", follow_redirects=False)
    assert res_root.status_code in [302, 307]
    assert res_root.headers["location"] == "/docs"

    # Test Swagger UI HTML
    res_docs = client.get("/docs")
    assert res_docs.status_code == 200
    assert "swagger-ui" in res_docs.text.lower()

    # Test OpenAPI JSON schema includes HTTPBearer security
    res_openapi = client.get("/openapi.json")
    assert res_openapi.status_code == 200
    schema = res_openapi.json()
    assert "components" in schema
    assert "securitySchemes" in schema["components"]
    assert "HTTPBearer" in schema["components"]["securitySchemes"]

