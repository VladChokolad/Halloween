"""Аварийный бэкдор /django-admin/ (план бэкенда §2–§3): штатная регистрация
моделей в Django admin, доступ только superuser (ADMIN_EMAIL, команда
ensure_superuser — вне скоупа этапа 2, создаётся createsuperuser).
"""
from django.contrib import admin

from core.models import AdminLog, Group, Participant, State, Vote, Voter


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    ordering = ("number",)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    filter_horizontal = ("participants",)


@admin.register(Voter)
class VoterAdmin(admin.ModelAdmin):
    list_display = ("token", "created_at", "voted_at", "ip_hash")
    list_filter = ("voted_at",)


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("category", "subject_type", "participant", "group", "voter", "created_at")
    list_filter = ("category", "subject_type")
    search_fields = ("voter__token",)


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ("id", "state", "publish_results", "allow_skip", "soft_ip_limit", "updated_at")


@admin.register(AdminLog)
class AdminLogAdmin(admin.ModelAdmin):
    list_display = ("action", "created_at")
    list_filter = ("action",)
