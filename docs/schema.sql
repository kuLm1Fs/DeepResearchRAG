-- Deep Research Agent 数据库 Schema
-- PostgreSQL 15+
-- 执行方式: psql -d rag_news -f docs/schema.sql

-- =============================================
-- 公司表 (Company)
-- =============================================
CREATE TABLE IF NOT EXISTS companies (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    plan VARCHAR(32) DEFAULT 'free' CHECK (plan IN ('free', 'pro', 'enterprise')),
    quota_limit INT DEFAULT 10,  -- 每月研究次数限制
    quota_used INT DEFAULT 0,     -- 当月已使用次数
    quota_reset_at DATE DEFAULT CURRENT_DATE,  -- 配额重置日期
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 公司名唯一
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_name ON companies(name);

-- 配额重置逻辑（每月重置）
CREATE OR REPLACE FUNCTION reset_monthly_quota()
RETURNS TRIGGER AS $$
BEGIN
    IF EXTRACT(MONTH FROM CURRENT_DATE) != EXTRACT(MONTH FROM NEW.quota_reset_at)
       OR EXTRACT(YEAR FROM CURRENT_DATE) != EXTRACT(YEAR FROM NEW.quota_reset_at) THEN
        NEW.quota_used = 0;
        NEW.quota_reset_at = CURRENT_DATE;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_reset_quota
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION reset_monthly_quota();


-- =============================================
-- 用户表 (User)
-- =============================================
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(256) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    company_id VARCHAR(64) REFERENCES companies(id) ON DELETE CASCADE,
    role VARCHAR(32) DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户邮箱索引
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- 用户所属公司索引
CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);


-- =============================================
-- 研究任务表 (Research Task)
-- =============================================
CREATE TABLE IF NOT EXISTS research_tasks (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) REFERENCES users(id) ON DELETE SET NULL,
    company_id VARCHAR(64) REFERENCES companies(id) ON DELETE CASCADE,
    title VARCHAR(1024) NOT NULL,
    query VARCHAR(4096),                  -- 原始查询
    status VARCHAR(32) DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    current_step VARCHAR(32),             -- 当前执行节点: planner/retriever/analyst/checker/writer
    result_summary TEXT,                  -- 报告摘要
    result_markdown TEXT,                -- Markdown 报告全文
    result_slides JSONB,                 -- PPT 大纲 + 逐页内容 JSON
    sources_used INT DEFAULT 0,           -- 使用的来源数量
    gaps_identified JSONB,                -- 识别的证据缺口
    conflicts_detected JSONB,             -- 检测到的冲突
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 任务所属公司索引
CREATE INDEX IF NOT EXISTS idx_tasks_company ON research_tasks(company_id);

-- 任务所属用户索引
CREATE INDEX IF NOT EXISTS idx_tasks_user ON research_tasks(user_id);

-- 任务状态索引（查询待处理任务用）
CREATE INDEX IF NOT EXISTS idx_tasks_status ON research_tasks(status);

-- 更新时间索引
CREATE INDEX IF NOT EXISTS idx_tasks_updated ON research_tasks(updated_at DESC);


-- =============================================
-- 用户偏好表 (User Preference)
-- =============================================
CREATE TABLE IF NOT EXISTS user_preferences (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    language VARCHAR(10) DEFAULT 'zh',
    report_style VARCHAR(32) DEFAULT 'conclusion_first',  -- conclusion_first / detail_first
    default_time_window VARCHAR(32) DEFAULT 'last_3_months',
    preferred_output VARCHAR(32) DEFAULT 'markdown_report',  -- markdown_report / ppt_json
    ppt_pages INT DEFAULT 10,
    notification_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- =============================================
-- 刷新令牌表 (Refresh Token)
-- =============================================
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(256) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    revoked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户活跃刷新令牌索引
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id) WHERE NOT revoked;


-- =============================================
-- 审计日志表 (Audit Log) - 可选，ToB 建议加
-- =============================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(64),
    company_id VARCHAR(64),
    action VARCHAR(64) NOT NULL,   -- login / query / research / export
    resource_type VARCHAR(64),
    resource_id VARCHAR(64),
    ip_address VARCHAR(48),
    user_agent TEXT,
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 审计日志按用户和时间查询
CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_company_time ON audit_logs(company_id, created_at DESC);
