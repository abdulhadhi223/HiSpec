from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://test:test@10.192.26.4:8080/nmdb_ewtrack"
    MAX_FILE_SIZE_MB: int = 100

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
