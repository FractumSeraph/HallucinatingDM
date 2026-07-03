from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-secret-do-not-use-in-production"

    data_dir: Path = Path("./data")
    static_dir: Path | None = None
    database_url: str | None = None  # derived from data_dir unless set

    # LLM defaults; app_settings rows override these at runtime via the admin UI.
    llm_provider: str = "openai_compat"  # openai_compat | mock
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3.6:35b-a3b"
    llm_toolcall_mode: str = "auto"  # native | prompted | auto
    embedding_base_url: str = "http://localhost:11434/v1"
    embedding_api_key: str = "ollama"
    embedding_model: str = "nomic-embed-text"

    public_origin: str = ""
    access_token_ttl_hours: int = 24 * 14

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.data_dir / 'app.db'}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def cookie_secure(self) -> bool:
        return self.public_origin.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
