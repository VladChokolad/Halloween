"""Публичные страницы (план бэкенда §3, §9.1): /results (гейт FINISHED +
publish_results) — server-rendered CSS-бары (перенос из прототипа results.html), только
сводные данные, без токенов.
"""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from core.catalog import CATEGORIES, CATEGORY_COLORS
from core.models import State
from core.services.export import category_tallies, voters_total

MEDALS = ["🥇", "🥈", "🥉"]


def _sections() -> list[dict]:
    """Топ-3 по каждой номинации + ширина CSS-бара в % от лидера."""
    tallies = category_tallies()
    sections = []
    for cat in CATEGORIES:
        rows = (tallies.get(cat["id"]) or [])[:3]
        max_votes = rows[0]["votes"] if rows else 0
        items = []
        for i, row in enumerate(rows):
            width = round(row["votes"] / max_votes * 100) if max_votes else 0
            # «(снято)» для неактивных кандидатов (E2)
            if row["subject_type"] == "GROUP":
                from core.models import Group

                active = Group.objects.filter(pk=row["subject_id"], is_active=True).exists()
            else:
                from core.models import Participant

                active = Participant.objects.filter(pk=row["subject_id"], is_active=True).exists()
            suffix = "" if active else " (снято)"
            items.append(
                {
                    "medal": MEDALS[i],
                    "place": i + 1,
                    "number": row["number"],
                    "name": row["name"] + suffix,
                    "votes": row["votes"],
                    "width": width,
                }
            )
        sections.append(
            {
                "id": cat["id"],
                "name": cat["name"],
                "color": CATEGORY_COLORS.get(cat["id"], "#FF7518"),
                "rows": items,
                "empty": not items,
            }
        )
    return sections


def results_public(request: HttpRequest) -> HttpResponse:
    """Гейт: только FINISHED + publish_results (FR-R-03, E10); иначе — на /."""
    state = State.load()
    if state.state != "FINISHED" or not state.publish_results:
        return redirect("/")
    return render(
        request,
        "results_public.html",
        {
            "sections": _sections(),
            "voters_total": voters_total(),
            "state": state.state,
        },
    )
