from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core import configure_logging, get_logger, TraceIDMiddleware, settings, setup_langsmith
from src.core.errors import RAGError
from .routes import router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    configure_logging()
    logger.info("app_starting", env=settings.env, debug=settings.debug)
    setup_langsmith()

    # 生产环境验证
    if not settings.debug:
        logger.info("生产模式启动")
        # 验证 LLM 缓存已关闭
        if settings.LLM_CACHE_ENABLED:
            logger.warning("生产环境 LLM_CACHE_ENABLED 应为 False，建议在 .env.prod 中设置")

    yield
    logger.info("app_shutting_down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="RAG News Intelligence API",
        description="News RAG system with LangGraph Agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Add middleware
    app.add_middleware(TraceIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to frontend origin
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add routes
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