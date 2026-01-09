from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Instagram
    ig_username: str
    ig_password: str
    ig_totp_seed: str | None = None

    # Telegram
    tg_bot_token: str
    tg_owner_id: int

    # Behavior
    poll_interval: int = 30
    download_timeout: int = 60
    max_file_size_mb: int = 50

    # Filters
    allowed_users: str | None = None  # comma-separated

    class Config:
        env_file = ".env"
