"""Серверные правила голосования — единственная точка истины (план бэкенда §5).

Портирование из клиентского vote.js прототипа (canVoteFor — строки 105–114, validateVotes —
строки 118–130) логика переносится 1-в-1; поверх добавлены серверные проверки,
которые UI не покрывает (активность кандидата, типы, дубликаты, пустой payload,
мягкий IP-лимит).

Формат ошибки — совместим с обработкой 422 в vote.js:
    {"errors": [{"code": "conflict", "category": "FUNNY", "subject_id": 3}, ...]}
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from core.models import Group, Participant, State, Voter

# 4 номинации в фиксированном порядке шагов 1–4 (FR-V-03);
# GRANDPRIX — 5-й шаг, в NOMINATION_CATEGORIES не входит.
NOMINATION_CATEGORIES = ("SCARY", "FUNNY", "ORIGINAL", "GROUP")
GRANDPRIX_CATEGORY = "GRANDPRIX"
ALL_CATEGORIES = NOMINATION_CATEGORIES + (GRANDPRIX_CATEGORY,)

# Ожидаемый subject_type для каждой номинации. GRANDPRIX — по флагу
# State.grandprix_includes_groups: False → только PARTICIPANT (FR-V-03).
EXPECTED_SUBJECT_TYPE = {
    "SCARY": "PARTICIPANT",
    "FUNNY": "PARTICIPANT",
    "ORIGINAL": "PARTICIPANT",
    "GROUP": "GROUP",
}


# ============================================================
# canVoteFor — изолированный порт для переиспользования (UI-логика
# блокировки карточек; типы кандидатов в черновике — lowercase
# 'participant'/'group', как в vote.js).
# ============================================================
def can_vote_for(
    cat_id: str,
    subject_type: str,
    subject_id: Any,
    choices: Mapping[str, Optional[Mapping[str, Any]]],
    nom_categories: Iterable[str] = NOMINATION_CATEGORIES,
) -> Optional[str]:
    """FR-V-05: кандидат, выбранный в одной из 4 номинаций, блокируется в
    остальных трёх. FR-V-06: гран-при не конфликтует ни с чем.

    choices — черновик {cat_id: {"type": ..., "id": ...} | None}, как
    draft.choices в vote.js. Возвращает None, если голосовать можно,
    иначе — id конфликтной категории (для бейджа «Уже выбран: …»).
    """
    if cat_id == GRANDPRIX_CATEGORY:
        return None
    for c in nom_categories:
        if c == cat_id:
            continue
        ch = choices.get(c)
        if ch and ch.get("type") == subject_type and str(ch.get("id")) == str(subject_id):
            return c
    return None


# ============================================================
# validate_payload — серверная сторона контракта (FR-V-05),
# расширенная серверными проверками (план бэкенда §5).
# ============================================================
def validate_payload(choices: list[dict]) -> list[dict]:
    """choices = голоса 4 номинаций + GRANDPRIX (гран-при попадает в общий
    список с category=GRANDPRIX). Возвращает список ошибок формата
    {"code", "category", "subject_id"} — совместимо с обработкой 422 в vote.js.
    """
    errors: list[dict] = []
    used: dict[str, str] = {}
    seen_categories: set[str] = set()

    # пустой payload: votes==[] и grandprix==null → merged == [] → 422 empty_vote
    if not choices:
        return [{"code": "empty_vote"}]

    gp_allows_groups = State.load().grandprix_includes_groups

    for v in choices:
        category = v.get("category")
        subject_type = v.get("subject_type")
        subject_id = v.get("subject_id")

        if category == GRANDPRIX_CATEGORY:
            # FR-V-06: гран-при не конфликтует ни с чем; но subject_type
            # ограничен флагом State.grandprix_includes_groups.
            if not gp_allows_groups and subject_type != "PARTICIPANT":
                errors.append(
                    {"code": "wrong_subject_type", "category": category, "subject_id": subject_id}
                )
            continue

        if category not in NOMINATION_CATEGORIES:
            errors.append(
                {"code": "bad_category", "category": category, "subject_id": subject_id}
            )
            continue

        if category in seen_categories:
            errors.append(
                {"code": "duplicate_category", "category": category, "subject_id": subject_id}
            )
        seen_categories.add(category)

        # chk_group_category: GROUP-номинация — только группы; соло-номинации — только участники
        expected_type = EXPECTED_SUBJECT_TYPE.get(category, "PARTICIPANT")
        if subject_type != expected_type:
            errors.append(
                {"code": "bad_subject_type", "category": category, "subject_id": subject_id}
            )

        # уникальность кандидата между номинациями (порт validateVotes 1-в-1)
        key = f"{subject_type}:{subject_id}"
        if key in used:
            errors.append(
                {"code": "conflict", "category": category, "subject_id": subject_id}
            )
        else:
            used[key] = category

    return errors


def validate_subjects(choices: list[dict]) -> list[dict]:
    """Активность и существование кандидатов (план бэкенда §5): каждый
    subject_id должен существовать и is_active=True → иначе inactive_subject.
    """
    errors: list[dict] = []
    for v in choices:
        category = v.get("category")
        subject_type = v.get("subject_type")
        subject_id = v.get("subject_id")

        try:
            sid = int(subject_id)
        except (TypeError, ValueError):
            errors.append(
                {"code": "unknown_subject", "category": category, "subject_id": subject_id}
            )
            continue

        if subject_type == "PARTICIPANT":
            exists_active = Participant.objects.filter(pk=sid, is_active=True).exists()
        elif subject_type == "GROUP":
            exists_active = Group.objects.filter(pk=sid, is_active=True).exists()
        else:
            errors.append(
                {"code": "unknown_subject", "category": category, "subject_id": subject_id}
            )
            continue

        if not exists_active:
            errors.append(
                {"code": "inactive_subject", "category": category, "subject_id": subject_id}
            )
    return errors


def soft_ip_limit_exceeded(ip_hash: str) -> bool:
    """Мягкий IP-лимит (Т2, план бэкенда §5): State.soft_ip_limit > 0 и
    голосов (проголосовавших Voter) с этого ip_hash ≥ лимита.
    API отвечает 409 already_voted, чтобы не подсказывать боту природу отказа.
    """
    if not ip_hash:
        return False
    state = State.load()
    if state.soft_ip_limit <= 0:
        return False
    voted_with_ip = Voter.objects.filter(ip_hash=ip_hash, voted_at__isnull=False).count()
    return voted_with_ip >= state.soft_ip_limit
