"""
Configuration management for KALYX trading system.
Uses pydantic-settings for environment variable handling.
"""
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "KALYX Trading System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False, description="Debug mode")
    
    # Server
    HOST: str = Field(default="0.0.0.0", description="Server host")
    PORT: int = Field(default=8000, description="Server port")
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:3001"],
        description="CORS allowed origins"
    )
    
    # Database
    DATABASE_URL: str = Field(
        default="postgresql://kalyx:kalyx@localhost:5432/kalyx",
        description="PostgreSQL connection URL"
    )
    DATABASE_ECHO: bool = Field(default=False, description="SQLAlchemy echo mode")
    
    # Redis
    REDIS_HOST: str = Field(default="localhost", description="Redis host")
    REDIS_PORT: int = Field(default=6379, description="Redis port")
    REDIS_DB: int = Field(default=0, description="Redis database number")
    REDIS_PASSWORD: Optional[str] = Field(default=None, description="Redis password")
    
    # Zerodha API
    ZERODHA_API_KEY: str = Field(..., description="Zerodha Kite Connect API key")
    ZERODHA_API_SECRET: str = Field(..., description="Zerodha Kite Connect API secret")
    ZERODHA_REQUEST_TOKEN: Optional[str] = Field(
        default=None,
        description="Zerodha request token (provided daily)"
    )
    
    # Security
    SECRET_KEY: str = Field(
        default="change-me-in-production",
        description="Secret key for encryption"
    )
    ENCRYPTION_KEY: Optional[str] = Field(
        default=None,
        description="Key for encrypting stored tokens"
    )
    
    # Risk Management
    MAX_CAPITAL_USAGE_PCT: float = Field(
        default=80.0,
        description="Maximum capital usage percentage"
    )
    MAX_LOSS_PER_DAY: float = Field(
        default=50000.0,
        description="Maximum loss per day in INR"
    )
    MAX_TRADES_PER_DAY: int = Field(
        default=50,
        description="Maximum trades per day"
    )
    
    # LLM Configuration
    LLM_PROVIDER: str = Field(
        default="openai",
        description="LLM provider: openai, anthropic, or ollama"
    )
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API key")
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, description="Anthropic API key")
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434",
        description="Ollama base URL"
    )
    LLM_MODEL: str = Field(
        default="gpt-4",
        description="LLM model name"
    )
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(default=None, description="Telegram bot token")
    TELEGRAM_CHAT_ID: Optional[str] = Field(default=None, description="Telegram chat ID")
    ACCOUNTS_CONFIG_PATH: str = Field(default="config/accounts.yaml", description="Path to accounts YAML configuration")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FORMAT: str = Field(
        default="json",
        description="Log format: json or text"
    )
    
    # Trading
    DEFAULT_INSTRUMENT_TYPE: str = Field(
        default="OPTIDX",
        description="Default instrument type"
    )
    DEFAULT_EXCHANGE: str = Field(default="NFO", description="Default exchange")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global settings instance
settings = Settings()

