# RAG News Intelligence

English | [简体中文](README.md)

RAG News Intelligence is a bilingual news RAG system for Chinese and English news. It supports multi-source collection, cleaning, embedding, hybrid retrieval, LangGraph Agent-powered Q&A, and source citations. The system is designed to handle 100K to 1M news articles on a 4-core / 15.6GB server.

## Features

- Multi-source ingestion: RSS, HN API, Reddit API, HuggingFace datasets, and custom crawlers.
- Bilingual processing: Chinese and English cleaning, chunking, retrieval, and Q&A.
- Hybrid retrieval: semantic vector search, Milvus FULLTEXT keyword search, and exact title matching.
- RRF fusion: default `k=60` with weights `0.5 / 0.3 / 0.2`.
- Agent workflow: LangGraph orchestration for query analysis, routing, retrieval evaluation, multi-source comparison, answer generation, and self-reflection.
- Pluggable LLM providers: DeepSeek by default, with OpenAI and Qwen as fallbacks via `LLM_PROVIDER`.
- Cloud embeddings: Volcengine Embedding API, 1024 dimensions, default batch size 50.
- Observability: request-level `trace_id`, structured logs, sensitive value redaction, controlled debug mode, and optional LLM cache.
- Full-stack app: FastAPI SSE streaming backend with a React / Vite / Tailwind frontend.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.10+, FastAPI |
| Agent / RAG | LangChain, LangGraph |
| LLM | DeepSeek, OpenAI, Qwen |
| Embedding | Volcengine Embedding API |
| Vector DB | Milvus standalone + etcd + MinIO |
| Structured Storage | PostgreSQL |
| Frontend | React, TypeScript, Vite, Tailwind CSS |

## Architecture

```text
User query
  -> FastAPI SSE API
  -> LangGraph Agent
      -> Query analysis
      -> Route decision
      -> Multi-path retrieval
          -> Semantic vector search
          -> Keyword full-text search
          -> Exact title match
      -> RRF fusion
      -> Result evaluation
      -> Multi-source comparison
      -> Answer generation
      -> Self-reflection
  -> Streaming answer with source citations
```

## Repository Layout

```text
.
├── backend/                 # FastAPI, LangGraph Agent, retrieval, ingestion, evaluation
│   ├── src/
│   ├── scripts/
│   ├── tests/
│   ├── configs/.env.example
│   └── Makefile
├── frontend/                # React + TypeScript frontend
├── docker/                  # Milvus, etcd, MinIO, PostgreSQL
├── docs/                    # Design docs, API docs, database schema
├── scripts/                 # Project-level scripts
└── README.md                # Chinese README
```

## Requirements

- Python 3.10+
- Node.js 18+
- Docker / Docker Compose
- A DeepSeek, OpenAI, or Qwen API key
- A Volcengine Embedding API key

## Quick Start

### 1. Start Infrastructure Services

```bash
cd docker
docker compose up -d
docker compose ps
```

This starts Milvus, etcd, MinIO, and PostgreSQL.

### 2. Initialize PostgreSQL

```bash
cd docker
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -d rag_news < ../docs/schema.sql
```

If the database does not exist yet, create it first:

```bash
cd docker
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -c "CREATE DATABASE rag_news;"
```

### 3. Configure and Run the Backend

```bash
cd backend
cp configs/.env.example configs/.env.dev
```

Edit `backend/configs/.env.dev` and provide at least:

```bash
DEEPSEEK_API_KEY=sk-xxx
VOLCENGINE_API_KEY=xxx
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
```

Install dependencies and start the development server:

```bash
make install
make dev
```

Or use uv directly:

```bash
uv sync
uv run uvicorn src.api.app:app --reload
```

The backend API docs are available at http://localhost:8000/docs by default.

### 4. Run the Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server is available at http://localhost:5173 by default.

## Ingestion and Evaluation

Import sample HuggingFace `ag_news` data:

```bash
cd backend
python scripts/seed_data.py
```

Evaluate retrieval quality:

```bash
cd backend
python scripts/evaluate_retrieval.py
```

Evaluation output is written to `backend/data/eval_results/`. The target metric is `Precision@5 >= 0.8`.

## Core Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `ENV` | Runtime environment | `dev` |
| `DEBUG` | Enable debug mode | `true` |
| `LLM_PROVIDER` | LLM provider: `deepseek`, `openai`, or `qwen` | `deepseek` |
| `LLM_MODEL` | LLM model name | `deepseek-chat` |
| `DEEPSEEK_API_KEY` | DeepSeek API key | - |
| `OPENAI_API_KEY` | OpenAI API key | - |
| `QWEN_API_KEY` | Qwen API key | - |
| `VOLCENGINE_API_KEY` | Volcengine API key | - |
| `MILVUS_HOST` | Milvus host | `localhost` |
| `MILVUS_PORT` | Milvus port | `19530` |
| `POSTGRES_HOST` | PostgreSQL host | `localhost` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `LLM_CACHE` | Enable LLM response cache | `true` |
| `PROMPT_VERSION` | Prompt version | `v1` |

Production mode forces debug capabilities such as `llm_cache`, `retrieval_dump`, and `debug` off.

## API

Main endpoints:

- `POST /api/query`: SSE streaming Q&A endpoint.
- `GET /api/stats`: data and system statistics.
- Data management endpoints for article ingestion, status checks, and retrieval debugging.

See `docs/api-docs.md` for more details.

## Development Commands

Backend:

```bash
cd backend
make install
make dev
make lint
uv run pytest
```

Frontend:

```bash
cd frontend
npm run dev
npm run build
```

Infrastructure:

```bash
cd docker
docker compose up -d
docker compose down
```

## Prompts and Cache

Prompt templates live in `backend/src/agent/templates/` and are versioned by directory, such as `v1/` and `v2/`, with an optional `current` symlink. Select a prompt set at runtime through `PROMPT_VERSION`.

LLM response cache lives in `backend/data/llm_cache/{version}/`. Cache keys include the model, prompt version, and input content to make experiments easier to reproduce.

## Observability and Safety

- Every request gets a `trace_id`, propagated through the `X-Trace-ID` response header.
- structlog is used for structured logging.
- Logs redact sensitive patterns such as API keys.
- Errors are split into ignorable and critical levels: empty retrievals can be logged and skipped, while Milvus outages or invalid API keys abort the request.

## License

Add a LICENSE file before publishing this project as open source.
