"""WSGI-точка входа (Render start command: gunicorn tykvogolos.wsgi:application)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tykvogolos.settings.prod")

application = get_wsgi_application()
