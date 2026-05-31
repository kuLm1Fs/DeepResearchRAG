# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RAG Finance Intelligence — a finance-focused RAG system supporting Chinese/English, multi-source financial data collection, vector retrieval, and LangGraph Agent-powered Q&A with source citations. Designed for 100K–1M financial documents on a 4-core/15.6GB server.

## Tech Stack

| Layer | Choice |
|-------|--------|
| Backend | Python + FastAPI |
| RAG Framework | LangChain + LangGraph |
| LLM | DeepSeek API (primary), OpenAI / Qwen (fallback) — switched via `LLM_PROVIDER` env var |
| Embedding | 火山引擎 Embedding API (cloud, dim=1024, batch_size=50) |
| Vector DB | Milvus full edition (Docker Compose: milvus + etcd + MinIO) |
| Frontend | React + TypeScript + Vite + Tailwind CSS |

## Architecture

```
User Query → FastAPI (SSE) → LangGraph Agent
                                ├─ Query Analysis (LLM structured output)
                                ├─ Route Decision (rules + LLM fallback)
                                ├─ Multi-path Retrieval
                                │   ├─ Semantic (COSINE vector search)
                                │   ├─ Keyword (Milvus FULLTEXT)
                                │   └─ Title exact match
                                ├─ RRF Fusion (k=60, weights [0.5, 0.3, 0.2])
                                ├─ Result Evaluation
                                ├─ Multi-source Comparison
                                ├─ Answer Generation (LLM)
                                └─ Self-reflection
```

## Key Conventions

### Prompt Management
- Prompts stored in `src/agent/templates/` as `.txt` files, versioned by directory (`v1/`, `v2/`, `current` symlink)
- Switch version via `PROMPT_VERSION` env var
- Debug mode logs full prompt content with truncated variables

### LLM Abstraction
- `BaseLLM` ABC with `chat()` and `stream_chat()` methods
- Concrete: `DeepSeekLLM`, `OpenAILLM`, `QwenLLM`
- LLM responses cached in `data/llm_cache/{version}/` — cache key includes model + prompt version

### Observability
- `trace_id` middleware: every request gets a UUID, propagated through the entire call chain via `X-Trace-ID` header
- structlog for structured logging; sensitive patterns (API keys) auto-redacted in logs
- Production (`env=prod`) forces off: `llm_cache`, `retrieval_dump`, `debug`

### Error Handling
- Two levels: **ignorable** (log + continue, e.g. empty retrieval) and **critical** (raise + abort, e.g. Milvus down, invalid API key)

### Milvus Schema
- Collection: `news_articles`, IVF_FLAT index on embedding (COSINE, nlist=128)
- Incremental updates via `content_hash` (SHA256) dedup
- Fulltext index on `title` and `content` for keyword retrieval

### Embedding
- 火山引擎 API with tenacity retry (3 attempts, exponential backoff)
- Auto-batching at batch_size=50, zero local model load

## Development

### Backend (Python)
```bash
cd backend
# Install dependencies
pip install -e .

# Run development server
uvicorn src.api.app:app --reload

# Seed data (HuggingFace ag_news, 10K records)
python scripts/seed_data.py

# Evaluate retrieval quality
python scripts/evaluate_retrieval.py
# Output: data/eval_results/{date}.json, target: Precision@5 ≥ 0.8
```

### Frontend (React)
```bash
cd frontend
npm install
npm run dev      # Vite dev server
npm run build    # Production build
```

### Docker (Milvus)
```bash
cd docker
docker compose up -d     # Start Milvus + etcd + MinIO
docker compose down      # Stop all
```

### Environment
- `.env.dev` — local dev: `DEBUG=true`, `LLM_CACHE=true`
- `.env.prod` — production: `DEBUG=false`, all dumps disabled
- Key vars: `DEEPSEEK_API_KEY`, `VOLCENGINE_API_KEY`, `MILVUS_HOST`, `MILVUS_PORT`, `LLM_PROVIDER`, `LLM_MODEL`

## Data Flow

1. **Ingestion**: Financial data sources (finance RSS, SEC filings, financial news APIs, HuggingFinance datasets) → `BaseCollector` subclasses → preprocessor (clean + chunk via `RecursiveCharacterTextSplitter`, chunk_size=500) → 火山引擎 embedding → Milvus insert (dedup via content_hash)
2. **Retrieval**: Multi-path recall → RRF fusion → optional re-ranking (BAAI/bge-reranker-v2-m3)
3. **Generation**: LangGraph agent state flows through nodes, answer includes source citations
4. **API**: `POST /api/query` (SSE streaming), `GET /api/stats`, data management endpoints
5. **Frontend**: 70/30 split layout — chat window (streaming) + collapsible source panel with hover-expand cards
