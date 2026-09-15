from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MECORRESPONDE Internal Alpha"
    database_url: str = "sqlite:///./mecorresponde.db"
    storage_dir: str = "./storage"
    document_storage_backend: str = "local"
    document_storage_persistent: bool = False
    max_upload_bytes: int = 15 * 1024 * 1024

    # Render sets RENDER=true automatically at runtime. We use it to prevent
    # accepting real documents on an ephemeral filesystem.
    render: bool = False

    # S3-compatible object storage. Secrets are supplied only through runtime
    # environment variables; never commit them to the repository.
    s3_endpoint_url: str = ""
    s3_region: str = "auto"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_prefix: str = "mecorresponde"

    cors_origins: str = "http://localhost:3000"
    legal_holidays_csv: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


settings = Settings()
