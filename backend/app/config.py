from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MECORRESPONDE Internal Alpha"
    database_url: str = "sqlite:///./mecorresponde.db"
    storage_dir: str = "./storage"
    cors_origins: str = "http://localhost:3000"
    legal_holidays_csv: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


settings = Settings()
