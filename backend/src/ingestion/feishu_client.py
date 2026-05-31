"""
飞书 Open Platform API 客户端

封装认证、限速、分页、重试逻辑，提供高层 API 方法：
- list_spaces(): 列出可访问的知识库
- list_nodes(): 递归列出知识库下的所有文档节点
- get_document_blocks(): 获取文档的结构化 block 列表

设计为同步客户端（因 collector 运行在线程池中）。
"""

import time
from collections import deque
from typing import Iterator

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)


class _RateLimiter:
    """滑动窗口限速器。

    用 deque 记录最近 N 次请求的时间戳，
    当窗口满时 sleep 到最早的请求过期。
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window = window_seconds
        self._timestamps: deque[float] = deque()

    def wait(self) -> None:
        now = time.monotonic()
        # 清理窗口外的旧时间戳
        while self._timestamps and now - self._timestamps[0] > self.window:
            self._timestamps.popleft()
        # 窗口满了，等到最早的请求过期
        if len(self._timestamps) >= self.max_requests:
            sleep_until = self._timestamps[0] + self.window
            sleep_time = sleep_until - now
            if sleep_time > 0:
                time.sleep(sleep_time)
        self._timestamps.append(time.monotonic())


class FeishuClient:
    """飞书 Open Platform API 客户端。"""

    def __init__(self, app_id: str, app_secret: str, api_base: str):
        self._app_id = app_id
        self._app_secret = app_secret
        self._api_base = api_base.rstrip("/")

        # Token 缓存
        self._token: str = ""
        self._token_expires_at: float = 0.0

        # 限速器：Wiki 100次/分钟，Docx 5次/秒
        self._wiki_limiter = _RateLimiter(100, 60.0)
        self._docx_limiter = _RateLimiter(5, 1.0)

        # HTTP 客户端（复用连接）
        self._http = httpx.Client(timeout=30.0)

    def _ensure_token(self) -> str:
        """获取或刷新 tenant_access_token。

        Token 有效期 2 小时，提前 5 分钟刷新。
        当剩余有效期 >= 30 分钟时，API 返回同一个 token（不会浪费）。
        """
        now = time.time()
        if self._token and now < self._token_expires_at:
            return self._token

        logger.info("feishu_token_refreshing")
        resp = self._http.post(
            f"{self._api_base}/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {data.get('msg')}")

        self._token = data["tenant_access_token"]
        ttl = data.get("expire", 7200)
        # 提前 5 分钟刷新，避免边界情况
        self._token_expires_at = now + ttl - 300

        logger.info("feishu_token_refreshed", ttl=ttl)
        return self._token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._ensure_token()}"}

    def _rate_limited_get(
        self, url: str, params: dict | None, limiter: _RateLimiter
    ) -> httpx.Response:
        """带限速和重试的 GET 请求。"""
        limiter.wait()
        return self._get(url, params)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        """带重试的 GET 请求。"""
        resp = self._http.get(url, headers=self._auth_headers(), params=params)

        # 429 限速 — 等待后重试
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning("feishu_rate_limited", retry_after=retry_after)
            time.sleep(retry_after)
            raise httpx.HTTPStatusError(
                "Rate limited", request=resp.request, response=resp
            )

        resp.raise_for_status()

        # 飞书 API 业务错误码
        body = resp.json()
        if body.get("code") != 0:
            logger.error(
                "feishu_api_error",
                code=body.get("code"),
                msg=body.get("msg"),
                url=url,
            )
            raise RuntimeError(f"Feishu API error {body.get('code')}: {body.get('msg')}")

        return resp

    def _paginated_get(
        self, url: str, items_key: str, params: dict | None, limiter: _RateLimiter
    ) -> Iterator[dict]:
        """通用分页遍历器。"""
        page_token = ""
        while True:
            p = dict(params) if params else {}
            p["page_size"] = 50
            if page_token:
                p["page_token"] = page_token

            resp = self._rate_limited_get(url, p, limiter)
            body = resp.json()
            data = body.get("data", {})
            items = data.get(items_key, [])
            yield from items

            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")

    # ─── 公开 API ───────────────────────────────────────────────

    def list_spaces(self) -> list[dict]:
        """列出可访问的知识库 space 列表。"""
        url = f"{self._api_base}/wiki/v2/spaces"
        return list(self._paginated_get(url, "items", None, self._wiki_limiter))

    def list_nodes(
        self, space_id: str, parent_node_token: str = ""
    ) -> Iterator[dict]:
        """递归列出知识库下的所有文档节点（深度优先）。

        Args:
            space_id: 知识库 ID
            parent_node_token: 父节点 token，空 = 根节点

        Yields:
            每个 node 的 dict，包含 node_token, obj_token, obj_type, title 等
        """
        url = f"{self._api_base}/wiki/v2/spaces/{space_id}/nodes"
        params: dict = {}
        if parent_node_token:
            params["parent_node_token"] = parent_node_token

        for node in self._paginated_get(url, "items", params, self._wiki_limiter):
            yield node
            # 递归获取子节点
            if node.get("has_child"):
                yield from self.list_nodes(space_id, node["node_token"])

    def get_document_blocks(self, document_id: str) -> list[dict]:
        """获取文档的全部 block（分页合并为一个列表）。

        Args:
            document_id: 文档的 obj_token

        Returns:
            block dict 列表
        """
        url = f"{self._api_base}/docx/v1/documents/{document_id}/blocks"
        return list(
            self._paginated_get(url, "items", None, self._docx_limiter)
        )

    def close(self) -> None:
        """关闭 HTTP 客户端。"""
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
