import uuid
import hashlib
import pytest
from app.storage import StorageService

def test_storage_service_local():
    storage = StorageService()
    storage.backend = "local"
    storage.storage_root = "/tmp/test_storage_road_events"

    event_id = uuid.uuid4()
    content = b"test-image-bytes-hello-world"
    sha = hashlib.sha256(content).hexdigest()

    saved_path = storage.save_photo(event_id, content, sha)
    assert saved_path.endswith(f"{event_id}.jpg")

    read_bytes = storage.get_photo(saved_path)
    assert read_bytes == content

def test_storage_service_sha_mismatch():
    storage = StorageService()
    storage.backend = "local"
    event_id = uuid.uuid4()
    content = b"test-image-bytes"

    with pytest.raises(ValueError):
        storage.save_photo(event_id, content, "bad-sha-hash")
