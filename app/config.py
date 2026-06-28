from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    db_path: Path = Path("data/movies.db")
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
