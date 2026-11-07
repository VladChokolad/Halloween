"""Статус-машина голосования (план бэкенда §6, ТЗ §13).

NOT_STARTED → ACTIVE; ACTIVE ⇄ PAUSED; ACTIVE/PAUSED → FINISHED;
FINISHED — терминально (E8); выход только через опасную зону (сбросы).

apply_transition — сервер не доверяет клиенту (ТЗ §13.3): повторная проверка
допустимости перехода и контрольной фразы внутри transaction.atomic +
select_for_update() на State, запись в AdminLog.
"""
from __future__ import annotations

from typing import Optional

from django.db import transaction

from core.models import AdminLog, State

TRANSITIONS: dict[str, set[str]] = {
    "NOT_STARTED": {"ACTIVE"},
    "ACTIVE": {"PAUSED", "FINISHED"},
    "PAUSED": {"ACTIVE", "FINISHED"},
    "FINISHED": set(),  # терминально (E8); выход только через опасную зону
}

PHRASES = {
    "ACTIVE": "НАЧАТЬ",
    "PAUSED": "ПАУЗА",
    "ACTIVE_FROM_PAUSED": "ПРОДОЛЖИТЬ",
    "FINISHED": "ЗАВЕРШИТЬ",
}


class TransitionError(Exception):
    """Отказ перехода: invalid_transition / bad_phrase."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)


def allowed_transitions(state: str) -> set[str]:
    return set(TRANSITIONS.get(state, set()))


def expected_phrase(from_state: str, to_state: str) -> Optional[str]:
    """Контрольная фраза для перехода. ACTIVE зависит от направления:
    из NOT_STARTED — «НАЧАТЬ», из PAUSED — «ПРОДОЛЖИТЬ»."""
    if to_state == "ACTIVE" and from_state == "PAUSED":
        return PHRASES["ACTIVE_FROM_PAUSED"]
    return PHRASES.get(to_state)


def normalize_phrase(phrase: str) -> str:
    """Нормализация контрольной фразы: casefold + strip (ТЗ §13)."""
    return (phrase or "").strip().casefold()


def apply_transition(new_state: str, phrase: str) -> State:
    """Выполняет переход состояния с серверной перепроверкой (план бэкенда §6).

    Raises:
        TransitionError: код invalid_transition (недопустимый переход)
        или bad_phrase (неверная/пустая контрольная фраза).
    """
    with transaction.atomic():
        state = State.objects.select_for_update().get(pk=1)
        current = state.state

        if new_state not in allowed_transitions(current):
            raise TransitionError("invalid_transition", f"Переход {current} → {new_state} запрещён")

        expected = expected_phrase(current, new_state)
        if expected is None or normalize_phrase(phrase) != normalize_phrase(expected):
            raise TransitionError("bad_phrase", "Неверная контрольная фраза")

        state.state = new_state
        state.save(update_fields=["state", "updated_at"])
        AdminLog.objects.create(
            action="state_changed",
            details={"from": current, "to": new_state, "phrase_ok": True},
        )
    return state
