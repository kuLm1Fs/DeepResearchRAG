# Deep Research Agent — 数据库设计

## 概览

| 数据库 | 用途 | 数据特点 |
|--------|------|---------|
| **PostgreSQL** | 用户、公司、任务、认证 | 关系型，结构化 |
| **Milvus** | 向量检索 | ai_industry_articles collection |
| **MinIO** | 文件存储 | PPT/报告文件 |

---

## 表结构

### 1. companies（公司表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(64) | 主键 |
| name | VARCHAR(256) | 公司名称，唯一 |
| plan | VARCHAR(32) | free / pro / enterprise |
| quota_limit | INT | 每月研究次数限制 |
| quota_used | INT | 当月已使用次数 |
| quota_reset_at | DATE | 配额重置日期（每月重置） |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

**配额逻辑**：
- 免费版每月 10 次
- 每月 1 号自动重置 quota_used = 0
- 研究任务完成时检查配额，超限则拒绝

---

### 2. users（用户表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(64) | 主键 |
| email | VARCHAR(256) | 邮箱，唯一 |
| password_hash | VARCHAR(256) | 密码哈希（bcrypt） |
| company_id | VARCHAR(64) | 所属公司，外键 |
| role | VARCHAR(32) | admin / member |
| is_active | BOOLEAN | 账号是否启用 |
| last_login_at | TIMESTAMP | 最后登录时间 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

**说明**：
- admin 可以管理公司成员
- member 只有使用权限
- is_active 用于禁用账号，不删除数据

---

### 3. research_tasks（研究任务表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(64) | 主键 |
| user_id | VARCHAR(64) | 创建者，外键 |
| company_id | VARCHAR(64) | 所属公司，外键 |
| title | VARCHAR(1024) | 任务标题 |
| query | VARCHAR(4096) | 原始查询 |
| status | VARCHAR(32) | pending / running / completed / failed |
| result_summary | TEXT | 报告摘要 |
| result_markdown | TEXT | Markdown 报告全文 |
| result_slides | JSONB | PPT 大纲 + 逐页内容 |
| sources_used | INT | 使用的来源数量 |
| gaps_identified | JSONB | 识别的证据缺口 |
| conflicts_detected | JSONB | 检测到的冲突 |
| error_message | TEXT | 错误信息 |
| started_at | TIMESTAMP | 开始时间 |
| completed_at | TIMESTAMP | 完成时间 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

**result_slides JSON 结构**：
```json
{
  "title": "AI Agent 行业现状分析",
  "audience": "产品经理",
  "slides": [
    {
      "page": 1,
      "title": "核心结论",
      "bullets": ["结论1", "结论2"],
      "speaker_notes": "演讲者备注",
      "sources": ["source_id_1"]
    }
  ]
}
```

---

### 4. user_preferences（用户偏好表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(64) | 主键 |
| user_id | VARCHAR(64) | 用户，外键，唯一 |
| language | VARCHAR(10) | zh / en |
| report_style | VARCHAR(32) | conclusion_first / detail_first |
| default_time_window | VARCHAR(32) | last_3_months / last_6_months / last_year |
| preferred_output | VARCHAR(32) | markdown_report / ppt_json |
| ppt_pages | INT | 默认 PPT 页数 |
| notification_enabled | BOOLEAN | 通知是否开启 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

---

### 5. refresh_tokens（刷新令牌表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(64) | 主键 |
| user_id | VARCHAR(64) | 用户，外键 |
| token_hash | VARCHAR(256) | token 哈希（安全存储） |
| expires_at | TIMESTAMP | 过期时间 |
| revoked | BOOLEAN | 是否已撤销 |
| created_at | TIMESTAMP | 创建时间 |

**说明**：
- refresh_token 有效期 7-30 天
- 登出时设置 revoked = TRUE
- 定期清理过期 token

---

### 6. audit_logs（审计日志表，可选）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| user_id | VARCHAR(64) | 用户 |
| company_id | VARCHAR(64) | 公司 |
| action | VARCHAR(64) | login / query / research / export |
| resource_type | VARCHAR(64) | 资源类型 |
| resource_id | VARCHAR(64) | 资源 ID |
| ip_address | INET | IP 地址 |
| user_agent | TEXT | 用户代理 |
| details | JSONB | 详细信息 |
| created_at | TIMESTAMP | 时间 |

**用途**：
- 合规要求（ToB 客户审计）
- 问题排查
- 用户行为分析

---

## 索引设计

| 表 | 索引 | 用途 |
|----|------|------|
| companies | idx_companies_name | 公司名唯一约束 |
| users | idx_users_email | 邮箱唯一约束 |
| users | idx_users_company | 按公司查成员 |
| research_tasks | idx_tasks_company | 按公司查任务 |
| research_tasks | idx_tasks_user | 按用户查任务 |
| research_tasks | idx_tasks_status | 查询待处理任务 |
| research_tasks | idx_tasks_updated | 按更新时间排序 |
| refresh_tokens | idx_refresh_user | 查询活跃 token |
| audit_logs | idx_audit_user_time | 按用户查审计 |
| audit_logs | idx_audit_company_time | 按公司查审计 |

---

## 数据隔离策略

```
company_id 贯穿所有表：
- users.company_id → companies.id
- research_tasks.company_id → companies.id
- audit_logs.company_id → companies.id

查询时强制加 company_id 条件：
SELECT * FROM research_tasks
WHERE company_id = :current_company_id
  AND user_id = :current_user_id
```

---

## 认证流程

```
1. 注册 → users + companies（公司不存在时自动创建）
2. 登录 → 验证密码 → 生成 access_token + refresh_token
3. 请求 → Authorization: Bearer {access_token}
4. token 过期 → 用 refresh_token 换新 access_token
5. 登出 → refresh_token 设置 revoked = true
```

---

## 配额控制

```python
def check_quota(company_id: str) -> bool:
    company = db.query("SELECT * FROM companies WHERE id = ?", company_id)
    if company.quota_used >= company.quota_limit:
        return False  # 超限
    return True

def increment_quota(company_id: str):
    db.execute("UPDATE companies SET quota_used = quota_used + 1 WHERE id = ?", company_id)
```

---

## 外部依赖

- PostgreSQL 15+
- psycopg2 / asyncpg（Python 驱动）
- bcrypt（密码哈希）