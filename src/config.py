"""Configuration management for the Cortellis sync application."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class CortellisConfig:
    """Cortellis API configuration."""
    username: str
    password: str
    base_url: str = "https://api.cortellis.com/api-ws/ws/rs"

    @property
    def auth_url(self) -> str:
        return f"{self.base_url}/auth-v2"

    @property
    def deals_url(self) -> str:
        return f"{self.base_url}/deals-v2"


@dataclass
class DatabaseConfig:
    """PostgreSQL database configuration."""
    host: str
    port: int
    database: str
    user: str
    password: str

    @property
    def connection_string(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class OpenAIConfig:
    """OpenAI API configuration."""
    api_key: str
    model: str = "gpt-4-turbo-preview"


@dataclass
class AppConfig:
    """Main application configuration."""
    cortellis: CortellisConfig
    database: DatabaseConfig
    openai: OpenAIConfig
    sync_schedule: str
    data_dir: str
    contracts_dir: str


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    cortellis = CortellisConfig(
        username=os.environ["CORTELLIS_USERNAME"],
        password=os.environ["CORTELLIS_PASSWORD"],
        base_url=os.getenv("CORTELLIS_BASE_URL", "https://api.cortellis.com/api-ws/ws/rs"),
    )

    database = DatabaseConfig(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "cortellis"),
        user=os.getenv("POSTGRES_USER", "cortellis"),
        password=os.environ["POSTGRES_PASSWORD"],
    )

    openai = OpenAIConfig(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        model=os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview"),
    )

    return AppConfig(
        cortellis=cortellis,
        database=database,
        openai=openai,
        sync_schedule=os.getenv("SYNC_SCHEDULE", "0 2 * * *"),
        data_dir=os.getenv("DATA_DIR", "/app/data"),
        contracts_dir=os.getenv("CONTRACTS_DIR", "/app/data/contracts"),
    )
