from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Environment
    env: str = "dev"
    debug: bool = True

    # LLM
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    qwen_api_key: str = ""

    # Embedding
    volcengine_api_key: str = ""
    volc_engine_embedding_url: str = "https://open.volcengineapi.com/api/v1/embeddings"

    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_user: str = ""
    milvus_password: str = ""

    # Observability
    llm_cache: bool = True
    log_level: str = "DEBUG"

    # Paths
    project_root: Path = Path(__file__).parent.parent.parent
    data_dir: Path = project_root / "data"
    llm_cache_dir: Path = data_dir / "llm_cache"
    eval_results_dir: Path = data_dir / "eval_results"
    prompt_dir: Path = project_root / "src" / "agent" / "templates"

    # Prompt versioning
    prompt_version: str = "v1"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


settings = Settings()