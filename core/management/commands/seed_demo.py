"""Management-команда переноса мок-данных прототипа в БД —
для dev-среды и сухого прогона (план бэкенда §2).

Использование: python manage.py seed_demo
Idempotent: update_or_create по number — справочники не задваиваются.

Также создаёт/обновляет superuser для аварийного бэкдора /django-admin/
(username/пароль — settings.ADMIN_LOGIN/ADMIN_PASSWORD, по умолчанию max/max).
"""
from django.conf import settings
from django.contrib.auth import get_user_model
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

        self._ensure_superuser()

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

    def _ensure_superuser(self):
        """Superuser для /django-admin/: username=ADMIN_LOGIN, пароль
        ADMIN_PASSWORD (idempotent — пароль обновляется при каждом сиде)."""
        user_model = get_user_model()
        username = settings.ADMIN_LOGIN
        password = settings.ADMIN_PASSWORD
        if not username or not password:
            self.stdout.write(
                self.style.WARNING(
                    "ADMIN_LOGIN/ADMIN_PASSWORD не заданы — superuser не создан"
                )
            )
            return
        user, created = user_model.objects.update_or_create(
            username=username,
            defaults={
                "email": settings.ADMIN_EMAIL,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        user.set_password(password)
        user.save(update_fields=["password"])
        self.stdout.write(
            self.style.SUCCESS(
                "Superuser '%s' %s (%s)" % (username, "создан" if created else "обновлён", settings.ADMIN_EMAIL)
            )
        )
