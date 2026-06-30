from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    openai_api_key: str
    db_path: Path = Path("data/movies.db")
    log_level: str = "INFO"
    llm_chat_model: str = "gpt-4o-mini"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
