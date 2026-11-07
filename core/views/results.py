"""Результаты админки (план бэкенда §8.6): /admin/results/ — таблицы
«место/кандидат/голосов/%» по каждой номинации + Chart.js бар-диаграммы
в цвете номинации; /admin/charts/<slug>/ — полноэкранный режим «⛶»
(топ-3, тёмный фон, читаемо с 5 м). Снявшие — «(снято)» (E2).
"""
from __future__ import annotations

from django.contrib.staticfiles import finders
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.catalog import CATEGORIES, CATEGORY_COLORS
from core.decorators import admin_required
from core.models import Group, Participant, State
from core.services.export import category_tallies, voters_total

CHART_SLUGS = {c["id"].lower(): c["id"] for c in CATEGORIES}
# «summary» — сводка явки по номинациям (все категории на одном экране)
CHART_SLUGS["summary"] = "SUMMARY"


def _category_rows(category: str) -> list[dict]:
    """Таблица по номинации: место/кандидат/голосов/% от проголосовавших."""
    voters = voters_total()
    rows = category_tallies().get(category, [])
    out = []
    for place, item in enumerate(rows, start=1):
        if item["subject_type"] == "GROUP":
            active = Group.objects.filter(pk=item["subject_id"], is_active=True).exists()
        else:
            active = Participant.objects.filter(pk=item["subject_id"], is_active=True).exists()
        out.append(
            {
                "place": place,
                "number": item["number"],
                "name": item["name"] + ("" if active else " (снято)"),
                "votes": item["votes"],
                "pct": round(item["votes"] / voters * 100, 1) if voters else 0,
                "subject_type": item["subject_type"],
            }
        )
    return out


def _chartjs_available() -> bool:
    return finders.find("vendor/chart.umd.min.js") is not None


@admin_required
def results(request: HttpRequest) -> HttpResponse:
    state_qs = State.load()
    sections = []
    for cat in CATEGORIES:
        rows = _category_rows(cat["id"])
        sections.append(
            {
                "id": cat["id"],
                "name": cat["name"],
                "color": CATEGORY_COLORS.get(cat["id"], "#FF7518"),
                "rows": rows,
                "empty": not rows,
                "max_votes": rows[0]["votes"] if rows else 0,
            }
        )
    return render(
        request,
        "panel/results.html",
        {
            "sections": sections,
            "voters_total": voters_total(),
            "state": state_qs,
            "chartjs": _chartjs_available(),
        },
    )


@admin_required
def chart(request: HttpRequest, slug: str) -> HttpResponse:
    category = CHART_SLUGS.get(slug.lower())
    if category is None:
        from django.http import Http404

        raise Http404("Неизвестная номинация")
    cat = next(c for c in CATEGORIES if c["id"] == category)
    if category == "SUMMARY":
        sections = [
            {
                "id": c["id"],
                "name": c["name"],
                "color": CATEGORY_COLORS.get(c["id"], "#FF7518"),
                "rows": _category_rows(c["id"])[:3],
            }
            for c in CATEGORIES
        ]
        labels: list[str] = []
        data: list[int] = []
        colors: list[str] = []
        for section in sections:
            for row in section["rows"]:
                labels.append(f"{section['id']}: №{row['number']} {row['name']}")
                data.append(row["votes"])
                colors.append(section["color"])
    else:
        rows = _category_rows(category)[:3]
        labels = [f"№{r['number']} {r['name']}" for r in rows]
        data = [r["votes"] for r in rows]
        colors = [CATEGORY_COLORS.get(category, "#FF7518")] * len(rows)

    chart_items = [{"label": label, "votes": votes} for label, votes in zip(labels, data)]

    return render(
        request,
        "panel/chart.html",
        {
            "slug": slug.lower(),
            "category": category,
            "name": cat["name"],
            "color": CATEGORY_COLORS.get(category, "#FF7518"),
            "labels": labels,
            "data": data,
            "chart_items": chart_items,
            "chartjs": _chartjs_available(),
        },
    )
