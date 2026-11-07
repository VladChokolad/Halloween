"""Опасная зона /admin/danger/ (план бэкенда §8.2, шпаргалка 05 правило 1).

- Сброс голосов: фраза `СБРОС ГОЛОСОВ` — Vote→0, voted_at→null, State→
  NOT_STARTED, справочники целы, запись в AdminLog.
- Полный сброс: фраза `ПОЛНЫЙ СБРОС` — голоса+участники+группы+voter'ы+
  журнал (журнал очищается последним, эпитафия в stdout-лог), State→NOT_STARTED.

Единственный путь из FINISHED (E8).
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.decorators import admin_required
from core.models import AdminLog, Group, Participant, State, Vote, Voter
from core.services.state_machine import normalize_phrase

logger = logging.getLogger("tykvogolos.danger")

PHRASE_RESET_VOTES = "СБРОС ГОЛОСОВ"
PHRASE_FULL_RESET = "ПОЛНЫЙ СБРОС"


@require_GET
@admin_required
def danger(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "panel/danger.html",
        {
            "phrase_reset_votes": PHRASE_RESET_VOTES,
            "phrase_full_reset": PHRASE_FULL_RESET,
            "votes_total": Vote.objects.count(),
            "voters_total": Voter.objects.count(),
            "participants_total": Participant.objects.count(),
            "groups_total": Group.objects.count(),
            "reset_fields": {"action": "reset_votes"},
            "full_fields": {"action": "full_reset"},
            "reset_consequences": [
                f"Будет удалено голосов: {Vote.objects.count()}.",
                f"Отметки «проголосовал» будут сняты у {Voter.objects.count()} гостей — они смогут голосовать заново.",
                "Состояние вернётся в НЕ НАЧАТО (выход из FINISHED, E8).",
                "Справочники участников и групп останутся целы.",
            ],
            "full_consequences": [
                "Будут удалены: голоса, гости, участники, группы, журнал действий.",
                "База останется пустой — восстановить данные будет НЕВОЗМОЖНО.",
                "Состояние вернётся в НЕ НАЧАТО.",
                "Правило №1: сначала скачайте экспорт!",
            ],
        },
    )


@require_POST
@admin_required
def danger_action(request: HttpRequest) -> HttpResponse:
    action = request.POST.get("action", "")
    phrase = request.POST.get("phrase", "")

    if action == "reset_votes":
        if normalize_phrase(phrase) != normalize_phrase(PHRASE_RESET_VOTES):
            messages.error(request, "Отказ: неверная контрольная фраза (нужно «СБРОС ГОЛОСОВ»)")
            return redirect("admin_danger")
        with transaction.atomic():
            deleted_votes, _ = Vote.objects.all().delete()
            Voter.objects.update(voted_at=None)
            state = State.load()
            state.state = State.VotingState.NOT_STARTED
            state.publish_results = False
            state.save(update_fields=["state", "publish_results", "updated_at"])
            AdminLog.objects.create(
                action="reset_votes",
                details={"deleted_votes": deleted_votes, "state": "NOT_STARTED"},
            )
        logger.warning("reset_votes: %d votes deleted, State → NOT_STARTED", deleted_votes)
        messages.success(request, f"Голоса сброшены ({deleted_votes} записей). Состояние: НЕ НАЧАТО.")
        return redirect("admin_dashboard")

    if action == "full_reset":
        if normalize_phrase(phrase) != normalize_phrase(PHRASE_FULL_RESET):
            messages.error(request, "Отказ: неверная контрольная фраза (нужно «ПОЛНЫЙ СБРОС»)")
            return redirect("admin_danger")
        with transaction.atomic():
            Vote.objects.all().delete()
            Voter.objects.all().delete()
            # M2M через таблицу — удаляем связи до удаления групп/участников
            Group.participants.through.objects.all().delete()
            Participant.objects.all().delete()
            Group.objects.all().delete()
            state = State.load()
            state.state = State.VotingState.NOT_STARTED
            state.publish_results = False
            state.save(update_fields=["state", "publish_results", "updated_at"])
            AdminLog.objects.create(action="full_reset", details={"db": "purged"})
            AdminLog.objects.all().delete()  # журнал очищается последним
        logger.warning("full_reset: база очищена до пустой; State → NOT_STARTED")
        messages.success(request, "ПОЛНЫЙ СБРОС выполнен: база пуста, состояние НЕ НАЧАТО.")
        return redirect("admin_dashboard")

    messages.error(request, "Неизвестное действие")
    return redirect("admin_danger")
