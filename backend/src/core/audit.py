"""Audit log helper — non-blocking writes to audit_logs table."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import insert

from .logging import get_logger

if TYPE_CHECKING:
    pass  # db imports deferred to avoid circular import

logger = get_logger(__name__)


async def write_audit_log(
    *,
    action: str,
    user_id: str | None = None,
    company_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Insert an audit log row. Designed to be called as a FastAPI background task."""
    # Lazy import to break circular dependency: core → db → core
    from db import AuditLog, get_db_session

    try:
        async with get_db_session() as db:
            await db.execute(
                insert(AuditLog).values(
                    user_id=user_id,
                    company_id=company_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details=details,
                )
            )
    except Exception as e:
        # Audit logging should never break the request flow
        logger.error("audit_log_write_failed", action=action, error=str(e))
