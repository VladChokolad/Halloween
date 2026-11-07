"""Хелперы фикстур тестов (план бэкенда §2, core/tests/factories.py)."""
import uuid

from django.utils import timezone

from core.models import Group, Participant, State, Voter


def load_state(**kwargs) -> State:
    """Singleton State + переопределение полей (state, soft_ip_limit, ...)."""
    state = State.load()
    dirty = False
    for key, value in kwargs.items():
        if getattr(state, key) != value:
            setattr(state, key, value)
            dirty = True
    if dirty:
        state.save()
    return state


def make_participant(number=1, name="Тест-призрак", is_active=True, **extra) -> Participant:
    return Participant.objects.create(
        number=number, name=name, is_active=is_active, **extra
    )


def make_group(number=1, name="Тест-группа", is_active=True, **extra) -> Group:
    return Group.objects.create(number=number, name=name, is_active=is_active, **extra)


def make_voter(voted=False, ip_hash="", user_agent="pytest-agent") -> Voter:
    return Voter.objects.create(
        token=uuid.uuid4(),
        voted_at=timezone.now() if voted else None,
        ip_hash=ip_hash,
        user_agent=user_agent[:255],
    )
