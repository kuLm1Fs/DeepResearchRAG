# 项目启动文档

## 环境要求

- Python 3.10+
- Node.js 18+
- Docker Desktop

---

## 1. 启动 Milvus 向量数据库

```bash
cd docker
docker compose up -d
```

验证:
```bash
docker ps  # 应看到 milvus-standalone 容器
```

停止:
```bash
docker compose down
```

---

## 2. 配置后端

```bash
cd backend

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -e .

# 复制环境配置模板
cp configs/.env.example .env

# 编辑 .env 填入你的 API keys
# DEEPSEEK_API_KEY=sk-xxx
# VOLCENGINE_API_KEY=xxx
```

---

## 3. 启动后端服务

```bash
cd backend
source .venv/bin/activate
uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
```

API 文档: http://localhost:8000/docs

---

## 4. 播种测试数据（可选）

```bash
cd backend
source .venv/bin/activate

# 播种 10000 条 ag_news 数据
python scripts/seed_data.py --limit 10000

# 查看数据统计
curl http://localhost:8000/api/stats
```

---

## 5. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 开发模式
npm run dev
```

前端: http://localhost:3000

生产构建:
```bash
npm run build
```

---

## 6. 完整流程（一次性启动）

```bash
# 终端 1: 启动 Milvus
cd docker && docker compose up -d

# 终端 2: 启动后端
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp configs/.env.example .env
# 编辑 .env 填入 API keys
uvicorn src.api.app:app --reload

# 终端 3: 启动前端
cd frontend
npm install
npm run dev
```

---

## 环境变量说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ENV` | 环境 | `dev` |
| `LLM_PROVIDER` | LLM 提供商 | `deepseek` |
| `LLM_MODEL` | 模型名称 | `deepseek-chat` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `VOLCENGINE_API_KEY` | 火山引擎 API Key | - |
| `MILVUS_HOST` | Milvus 主机 | `localhost` |
| `MILVUS_PORT` | Milvus 端口 | `19530` |
| `LLM_CACHE` | 启用 LLM 缓存 | `true` |
| `DEBUG` | 调试模式 | `true` |

---

## 目录结构

```
backend/
├── src/
│   ├── api/         # FastAPI 路由
│   ├── agent/        # LangGraph Agent
│   ├── core/         # 核心配置
│   ├── llm/          # LLM 客户端
│   ├── retrieval/    # 多路召回
│   └── vectorstore/  # Milvus 存储
├── scripts/
│   ├── seed_data.py        # 播种数据
│   └── evaluate_retrieval.py  # 评估检索
└── .env                  # 环境配置

frontend/
├── src/
│   ├── components/    # React 组件
│   ├── api/          # API 调用
│   └── App.tsx       # 主界面
└── package.json

docker/
└── docker-compose.yml  # Milvus 服务
```