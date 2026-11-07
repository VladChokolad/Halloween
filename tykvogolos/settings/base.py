"""Общие настройки «Тыквоголос» (план бэкенда §2, 04 §4).

Специфичное для сред — в dev.py / prod.py. Значения из окружения — по 04 §3.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY: в prod.py SECRET_KEY обязателен из окружения; дефолт — только
# чтобы `manage.py check`/тесты dev-среды не падали без .env.
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-dev-only-not-for-production")

DEBUG = False

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

# --- приложения (план бэкенда §2: django contrib + core + WhiteNoise) ---
# Примечание: whitenoise~=6.7 разрешает 6.12+, где модуль whitenoise.run
# (CompileStaticFiles) удалён — WhiteNoise работает через middleware +
# STORAGES["staticfiles"], отдельная запись в INSTALLED_APPS не нужна.
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # сразу после SecurityMiddleware (04 §4)
    "core.middleware.VoteRateLimitMiddleware",     # rate-limit POST /api/v1/vote → 429 (§11)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Отказ CSRF на /api/v1/vote → JSON 400 {"error":"bad_request"} (§7.1),
# а не HTML-страница: контракт vote.js.
CSRF_FAILURE_VIEW = "core.views.api.csrf_failure"

ROOT_URLCONF = "tykvogolos.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "tykvogolos.wsgi.application"

# --- i18n / часовой пояс ---
LANGUAGE_CODE = "ru"
TIME_ZONE = os.environ.get("TIME_ZONE", "Europe/Moscow")
USE_I18N = True
USE_TZ = True  # хранение всегда UTC (E7)

# --- пароли ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- статика (WhiteNoise; хранилище переопределяется в средах) ---
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- константы правил и защиты (04 §3, план бэкенда §5–§7) ---
VOTER_COOKIE_NAME = os.environ.get("VOTER_COOKIE_NAME", "voter_token")
VOTER_COOKIE_DAYS = int(os.environ.get("VOTER_COOKIE_DAYS", "30"))
VOTER_COOKIE_HTTPONLY = True   # дубль токена для восстановления — в localStorage (FR-V-02)
VOTER_COOKIE_SECURE = False    # True в prod.py
VOTER_COOKIE_SAMESITE = "Lax"

SOFT_IP_LIMIT = int(os.environ.get("SOFT_IP_LIMIT", "0"))          # 0 = выкл (Т2)
VOTE_RATE_LIMIT = int(os.environ.get("VOTE_RATE_LIMIT", "10"))     # POST/мин с IP (FR-V-12)
PHOTO_MAX_MB = int(os.environ.get("PHOTO_MAX_MB", "5"))
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCK_MINUTES = int(os.environ.get("LOGIN_LOCK_MINUTES", "10"))

# --- админ-панель (этап 2; читаем из окружения уже сейчас, 04 §3) ---
# Дефолт max/max — чтобы из коробки без .env вход в /admin/ работал
# (локальная dev-среда); в prod обязательно задать через окружение.
ADMIN_LOGIN = os.environ.get("ADMIN_LOGIN", "max")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "max")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "max@example.com")

# --- логирование в stdout (Render собирает, 04 §4) ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
