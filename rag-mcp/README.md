# rag-mcp

把这个仓库里已经写好的金融检索，做成标准 MCP 工具。Claude Code、Cursor，以及你自己的 Agent 平台，都可以用同一套 `search` / `ingest` / `get_document` 查文档、导入文档、核对引用。

检索和入库仍由 Python 完成（Milvus、火山引擎 Embedding、RRF、时间衰减、来源加权、bge reranker、`analyze_query`）。Go 进程只负责 MCP 协议、Bearer Token、租户隔离和超时取消。排序逻辑不在 Go 里重写一份。

## 准备

1. Python 后端能启动，并且能连上 Milvus。Embedding 要用的 `VOLCENGINE_API_KEY`（或你当前配置的 Embedding 服务）按原项目准备。
2. 本机有 Go。`mark3labs/mcp-go` v1.5 需要 Go 1.25.5。更早的 Go 会在 `go test` / `go build` 时自动下载这个工具链。Docker 镜像用 `golang:1.25.5`。
3. 后端和 MCP 进程使用同一个内部口令 `MCP_INTERNAL_TOKEN`。这个口令不给模型，只给这两个进程。

后端需要新增的环境变量：

| 变量 | 作用 |
| --- | --- |
| `MCP_INTERNAL_TOKEN` | Go 调用 `/api/internal/mcp/*` 时携带的共享口令。为空时这些接口返回 503。 |
| `MCP_SHARED_CORPUS` | 默认 `false`。设为 `true` 时，检索还可以读到 `company_id` 为空的公共文档（例如直接 seed 进 Milvus 的 FinanceBench），仍然读不到其他租户的文档。 |

## 环境变量（Go 进程）

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `RAG_BACKEND_URL` | `http://127.0.0.1:8000` | Python 后端地址 |
| `MCP_INTERNAL_TOKEN` | 无，必填 | 与后端一致的内部口令 |
| `MCP_TENANT_ID` | `local` | stdio 模式使用的租户，写入 Milvus 的 `company_id` |
| `MCP_TOKENS` | 空 | HTTP 模式必填。格式 `token=tenant,token2=tenant2`，或 JSON `{"token":"tenant"}` |
| `MCP_BEARER_TOKEN` | 空 | 只配一个 token 时，可以代替 `MCP_TOKENS`，租户用 `MCP_TENANT_ID` |
| `RAG_MCP_TRANSPORT` | `stdio` | `stdio` 或 `http` |
| `RAG_MCP_ADDR` | `:8081` | HTTP 监听地址 |
| `RAG_MCP_INGEST_ROOT` | 空 | `ingest` 的 `file_path` 只能读这个目录里的文件。不设就拒绝 `file_path` |
| `RAG_MCP_SEARCH_TIMEOUT` | `45s` | 单次 search 超时 |
| `RAG_MCP_INGEST_TIMEOUT` | `120s` | 单次 ingest 超时 |
| `RAG_MCP_DOCUMENT_TIMEOUT` | `20s` | 单次 get_document 超时 |
| `LOG_LEVEL` | `INFO` | 日志打到 stderr，JSON，每条工具调用带 `trace_id` |

示例见 `rag-mcp/.env.example`。

## 一条命令启动

先起后端（在仓库根目录另开一个终端）：

```bash
cd backend
export PYTHONPATH=src
export MCP_INTERNAL_TOKEN=dev-internal-token-please-change
uvicorn src.api.app:app --reload --port 8000
```

本地 stdio（给 Claude Code / Cursor 拉起进程用；你自己试手时也可以直接跑）：

```bash
cd rag-mcp
export MCP_INTERNAL_TOKEN=dev-internal-token-please-change
export MCP_TENANT_ID=local
export RAG_BACKEND_URL=http://127.0.0.1:8000
make run-stdio
```

远程 HTTP：

```bash
cd rag-mcp
export MCP_INTERNAL_TOKEN=dev-internal-token-please-change
export MCP_TOKENS=dev-bearer-token=local
export RAG_BACKEND_URL=http://127.0.0.1:8000
make run-http
```

健康检查：`curl -s http://127.0.0.1:8081/healthz`，应返回 `{"status":"ok"}`。MCP 入口是 `http://127.0.0.1:8081/mcp`，没有 Bearer Token 会 401。

只用 Docker 起 MCP 进程（后端已经在宿主机的 8000 端口）：

```bash
cd rag-mcp
export MCP_INTERNAL_TOKEN=dev-internal-token-please-change
export MCP_TOKENS=dev-bearer-token=local
docker compose up --build
```

整套栈一起起（Milvus、后端、MCP）。在 `docker/` 目录：

```bash
export MCP_INTERNAL_TOKEN=dev-internal-token-please-change
export MCP_TOKENS=dev-bearer-token=local
docker compose --profile mcp up -d --build rag-mcp
```

`rag-mcp` 用了 compose profile `mcp`，平常 `docker compose up` 不会把它拉起来。

导入本地文件前，设置 `RAG_MCP_INGEST_ROOT` 指向放财报的目录。Docker 里这个目录挂到容器的 `/data`，宿主机目录用 `RAG_MCP_INGEST_HOST_DIR` 指定。

## 接到 Claude Code

在项目根目录放 `.mcp.json`，或写进用户配置。stdio 由 Claude Code 自己拉起进程，不需要先手动 `make run-stdio`。

```json
{
  "mcpServers": {
    "rag-finance": {
      "command": "/绝对路径/DeepResearchRAG/rag-mcp/bin/rag-mcp",
      "args": ["-transport", "stdio"],
      "env": {
        "RAG_BACKEND_URL": "http://127.0.0.1:8000",
        "MCP_INTERNAL_TOKEN": "dev-internal-token-please-change",
        "MCP_TENANT_ID": "local",
        "RAG_MCP_INGEST_ROOT": "/绝对路径/filings"
      }
    }
  }
}
```

二进制先在 `rag-mcp` 里执行一次 `make build`。后端要先在 8000 端口跑着。

已经单独起了 HTTP 服务时，改成远程连接：

```json
{
  "mcpServers": {
    "rag-finance": {
      "type": "http",
      "url": "http://127.0.0.1:8081/mcp",
      "headers": {
        "Authorization": "Bearer dev-bearer-token"
      }
    }
  }
}
```

`dev-bearer-token` 必须出现在 `MCP_TOKENS` 里。这个 token 决定租户，模型改不了。

## 接到 Cursor

项目里的 `.cursor/mcp.json`，或 Cursor Settings → MCP。stdio：

```json
{
  "mcpServers": {
    "rag-finance": {
      "command": "/绝对路径/DeepResearchRAG/rag-mcp/bin/rag-mcp",
      "args": ["-transport", "stdio"],
      "env": {
        "RAG_BACKEND_URL": "http://127.0.0.1:8000",
        "MCP_INTERNAL_TOKEN": "dev-internal-token-please-change",
        "MCP_TENANT_ID": "local"
      }
    }
  }
}
```

远程 Streamable HTTP：

```json
{
  "mcpServers": {
    "rag-finance": {
      "url": "http://127.0.0.1:8081/mcp",
      "headers": {
        "Authorization": "Bearer dev-bearer-token"
      }
    }
  }
}
```

自己的 Agent 平台同样：stdio 就拉起上面的二进制；远程就连 `http://<host>:8081/mcp`，请求头带 `Authorization: Bearer <token>`。给每个客户发不同的 token，就得到不同的数据集。

## 三个工具怎么调

先在同一个租户里导入，再搜。stdio 的租户是 `MCP_TENANT_ID`（默认 `local`）。别的租户、以及 `company_id` 为空的旧数据，默认都搜不到。旧的公共库要被搜到时，后端设 `MCP_SHARED_CORPUS=true`。

**search**

```json
{
  "query": "3M 2018 年资本开支是多少？",
  "top_k": 5,
  "rewrite": true,
  "context": "上一轮在看 3M 的 10-K",
  "filters": {
    "language": "en",
    "source": "sec",
    "published_at_from": 1514764800,
    "published_at_to": 1546300799
  }
}
```

`rewrite` 默认 true。它会调用仓库里的 `analyze_query`：补全指代（靠 `context`），并把复杂问题拆成子问题，再逐条检索、去重。改写失败时用原问题继续搜，结果里的 `rewrite_fallback` 为 true。

返回的每条 evidence 都有 `doc_id`、`source`、`timestamp`、`score`，以及 `title`、`content`、`chunk_id`。`score` 用的是加权后的排序分（有 `boosted_score` 用它，否则用融合分）。

**ingest**

三选一：`text`、`url`、`file_path`。

```json
{ "text": "3M 2018 10-K. Purchases of property, plant and equipment were $1,577 million.", "title": "3M 2018 capex", "source": "sec" }
```

```json
{ "url": "https://example.com/filing.html", "source": "sec" }
```

```json
{ "file_path": "3M_2018_10K.txt", "source": "sec" }
```

`file_path` 相对 `RAG_MCP_INGEST_ROOT`，不能跳出这个目录，也不跟随指向目录外的符号链接。`url` 只允许公网 http/https，回环、内网和云元数据地址会被拒绝。返回 `doc_id`。正文超过约 40 万字会截断，并在 `truncated` 里标明。

**get_document**

```json
{ "doc_id": "上一步返回的 doc_id" }
```

把该文档的分块按顺序拼回正文，用来核对引用。别的租户的 id 返回 404，不说明这份文档是否存在。

## 设计（面试时可以这么讲）

**为什么是 MCP。** 检索能力原来只在 FastAPI 的 `/api/query` 后面，每个 Agent 都得单独接。MCP 是 Claude Code、Cursor 和自建 Agent 平台都认识的工具协议。检索只维护一份，接新客户端只改配置，不改排序。

**为什么 Go 不重写排序。** 向量检索、关键词、标题匹配、RRF、时间衰减、来源质量、bge 交叉编码器、查询改写，都已经在 Python 里跑过。再在 Go 里写一遍，两边会慢慢不一致。Go 做协议、鉴权、超时和日志；Python 在 `/api/internal/mcp/` 下把原来的 `MultiPathRetriever`、`analyze_query` 和入库流水线包出来。内部口令不对，这组接口不可用。

**两种传输。** `stdio` 给本机 IDE：编辑器拉起进程，走标准输入输出，没有端口，租户固定为 `MCP_TENANT_ID`。`http` 是 Streamable HTTP，给远程和多租户：一个进程，多个 Bearer Token，每个 token 在启动时绑死一个租户。同一个 `/mcp` 同时接受带 session 的旧协议（到 2025-11-25）和 2026-07-28 的无 session 协议，Claude Code 和 Cursor 用哪一版都能连。

**租户隔离。** 模型能填的只有 query、过滤器和文档内容，没有租户字段。HTTP 中间件先检查 Bearer Token，未知 token 直接 401。通过后，token 对应的租户放进请求上下文，再作为 `X-Tenant-ID` 交给 Python。Python 把 Milvus 过滤条件里的 `company_id` 设成这个租户，并丢掉调用方自己传的 `company_id` / `user_id`。取回的行还会再对一遍，别的租户的 chunk 丢掉。`get_document` 用同一条 `company_id` 条件。所以换一个 token，就是另一套文档；知道别人的 `doc_id` 也读不出来。

**取消和超时。** 每次工具调用在 Go 里套一个超时（search 45 秒、ingest 120 秒、get_document 20 秒）。客户端取消 MCP 请求时，这个 context 被取消，打到 Python 的 HTTP 请求一起断开。Python 在等待检索或入库时检查连接是否已断开，断开就取消任务，不再占着 Embedding 或 Milvus。日志是 JSON，打在 stderr（避免污染 stdio 协议），每条带这次调用的 `trace_id`，并传给后端的 `X-Trace-ID`。

**慢查询进度。** 如果客户端在工具调用里带了 MCP 的 `progressToken`，search 会按阶段发 `notifications/progress`：改写、检索、完成。检索超过两秒还会补一条 “still searching”。mcp-go 支持这组通知；客户端没要进度时不发，避免无 token 的通知被拒绝。

## 测试和评测

Go 工具处理函数用假的后端测过租户、改写失败回退、路径越界和取消：

```bash
cd rag-mcp
go test ./...
```

Python 桥接不连 Milvus：

```bash
cd backend
python -m pytest tests/test_mcp_internal.py -q
```

FinanceBench 对比脚本在 `rag-mcp/eval/eval_financebench.py`。它比较「用 MCP 检索到的证据」和「不给证据、直接让模型答」：证据命中率，以及金标数字有没有出现在答案里。脚本连不上 MCP、检索报错，或你没让它跑时，不会输出分数。

```bash
cd rag-mcp
python eval/eval_financebench.py --self-check
```

真正开跑（后端、Milvus、Embedding、MCP HTTP 都已就绪，并且该租户能搜到 FinanceBench 文档；公共 seed 数据需要后端 `MCP_SHARED_CORPUS=true`）：

```bash
export MCP_BEARER_TOKEN=dev-bearer-token
export DEEPSEEK_API_KEY=...          # 不设的话只算证据命中率，答案质量标成未测量
python eval/eval_financebench.py --limit 20 --out eval/results.json
```

没有密钥或 Milvus 时不要跑出数字来填简历。简历上写「做了可复现的对比脚本」即可，数字必须来自你自己跑出来的 `results.json`。
