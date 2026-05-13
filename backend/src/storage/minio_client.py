"""
MinIO 存储客户端 - 存储原始文章全文
"""
import hashlib
from typing import Any

import structlog

from core import get_logger, settings

logger = get_logger(__name__)

try:
    from minio import Minio
    from minio.error import S3Error
except ImportError:
    logger.warning("minio_not_installed", message="pip install minio to enable MinIO storage")
    Minio = None
    S3Error = Exception


class MinioStore:
    """MinIO 存储客户端，存原始全文"""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
    ):
        """
        初始化 MinIO 客户端

        Args:
            host: MinIO 服务器地址
            port: MinIO 端口
            access_key: 访问密钥
            secret_key: 秘密密钥
            bucket: 存储桶名称
        """
        self.bucket = bucket or settings.minio_bucket
        self._client: Minio | None = None
        self._host = host or settings.minio_host
        self._port = port or settings.minio_port
        self._access_key = access_key or settings.minio_access_key
        self._secret_key = secret_key or settings.minio_secret_key

    @property
    def client(self) -> Minio:
        """Get or create MinIO client (lazy initialization)."""
        if self._client is None:
            if Minio is None:
                raise RuntimeError("MinIO not installed. Run: pip install minio")
            endpoint = f"{self._host}:{self._port}"
            self._client = Minio(
                endpoint=endpoint,
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=False,  # 使用 HTTP
            )
            # 确保 bucket 存在
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)
                logger.info("minio_bucket_created", bucket=self.bucket)
        return self._client

    def _get_object_key(self, content_hash: str) -> str:
        """生成 MinIO 对象路径"""
        return f"articles/{content_hash}.txt"

    def upload_article(self, content_hash: str, full_text: str) -> str:
        """
        上传原文到 MinIO

        Args:
            content_hash: 文章内容哈希（用作对象键）
            full_text: 完整的文章文本

        Returns:
            MinIO 存储路径 (bucket/key)
        """
        import io

        object_key = self._get_object_key(content_hash)
        data = io.BytesIO(full_text.encode("utf-8"))
        data_size = len(full_text.encode("utf-8"))

        try:
            self.client.put_object(
                bucket_name=self.bucket,
                object_name=object_key,
                data=data,
                length=data_size,
                content_type="text/plain; charset=utf-8",
            )
            logger.debug("minio_upload_success", content_hash=content_hash, key=object_key)
            return f"{self.bucket}/{object_key}"
        except S3Error as e:
            logger.error("minio_upload_failed", content_hash=content_hash, error=str(e))
            raise

    def download_article(self, content_hash: str) -> str | None:
        """
        从 MinIO 下载原文

        Args:
            content_hash: 文章内容哈希

        Returns:
            完整的文章文本，如果不存在返回 None
        """
        object_key = self._get_object_key(content_hash)

        try:
            response = self.client.get_object(bucket_name=self.bucket, object_name=object_key)
            content = response.read().decode("utf-8")
            response.close()
            response.release_conn()
            logger.debug("minio_download_success", content_hash=content_hash)
            return content
        except S3Error as e:
            if "NoSuchKey" in str(e) or e.code == "NoSuchKey":
                logger.debug("minio_article_not_found", content_hash=content_hash)
                return None
            logger.error("minio_download_failed", content_hash=content_hash, error=str(e))
            raise

    def article_exists(self, content_hash: str) -> bool:
        """
        检查文章是否已存在于 MinIO

        Args:
            content_hash: 文章内容哈希

        Returns:
            是否存在
        """
        object_key = self._get_object_key(content_hash)
        try:
            self.client.stat_object(bucket_name=self.bucket, object_name=object_key)
            return True
        except S3Error:
            return False

    def delete_article(self, content_hash: str) -> bool:
        """
        从 MinIO 删除文章

        Args:
            content_hash: 文章内容哈希

        Returns:
            是否删除成功
        """
        object_key = self._get_object_key(content_hash)
        try:
            self.client.remove_object(bucket_name=self.bucket, object_name=object_key)
            logger.info("minio_article_deleted", content_hash=content_hash)
            return True
        except S3Error as e:
            logger.error("minio_delete_failed", content_hash=content_hash, error=str(e))
            return False

    def stats(self) -> str:
        """返回存储统计信息"""
        try:
            objects = sum(1 for _ in self.client.list_objects(self.bucket, recursive=True))
            return f"bucket={self.bucket}, objects≈{objects}"
        except Exception:
            return f"bucket={self.bucket}, stats unavailable"
