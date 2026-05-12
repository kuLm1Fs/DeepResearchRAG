# RAG News Intelligence — API 文档

## 后端 API

### 查询接口

```
POST /api/query
```

**请求体：**
```json
{
  "query": "最近 AI 领域有什么重大进展？",
  "filters": {
    "language": "zh",
    "date_from": "2026-01-01",
    "sources": ["36kr", "techcrunch"]
  },
  "stream": true
}
```

**响应：** SSE 流式输出

---

### 数据管理接口

```
POST /api/ingest/trigger     # 触发数据采集
GET  /api/ingest/status      # 查看采集状态
GET  /api/stats              # 数据统计
DELETE /api/articles/{id}    # 删除文章
```

### 系统管理接口

```
GET /api/health              # 健康检查
GET /api/config              # 查看当前配置
```

---

## 数据采集层 API

### RSSCollector

```python
from src.ingestion import RSSCollector

collector = RSSCollector()  # 使用默认源
articles = await collector.collect(since=datetime(2026, 1, 1))
```

**参数：**
- `sources`: `list[dict] | None` — RSS 源列表，每项含 `name`, `url`, `language`

**方法：**
- `collect(since=None)` → `list[Article]` — 采集所有源的文章

---

### HNCollector

```python
from src.ingestion import HNCollector

collector = HNCollector(max_stories=50)
articles = await collector.collect()
```

**参数：**
- `max_stories: int` — 最大采集数（默认 100）

**方法：**
- `collect(since=None)` → `list[Article]`

---

### DatasetCollector

```python
from src.ingestion import DatasetCollector

collector = DatasetCollector("ag_news", split="train")
articles = collector.collect(limit=1000)
```

**参数：**
- `dataset_name: str` — 数据集名（`ag_news` / `cnn_dailymail`）
- `split: str` — 分割（`train` / `test`）

**方法：**
- `collect(limit=None)` → `list[Article]`

---

### IngestionPipeline

```python
from src.ingestion import IngestionPipeline

pipeline = IngestionPipeline()
pipeline.register_defaults()  # 注册 RSS + HN + Dataset 采集器

# 批量采集
stats = await pipeline.run_all(since=datetime(2026, 1, 1))

# 单个采集
articles = await pipeline.run_single("rss")
```

**方法：**
- `register_collector(name, collector)` — 注册采集器
- `register_defaults()` — 注册默认采集器集合
- `run_all(since=None)` → `IngestionStats` — 运行所有
- `run_single(name, since=None)` → `list[Article]` — 运行指定

---

## 多路召回 API

### MultiPathRetriever

```python
from src.retrieval import MultiPathRetriever
from src.vectorstore import MilvusStore

store = MilvusStore()
retriever = MultiPathRetriever(store)
results = retriever.retrieve("AI news", top_k=5)
```

**参数：**
- `store: MilvusStore` — 向量存储实例
- `semantic_weight: float` — 语义召回权重（默认 0.5）
- `keyword_weight: float` — 关键词召回权重（默认 0.3）
- `title_weight: float` — 标题匹配权重（默认 0.2）

**方法：**
- `retrieve(query, top_k=5, filters=None)` → `list[dict]`

---

## LLM 缓存 API

### FileCache

```python
from src.core.cache import FileCache

cache = FileCache(cache_dir="data/llm_cache/v1", ttl=3600)
cache.set("key1", {"result": "value"})
data = cache.get("key1")
exists = cache.has("key1")
cache.delete("key1")
```

**方法：**
- `set(key, value)` — 存储
- `get(key)` → `Any | None` — 获取
- `has(key)` → `bool` — 是否存在
- `delete(key)` — 删除
- `clear()` — 清空所有

---

## CLI 命令

```bash
# 触发数据采集
python -m src.cli.main ingest --source rss
python -m src.cli.main ingest --all

# CLI 查询
python -m src.cli.main query "最近 AI 有什么进展？"

# 查看统计
python -m src.cli.main stats
```
