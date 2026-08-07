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
    # 30 días a propósito: con el desbloqueo por huella en el frontend, la
    # idea es que solo haga falta volver a meter la contraseña completa una
    # vez al mes (alineado con el ciclo de pago), no cada semana.
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REFRESH_TOKEN_COOKIE_NAME: str = "refresh_token"
    # Ventana en la que un token ya rotado se sigue aceptando, para que dos
    # pestañas (o un reintento de red) que refrescan a la vez no dejen a
    # nadie deslogueado. Pasada la ventana, reusar un token rotado se trata
    # como robo de cookie -> se cierran todas las sesiones del usuario.
    REFRESH_TOKEN_GRACIA_SEGUNDOS: int = 30

    # Bloqueo de cuenta por fuerza bruta en /auth/login
    LOGIN_MAX_INTENTOS: int = 5
    LOGIN_BLOQUEO_MINUTOS: int = 15

    # Límite por IP en los endpoints públicos (registro, recuperación de
    # contraseña, Google). Distinto del bloqueo de cuenta de arriba: ese
    # protege una cuenta concreta, este protege al servicio de alguien que
    # crea cuentas en masa o quema la cuota de correo desde una misma IP.
    IP_MAX_INTENTOS: int = 10
    IP_VENTANA_MINUTOS: int = 15

    # Monitoreo de errores (Sentry). Sin DSN configurado no se envía nada --
    # así en desarrollo y en los tests no se reporta ruido.
    SENTRY_DSN: str | None = None
    # Porcentaje de peticiones de las que se mide rendimiento (0.0 a 1.0). El
    # plan gratuito tiene cupo limitado, así que conviene un valor bajo: con
    # 0.05 se ve la tendencia sin quemar la cuota.
    SENTRY_TRACES_SAMPLE_RATE: float = 0.05

    # Zona horaria del negocio. Todo se GUARDA en UTC, pero "hoy" para el
    # usuario es su día local: en Colombia (UTC-5), entre las 7pm y la
    # medianoche el día UTC ya cambió y el suyo no. Sin esto, métricas como
    # "devueltas hoy" salen mal varias horas cada día.
    ZONA_HORARIA: str = "America/Bogota"

    # URL del frontend (Lovable) -- se usa para armar links en los correos
    # (ej. "restablece tu contraseña aquí"). Sin path, solo el origen.
    FRONTEND_URL: str = "https://orderscode.com"

    # Google Sign-In -- Client ID del proyecto en Google Cloud Console.
    # Sin esto configurado, POST /auth/google rechaza todo (ver core/google_auth.py).
    GOOGLE_CLIENT_ID: str | None = None

    # Correo transaccional (recuperar contraseña, aviso de cambio de
    # contraseña) -- API HTTP de Resend, no SMTP: Render bloquea el puerto
    # SMTP saliente (confirmado por TimeoutError en producción), pero HTTPS
    # normal sí funciona. Si RESEND_API_KEY no está configurada, el envío se
    # omite (log de aviso) en vez de fallar -- útil en desarrollo.
    RESEND_API_KEY: str | None = None
    EMAIL_FROM_EMAIL: str = "no-reply@localhost"
    EMAIL_FROM_NAME: str = "Digitalización Producción"

    # Recuperación de contraseña
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # Días entre que el cliente pide borrar su cuenta y que los datos se
    # purgan de verdad. En esa ventana puede arrepentirse y cancelar, y
    # también le da tiempo de exportar su información.
    ELIMINACION_CUENTA_DIAS_GRACIA: int = 30

    # CORS
    CORS_ORIGINS: str = "https://orderscode.com"
    CORS_ORIGIN_REGEX: str | None = None

    # WhatsApp Cloud API (Meta) -- envío de la ficha técnica en PDF al taller
    # cuando se le asigna un lote. Sin WHATSAPP_ACCESS_TOKEN, el envío se
    # omite (log de aviso), igual que con los correos.
    WHATSAPP_PHONE_NUMBER_ID: str | None = None
    WHATSAPP_ACCESS_TOKEN: str | None = None
    WHATSAPP_TEMPLATE_NAME: str | None = None
    WHATSAPP_TEMPLATE_LANGUAGE: str = "es"
    WHATSAPP_API_VERSION: str = "v20.0"
    # Se antepone a un teléfono que no venga ya con código de país (ver
    # core/whatsapp.py) -- 57 = Colombia, cámbialo si tus talleres son de
    # otro país.
    WHATSAPP_DEFAULT_COUNTRY_CODE: str = "57"

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