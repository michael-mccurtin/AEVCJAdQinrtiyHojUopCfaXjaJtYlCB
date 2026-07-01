from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # Optional so non-LLM entry points (the ingest script, tests) can run
    # without a key. The LLM client fails clearly if it is actually used unset.
    openai_api_key: str | None = None

    db_path: Path = Path("data/movies.db")
    log_level: str = "INFO"
    llm_chat_model: str = "gpt-4o-mini"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
