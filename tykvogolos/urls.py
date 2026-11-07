"""Полная URL-карта этапа 2 (ТЗ §6, план бэкенда §3).

Гостевой поток и API — через include("core.urls"); админка — тоже в core.urls
(/admin/*), аварийный бэкдор Django-admin — /django-admin/.
"""
from django.contrib import admin
from django.urls import include, path

from tykvogolos import views

admin.site.site_header = "Тыквоголос — аварийный бэкдор"
admin.site.site_title = "Тыквоголос admin"

urlpatterns = [
    path("", include("core.urls")),
    path("healthz", views.healthz, name="healthz"),
    path("photo/p/<int:pk>.jpg", views.photo_participant, name="photo_participant"),
    path("photo/g/<int:pk>.jpg", views.photo_group, name="photo_group"),
    path("django-admin/", admin.site.urls),
]
