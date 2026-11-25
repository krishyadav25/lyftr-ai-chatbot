import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ensure the root .env at D:\lyftr-ai-chatbot\.env is loaded regardless of current working directory
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_ENV_PATH = ROOT_DIR / ".env"
if ROOT_ENV_PATH.exists():
    load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)


class Settings(BaseSettings):
    """Application settings and configuration."""

    DATABASE_URL: str = "sqlite:///./data/app.db"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    ENABLE_FAILURE_SIMULATION: bool = False
    LLM_API_KEYS: str = ""
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    LLM_MODEL: str = "gemini/gemini-2.5-flash"
    DEFAULT_SYSTEM_PROMPT: str = "You are a helpful and concise AI assistant."

    model_config = SettingsConfigDict(
        env_file=(str(ROOT_ENV_PATH), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def get_allowed_origins(self) -> List[str]:
        """Parse ALLOWED_ORIGINS into a clean list of URLs without trailing slashes."""
        if not self.ALLOWED_ORIGINS:
            return ["*"]
        return [
            origin.strip().rstrip("/")
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    def get_key_pool(self) -> List[str]:
        """Parse LLM_API_KEYS into a list of configured API keys."""
        if not self.LLM_API_KEYS:
            return []
        return [k.strip() for k in self.LLM_API_KEYS.split(",") if k.strip()]

    def get_db_path(self) -> str:
        """Extract filesystem path from DATABASE_URL and ensure parent directories exist."""
        url = self.DATABASE_URL.strip()
        if url == ":memory:" or url == "sqlite:///:memory:":
            return ":memory:"
        if url.startswith("sqlite:////"):
            path = "/" + url[11:]
        elif url.startswith("sqlite:///"):
            path = url[10:]
        elif url.startswith("sqlite://"):
            path = url[9:]
        else:
            path = url

        if path != ":memory:":
            # Handle Windows relative/absolute path conventions
            normalized = os.path.normpath(path)
            dir_name = os.path.dirname(normalized)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            return normalized
        return path


settings = Settings()
