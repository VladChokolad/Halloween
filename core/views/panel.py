"""Админка (план бэкенда §3, §8; шпаргалка 05): session-логин с троттлингом,
дашборд с автообновлением и аномалиями, POST /admin/state/ (контрольная фраза
проверяется сервером повторно), CRUD участников/групп (мягкое удаление,
фото через photos.py, E9 для групп), переключатель publish_results только
при FINISHED (E10).
"""
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.decorators import (
    admin_required,
    login_locked,
    mark_admin,
    register_login_failure,
    reset_login_failures,
    unmark_admin,
)
from core.forms import GroupForm, ParticipantForm
from core.models import AdminLog, Group, Participant, State, Vote, Voter
from core.services import anomaly
from core.services.export import voters_total
from core.services.state_machine import (
    TransitionError,
    allowed_transitions,
    apply_transition,
    expected_phrase,
)


# ============================================================
# Логин/логаут (троттлинг 5× → 10 мин, план бэкенда §3)
# ============================================================
def admin_login(request: HttpRequest) -> HttpResponse:
    if request.session.get("is_admin"):
        return redirect("admin_dashboard")

    locked_for = login_locked(request)
    error = ""

    if request.method == "POST":
        if locked_for:
            # даже верный пароль в лок-окно отклоняется (тест 22)
            minutes = max(locked_for // 60, 1)
            return render(
                request,
                "panel/login.html",
                {"error": f"Слишком много попыток — подождите {minutes} мин 🦇"},
                status=429,
            )
        login = (request.POST.get("login") or "").strip()
        password = request.POST.get("password") or ""
        # пустые учётные данные из env — логин невозможен (защита от «max/»)
        if (
            settings.ADMIN_LOGIN
            and settings.ADMIN_PASSWORD
            and login == settings.ADMIN_LOGIN
            and password == settings.ADMIN_PASSWORD
        ):
            reset_login_failures(request)
            mark_admin(request)
            next_url = request.GET.get("next") or request.POST.get("next")
            if next_url and next_url.startswith("/admin") and not next_url.startswith("/admin/login"):
                return redirect(next_url)
            return redirect("admin_dashboard")
        register_login_failure(request)
        error = "Неверный логин или пароль"

    return render(
        request,
        "panel/login.html",
        {
            "error": error,
            "locked_for": 0,
            "next": request.GET.get("next", ""),
        },
    )


@require_GET
def admin_logout(request: HttpRequest) -> HttpResponse:
    unmark_admin(request)
    return redirect("admin_login")


# ============================================================
# Общий контекст админ-шаблонов
# ============================================================
def _admin_context() -> dict:
    state = State.load()
    transitions = []
    for target in sorted(allowed_transitions(state.state)):
        transitions.append(
            {
                "to": target,
                "phrase": expected_phrase(state.state, target),
                "fields": {"state": target},
                "label": {
                    "ACTIVE": "▶ Начать голосование",
                    "PAUSED": "☕ Пауза",
                    "FINISHED": "🔮 Завершить",
                }.get(target, target),
            }
        )
    return {
        "state": state,
        "transitions": transitions,
        "voters_total": voters_total(),
        "votes_total": Vote.objects.count(),
        "participants_total": Participant.objects.count(),
        "participants_active": Participant.objects.filter(is_active=True).count(),
        "groups_total": Group.objects.count(),
        "groups_active": Group.objects.filter(is_active=True).count(),
    }


# ============================================================
# Дашборд: бейдж состояния + переходы, счётчики, аномалии;
# автообновление счётчика — fetch /api/v1/stats каждые 30 с (§8.3)
# ============================================================
@admin_required
def dashboard(request: HttpRequest) -> HttpResponse:
    context = _admin_context()
    context["anomalies"] = anomaly.anomaly_report()
    context["recent_log"] = AdminLog.objects.all()[:10]
    context["superuser_email"] = settings.ADMIN_EMAIL
    return render(request, "panel/dashboard.html", context)


@require_POST
@admin_required
def set_state(request: HttpRequest) -> HttpResponse:
    """POST /admin/state/ — переход статус-машины; фраза проверяется
    сервером повторно (ТЗ §13.3, план бэкенда §6)."""
    target = request.POST.get("state", "")
    phrase = request.POST.get("phrase", "")
    try:
        apply_transition(target, phrase)
        messages.success(request, f"Состояние изменено: {target}")
    except TransitionError as exc:
        messages.error(request, f"Отказ: {exc.message}")
    return redirect("admin_dashboard")


@require_POST
@admin_required
def toggle_publish(request: HttpRequest) -> HttpResponse:
    """Переключатель publish_results — доступен только при FINISHED (E10)."""
    state = State.load()
    if state.state != "FINISHED":
        messages.error(request, "Публикация результатов доступна только после завершения (E10).")
        return redirect("admin_results")
    state.publish_results = not state.publish_results
    state.save(update_fields=["publish_results", "updated_at"])
    AdminLog.objects.create(
        action="publish_toggled", details={"publish_results": state.publish_results}
    )
    return redirect("admin_results")


# ============================================================
# CRUD участников (§8.4): фото ≤5 МБ → Pillow 640px q80, номер unique,
# мягкое удаление is_active=false, фильтр «архив», восстановление,
# предпросмотр «глазами гостя»
# ============================================================
@admin_required
def participants(request: HttpRequest) -> HttpResponse:
    show_archive = request.GET.get("filter") == "archive"
    qs = Participant.objects.all() if show_archive else Participant.objects.filter(is_active=True)
    search = (request.GET.get("q") or "").strip()
    if search:
        qs = qs.filter(name__icontains=search)
    votes_by_participant = {
        row["participant_id"]: row["total"]
        for row in Vote.objects.values("participant_id").annotate(total=Count("id"))
    }
    rows = [
        {
            "p": p,
            "votes": votes_by_participant.get(p.pk, 0),
            "delete_url": f"/admin/participants/{p.pk}/delete/",
            "delete_title": f"Снять участника №{p.number} «{p.name}»",
            # id модалов собираются в виде (фильтр add не конкатенирует строку с числом)
            "modal_id": f"confirm-del-{p.pk}",
            "trigger_id": f"trigger-del-{p.pk}",
            # предупреждение при мягком удалении: голоса остаются «(снято)» (E2)
            "consequences": [
                f"Участник №{p.number} «{p.name}» исчезнет из карточек голосования.",
                (
                    f"У участника {votes_by_participant.get(p.pk, 0)} голосов — "
                    "они ОСТАНУТСЯ в итогах с пометкой «(снято)»."
                    if votes_by_participant.get(p.pk)
                    else "Голосов у участника нет."
                ),
                "Вернуть участника можно в архиве кнопкой «Восстановить».",
            ],
        }
        for p in qs
    ]
    return render(
        request,
        "panel/participants.html",
        {
            "rows": rows,
            "show_archive": show_archive,
            "search": search,
        },
    )


@admin_required
def participant_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    obj = get_object_or_404(Participant, pk=pk) if pk else None
    if request.method == "POST":
        form = ParticipantForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Участник сохранён")
            return redirect("admin_participants")
    else:
        if obj is None:
            form = ParticipantForm(initial={"number": _next_number(Participant)})
        else:
            form = ParticipantForm(instance=obj)
    has_votes = bool(obj and Vote.objects.filter(participant=obj).exists())
    return render(
        request,
        "panel/participant_form.html",
        {"form": form, "object": obj, "has_votes": has_votes},
    )


@require_POST
@admin_required
def participant_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Мягкое удаление is_active=false (E2): голоса остаются в итогах."""
    participant = get_object_or_404(Participant, pk=pk)
    participant.is_active = False
    participant.save(update_fields=["is_active", "updated_at"])
    votes = Vote.objects.filter(participant=participant).count()
    AdminLog.objects.create(
        action="participant_deactivated",
        details={"id": participant.pk, "number": participant.number, "votes_kept": votes},
    )
    messages.success(request, f"Участник №{participant.number} снят (архив). Голоса остались в итогах.")
    return redirect("admin_participants")


@require_POST
@admin_required
def participant_restore(request: HttpRequest, pk: int) -> HttpResponse:
    participant = get_object_or_404(Participant, pk=pk)
    participant.is_active = True
    participant.save(update_fields=["is_active", "updated_at"])
    AdminLog.objects.create(
        action="participant_restored", details={"id": participant.pk}
    )
    messages.success(request, f"Участник №{participant.number} восстановлен")
    return redirect("admin_participants")


# ============================================================
# CRUD групп (§8.5): M2M-состав, валидация E9 в форме
# ============================================================
@admin_required
def groups(request: HttpRequest) -> HttpResponse:
    show_archive = request.GET.get("filter") == "archive"
    qs = Group.objects.prefetch_related("participants")
    qs = qs.all() if show_archive else qs.filter(is_active=True)
    return render(
        request,
        "panel/groups.html",
        {"groups": qs, "show_archive": show_archive},
    )


@admin_required
def group_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    obj = get_object_or_404(Group, pk=pk) if pk else None
    if request.method == "POST":
        form = GroupForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Группа сохранена")
            return redirect("admin_groups")
    else:
        if obj is None:
            form = GroupForm(initial={"number": _next_number(Group)})
        else:
            form = GroupForm(instance=obj)
    return render(request, "panel/group_form.html", {"form": form, "object": obj})


@require_POST
@admin_required
def group_delete(request: HttpRequest, pk: int) -> HttpResponse:
    group = get_object_or_404(Group, pk=pk)
    group.is_active = False
    group.save(update_fields=["is_active"])
    AdminLog.objects.create(action="group_deactivated", details={"id": group.pk})
    messages.success(request, f"Группа №{group.number} снята (архив)")
    return redirect("admin_groups")


@require_POST
@admin_required
def group_restore(request: HttpRequest, pk: int) -> HttpResponse:
    group = get_object_or_404(Group, pk=pk)
    group.is_active = True
    group.save(update_fields=["is_active"])
    AdminLog.objects.create(action="group_restored", details={"id": group.pk})
    messages.success(request, f"Группа №{group.number} восстановлена")
    return redirect("admin_groups")


# ============================================================
# Хелперы
# ============================================================
def _next_number(model) -> int:
    last = model.objects.order_by("-number").values_list("number", flat=True).first()
    return (last or 0) + 1
