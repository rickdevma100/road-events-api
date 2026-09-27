import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DEVICE_TOKEN: str = "secret-device-token-12345"
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/roadevents"
    MAX_PHOTO_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MiB
    
    # Storage configuration: "s3" (MinIO) or "local" (Filesystem)
    STORAGE_BACKEND: str = "s3"
    STORAGE_ROOT: str = "./data/photos"
    S3_ENDPOINT_URL: str = "http://lang-learn-minio.lang-learn.svc.cluster.local:9000"
    S3_BUCKET_NAME: str = "road-events"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_REGION: str = "us-east-1"
    
    # Bulb configuration
    BULB_ADAPTER: str = "mock"  # "mock" or "tuya"
    BULB_IP: str = "192.168.0.109"
    BULB_DEVICE_ID: str = "d798b17a8abfe1e652uoe1"
    BULB_LOCAL_KEY: str = "t5lS>p7jES(}Lby}"
    BULB_PROTOCOL: str = "3.5"
    BULB_BRIGHTNESS: int = 1000  # Scale: 10 to 1000
    
    # Stale thresholds (seconds)
    STALE_SPEED_TIMEOUT_SEC: float = 15.0
    
    # Pulse duration (seconds)
    INCIDENT_PULSE_DURATION_SEC: float = 60.0

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
