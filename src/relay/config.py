"""Settings loaded from environment variables / .env.

Kept deliberately small: each milestone adds only the settings it uses.
"""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    # Optional until M3; SecretStr keeps it out of reprs and logs.
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"

    papers_dir: Path = PROJECT_ROOT / "papers"
    results_dir: Path = PROJECT_ROOT / "results"


def get_settings() -> Settings:
    return Settings()
