#!/usr/bin/env bash
# Build-команда Render (04 §6.3): pip install → collectstatic → migrate.
# Миграции при билде — по плану; Neon через pgbouncer выдерживает.
set -euo pipefail

echo "=== Тыквоголос: build start ==="
pip install --no-cache-dir -r requirements.txt

echo "=== collectstatic ==="
python manage.py collectstatic --noinput

echo "=== migrate ==="
python manage.py migrate --noinput

echo "=== build done ==="
