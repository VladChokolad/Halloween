"""Rate-limit middleware (план бэкенда §11, FR-V-12).

POST /api/v1/vote — не более settings.VOTE_RATE_LIMIT запросов в минуту
с одного IP → 429 {"error":"rate_limited"}. Счётчик — в кэше Django
(LocMemCache на одном процессе; для 2×4 threads Gunicorn этого достаточно,
нюанс допущен в 04 §4). Тот же механизм используется для троттлинга логина
админки (core/decorators.py).
"""
from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache

from core.services.voters import get_client_ip, hash_ip

RATE_PATH = "/api/v1/vote"
RATE_METHOD = "POST"


def _minute_bucket() -> int:
    return int(time.time() // 60)


def rate_limit_key(ip: str) -> str:
    return f"rl:{hash_ip(ip)}:{_minute_bucket()}"


def check_rate_limit(ip: str, limit: int) -> bool:
    """Увеличивает счётчик и возвращает True, если запрос разрешён.

    cache.add — атомарный «set, если нет ключа»: безопасно при гонке потоков.
    """
    if limit <= 0:
        return True
    key = rate_limit_key(ip)
    # метка бакета в ключе — счётчик живёт ровно одну минуту
    if not cache.add(key, 1, timeout=120):
        try:
            count = cache.incr(key)
        except ValueError:
            # ключ вытеснен между add и incr — начинаем заново
            cache.add(key, 1, timeout=120)
            return True
        return count <= limit
    return True


class VoteRateLimitMiddleware:
    """429 для POST /api/v1/vote сверх VOTE_RATE_LIMIT в минуту (FR-V-12)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == RATE_PATH and request.method == RATE_METHOD:
            limit = getattr(settings, "VOTE_RATE_LIMIT", 10)
            ip = get_client_ip(request) or "unknown"
            if not check_rate_limit(ip, limit):
                from django.http import JsonResponse

                return JsonResponse({"error": "rate_limited"}, status=429)
        return self.get_response(request)
