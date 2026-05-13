"""Storage module for MinIO and other storage backends."""
from .minio_client import MinioStore

__all__ = ["MinioStore"]
