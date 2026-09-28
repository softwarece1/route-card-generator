"""MinIO client with short connect timeouts so offline/dev PCs fail fast to local disk."""

from __future__ import annotations

import os
from datetime import timedelta
from io import BytesIO
from typing import BinaryIO

import urllib3
from fastapi import HTTPException
from minio import Minio
from minio.error import S3Error


def _timeouts() -> tuple[float, float]:
    try:
        from app.config.settings import settings

        connect = float(getattr(settings, "MINIO_CONNECT_TIMEOUT_SEC", 2.0) or 2.0)
        read = float(getattr(settings, "MINIO_READ_TIMEOUT_SEC", 10.0) or 10.0)
        return max(0.5, connect), max(1.0, read)
    except Exception:
        return 2.0, 10.0


class MinioService:
    def __init__(self):
        connect_t, read_t = _timeouts()
        # Without an explicit http_client, urllib3 can stall ~60s+ when MinIO is down.
        http_client = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=connect_t, read=read_t),
            retries=False,
        )
        endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
        try:
            from app.config.settings import settings

            endpoint = getattr(settings, "MINIO_ENDPOINT", None) or endpoint
            access = getattr(settings, "MINIO_ACCESS_KEY", None) or os.getenv(
                "MINIO_ACCESS_KEY", "admin"
            )
            secret = getattr(settings, "MINIO_SECRET_KEY", None) or os.getenv(
                "MINIO_SECRET_KEY", "password123"
            )
            secure = bool(getattr(settings, "MINIO_SECURE", False))
            self.bucket_name = getattr(settings, "MINIO_BUCKET_NAME", None) or os.getenv(
                "MINIO_BUCKET_NAME", "documents"
            )
        except Exception:
            access = os.getenv("MINIO_ACCESS_KEY", "admin")
            secret = os.getenv("MINIO_SECRET_KEY", "password123")
            secure = os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes"}
            self.bucket_name = os.getenv("MINIO_BUCKET_NAME", "documents")

        self.client = Minio(
            endpoint=endpoint,
            access_key=access,
            secret_key=secret,
            secure=secure,
            http_client=http_client,
        )
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """Ensure the bucket exists, create if it doesn't"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except Exception as e:
            # Log warning but don't crash — allow app to start even if MinIO is unavailable
            print(f"Warning: Failed to connect to MinIO bucket: {str(e)}")

    def ping(self) -> bool:
        """Cheap reachability check (uses connect timeout)."""
        try:
            self.client.bucket_exists(self.bucket_name)
            return True
        except Exception:
            return False

    def generate_object_path(self, part_number: str, doc_type: str, doc_id: int, version_id: int) -> str:
        """Generate standardized object path"""
        return f"{part_number}/{doc_type}/{doc_id}/{version_id}"

    def upload_file(self, file: BinaryIO, object_name: str, content_type: str | None = None) -> bool:
        """Upload a file to MinIO"""
        try:
            if isinstance(file, BytesIO):
                file_size = file.getbuffer().nbytes
            else:
                file.seek(0, 2)
                file_size = file.tell()
                file.seek(0)

            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                data=file,
                length=file_size,
                content_type=content_type or "application/octet-stream",
            )
            return True
        except S3Error as e:
            raise Exception(f"Failed to upload file: {str(e)}") from e

    def download_file(self, object_name: str) -> BytesIO:
        """Download a file from MinIO"""
        try:
            data = self.client.get_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
            )
            return data.stream(32 * 1024)
        except S3Error as e:
            raise Exception(f"Failed to download file: {str(e)}") from e

    def get_file(self, object_name: str) -> BinaryIO:
        """Get a file from MinIO"""
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            return response
        except S3Error as e:
            raise HTTPException(status_code=404, detail=f"File not found: {str(e)}") from e

    def get_presigned_url(self, object_name: str, expires: timedelta = timedelta(hours=1)) -> str:
        """Generate a presigned URL for object access"""
        try:
            return self.client.presigned_get_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                expires=expires,
            )
        except S3Error as e:
            raise HTTPException(status_code=500, detail=f"URL generation failed: {str(e)}") from e

    def delete_file(self, object_name: str) -> bool:
        """Delete a file from MinIO"""
        try:
            self.client.remove_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
            )
            return True
        except S3Error as e:
            raise Exception(f"Failed to delete file: {str(e)}") from e

    def get_file_url(self, object_name: str, expires: int = 3600) -> str:
        """Get a presigned URL for object download"""
        try:
            return self.client.presigned_get_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                expires=expires,
            )
        except S3Error as e:
            raise Exception(f"Failed to get file URL: {str(e)}") from e
