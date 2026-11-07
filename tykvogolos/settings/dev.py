"""Dev-настройки (план бэкенда §11): SQLite data/db.sqlite3, DEBUG=True,
cookies без Secure, WhiteNoise без Manifest-хранилища.

Запуск: DJANGO_SETTINGS_MODULE=tykvogolos.settings.dev
"""
from pathlib import Path

from .base import *  # noqa: F401,F403
from .base import BASE_DIR

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "db.sqlite3",
    }
}

# каталог для локального SQLite создаём заранее
(BASE_DIR / "data").mkdir(exist_ok=True)

# статики: без Manifest (проще перезапуск, план бэкенда §11)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# cookies по HTTP (без HTTPS на localhost)
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
VOTER_COOKIE_SECURE = False

# почта — в консоль
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
