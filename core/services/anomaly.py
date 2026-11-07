"""Аномалии голосования (план бэкенда §8.3): счётчики голосов по ip_hash
и пороги для блока аномалий дашборда. В БД только хэш — приватность (Т2).
"""
from __future__ import annotations

from django.db.models import Count

from core.models import Vote

DEFAULT_LIMIT = 10
DEFAULT_THRESHOLD = 3


def top_ip_hashes(limit: int = DEFAULT_LIMIT, min_votes: int = DEFAULT_THRESHOLD) -> list[dict]:
    """Топ ip_hash по числу голосов (голосов ≥ min_votes, по убыванию).

    Возвращает [{"ip_hash": ..., "votes": ...}] для дашборда админки.
    """
    qs = (
        Vote.objects.values("voter__ip_hash")
        .annotate(votes=Count("id"))
        .filter(votes__gte=min_votes)
        .order_by("-votes")[:limit]
    )
    return [{"ip_hash": row["voter__ip_hash"], "votes": row["votes"]} for row in qs]


def anomaly_report(threshold: int = DEFAULT_THRESHOLD) -> dict:
    """Сводка для дашборда: топ ip_hash + порог."""
    entries = top_ip_hashes(min_votes=threshold)
    return {
        "threshold": threshold,
        "count": len(entries),
        "items": entries,
    }
