"""Модели «Тыквоголос» — по ТЗ §5 / план бэкенда §4.

Единственное приложение проекта (ТЗ §8). Голоса нельзя потерять каскадом:
Vote → субъект on_delete=PROTECT, мягкое удаление (is_active) — единственный
путь «снятия» кандидата (E2).
"""
import uuid

from django.db import models
from django.db.models import Q


class Participant(models.Model):
    number = models.PositiveIntegerField(unique=True)  # порядок карточек (FR-A-04)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    photo_data = models.BinaryField(null=True, blank=True)  # ≤640px q80 bytes
    photo_mime = models.CharField(max_length=32, blank=True)
    photo_etag = models.CharField(max_length=32, blank=True)  # для /photo/* кэширования
    is_active = models.BooleanField(default=True)  # мягкое удаление (E2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["number"]
        indexes = [models.Index(fields=["is_active", "number"])]

    def __str__(self) -> str:
        return f"№{self.number} {self.name}"


class Group(models.Model):
    number = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    photo_data = models.BinaryField(null=True, blank=True)
    photo_mime = models.CharField(max_length=32, blank=True)
    photo_etag = models.CharField(max_length=32, blank=True)
    participants = models.ManyToManyField(Participant, related_name="groups", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["number"]
        indexes = [models.Index(fields=["is_active", "number"])]

    def __str__(self) -> str:
        return f"№{self.number} {self.name} (группа)"


class Voter(models.Model):
    token = models.UUIDField(primary_key=True)  # выдаётся сервером (FR-V-02)
    created_at = models.DateTimeField(auto_now_add=True)
    voted_at = models.DateTimeField(null=True, blank=True)  # «уже проголосовал» (FR-V-10)
    ip_hash = models.CharField(max_length=16, blank=True)  # sha256(IP+SECRET)[:16] — приватность
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [models.Index(fields=["ip_hash"]), models.Index(fields=["voted_at"])]


class Vote(models.Model):
    class Category(models.TextChoices):
        SCARY = "SCARY"
        FUNNY = "FUNNY"
        ORIGINAL = "ORIGINAL"
        GROUP = "GROUP"
        GRANDPRIX = "GRANDPRIX"

    class SubjectType(models.TextChoices):
        PARTICIPANT = "PARTICIPANT"
        GROUP = "GROUP"

    voter = models.ForeignKey(Voter, on_delete=models.CASCADE, related_name="votes")
    category = models.CharField(max_length=16, choices=Category.choices)
    subject_type = models.CharField(max_length=16, choices=SubjectType.choices)
    participant = models.ForeignKey(
        Participant, null=True, blank=True, on_delete=models.PROTECT, related_name="votes"
    )
    group = models.ForeignKey(
        Group, null=True, blank=True, on_delete=models.PROTECT, related_name="votes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["voter", "category"], name="uniq_voter_category"),  # E4
            models.CheckConstraint(
                name="chk_subject_match",
                check=(
                    Q(subject_type="PARTICIPANT", participant__isnull=False, group__isnull=True)
                    | Q(subject_type="GROUP", group__isnull=False, participant__isnull=True)
                ),
            ),
            # GROUP-номинация ⇔ группа; 4 соло-номинации — только участники;
            # тип GRANDPRIX ограничивает rules.py по флагу grandprix_includes_groups.
            models.CheckConstraint(
                name="chk_group_category",
                check=(
                    Q(category="GROUP", subject_type="GROUP")
                    | Q(category="GRANDPRIX")
                    | (~Q(category__in=("GROUP", "GRANDPRIX")) & Q(subject_type="PARTICIPANT"))
                ),
            ),
        ]
        indexes = [
            models.Index(fields=["category", "subject_type"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.voter_id} → {self.category}:{self.subject_type}#{self.participant_id or self.group_id}"


class State(models.Model):
    """Singleton id=1, строка создаётся data-миграцией 0002."""

    class VotingState(models.TextChoices):
        NOT_STARTED = "NOT_STARTED"
        ACTIVE = "ACTIVE"
        PAUSED = "PAUSED"
        FINISHED = "FINISHED"

    state = models.CharField(
        max_length=16, choices=VotingState.choices, default=VotingState.NOT_STARTED  # FR-S-01
    )
    publish_results = models.BooleanField(default=False)  # FR-R-03
    allow_skip = models.BooleanField(default=True)
    grandprix_includes_groups = models.BooleanField(default=False)  # гран-при: только участники
    soft_ip_limit = models.PositiveIntegerField(default=0)  # 0 = выкл (Т2)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(name="chk_state_singleton", check=Q(id=1)),
        ]

    @classmethod
    def load(cls) -> "State":
        """Единственная точка доступа к состоянию (singleton id=1)."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        return f"State({self.state})"


class AdminLog(models.Model):
    action = models.CharField(max_length=64)  # state_changed / reset_votes / full_reset / crud_*
    details = models.JSONField(default=dict)  # {from, to, phrase_ok, ip_hash, ...}
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"
