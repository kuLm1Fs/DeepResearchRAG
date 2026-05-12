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
pip install -e .
cp configs/.env.example .env
# Edit .env with your API keys
uvicorn src.api.app:app --reload
```

### 3. Seed Data

```bash
python scripts/seed_data.py --limit 10000
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

## Architecture

User Query → FastAPI → LangGraph Agent → Multi-path Retrieval → RRF Fusion → Answer Generation