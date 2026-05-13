# RAG News Intelligence — TODO

## Phase 1: 基础架构 ✅ 全部完成

- [x] 项目结构搭建（monorepo: backend + frontend）
- [x] Docker Compose（Milvus + etcd + MinIO）
- [x] 核心模块：config / logging / errors / middleware / cache
- [x] 采集器：RSS（8个源）/ HN / HuggingFace ag_news
- [x] 采集 Pipeline
- [x] Embedding 模块（aihubmix bge-large-zh）
- [x] Milvus 向量存储
- [x] 检索器：多路检索 + RRF 融合 + CrossEncoder 重排
- [x] LLM 客户端（DeepSeek）
- [x] LLM 缓存
- [x] Agent 状态定义
- [x] Agent 节点：retrieve / generate_answer / self_reflect
- [x] Agent 图：LangGraph 流程
- [x] Prompt 模板系统（v1）
- [x] API 路由（FastAPI + SSE 流式）
- [x] 数据导入 CLI 脚本（seed_data.py）
- [x] 前端：ChatWindow / HealthBadge / IngestPanel

## Phase 2: Bug 修复 ✅ 全部完成

- [x] Issue 1: agent/nodes.py 相对导入路径错误
- [x] Issue 2: llm/cache.py 循环导入
- [x] Issue 3: api/models.py 缺少 fastapi 依赖
- [x] Issue 4: core/logging.py Processor 类型错误
- [x] Issue 5: core/logging.py structlog.INFO 不存在
- [x] Issue 6: Embedding batch_size=50 导致零向量（修复为16）
- [x] Issue 7: Semantic search async 嵌套 asyncio.run() 报错
- [x] Issue 8: 前端 markdown 渲染（添加 react-markdown + remark-gfm）

## Phase 3: Agent Workflow 升级 ✅ 全部完成

- [x] analyze_query 改为 LLM 调用（意图分析 + query 改写 + 子查询生成）
- [x] 新增 plan_retrieval 节点（按意图规划检索策略）
- [x] retrieve 升级为多轮检索 + 去重合并
- [x] evaluate_relevance 改为 LLM 调用（质量评估 + 缺口识别）
- [x] 新增 should_research 条件边（是否需要补检索）
- [x] 新增 re_search 节点（补充检索，最多1轮）
- [x] 新增 analyze_query.txt prompt 模板（JSON 输出）
- [x] 新增 evaluate_relevance.txt prompt 模板（JSON 输出）
- [x] 更新 generate_answer.txt prompt（意图分类 + markdown 格式）
- [x] LLM JSON 解析 fallback 机制
- [x] 端到端测试通过（API → Agent → LLM → SSE 流式响应）

## Phase 4: 功能增强 ⏳ 待开发

- [ ] RSS 全文抓取（trafilatura）— 用户明确要求
- [ ] RSS 数据导入 Milvus（目前只有 ag_news 1000条）
- [ ] RSS 定时采集 cron
- [ ] 多语言搜索支持
- [ ] 搜索结果历史记录

## Phase 5: 部署 ⏳ 待开发

- [ ] .env.prod 安全检查（API keys 不能提交到 git）
- [ ] 生产环境配置
- [ ] 前端构建优化
- [ ] Docker 部署配置

## 待处理

- [ ] 当前改动 git commit（8个文件未提交）
- [ ] 前端效果验证（用户刷新浏览器测试）
- [ ] task-*.txt 临时文件清理
