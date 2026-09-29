import uuid
from datetime import datetime, timezone, timedelta
import pytest

def get_auth_headers():
    return {"Authorization": "Bearer test-secret-token"}

def test_ride_status_normal_flow(client):
    ride_id = str(uuid.uuid4())

    # 1. Ride starts (moving at 30 km/h) -> desired mode green
    now = datetime.now(timezone.utc)
    payload1 = {
        "sequence": 1,
        "observed_at": now.isoformat(),
        "ride_state": "active",
        "speed_kmh": 30.0,
        "last_valid_speed_at": now.isoformat(),
        "motion_state": "moving",
        "incident": None
    }
    res1 = client.put(f"/api/v1/rides/{ride_id}/status", json=payload1, headers=get_auth_headers())
    assert res1.status_code == 200
    assert res1.json()["accepted_sequence"] == 1
    assert res1.json()["desired_mode"] == "green"

    # 2. Slow down (< 25 km/h) -> desired mode yellow
    now = datetime.now(timezone.utc)
    payload2 = {
        "sequence": 2,
        "observed_at": now.isoformat(),
        "ride_state": "active",
        "speed_kmh": 15.0,
        "last_valid_speed_at": now.isoformat(),
        "motion_state": "slow",
        "incident": None
    }
    res2 = client.put(f"/api/v1/rides/{ride_id}/status", json=payload2, headers=get_auth_headers())
    assert res2.status_code == 200
    assert res2.json()["accepted_sequence"] == 2
    assert res2.json()["desired_mode"] == "yellow"

    # 3. Stop -> desired mode red
    now = datetime.now(timezone.utc)
    payload3 = {
        "sequence": 3,
        "observed_at": now.isoformat(),
        "ride_state": "active",
        "speed_kmh": 0.0,
        "last_valid_speed_at": now.isoformat(),
        "motion_state": "stopped",
        "incident": None
    }
    res3 = client.put(f"/api/v1/rides/{ride_id}/status", json=payload3, headers=get_auth_headers())
    assert res3.status_code == 200
    assert res3.json()["accepted_sequence"] == 3
    assert res3.json()["desired_mode"] == "red"

    # 4. End ride -> desired mode restore_off
    now = datetime.now(timezone.utc)
    payload4 = {
        "sequence": 4,
        "observed_at": now.isoformat(),
        "ride_state": "ended",
        "speed_kmh": 0.0,
        "last_valid_speed_at": now.isoformat(),
        "motion_state": "stopped",
        "incident": None
    }
    res4 = client.put(f"/api/v1/rides/{ride_id}/status", json=payload4, headers=get_auth_headers())
    assert res4.status_code == 200
    assert res4.json()["accepted_sequence"] == 4
    assert res4.json()["desired_mode"] == "restore_off"

def test_ride_status_monotonic_sequence(client):
    ride_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Send sequence 5
    payload = {
        "sequence": 5,
        "observed_at": now.isoformat(),
        "ride_state": "active",
        "speed_kmh": 35.0,
        "motion_state": "moving",
        "incident": None
    }
    res = client.put(f"/api/v1/rides/{ride_id}/status", json=payload, headers=get_auth_headers())
    assert res.status_code == 200
    assert res.json()["accepted_sequence"] == 5

    # Send older sequence 3 -> should ignore and return current sequence 5
    payload_old = {
        "sequence": 3,
        "observed_at": (now - timedelta(seconds=5)).isoformat(),
        "ride_state": "active",
        "speed_kmh": 10.0,
        "motion_state": "slow",
        "incident": None
    }
    res_old = client.put(f"/api/v1/rides/{ride_id}/status", json=payload_old, headers=get_auth_headers())
    assert res_old.status_code == 200
    assert res_old.json()["accepted_sequence"] == 5

def test_incident_alert_and_clearing(client):
    ride_id = str(uuid.uuid4())
    alert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Trigger incident alert
    payload_incident = {
        "sequence": 1,
        "observed_at": now.isoformat(),
        "ride_state": "active",
        "speed_kmh": 0.0,
        "motion_state": "stopped",
        "incident": {
            "alert_id": alert_id,
            "state": "active",
            "detected_at": now.isoformat(),
            "source": "automatic",
            "cleared_at": None
        }
    }
    res = client.put(f"/api/v1/rides/{ride_id}/status", json=payload_incident, headers=get_auth_headers())
    assert res.status_code == 200
    assert res.json()["desired_mode"] == "alert_pulse"

    # Explicit clear: "I'm OK / Clear Alert"
    now_clear = datetime.now(timezone.utc)
    payload_cleared = {
        "sequence": 2,
        "observed_at": now_clear.isoformat(),
        "ride_state": "active",
        "speed_kmh": 28.0,
        "motion_state": "moving",
        "incident": {
            "alert_id": alert_id,
            "state": "cleared",
            "detected_at": now.isoformat(),
            "source": "automatic",
            "cleared_at": now_clear.isoformat()
        }
    }
    res_cleared = client.put(f"/api/v1/rides/{ride_id}/status", json=payload_cleared, headers=get_auth_headers())
    assert res_cleared.status_code == 200
    assert res_cleared.json()["desired_mode"] == "green"

def test_incident_alert_triggers_email(client, monkeypatch):
    from unittest.mock import MagicMock
    import app.main

    mock_send = MagicMock(return_value=True)
    monkeypatch.setattr(app.main, "send_alert_email", mock_send)

    ride_id = str(uuid.uuid4())
    alert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    payload = {
        "sequence": 1,
        "observed_at": now.isoformat(),
        "ride_state": "active",
        "speed_kmh": 0.0,
        "motion_state": "stopped",
        "incident": {
            "alert_id": alert_id,
            "state": "active",
            "detected_at": now.isoformat(),
            "source": "manual",
            "cleared_at": None,
            "latitude": 22.5726,
            "longitude": 88.3639
        }
    }

    res = client.put(f"/api/v1/rides/{ride_id}/status", json=payload, headers=get_auth_headers())
    assert res.status_code == 200
    assert mock_send.called
    call_kwargs = mock_send.call_args[1]
    assert call_kwargs["alert_id"] == alert_id
    assert call_kwargs["source"] == "manual"
    assert call_kwargs["latitude"] == 22.5726
    assert call_kwargs["longitude"] == 88.3639

def test_email_service_mock_smtp(monkeypatch):
    from unittest.mock import MagicMock
    from app.email_service import send_alert_email
    from app.config import settings

    monkeypatch.setattr(settings, "ALERT_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "mock-smtp-password")

    mock_smtp_instance = MagicMock()
    mock_smtp_class = MagicMock(return_value=mock_smtp_instance)
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", mock_smtp_class)

    result = send_alert_email(
        alert_id="test-alert-123",
        source="manual",
        detected_at="2026-09-27T18:00:00Z",
        latitude=22.5726,
        longitude=88.3639,
        speed_kmh=12.5
    )

    assert result is True
    assert mock_smtp_instance.login.called
    assert mock_smtp_instance.send_message.called
    sent_msg = mock_smtp_instance.send_message.call_args[0][0]
    assert "sayantikasaha400@gmail.com" in sent_msg["To"]
    body = sent_msg.get_body(preferencelist=('plain',)).get_content()
    assert "https://www.google.com/maps?q=22.5726,88.3639" in body

