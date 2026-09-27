import os
import hashlib
import uuid
import tempfile
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from app.config import settings

def calculate_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

class StorageService:
    def __init__(self):
        self.backend = settings.STORAGE_BACKEND
        if self.backend == "s3":
            self.s3_client = boto3.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT_URL,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
                region_name=settings.S3_REGION
            )
            self.bucket_name = settings.S3_BUCKET_NAME
        else:
            self.s3_client = None
            self.storage_root = os.path.abspath(settings.STORAGE_ROOT)
            os.makedirs(self.storage_root, exist_ok=True)

    def save_photo(self, event_id: uuid.UUID, photo_bytes: bytes, expected_sha256: str) -> str:
        """
        Validates SHA-256 and persists photo bytes either to MinIO S3 or local filesystem.
        Returns the persistent path or S3 URI.
        """
        actual_sha256 = calculate_sha256(photo_bytes)
        if actual_sha256.lower() != expected_sha256.lower():
            raise ValueError(f"SHA-256 mismatch: calculated {actual_sha256}, expected {expected_sha256}")

        event_str = str(event_id)
        prefix = event_str[:2]
        file_name = f"{event_str}.jpg"

        if self.backend == "s3":
            s3_key = f"photos/{prefix}/{file_name}"
            try:
                # Check if object already exists (idempotency recovery)
                head = self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
                existing_sha256 = head.get("Metadata", {}).get("sha256")
                if existing_sha256 and existing_sha256.lower() == expected_sha256.lower():
                    return f"s3://{self.bucket_name}/{s3_key}"
            except ClientError:
                pass  # Object does not exist yet

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=photo_bytes,
                ContentType="image/jpeg",
                Metadata={"sha256": expected_sha256.lower()}
            )
            return f"s3://{self.bucket_name}/{s3_key}"
        else:
            dir_path = os.path.join(self.storage_root, prefix)
            os.makedirs(dir_path, exist_ok=True)
            final_path = os.path.join(dir_path, file_name)

            if os.path.exists(final_path):
                # Verify existing file hash
                with open(final_path, "rb") as f:
                    if calculate_sha256(f.read()).lower() == expected_sha256.lower():
                        return final_path

            # Atomic write using temp file in same directory
            with tempfile.NamedTemporaryFile(dir=dir_path, delete=False) as tmp_file:
                tmp_file.write(photo_bytes)
                tmp_path = tmp_file.name

            os.replace(tmp_path, final_path)
            return final_path

    def get_photo(self, photo_path_or_uri: str) -> Optional[bytes]:
        """
        Retrieves raw photo bytes given an S3 URI or local filesystem path.
        """
        if photo_path_or_uri.startswith("s3://"):
            parts = photo_path_or_uri[5:].split("/", 1)
            bucket = parts[0]
            key = parts[1]
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()
        else:
            if os.path.exists(photo_path_or_uri):
                with open(photo_path_or_uri, "rb") as f:
                    return f.read()
            return None

storage_service = StorageService()
