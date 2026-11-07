"""Формы админки (план бэкенда §2, §8.4–8.5).

- ParticipantForm: номер unique, фото через photos.process_photo (≤5 МБ →
  Pillow 640px q80), вежливый отказ при превышении/нечитаемом файле.
- GroupForm: состав M2M + валидация E9 «участник не может входить в две
  активные группы».
"""
from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from core.models import Group, Participant
from core.services import photos


class ParticipantForm(forms.ModelForm):
    photo = forms.ImageField(
        required=False,
        label="Фото (≤5 МБ, пережмётся в 640px JPEG)",
        help_text="JPG/PNG. Превышение лимита — вежливый отказ.",
    )

    class Meta:
        model = Participant
        fields = ["number", "name", "description", "photo"]

    def clean_number(self) -> int:
        number = self.cleaned_data["number"]
        qs = Participant.objects.filter(number=number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Участник с таким номером уже существует.")
        return number

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not photo:
            return None
        try:
            return photos.process_photo(photo)
        except photos.PhotoTooLargeError as exc:
            raise ValidationError(str(exc)) from exc
        except photos.PhotoInvalidError as exc:
            raise ValidationError(str(exc)) from exc

    def save(self, commit: bool = True) -> Participant:
        participant = super().save(commit=False)
        processed = self.cleaned_data.get("photo")
        if processed:
            participant.photo_data = processed["data"]
            participant.photo_mime = processed["mime"]
            participant.photo_etag = processed["etag"]
        if commit:
            participant.save()
        return participant


class GroupForm(forms.ModelForm):
    photo = forms.ImageField(required=False, label="Фото (≤5 МБ)")
    participants = forms.ModelMultipleChoiceField(
        queryset=Participant.objects.filter(is_active=True),
        required=False,
        label="Состав",
        help_text="Участник не может входить в две активные группы (E9).",
    )

    class Meta:
        model = Group
        fields = ["number", "name", "description", "photo", "participants"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["participants"].initial = self.instance.participants.values_list(
                "pk", flat=True
            )

    def clean_number(self) -> int:
        number = self.cleaned_data["number"]
        qs = Group.objects.filter(number=number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Группа с таким номером уже существует.")
        return number

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not photo:
            return None
        try:
            return photos.process_photo(photo)
        except photos.PhotoTooLargeError as exc:
            raise ValidationError(str(exc)) from exc
        except photos.PhotoInvalidError as exc:
            raise ValidationError(str(exc)) from exc

    def clean(self):
        cleaned = super().clean()
        members = cleaned.get("participants")
        if not members:
            return cleaned
        # E9: участник не может входить в две активные группы.
        qs = Group.objects.filter(is_active=True, participants__in=members)
        if self.instance.pk and self.instance.is_active:
            qs = qs.exclude(pk=self.instance.pk)
        conflicts = qs.distinct()
        if conflicts.exists():
            names = "; ".join(g.name for g in conflicts)
            raise ValidationError(
                "Участник уже состоит в активной группе: " + names + " (E9)."
            )
        return cleaned

    def save(self, commit: bool = True) -> Group:
        group = super().save(commit=False)
        processed = self.cleaned_data.get("photo")
        if processed:
            group.photo_data = processed["data"]
            group.photo_mime = processed["mime"]
            group.photo_etag = processed["etag"]
        if commit:
            group.save()
            group.participants.set(self.cleaned_data.get("participants") or [])
        return group
