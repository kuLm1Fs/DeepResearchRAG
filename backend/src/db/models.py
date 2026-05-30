"""SQLAlchemy ORM 模型（对应 docs/schema.sql）"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    Index, Integer, String, Text, func, text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


class Company(Base):
    """公司表 - 存储公司信息和配额"""
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint("plan IN ('free', 'pro', 'enterprise')"),
        Index("idx_companies_name", "name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default="free")
    quota_limit: Mapped[int] = mapped_column(Integer, default=10)
    quota_used: Mapped[int] = mapped_column(Integer, default=0)
    quota_reset_at: Mapped[Date] = mapped_column(Date, server_default=text("CURRENT_DATE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    users: Mapped[list["User"]] = relationship("User", back_populates="company")


class User(Base):
    """用户表 - 存储用户信息和认证"""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'member')"),
        Index("idx_users_email", "email", unique=True),
        Index("idx_users_company", "company_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    company_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("companies.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    company: Mapped[Optional["Company"]] = relationship("Company", back_populates="users")
    tasks: Mapped[list["ResearchTask"]] = relationship("ResearchTask", back_populates="user")
    preferences: Mapped[Optional["UserPreference"]] = relationship("UserPreference", back_populates="user", uselist=False)


class ResearchTask(Base):
    """研究任务表 - 存储深度研究任务的结果和状态"""
    __tablename__ = "research_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')"),
        Index("idx_tasks_company", "company_id"),
        Index("idx_tasks_user", "user_id"),
        Index("idx_tasks_status", "status"),
        Index("idx_tasks_updated", "updated_at", postgresql_using="btree"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("users.id", ondelete="SET NULL"))
    company_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("companies.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    query: Mapped[Optional[str]] = mapped_column(String(4096))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    current_step: Mapped[Optional[str]] = mapped_column(String(32))
    result_summary: Mapped[Optional[str]] = mapped_column(Text)
    result_markdown: Mapped[Optional[str]] = mapped_column(Text)
    result_slides: Mapped[Optional[dict]] = mapped_column(JSONB)
    ppt_outline: Mapped[Optional[dict]] = mapped_column(JSONB)
    evidence_trace: Mapped[Optional[dict]] = mapped_column(JSONB)
    quality_report: Mapped[Optional[dict]] = mapped_column(JSONB)
    execution_log: Mapped[Optional[dict]] = mapped_column(JSONB)
    memory_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB)
    sources_used: Mapped[int] = mapped_column(Integer, default=0)
    gaps_identified: Mapped[Optional[dict]] = mapped_column(JSONB)
    conflicts_detected: Mapped[Optional[dict]] = mapped_column(JSONB)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[Optional["User"]] = relationship("User", back_populates="tasks")


class UserPreference(Base):
    """用户偏好表 - 存储用户的个性化设置"""
    __tablename__ = "user_preferences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    language: Mapped[str] = mapped_column(String(10), default="zh")
    report_style: Mapped[str] = mapped_column(String(32), default="conclusion_first")
    default_time_window: Mapped[str] = mapped_column(String(32), default="last_3_months")
    preferred_output: Mapped[str] = mapped_column(String(32), default="markdown_report")
    ppt_pages: Mapped[int] = mapped_column(Integer, default=10)
    notification_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="preferences")


class RefreshToken(Base):
    """刷新令牌表 - 存储 JWT 刷新令牌"""
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("idx_refresh_user", "user_id", postgresql_where=text("NOT revoked")),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    """审计日志表 - 记录用户操作日志"""
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_user_time", "user_id", "created_at", postgresql_using="btree"),
        Index("idx_audit_company_time", "company_id", "created_at", postgresql_using="btree"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64))
    company_id: Mapped[Optional[str]] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64))
    resource_id: Mapped[Optional[str]] = mapped_column(String(64))
    ip_address: Mapped[Optional[str]] = mapped_column(String(48))
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
