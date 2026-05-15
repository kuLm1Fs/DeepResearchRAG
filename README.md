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

### 1. Start Docker Services (Milvus + PostgreSQL)

```bash
cd docker
docker compose up -d

# 确认服务运行中
docker compose ps
```

### 2. Initialize PostgreSQL Database

```bash
# 建表（如果提示 database 不存在，先建数据库）
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -d rag_news < docs/schema.sql

# 或分步执行：
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -c "CREATE DATABASE rag_news;"
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -d rag_news < docs/schema.sql
```

### 3. Backend Setup

```bash
cd backend

# 复制配置并填写 API keys
cp configs/.env.example configs/.env.dev

# 安装依赖
make install   # 或：uv sync

# 开发模式启动（自动设置 PYTHONPATH）
make dev      # 或：uv run uvicorn src.api.app:app --reload
```

> **Tip**: 使用 `make dev` 不需要手动设置 PYTHONPATH，Makefile 已自动 export。

### 4. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

## Python Environment

后端使用 [uv](https://github.com/astral-sh/uv) 管理依赖：
- `uv sync` - 安装所有依赖
- `uv run <command>` - 在虚拟环境中运行命令
- `uv sync --frozen` - 生产部署锁定版本

Makefile 命令：
- `make install` - 安装依赖
- `make dev` - 开发模式启动
- `make lint` - 代码检查

## API Endpoints

User Query → FastAPI → LangGraph Agent → Multi-path Retrieval → RRF Fusion → Answer Generation