"""Декораторы этапа 2 (план бэкенда §2, §3): admin_required (session-аутентификация
админки из ADMIN_LOGIN/ADMIN_PASSWORD) + троттлинг логина (кэш Django,
LOGIN_MAX_ATTEMPTS × LOGIN_LOCK_MINUTES).
"""
from __future__ import annotations

import time
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import redirect

from core.services.voters import get_client_ip, hash_ip


# ============================================================
# Session-аутентификация админки
# ============================================================
SESSION_KEY = "is_admin"


def mark_admin(request) -> None:
    request.session[SESSION_KEY] = True
    request.session["admin_login"] = settings.ADMIN_LOGIN
    # сессия админа живёт не дольше суток события
    request.session.set_expiry(24 * 3600)


def unmark_admin(request) -> None:
    request.session.flush()


def admin_required(view):
    """Все /admin/* кроме /admin/login/ — только с админ-сессией;
    иначе redirect на /admin/login/?next=... (план бэкенда §3)."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.session.get(SESSION_KEY):
            from django.utils.http import url_has_allowed_host_and_scheme

            next_url = request.get_full_path()
            if url_has_allowed_host_and_scheme(next_url, allowed_hosts=None):
                return redirect(f"/admin/login/?next={next_url}")
            return redirect("/admin/login/")
        return view(request, *args, **kwargs)

    return wrapped


# ============================================================
# Троттлинг логина: LOGIN_MAX_ATTEMPTS неудач → лок на LOGIN_LOCK_MINUTES
# ============================================================
def _login_key(request) -> str:
    return f"login_fails:{hash_ip(get_client_ip(request) or 'unknown')}"


def login_locked(request) -> int:
    """Сколько секунд ещё действует лок (0 — лок нет)."""
    locked_until = cache.get(_login_key(request) + ":until")
    if not locked_until:
        return 0
    remaining = int(locked_until - time.time())
    return max(remaining, 0)


def register_login_failure(request) -> None:
    key = _login_key(request)
    max_attempts = getattr(settings, "LOGIN_MAX_ATTEMPTS", 5)
    lock_minutes = getattr(settings, "LOGIN_LOCK_MINUTES", 10)
    try:
        fails = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=lock_minutes * 60)
        fails = 1
    if fails >= max_attempts:
        cache.set(key + ":until", time.time() + lock_minutes * 60, timeout=lock_minutes * 60)
        cache.delete(key)


def reset_login_failures(request) -> None:
    key = _login_key(request)
    cache.delete(key)
    cache.delete(key + ":until")
