"""Каталог номинаций «Тыквоголос» — фиксированный порядок шагов 1–5 (FR-V-03),
цвета — токены из 03-Айдентика §4. Заменяет каталог статического прототипа (категории).

Сериализация участников/групп для гостевого bootstrap-JSON (план бэкенда §7.3).
"""
from __future__ import annotations

from core.models import Group, Participant

CATEGORIES: list[dict] = [
    {"id": "SCARY", "short": "Страшный", "name": "Самый страшный",
     "colorVar": "--cat-scary", "subjects": "participants"},
    {"id": "FUNNY", "short": "Смешной", "name": "Самый смешной",
     "colorVar": "--cat-funny", "subjects": "participants"},
    {"id": "ORIGINAL", "short": "Оригинал", "name": "Самый оригинальный",
     "colorVar": "--cat-original", "subjects": "participants"},
    {"id": "GROUP", "short": "Группа", "name": "Лучший групповой",
     "colorVar": "--cat-group", "subjects": "groups"},
    {"id": "GRANDPRIX", "short": "Гран-при", "name": "Гран-при: лучший костюм вечера",
     "colorVar": "--cat-grandprix", "subjects": "participants"},  # только участники (State.grandprix_includes_groups=False)
]

# Цвета номинаций для Chart.js (значения CSS-токенов 03-Айдентика §4)
CATEGORY_COLORS: dict[str, str] = {
    "SCARY": "#8B5CF6",
    "FUNNY": "#FF7518",
    "ORIGINAL": "#C6FF3D",
    "GROUP": "#38BDF8",
    "GRANDPRIX": "#FBBF24",
}


def participants_json() -> list[dict]:
    """Активные участники для карточек голосования (is_active=True)."""
    return [
        {
            "id": p.id,
            "number": p.number,
            "name": p.name,
            "desc": p.description,
            "type": "participant",
            "photo": bool(p.photo_data),
        }
        for p in Participant.objects.filter(is_active=True).order_by("number")
    ]


def groups_json() -> list[dict]:
    return [
        {
            "id": g.id,
            "number": g.number,
            "name": g.name,
            "desc": g.description,
            "type": "group",
            "photo": bool(g.photo_data),
        }
        for g in Group.objects.filter(is_active=True).order_by("number")
    ]
