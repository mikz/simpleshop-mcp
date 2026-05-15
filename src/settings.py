from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    simpleshop_login: str = Field(alias="SIMPLESHOP_LOGIN")
    simpleshop_api_key: SecretStr = Field(alias="SIMPLESHOP_API_KEY")
    simpleshop_base_url: AnyHttpUrl = Field(
        default="https://api.simpleshop.cz/2.0/",
        alias="SIMPLESHOP_BASE_URL",
    )
    simpleshop_timeout_seconds: float = Field(
        default=30.0,
        alias="SIMPLESHOP_TIMEOUT_SECONDS",
        gt=0,
    )


def load_settings() -> Settings:
    return Settings()
