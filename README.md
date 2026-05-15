# RAG News Intelligence

A news RAG system supporting Chinese/English, multi-source data collection, vector retrieval, and LangGraph Agent-powered Q&A with source citations.

## Tech Stack

- **Backend**: Python + FastAPI
- **RAG Framework**: LangChain + LangGraph
- **LLM**: DeepSeek API (primary), OpenAI/Qwen (fallback)
- **Embedding**: 火山引擎 Embedding API
- **Vector DB**: Milvus full edition
- **Frontend**: React + TypeScript + Vite + Tailwind CSS

## Quick Start

### 1. Start Milvus

```bash
cd docker
docker compose up -d
```

### 2. Backend Setup

```bash
cd backend
uv sync                    # 安装依赖（Rust 实现，比 pip 快）
cp configs/.env.example .env
# Edit .env with your API keys
uv run uvicorn src.api.app:app --reload
```

> **Tip**: 生产部署使用 `uv sync --frozen` 锁定依赖版本，确保开发/生产环境一致。

### 3. Seed Data

```bash
uv run python scripts/seed_data.py --limit 10000
```

### 4. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

## API Endpoints

- `POST /api/query` - Query with SSE streaming
- `GET /api/stats` - Collection statistics
- `GET /api/health` - Health check

## Python Environment

后端使用 [uv](https://github.com/astral-sh/uv) 管理依赖：
- `uv sync` - 安装所有依赖
- `uv run <command>` - 在虚拟环境中运行命令
- `uv sync --frozen` - 生产部署锁定版本

## Architecture

User Query → FastAPI → LangGraph Agent → Multi-path Retrieval → RRF Fusion → Answer Generation