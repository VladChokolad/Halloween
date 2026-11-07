"""Data-миграция: singleton State id=1 (план бэкенда §4).

Строка состояния создаётся сразу после схемы; доступ — State.load().
"""
from django.db import migrations


def create_singleton_state(apps, schema_editor):
    State = apps.get_model("core", "State")
    State.objects.get_or_create(
        pk=1,
        defaults={
            "state": "NOT_STARTED",
            "publish_results": False,
            "allow_skip": True,
            "grandprix_includes_groups": True,
            "soft_ip_limit": 0,
        },
    )


def remove_singleton_state(apps, schema_editor):
    State = apps.get_model("core", "State")
    State.objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_singleton_state, remove_singleton_state),
    ]
