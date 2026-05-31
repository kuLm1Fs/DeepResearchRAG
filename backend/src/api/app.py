from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from core import (
    RequestBodySizeMiddleware,
    SecurityHeadersMiddleware,
    TraceIDMiddleware,
    configure_logging,
    get_logger,
    settings,
    setup_langsmith,
)

logger = get_logger(__name__)

# Rate limiter instance — imported by endpoint modules for @limiter.limit()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default] if settings.rate_limit_enabled else [],
    enabled=settings.rate_limit_enabled,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    configure_logging()
    logger.info("app_starting", env=settings.env, debug=settings.debug)
    setup_langsmith()

    # 生产环境验证
    if settings.is_prod:
        logger.info("生产模式启动")
        # 验证 LLM 缓存已关闭
        if settings.llm_cache_enabled:
            logger.warning("生产环境 LLM_CACHE_ENABLED 应为 False，建议在 .env.prod 中设置")

    # Recover orphaned research tasks from previous worker incarnation
    await _recover_orphaned_tasks()

    yield
    logger.info("app_shutting_down")


async def _recover_orphaned_tasks():
    """Mark stale 'running' research tasks as failed on startup."""
    try:
        from db.database import get_db_session
        from db.models import ResearchTask
        from sqlalchemy import update

        async with get_db_session() as db:
            result = await db.execute(
                update(ResearchTask)
                .where(ResearchTask.status == "running")
                .values(status="failed", error="Worker restarted — task orphaned")
            )
            if result.rowcount:
                await db.commit()
                logger.info("orphaned_tasks_recovered", count=result.rowcount)
    except Exception as e:
        logger.warning("orphaned_task_recovery_failed", error=str(e))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="RAG News Intelligence API",
        description="News RAG system with LangGraph Agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Middleware registration (Starlette executes in reverse order)
    # Request flow: RequestBodySize → CORS → SecurityHeaders → TraceID → Route Handler
    app.add_middleware(TraceIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    if settings.is_prod:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Trace-ID"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_middleware(RequestBodySizeMiddleware)

    # Add routes
    from .routes import router

    app.include_router(router, prefix="/api")

    @app.get("/")
    async def root():
        return {"message": "RAG News Intelligence API", "version": "0.1.0"}

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
