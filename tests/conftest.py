import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.bulb_service import set_bulb_adapter, MockBulbAdapter
from app.storage import storage_service
from app.main import app

# Configure test environment variables
settings.DEVICE_TOKEN = "test-secret-token"
settings.STORAGE_BACKEND = "local"
test_temp_dir = tempfile.mkdtemp()
settings.STORAGE_ROOT = test_temp_dir
storage_service.backend = "local"
storage_service.storage_root = test_temp_dir

# Use in-memory SQLite with StaticPool
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    # Set fresh mock bulb
    mock_bulb = MockBulbAdapter()
    set_bulb_adapter(mock_bulb)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
