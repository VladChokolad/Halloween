"""Гостевой поток + API + админка (план бэкенда §3)."""
from django.urls import path

from core.views import api, danger, export as export_views, panel, public, qr, results
from core.views import vote_flow

urlpatterns = [
    # --- гостевой поток ---
    path("", vote_flow.index, name="index"),
    path("results", public.results_public, name="results_public"),
    # --- API ---
    path("api/v1/vote", api.vote, name="api_vote"),
    path("api/v1/stats", api.stats, name="api_stats"),
    # --- админка ---
    path("admin/login/", panel.admin_login, name="admin_login"),
    path("admin/logout/", panel.admin_logout, name="admin_logout"),
    path("admin/", panel.dashboard, name="admin_dashboard"),
    path("admin/state/", panel.set_state, name="admin_set_state"),
    path("admin/publish/", panel.toggle_publish, name="admin_toggle_publish"),
    path("admin/participants/", panel.participants, name="admin_participants"),
    path("admin/participants/new/", panel.participant_form, name="admin_participant_new"),
    path("admin/participants/<int:pk>/", panel.participant_form, name="admin_participant_edit"),
    path("admin/participants/<int:pk>/delete/", panel.participant_delete, name="admin_participant_delete"),
    path("admin/participants/<int:pk>/restore/", panel.participant_restore, name="admin_participant_restore"),
    path("admin/groups/", panel.groups, name="admin_groups"),
    path("admin/groups/new/", panel.group_form, name="admin_group_new"),
    path("admin/groups/<int:pk>/", panel.group_form, name="admin_group_edit"),
    path("admin/groups/<int:pk>/delete/", panel.group_delete, name="admin_group_delete"),
    path("admin/groups/<int:pk>/restore/", panel.group_restore, name="admin_group_restore"),
    path("admin/results/", results.results, name="admin_results"),
    path("admin/charts/<slug:slug>/", results.chart, name="admin_chart"),
    path("admin/export/", export_views.export_page, name="admin_export_page"),
    path("admin/export/<str:what>/", export_views.export, name="admin_export"),
    path("admin/danger/", danger.danger, name="admin_danger"),
    path("admin/danger/action/", danger.danger_action, name="admin_danger_action"),
    path("admin/qr/", qr.qr, name="admin_qr"),
]
