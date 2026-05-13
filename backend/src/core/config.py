from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dynamically resolve paths relative to this config file
# config.py is at: backend/src/core/config.py → go up 4 levels to project root
_project_root = Path(__file__).parent.parent.parent.parent
_env_file = _project_root / "configs" / ".env.dev"


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

    # LangSmith
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "rag-news-intelligence"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    # Paths
    project_root: Path = _project_root
    data_dir: Path = project_root / "data"
    llm_cache_dir: Path = data_dir / "llm_cache"
    eval_results_dir: Path = data_dir / "eval_results"
    prompt_dir: Path = project_root / "backend" / "src" / "agent" / "templates"

    # Prompt versioning
    prompt_version: str = "v1"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


settings = Settings()


if __name__ == "__main__":
    print(f"ENV={settings.env}")
    print(f"DEBUG={settings.debug}")
    print(f"LLM_PROVIDER={settings.llm_provider}")
    print(f"DEEPSEEK_API_KEY={'set' if settings.deepseek_api_key else 'MISSING'}")
    print(f"VOLCENGINE_API_KEY={'set' if settings.volcengine_api_key else 'MISSING'}")
    print(f"MILVUS_HOST={settings.milvus_host}")
    print(f"MILVUS_PORT={settings.milvus_port}")