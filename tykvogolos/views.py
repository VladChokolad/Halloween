"""Каркасные view: /healthz (04 §7.1) и фото из БД (план бэкенда §3):
/photo/p/<id>.jpg и /photo/g/<id>.jpg — ETag + max-age=86400; отсутствие
фото/кандидата → SVG-плейсхолдер призрака (200, кэшируемый).
"""
from __future__ import annotations

from django.db import connection
from django.http import HttpRequest, HttpResponse

from core.models import Group, Participant

GHOST_PLACEHOLDER = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
    '<rect width="120" height="120" rx="16" fill="#1A112E"/>'
    '<path d="M60 16c-21 0-33 17-33 38v46l9-7 8 7 8-7 8 7 8-7 8 7 9-7V54'
    'c0-21-12-38-33-38Z" fill="#4B3A72"/>'
    '<circle cx="47" cy="54" r="6" fill="#0C0716"/>'
    '<circle cx="73" cy="54" r="6" fill="#0C0716"/>'
    '<path d="M50 72c6 7 14 7 20 0" stroke="#0C0716" stroke-width="5"'
    ' fill="none" stroke-linecap="round"/></svg>'
).encode("utf-8")


def healthz(request):
    """Прогрев Render+Neon: SELECT 1, без кэша, 200 `ok` / 503."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        response = HttpResponse("db unavailable", status=503, content_type="text/plain")
    else:
        response = HttpResponse("ok", content_type="text/plain")
    response["Cache-Control"] = "no-store"
    return response


def _photo_response(request: HttpRequest, etag: str, mime: str, data: bytes | None) -> HttpResponse:
    """Фото из БД с ETag/max-age; нет данных → SVG-плейсхолдер (тест 36)."""
    if not data:
        data, mime, etag = GHOST_PLACEHOLDER, "image/svg+xml", "ghost-placeholder"
    quoted = f'"{etag}"'
    if request.headers.get("If-None-Match") in (etag, quoted):
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(data, content_type=mime)
        response["ETag"] = quoted
    response["Cache-Control"] = "public, max-age=86400"
    return response


def photo_participant(request: HttpRequest, pk: int) -> HttpResponse:
    participant = (
        Participant.objects.filter(pk=pk)
        .values("photo_data", "photo_mime", "photo_etag")
        .first()
    )
    if not participant:
        return _photo_response(request, "ghost-placeholder", "image/svg+xml", None)
    return _photo_response(
        request,
        participant["photo_etag"],
        participant["photo_mime"] or "image/jpeg",
        participant["photo_data"],
    )


def photo_group(request: HttpRequest, pk: int) -> HttpResponse:
    group = (
        Group.objects.filter(pk=pk)
        .values("photo_data", "photo_mime", "photo_etag")
        .first()
    )
    if not group:
        return _photo_response(request, "ghost-placeholder", "image/svg+xml", None)
    return _photo_response(
        request,
        group["photo_etag"],
        group["photo_mime"] or "image/jpeg",
        group["photo_data"],
    )
