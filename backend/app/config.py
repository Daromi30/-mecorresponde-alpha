from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MECORRESPONDE Internal Alpha"
    database_url: str = "sqlite:///./mecorresponde.db"
    storage_dir: str = "./storage"
    document_storage_backend: str = "local"
    document_storage_persistent: bool = False
    max_upload_bytes: int = 15 * 1024 * 1024
    alpha_max_documents_total: int = 100
    alpha_max_documents_per_case: int = 20

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

    # Internal beta backoffice. The value is required only at runtime and must
    # never be committed. Admin endpoints return 503 until it is configured.
    admin_api_token: str = ""

    # Transactional account email is opt-in and fail-closed. The only implemented
    # adapter is Brevo's HTTPS API; no SMTP dependency is introduced. A provider is
    # not considered ready unless credentials, a verified sender and a HTTPS public
    # base URL are all configured. No values are committed to the repository.
    email_delivery_provider: str = "disabled"
    brevo_api_key: str = ""
    email_sender_email: str = ""
    email_sender_name: str = "MECORRESPONDE"
    auth_action_base_url: str = ""
    transactional_email_verified: bool = False
    email_verification_enforced: bool = False

    cors_origins: str = "http://localhost:3000"
    legal_holidays_csv: str = ""

    # SEO remains fail-closed until both flags are intentionally configured.
    # This prevents an unfinished Render alpha from being indexed by mistake.
    public_indexing_enabled: bool = False
    public_base_url: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def public_indexing_ready(self) -> bool:
        return self.public_indexing_enabled and self.public_base_url.strip().startswith("https://")

    @property
    def transactional_email_ready(self) -> bool:
        return (
            self.email_delivery_provider.strip().casefold() == "brevo"
            and bool(self.brevo_api_key.strip())
            and "@" in self.email_sender_email.strip()
            and self.auth_action_base_url.strip().startswith("https://")
        )

    @property
    def transactional_email_operational(self) -> bool:
        return self.transactional_email_ready and self.transactional_email_verified


settings = Settings()
