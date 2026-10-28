from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    # .env.local is what `neon deploy` writes at the repo root; later files win.
    model_config = SettingsConfigDict(env_file=(".env", "../.env.local", ".env.local"), extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql://splitfast:splitfast@localhost:5432/splitfast"
    # Neon's direct (non -pooler) URL. Preferred because LISTEN/NOTIFY, the migration
    # advisory lock and asyncpg's prepared statements all break behind PgBouncer.
    database_url_unpooled: str = ""
    jwt_secret: str = DEV_JWT_SECRET
    jwt_ttl_hours: int = 24 * 7
    cors_origins: list[str] = ["http://localhost:5173"]
    # Folder holding the built frontend; when set, the API also serves the app.
    static_dir: str = ""

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    @property
    def razorpay_enabled(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    def model_post_init(self, _context) -> None:
        if self.database_url_unpooled:
            self.database_url = self.database_url_unpooled

    def check(self) -> None:
        if self.env == "prod" and self.jwt_secret == DEV_JWT_SECRET:
            raise RuntimeError("Refusing to start in prod with the development JWT secret")


settings = Settings()
