"""Management-команда переноса мок-данных прототипа в БД —
для dev-среды и сухого прогона (план бэкенда §2).

Использование: python manage.py seed_demo
Idempotent: update_or_create по number — справочники не задваиваются.
"""
from django.core.management.base import BaseCommand

from core.models import Group, Participant, State
from core.services.rules import ALL_CATEGORIES

# --- мок-данные из прототипа (имена из wireframes ТЗ §7) ---
PARTICIPANTS = [
    {"number": 1, "name": "Вдова Мортис", "description": "Плакала над рассадой"},
    {"number": 2, "name": "Скелет в отпуске", "description": "Загар прямо на костях"},
    {"number": 3, "name": "Кощей", "description": "Смерть — на конце иглы"},
    {"number": 4, "name": "Призрак офисного планктона", "description": "Дедлайн вечен"},
    {"number": 5, "name": "Летучая мышь-бариста", "description": "Кофе строго после полуночи"},
    {"number": 6, "name": "Зомби-фитнес", "description": "Кардио до расспада"},
    {"number": 7, "name": "Тыква-босс", "description": "Праведный гнев грядки"},
    {"number": 8, "name": "Инкогнито-призрак", "description": "Простыня с дыркой"},
]

GROUPS = [
    {"number": 1, "name": "Семейка Аддамс", "description": "Роднее некуда"},
    {"number": 2, "name": "Кладбищенский хор", "description": "Поют в терцию"},
]


class Command(BaseCommand):
    help = "Наполняет БД мок-данными из прототипа (8 участников, 2 группы)."

    def handle(self, *args, **options):
        state = State.load()

        for item in PARTICIPANTS:
            Participant.objects.update_or_create(
                number=item["number"],
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "is_active": True,
                },
            )

        for item in GROUPS:
            Group.objects.update_or_create(
                number=item["number"],
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "is_active": True,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Seed готов: участников=%d, групп=%d, состояние=%s, категории=%s"
                % (
                    Participant.objects.count(),
                    Group.objects.count(),
                    state.state,
                    ", ".join(ALL_CATEGORIES),
                )
            )
        )
