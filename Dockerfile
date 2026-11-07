FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Установка системных зависимостей для PostgreSQL и компиляции
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Сборка статики на этапе билда образа
RUN python manage.py collectstatic --noinput

CMD ["gunicorn", "tykvogolos.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]