"""JSON-API этапа 2 (план бэкенда §7): POST /api/v1/vote и GET /api/v1/stats.

Конвейер vote (§7.1): rate-limit (middleware) → CSRF (CSRF_FAILURE_VIEW) →
honeypot → resolve_voter → state-check → voted-check → validate_payload/
subjects → atomic + select_for_update(voter) с повторной проверкой voted_at
(гонка двух вкладок → 409; IntegrityError на UNIQUE → 409) → bulk_create →
voted_at=now → 200.

Формат ошибок ровно как ждёт клиентский vote.js: 200/409/400/422/429.
"""
from __future__ import annotations

import json
import logging

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.models import AdminLog, Group, Participant, State, Vote, Voter
from core.services import rules
from core.services.export import voters_total
from core.services.rules import soft_ip_limit_exceeded as ip_limit_hit
from core.services.voters import resolve_voter, set_voter_cookie

logger = logging.getLogger("tykvogolos.votes")

BAD_REQUEST = JsonResponse({"error": "bad_request"}, status=400)


def csrf_failure(request, reason=""):
    """CSRF_FAILURE_VIEW: JSON 400 вместо HTML-страницы (план бэкенда §7.1)."""
    return JsonResponse({"error": "bad_request"}, status=400)


def _parse_body(request: HttpRequest):
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    return body


def _merged_choices(body: dict) -> list[dict] | None:
    """body.votes + body.grandprix → единый список для validate_payload (§7.1 шаг 7)."""
    votes = body.get("votes")
    if votes is None or not isinstance(votes, list):
        return None
    merged = []
    for v in votes:
        if not isinstance(v, dict):
            return None
        merged.append(
            {
                "category": v.get("category"),
                "subject_type": v.get("subject_type"),
                "subject_id": v.get("subject_id"),
            }
        )
    gp = body.get("grandprix")
    if gp is not None:
        if not isinstance(gp, dict):
            return None
        merged.append(
            {
                "category": "GRANDPRIX",
                "subject_type": gp.get("subject_type"),
                "subject_id": gp.get("subject_id"),
            }
        )
    return merged


@require_POST  # CSRF проверяет CsrfViewMiddleware; отказ → csrf_failure (JSON 400)
def vote(request: HttpRequest) -> JsonResponse:
    body = _parse_body(request)
    if body is None:
        return BAD_REQUEST

    # honeypot: бот заполнил скрытое поле — молча, без подсказок (FR-V-08)
    website = body.get("website", "")
    if website:
        AdminLog.objects.create(action="honeypot", details={"ip_hash": ""})
        logger.warning("honeypot hit")
        return JsonResponse({"error": "honeypot"}, status=400)

    voter, needs_cookie = resolve_voter(request, body.get("token"))

    # состояние: голосовать можно только в ACTIVE (FR-S-03)
    state = State.load()
    if state.state == "PAUSED":
        return JsonResponse({"error": "paused"}, status=409)
    if state.state != "ACTIVE":
        return JsonResponse({"error": "not_active"}, status=409)

    # уже проголосовал — мгновенный отказ до валидации (FR-V-12, дёшево)
    if voter.voted_at is not None:
        return JsonResponse({"error": "already_voted"}, status=409)

    # мягкий IP-лимит (Т2): 409 already_voted, чтобы не подсказывать боту
    if ip_limit_hit(voter.ip_hash):
        AdminLog.objects.create(
            action="soft_ip_limit", details={"ip_hash": voter.ip_hash}
        )
        return JsonResponse({"error": "already_voted"}, status=409)

    merged = _merged_choices(body)
    if merged is None:
        return BAD_REQUEST

    errors = rules.validate_payload(merged)
    if errors:
        return JsonResponse({"errors": errors}, status=422)

    errors = rules.validate_subjects(merged)
    if errors:
        return JsonResponse({"errors": errors}, status=422)

    # --- атомарная запись (§7.1 шаги 10–11, FR-V-08) ---
    to_create: list[Vote] = []
    for v in merged:
        kwargs = dict(
            voter=voter,
            category=v["category"],
            subject_type=v["subject_type"],
        )
        if v["subject_type"] == "GROUP":
            kwargs["group_id"] = int(v["subject_id"])
        else:
            kwargs["participant_id"] = int(v["subject_id"])
        to_create.append(Vote(**kwargs))

    try:
        with transaction.atomic():
            locked = Voter.objects.select_for_update().get(pk=voter.pk)
            if locked.voted_at is not None:
                # гонка двух вкладок (E4): вторая вкладка проигрывает
                return JsonResponse({"error": "already_voted"}, status=409)
            Vote.objects.bulk_create(to_create)
            locked.voted_at = timezone.now()
            locked.save(update_fields=["voted_at"])
    except IntegrityError:
        # UNIQUE(voter, category) — дубликат при гонке → 409, без частичной записи
        return JsonResponse({"error": "already_voted"}, status=409)

    response = JsonResponse(
        {
            "status": "ok",
            "voters_total": Voter.objects.filter(voted_at__isnull=False).count(),
        }
    )
    if needs_cookie:
        set_voter_cookie(response, voter)
    return response


@require_GET
def stats(request: HttpRequest) -> JsonResponse:
    """GET /api/v1/stats → {"voters_total": N, "state": "..."} (§7.2).

    Расширенный ответ только для админ-сессии: голоса по категориям.
    """
    from core.decorators import SESSION_KEY

    payload = {
        "voters_total": voters_total(),
        "state": State.load().state,
    }
    if request.session.get(SESSION_KEY):
        payload["votes_by_category"] = {
            row["category"]: row["total"]
            for row in Vote.objects.values("category").annotate(total=Count("id"))
        }
        payload["participants_total"] = Participant.objects.filter(is_active=True).count()
        payload["groups_total"] = Group.objects.filter(is_active=True).count()
        payload["publish_results"] = State.load().publish_results
    return JsonResponse(payload)
