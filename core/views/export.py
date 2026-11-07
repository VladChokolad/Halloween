"""Экспорт (план бэкенда §3, §10): GET /admin/export/<what>/ — 5 файлов из
core/services/export.py, download-хедеры attachment. what: votes, participants,
groups, results-summary, results.json.
"""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render

from core.decorators import admin_required
from core.services import export as export_svc

EXPORT_FILES = [
    {"name": "votes", "label": "votes.csv", "what": "Голоса построчно"},
    {"name": "participants", "label": "participants.csv", "what": "Справочник участников"},
    {"name": "groups", "label": "groups.csv", "what": "Справочник групп"},
    {"name": "results-summary", "label": "results-summary.csv", "what": "Сводка итогов"},
    {"name": "results.json", "label": "results.json", "what": "Полные итоги (JSON)"},
]


@admin_required
def export(request: HttpRequest, what: str) -> HttpResponse:
    if what == "votes":
        content, ctype = export_svc.votes_csv(), "text/csv; charset=utf-8"
        filename = "votes.csv"
    elif what == "participants":
        content, ctype = export_svc.participants_csv(), "text/csv; charset=utf-8"
        filename = "participants.csv"
    elif what == "groups":
        content, ctype = export_svc.groups_csv(), "text/csv; charset=utf-8"
        filename = "groups.csv"
    elif what == "results-summary":
        content, ctype = export_svc.results_summary_csv(), "text/csv; charset=utf-8"
        filename = "results-summary.csv"
    elif what == "results.json":
        content, ctype = export_svc.results_json(), "application/json; charset=utf-8"
        filename = "results.json"
    else:
        return HttpResponseNotFound("Неизвестный экспорт")

    response = HttpResponse(content, content_type=ctype)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


@admin_required
def export_page(request: HttpRequest) -> HttpResponse:
    """Страница-указатель /admin/export/ со ссылками на 5 файлов (§8: «сначала
    экспорт» — ссылка также дублируется в опасной зоне)."""
    return render(request, "panel/export.html", {"files": EXPORT_FILES})
