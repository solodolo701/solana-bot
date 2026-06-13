from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram listener
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_phone: str = ""

    # Telegram control bot
    telegram_control_bot_token: str = ""
    telegram_chat_id: int = 0

    # Solana
    solana_rpc_url: str = ""
    jito_rpc_url: str = "https://mainnet.block-engine.jito.wtf/api/v1"
    wallet_private_key: str = ""

    # Trading parameters
    max_position_pct: float = 0.05
    max_concurrent_positions: int = 3
    daily_loss_limit_pct: float = 0.20
    time_sl_hours: float = 2.0

    # Signal channels (comma-separated string → list)
    signal_channels: list[str] = []

    @field_validator("signal_channels", mode="before")
    @classmethod
    def parse_channels(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            return [c.strip() for c in v.split(",") if c.strip()]
        return v

    # Safety switches
    dry_run: bool = True
    paper_trade: bool = True

    # Signal filtering
    min_conviction: int = 6


settings = Settings()
