"""
通用文件缓存模块

基于 JSON 文件的 key-value 存储，支持：
- TTL 过期
- 按版本分目录
"""
import json
import time
from pathlib import Path
from typing import Any

from core import get_logger

logger = get_logger(__name__)


class FileCache:
    """
    基于 JSON 文件的通用缓存

    特性：
    - key-value 存储，value 支持任意可序列化的 Python 对象
    - 支持 TTL 过期机制
    - 支持按 version 分目录存储
    """

    def __init__(self, cache_dir: str | Path, version: str = "default", default_ttl: int = 3600):
        """
        初始化文件缓存

        Args:
            cache_dir: 缓存根目录
            version: 版本标识，用于分区存储
            default_ttl: 默认 TTL（秒），0 表示永不过期
        """
        self.cache_dir = Path(cache_dir)
        self.version = version
        self.default_ttl = default_ttl

        # 创建版本子目录
        self.version_dir = self.cache_dir / self.version
        self.version_dir.mkdir(parents=True, exist_ok=True)

        logger.debug("[FileCache] 初始化缓存", cache_dir=str(self.cache_dir), version=version)

    def _get_file_path(self, key: str) -> Path:
        """
        获取 key 对应的缓存文件路径

        Args:
            key: 缓存键

        Returns:
            缓存文件路径
        """
        # 安全处理 key，防止路径穿越
        safe_key = key.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self.version_dir / f"{safe_key}.json"

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取缓存值

        Args:
            key: 缓存键
            default: 默认值，当缓存不存在或已过期时返回

        Returns:
            缓存值或默认值
        """
        file_path = self._get_file_path(key)

        if not file_path.exists():
            logger.debug("[FileCache] 缓存不存在", key=key)
            return default

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 检查过期时间
            expire_at = data.get("_expire_at", 0)
            if expire_at > 0 and time.time() > expire_at:
                # 已过期，删除文件
                file_path.unlink()
                logger.debug("[FileCache] 缓存已过期", key=key)
                return default

            logger.debug("[FileCache] 缓存命中", key=key)
            return data.get("value")

        except (json.JSONDecodeError, IOError) as e:
            logger.warning("[FileCache] 读取缓存失败", key=key, error=str(e))
            return default

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值（必须是可序列化的 Python 对象）
            ttl: TTL（秒），None 使用默认值，0 表示永不过期

        Returns:
            是否设置成功
        """
        if ttl is None:
            ttl = self.default_ttl

        file_path = self._get_file_path(key)

        # 构建缓存数据结构
        data = {
            "value": value,
            "_created_at": time.time(),
        }

        # 设置过期时间
        if ttl > 0:
            data["_expire_at"] = time.time() + ttl
        else:
            data["_expire_at"] = 0

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.debug("[FileCache] 缓存已设置", key=key, ttl=ttl)
            return True

        except (IOError, TypeError) as e:
            logger.warning("[FileCache] 设置缓存失败", key=key, error=str(e))
            return False

    def delete(self, key: str) -> bool:
        """
        删除缓存

        Args:
            key: 缓存键

        Returns:
            是否删除成功
        """
        file_path = self._get_file_path(key)

        if file_path.exists():
            try:
                file_path.unlink()
                logger.debug("[FileCache] 缓存已删除", key=key)
                return True
            except IOError as e:
                logger.warning("[FileCache] 删除缓存失败", key=key, error=str(e))
                return False

        return False

    def clear(self) -> int:
        """
        清空当前版本的所有缓存

        Returns:
            删除的文件数量
        """
        count = 0
        for file_path in self.version_dir.glob("*.json"):
            try:
                file_path.unlink()
                count += 1
            except IOError as e:
                logger.warning("[FileCache] 删除缓存失败", path=str(file_path), error=str(e))

        logger.info("[FileCache] 缓存已清空", version=self.version, count=count)
        return count

    def exists(self, key: str) -> bool:
        """
        检查缓存是否存在且未过期

        Args:
            key: 缓存键

        Returns:
            是否存在且未过期
        """
        file_path = self._get_file_path(key)

        if not file_path.exists():
            return False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 检查过期时间
            expire_at = data.get("_expire_at", 0)
            if expire_at > 0 and time.time() > expire_at:
                file_path.unlink()
                return False

            return True

        except (json.JSONDecodeError, IOError):
            return False

    def keys(self) -> list[str]:
        """
        获取当前版本的所有缓存键

        Returns:
            缓存键列表
        """
        keys = []
        for file_path in self.version_dir.glob("*.json"):
            key = file_path.stem
            keys.append(key)

        return keys

    def size(self) -> int:
        """
        获取缓存文件大小（字节）

        Returns:
            缓存总大小
        """
        total_size = 0
        for file_path in self.version_dir.glob("*.json"):
            total_size += file_path.stat().st_size

        return total_size