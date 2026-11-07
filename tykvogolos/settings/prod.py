"""Prod-настройки (04 §4): HTTPS-набор, cookies Secure/HttpOnly/Lax,
Neon через pgbouncer (conn_max_age=0), WhiteNoise CompressedManifest.

Переменные окружения читаются из os.environ; при наличии файла .env в
корне репозитория он загружается (setdefault — окружение приоритетнее).
"""
import os
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import BASE_DIR


def _load_env(path) -> None:
    """Мини-загрузчик .env без внешних зависимостей (04 §3)."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env(BASE_DIR / ".env")

DEBUG = False


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ImproperlyConfigured(
            f"Обязательная переменная окружения {name} не задана (см. .env.example, 04 §3)"
        )
    return value


SECRET_KEY = _env("SECRET_KEY")
ALLOWED_HOSTS = [h.strip() for h in _env("ALLOWED_HOSTS").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# HTTPS: Render терминирует TLS на своём прокси (04 §4)
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 3600  # домен живёт сутки; не жечь HSTS на месяцы
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Cookies: сессия админа + voter-токен (04 §4)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
VOTER_COOKIE_SECURE = True
# VOTER_COOKIE_NAME / VOTER_COOKIE_HTTPONLY / VOTER_COOKIE_SAMESITE — из base.py

# БД: Neon через pgbouncer (transaction pooling) — постоянные соединения ЗАПРЕЩЕНЫ
import dj_database_url  # noqa: E402

DATABASES = {
    "default": dj_database_url.config(
        default=_env("DATABASE_URL"),  # без тихого дефолта: нет переменной — внятная ошибка
        conn_max_age=0,          # pooler не держит долгоживущие соединения
        conn_health_checks=True,
    )
}

# Статика: WhiteNoise, без CDN (R3)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
