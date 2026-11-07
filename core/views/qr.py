"""QR-страница /admin/qr/ (план бэкенда §3, 04 §8.3): QR на «/» от текущего
Host (важно для плана B/C, когда адрес площадки меняется на месте).

Генерация — вендорный JS (static/vendor/qrcode.min.js, без CDN — площадка
с плохим Wi-Fi). Если файл не вендорится — graceful-фолбэк: крупная текстовая
ссылка на корень.
"""
from __future__ import annotations

from django.contrib.staticfiles import finders
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.decorators import admin_required


@admin_required
def qr(request: HttpRequest) -> HttpResponse:
    scheme = "https" if request.is_secure() else "http"
    host = request.get_host()
    target = f"{scheme}://{host}/"
    return render(
        request,
        "panel/qr.html",
        {
            "target": target,
            "qrcode_js": finders.find("vendor/qrcode.min.js") is not None,
        },
    )
