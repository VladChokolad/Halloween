"""Гостевой поток: GET / (план бэкенда §3, §7.3, §9).

Server-rendered index.html: voter-cookie + CSRF-cookie + JSON-bootstrap
`<script id="tg-bootstrap">` (state/voted/voters_total/categories/participants/
groups/csrfToken) — vote.js читает отсюда вместо data.js/state.js.
"""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.utils.timezone import now
from django.views.decorators.csrf import ensure_csrf_cookie

from core.catalog import CATEGORIES, groups_json, participants_json
from core.models import State
from core.services.export import voters_total
from core.services.voters import resolve_voter, set_voter_cookie


@ensure_csrf_cookie
def index(request: HttpRequest) -> HttpResponse:
    state = State.load()
    voter, needs_cookie = resolve_voter(request)

    # get_token выставляет csrftoken-cookie и возвращает токен для bootstrap
    csrf_token = get_token(request)

    bootstrap = {
        "name": "Бал нежити",
        "state": state.state,
        "voted": voter.voted_at is not None,
        "voters_total": voters_total(),
        "categories": CATEGORIES,
        "participants": participants_json(),
        "groups": groups_json(),
        "csrfToken": csrf_token,
        "serverTime": now().isoformat(),
    }

    response = render(request, "index.html", {"bootstrap": bootstrap})
    if needs_cookie:
        set_voter_cookie(response, voter)
    return response
