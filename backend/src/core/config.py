import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Dynamically resolve paths relative to this config file
# config.py is at: backend/src/core/config.py
_backend_root = Path(__file__).resolve().parents[2]
_project_root = _backend_root.parent
_env_file = Path(
    os.getenv("RAG_ENV_FILE")
    or os.getenv("ENV_FILE")
    or _backend_root / "configs" / ".env.dev"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_file,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    env: str = "dev"
    debug: bool = True

    # LLM
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    qwen_api_key: str = ""
    qwen_model: str = "qwen-turbo"

    # Embedding
    volcengine_api_key: str = ""
    volcengine_embedding_url: str = "https://aihubmix.com/v1/embeddings"
    volcengine_embedding_model: str = "bge-large-zh"

    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_user: str = ""
    milvus_password: str = ""

    # MinIO
    minio_host: str = "localhost"
    minio_port: int = 9000
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "news-articles"

    # Observability
    llm_cache: bool = True
    log_level: str = "DEBUG"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # LangSmith
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "rag-news-intelligence"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    # JWT Authentication
    jwt_secret: str = ""  # Must be set, no default
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "rag_news"
    postgres_user: str = "rag_user"
    postgres_password: str = ""

    # Prompt versioning
    prompt_version: str = "v1"

    @property
    def project_root(self) -> Path:
        return _project_root

    @property
    def backend_root(self) -> Path:
        return _backend_root

    @property
    def data_dir(self) -> Path:
        return self.backend_root / "data"

    @property
    def llm_cache_dir(self) -> Path:
        return self.data_dir / "llm_cache"

    @property
    def eval_results_dir(self) -> Path:
        return self.data_dir / "eval_results"

    @property
    def prompt_dir(self) -> Path:
        return self.backend_root / "src" / "agent" / "templates"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def debug_enabled(self) -> bool:
        return False if self.is_prod else self.debug

    @property
    def llm_cache_enabled(self) -> bool:
        return False if self.is_prod else self.llm_cache

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        if self.is_prod:
            return [origin for origin in origins if origin != "*"]
        return origins or ["http://localhost:5173", "http://localhost:3000"]


settings = Settings()


if __name__ == "__main__":
    print(f"ENV={settings.env}")
    print(f"DEBUG={settings.debug}")
    print(f"LLM_PROVIDER={settings.llm_provider}")
    print(f"DEEPSEEK_API_KEY={'set' if settings.deepseek_api_key else 'MISSING'}")
    print(f"VOLCENGINE_API_KEY={'set' if settings.volcengine_api_key else 'MISSING'}")
    print(f"MILVUS_HOST={settings.milvus_host}")
    print(f"MILVUS_PORT={settings.milvus_port}")
