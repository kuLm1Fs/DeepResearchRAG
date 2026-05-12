"""LangSmith tracing setup for development debugging."""
from core import get_logger, settings

logger = get_logger(__name__)


def setup_langsmith():
    """Configure LangSmith tracing if enabled."""
    if not settings.langchain_api_key:
        logger.info("langsmith_disabled", reason="no API key")
        return False

    import os
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint

    logger.info("langsmith_configured",
        project=settings.langchain_project,
        endpoint=settings.langchain_endpoint,
    )
    return True


def get_langsmith_client():
    """Get LangSmith client instance."""
    try:
        from langsmith import Client
        return Client(api_key=settings.langchain_api_key)
    except ImportError:
        logger.warning("langsmith_not_installed")
        return None