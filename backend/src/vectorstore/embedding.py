import hashlib
import json
from pathlib import Path

import httpx
import tenacity
from tqdm import tqdm

from core import get_logger, settings

logger = get_logger(__name__)

EMBEDDING_DIM = 1024
BATCH_SIZE = 50


def compute_cache_key(texts: list[str]) -> str:
    """Compute cache key from texts content."""
    content = "|".join(texts)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def _call_embedding_api(texts: list[str]) -> list[list[float]]:
    """Call 火山引擎 embedding API with retry."""
    url = settings.volc_engine_embedding_url
    headers = {
        "Authorization": f"Bearer {settings.volcengine_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "volcengine_public",
        "input": texts,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    # Extract embeddings from response
    embeddings = []
    for item in data.get("data", []):
        embeddings.append(item.get("embedding", [0.0] * EMBEDDING_DIM))
    return embeddings


async def embed_texts_async(texts: list[str], batch_size: int = BATCH_SIZE) -> list[list[float]]:
    """Embed texts in batches with API calls."""
    all_embeddings = []

    for i in tqdm(range(0, len(texts), batch_size), desc="Embedding"):
        batch = texts[i:i + batch_size]
        try:
            embeddings = await _call_embedding_api(batch)
            all_embeddings.extend(embeddings)
        except Exception as e:
            logger.error("embedding_batch_failed", batch=i//batch_size, error=str(e))
            # Return zero embeddings for failed batch
            all_embeddings.extend([[0.0] * EMBEDDING_DIM] * len(batch))

    return all_embeddings


def embed_texts(texts: list[str], batch_size: int = BATCH_SIZE) -> list[list[float]]:
    """Synchronous wrapper for embed_texts_async."""
    import asyncio
    return asyncio.run(embed_texts_async(texts, batch_size))


class CachedEmbedding:
    """Embedding with local file caching."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or settings.llm_cache_dir / "embeddings"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, list[list[float]]] = {}

    def _get_cache_path(self, texts: list[str]) -> Path:
        key = compute_cache_key(texts)
        return self.cache_dir / f"{key}.json"

    def get(self, texts: list[str]) -> list[list[float]] | None:
        """Get cached embeddings if available."""
        key = compute_cache_key(texts)
        if key in self._memory_cache:
            return self._memory_cache[key]

        cache_path = self._get_cache_path(texts)
        if cache_path.exists():
            try:
                with open(cache_path) as f:
                    data = json.load(f)
                self._memory_cache[key] = data["embeddings"]
                return data["embeddings"]
            except Exception:
                return None
        return None

    def set(self, texts: list[str], embeddings: list[list[float]]) -> None:
        """Cache embeddings to disk."""
        key = compute_cache_key(texts)
        self._memory_cache[key] = embeddings

        cache_path = self._get_cache_path(texts)
        with open(cache_path, "w") as f:
            json.dump({"texts": texts, "embeddings": embeddings}, f)

    def embed_cached(self, texts: list[str]) -> list[list[float]]:
        """Get cached or compute and cache."""
        cached = self.get(texts)
        if cached is not None:
            logger.debug("embedding_cache_hit", count=len(texts))
            return cached

        logger.debug("embedding_cache_miss", count=len(texts))
        embeddings = embed_texts(texts)
        self.set(texts, embeddings)
        return embeddings