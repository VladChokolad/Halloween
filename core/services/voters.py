"""Резолвинг гостя-голосующего (план бэкенда §7.1, шаг 4; FR-V-02).

Порядок: cookie voter_token ‖ заголовок X-Voter-Token ‖ token из тела
запроса ‖ новый UUID (cookie ставится в ответе). В БД только UUID +
ip_hash (принятый риск T1).
"""
from __future__ import annotations

import hashlib
import uuid

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from core.models import Voter


def get_client_ip(request: HttpRequest) -> str:
    """IP гостя: за прокси Render — первый элемент X-Forwarded-For."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def hash_ip(ip: str) -> str:
    """sha256(IP + SECRET_KEY)[:16] — приватность, восстановление IP невозможно."""
    return hashlib.sha256(f"{ip}{settings.SECRET_KEY}".encode("utf-8")).hexdigest()[:16]


def _valid_uuid(token: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(token))
    except (ValueError, AttributeError, TypeError):
        return None


def resolve_voter(request: HttpRequest, body_token: str | None = None) -> tuple[Voter, bool]:
    """Находит или создаёт Voter по токену (план бэкенда §7.1).

    Возвращает (voter, needs_cookie), где needs_cookie=True, когда токен
    пришёл не из cookie (новый гость или потерянная cookie — её ставим
    заново в ответе).
    """
    token = request.COOKIES.get(settings.VOTER_COOKIE_NAME, "") or ""
    needs_cookie = not token
    if not token:
        token = request.headers.get("X-Voter-Token", "") or ""
    if not token and body_token:
        token = str(body_token)
    parsed = _valid_uuid(token)
    if parsed is None:
        parsed = uuid.uuid4()
        needs_cookie = True

    voter, _created = Voter.objects.get_or_create(pk=parsed)
    voter.ip_hash = hash_ip(get_client_ip(request))
    voter.user_agent = (request.META.get("HTTP_USER_AGENT", "") or "")[:255]
    voter.save(update_fields=["ip_hash", "user_agent"])
    return voter, needs_cookie


def set_voter_cookie(response: HttpResponse, voter: Voter) -> None:
    """Ставит httpOnly cookie voter_token (30 дней, FR-V-02)."""
    response.set_cookie(
        settings.VOTER_COOKIE_NAME,
        str(voter.pk),
        max_age=settings.VOTER_COOKIE_DAYS * 86400,
        httponly=settings.VOTER_COOKIE_HTTPONLY,
        secure=settings.VOTER_COOKIE_SECURE,
        samesite=settings.VOTER_COOKIE_SAMESITE,
    )
