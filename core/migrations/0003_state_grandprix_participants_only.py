"""Гран-при: только участники.

State.grandprix_includes_groups → default=False + выставить флаг в False
у существующей строки State (0002 создавала её с True).
"""
from django.db import migrations, models


def set_flag_false(apps, schema_editor):
    State = apps.get_model("core", "State")
    State.objects.update(grandprix_includes_groups=False)


def restore_flag_true(apps, schema_editor):
    State = apps.get_model("core", "State")
    State.objects.update(grandprix_includes_groups=True)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_initial_data"),
    ]

    operations = [
        migrations.AlterField(
            model_name="state",
            name="grandprix_includes_groups",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(set_flag_false, restore_flag_true),
    ]
