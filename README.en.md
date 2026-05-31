# RAG Finance Intelligence

English | [简体中文](README.md)

A bilingual finance-focused RAG system for Chinese and English. Supports multi-source financial data collection, vectorization, hybrid retrieval, LangGraph Agent Q&A, and source citations. Designed to handle 100K–1M financial documents on a 4-core / 15.6GB server.

## Features

### Data Collection & Processing
- Multi-source ingestion: financial RSS, SEC filings, financial news APIs, HuggingFace finance datasets
- Bilingual processing: Chinese/English cleaning, chunking (RecursiveCharacterTextSplitter, chunk_size=500), retrieval, and Q&A
- Cloud embedding: Volcengine API, 1024 dimensions, batch size 50, auto-retry
- Incremental dedup: SHA256 content_hash-based Milvus upserts

### Retrieval & Generation
- Hybrid retrieval: semantic vector search (COSINE), Milvus FULLTEXT keyword search, exact title match
- RRF fusion: `k=60`, weights `0.5 / 0.3 / 0.2`
- Time decay boosting: exponential decay based on `published_at` (configurable half-life)
- Date range filtering: `date_from` / `date_to` query parameters
- LangGraph Agent workflow: query analysis → routing → multi-path retrieval → evaluation → comparison → generation → self-reflection
- Pluggable LLM: DeepSeek by default, OpenAI / Qwen via `LLM_PROVIDER`

### Deep Research
- Five-stage pipeline: Planner → Retriever → Analyst → Checker → Writer
- Auto gap-filling: Checker triggers re-retrieval when gaps detected (up to 20 tool calls)
- Quality reports: evidence coverage, source diversity, freshness, credibility issues, gap/conflict detection
- PPT outline generation: automatic slide outline extraction from research reports
- Real-time progress: SSE streaming of current step, execution logs, and intermediate results
- Task cancellation: cancel running research tasks via API

### Platform Capabilities
- JWT auth: registration, login, token refresh, multi-device concurrency
- Multi-tenancy: company_id-based data isolation and quota management
- Audit logging: key operations (queries, ingestion, research) automatically logged
- Request-level observability: `trace_id` propagation, structlog, sensitive value redaction
- Full-stack: FastAPI SSE streaming + React / Vite / Tailwind frontend

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
| Deployment | Docker / Docker Compose |

## Architecture

```text
User Query
  -> FastAPI SSE API (JWT auth + trace_id)
  -> LangGraph Agent
      -> Query analysis (LLM structured output)
      -> Route decision (rules + LLM fallback)
      -> Multi-path retrieval
          -> Semantic vector search (COSINE)
          -> Keyword full-text search (FULLTEXT)
          -> Exact title match
      -> RRF fusion
      -> Time decay boosting
      -> Result evaluation
      -> Multi-source comparison
      -> Answer generation (LLM)
      -> Self-reflection
  -> Streaming answer with source citations
```

Deep Research flow:

```text
Research Question
  -> POST /api/research (async task creation)
  -> Planner (decompose into sub-questions)
  -> Retriever (multi-path retrieval)
  -> Analyst (extract claims)
  -> Checker (verify + gap detection)
      -> Gaps found? Loop back to Retriever (up to N rounds)
  -> Writer (generate report + PPT outline)
  -> SSE real-time progress streaming
```

## Repository Layout

```text
.
├── backend/                    # FastAPI backend
│   ├── src/
│   │   ├── api/                # Routes, auth, models
│   │   ├── agent/              # LangGraph Agent, Deep Research
│   │   ├── retrieval/          # Hybrid retrieval, fusion, reranking
│   │   ├── core/               # Logging, audit, rate limiting
│   │   └── db/                 # PostgreSQL connection & models
│   ├── tests/                  # pytest test suite
│   ├── scripts/                # Data import, evaluation scripts
│   ├── Dockerfile
│   └── Makefile
├── frontend/                   # React + TypeScript frontend
│   ├── src/
│   │   ├── components/         # ChatWindow, ResearchPanel, IngestPanel, etc.
│   │   ├── api/                # API client (token refresh, error handling)
│   │   └── types/              # TypeScript type definitions
│   └── Dockerfile
├── docker/                     # Docker Compose infrastructure
├── docs/                       # Design docs, deployment guide, database schema
└── .github/                    # CI/CD workflows
```

## Quick Start

### 1. Start Infrastructure

```bash
cd docker
docker compose up -d
```

Starts Milvus, etcd, MinIO, and PostgreSQL.

### 2. Initialize Database

```bash
cd docker
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -c "CREATE DATABASE rag_news;"
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -d rag_news < ../docs/schema.sql
```

### 3. Configure Backend

```bash
cd backend
cp configs/.env.example configs/.env.dev
```

Edit `configs/.env.dev` with at least:

```bash
DEEPSEEK_API_KEY=sk-xxx
VOLCENGINE_API_KEY=xxx
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
```

### 4. Start Backend

```bash
cd backend
make install
make dev
```

Or with uv:

```bash
uv sync
uv run uvicorn src.api.app:app --reload --app-dir src
```

API docs: http://localhost:8000/docs

### 5. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173

## Docker Deployment

Full Docker deployment guide: [docs/deployment.md](docs/deployment.md).

```bash
cd docker
docker compose up -d --build
docker compose logs -f backend
```

## API Endpoints

### Authentication

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/auth/register` | Register (optional company_name) |
| POST | `/api/auth/login` | Login, returns access + refresh tokens |
| POST | `/api/auth/refresh` | Refresh access token |

### Query & Retrieval

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/query` | SSE streaming Q&A, supports `date_from` / `date_to` |
| GET | `/api/stats` | Data and system statistics |
| GET | `/api/health` | Health check |

### Data Ingestion

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/ingest/trigger` | Trigger data collection (returns task_id) |
| GET | `/api/ingest/status` | Global ingestion status |
| GET | `/api/ingest/task/{task_id}` | Query single task progress |
| GET | `/api/ingest/tasks` | List all active tasks for current user |

### Deep Research

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/research` | Create research task (async execution) |
| GET | `/api/research/{task_id}` | Query task status and results |
| GET | `/api/research/{task_id}/status` | Query current step progress |
| GET | `/api/research/{task_id}/events` | SSE real-time progress stream |
| POST | `/api/research/{task_id}/cancel` | Cancel a running task |

See http://localhost:8000/docs (Swagger UI) for full details.

## Core Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `ENV` | Runtime environment | `dev` |
| `DEBUG` | Debug mode | `true` |
| `LLM_PROVIDER` | LLM provider | `deepseek` |
| `LLM_MODEL` | LLM model name | `deepseek-chat` |
| `DEEPSEEK_API_KEY` | DeepSeek API key | - |
| `VOLCENGINE_API_KEY` | Volcengine API key | - |
| `MILVUS_HOST` | Milvus host | `localhost` |
| `MILVUS_PORT` | Milvus port | `19530` |
| `POSTGRES_HOST` | PostgreSQL host | `localhost` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `JWT_SECRET` | JWT signing secret | - |
| `LLM_CACHE` | LLM response cache | `true` |
| `PROMPT_VERSION` | Prompt version | `v1` |

Production (`ENV=prod`) forces off: `llm_cache`, `retrieval_dump`, `debug`.

## Development

### Backend

```bash
cd backend
make install          # Install dependencies
make dev              # Start dev server
make lint             # Lint code
uv run pytest         # Run tests (97 test cases)
```

### Frontend

```bash
cd frontend
npm install           # Install dependencies
npm run dev           # Dev server
npm run build         # Production build
```

### Data Import & Evaluation

```bash
cd backend
python scripts/seed_data.py            # Import HuggingFace ag_news sample data
python scripts/evaluate_retrieval.py   # Retrieval quality evaluation (target Precision@5 >= 0.8)
```

## Prompt Management

Prompt templates live in `backend/src/agent/templates/`, versioned by directory (`v1/`, `v2/`), with a `current` symlink pointing to the active version. Select at runtime via `PROMPT_VERSION`.

LLM response cache lives in `backend/data/llm_cache/{version}/`. Cache keys include model, prompt version, and input for experiment reproducibility.

## Observability

- Every request gets a `trace_id`, propagated via `X-Trace-ID` header
- structlog structured logging with automatic API key redaction
- Error classification: ignorable errors (empty retrieval) log and continue; critical errors (Milvus down, invalid API key) abort the request
- Audit logging for key operations (queries, ingestion, research tasks)

## License

[MIT License](LICENSE)
