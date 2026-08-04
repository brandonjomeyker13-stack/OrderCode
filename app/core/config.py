# app/core/config.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuración centralizada. Se carga una sola vez desde .env y se
    reutiliza en todo el proyecto vía `from app.core.config import settings`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Proyecto
    PROJECT_NAME: str = "Digitalización Producción API"
    API_V1_PREFIX: str = "/api/v1"

    # Entorno
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Base de datos
    DATABASE_URL: str

    # Seguridad / JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REFRESH_TOKEN_COOKIE_NAME: str = "refresh_token"

    # Bloqueo de cuenta por fuerza bruta en /auth/login
    LOGIN_MAX_INTENTOS: int = 5
    LOGIN_BLOQUEO_MINUTOS: int = 15

    # URL del frontend (Lovable) -- se usa para armar links en los correos
    # (ej. "restablece tu contraseña aquí"). Sin path, solo el origen.
    FRONTEND_URL: str = "https://orderscode.com"

    # Google Sign-In -- Client ID del proyecto en Google Cloud Console.
    # Sin esto configurado, POST /auth/google rechaza todo (ver core/google_auth.py).
    GOOGLE_CLIENT_ID: str | None = None

    # Correo transaccional (recuperar contraseña, aviso de cambio de
    # contraseña) -- SMTP genérico, funciona con cualquier proveedor.
    # Si SMTP_HOST no está configurado, el envío se omite (log de aviso) en
    # vez de fallar -- útil en desarrollo sin credenciales reales todavía.
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str = "no-reply@localhost"
    SMTP_FROM_NAME: str = "Digitalización Producción"

    # Recuperación de contraseña
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    CORS_ORIGINS: str = "https://orderscode.com"
    CORS_ORIGIN_REGEX: str | None = None

    # n8n (automatización PDF + WhatsApp)
    N8N_WEBHOOK_URL: str | None = None
    N8N_WEBHOOK_SECRET: str | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()