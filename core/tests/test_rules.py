"""Правила голосования (план бэкенда §12, тесты 1–8).

Mirror-принцип: validate_payload сверяется с точным портом
window.TG_VOTE.validateVotes из vote.js прототипа (строки 118–130) —
те же входы → те же ошибки.
"""
from django.db import IntegrityError
from django.test import TestCase

from core.models import Group, Participant, Vote
from core.services.rules import (
    can_vote_for,
    soft_ip_limit_exceeded,
    validate_payload,
    validate_subjects,
)

from . import factories


def v(category, subject_type, subject_id):
    return {"category": category, "subject_type": subject_type, "subject_id": subject_id}


def js_validate_votes(votes):
    """Точный порт validateVotes из vote.js прототипа:118–130 (эталон mirror-теста)."""
    used = {}
    errors = []
    for item in votes:
        key = item["subject_type"] + ":" + str(item["subject_id"])
        if key in used:
            errors.append(
                {"code": "conflict", "category": item["category"], "subject_id": item["subject_id"]}
            )
        else:
            used[key] = item["category"]
    return errors


class NominationConflictTests(TestCase):
    """Тест 1: кандидат в номинации A блокируется в B/C/D."""

    @classmethod
    def setUpTestData(cls):
        factories.load_state()
        cls.p3 = factories.make_participant(number=3, name="Кощей")

    def test_conflict_between_nominations(self):
        payload = [v("SCARY", "PARTICIPANT", self.p3.id), v("FUNNY", "PARTICIPANT", self.p3.id)]
        errors = validate_payload(payload)
        self.assertEqual(
            errors, [{"code": "conflict", "category": "FUNNY", "subject_id": self.p3.id}]
        )

    def test_conflict_in_each_other_nomination(self):
        for first_cat, other_cat in (
            ("SCARY", "FUNNY"),
            ("FUNNY", "ORIGINAL"),
            ("SCARY", "ORIGINAL"),
        ):
            with self.subTest(first=first_cat, other=other_cat):
                payload = [v(first_cat, "PARTICIPANT", self.p3.id), v(other_cat, "PARTICIPANT", self.p3.id)]
                errors = validate_payload(payload)
                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0]["code"], "conflict")
                self.assertEqual(errors[0]["category"], other_cat)

    def test_group_nomination_conflict_marks_wrong_subject_type_too(self):
        """Участник в GROUP-номинации: и тип неверный, и кандидат занят."""
        payload = [v("SCARY", "PARTICIPANT", self.p3.id), v("GROUP", "PARTICIPANT", self.p3.id)]
        codes = [e["code"] for e in validate_payload(payload)]
        self.assertEqual(codes, ["bad_subject_type", "conflict"])


class GrandprixTests(TestCase):
    """Тесты 2 и 4: гран-при не конфликтует; гран-при — только участники
    (grandprix_includes_groups=False), группа → 422 wrong_subject_type."""

    @classmethod
    def setUpTestData(cls):
        factories.load_state()
        cls.p1 = factories.make_participant(number=1, name="Вдова Мортис")
        cls.p2 = factories.make_participant(number=2, name="Скелет в отпуске")
        cls.p3 = factories.make_participant(number=3, name="Кощей")
        cls.p4 = factories.make_participant(number=4, name="Зомби-фитнес")
        cls.group = factories.make_group(number=1, name="Семейка Аддамс")

    def test_grandprix_does_not_conflict(self):
        """FR-V-06: тот же кандидат и в номинации, и в гран-при → ошибок нет."""
        payload = [
            v("SCARY", "PARTICIPANT", self.p3.id),
            v("FUNNY", "PARTICIPANT", self.p1.id),
            v("ORIGINAL", "PARTICIPANT", self.p2.id),
            v("GROUP", "GROUP", self.group.id),
            v("GRANDPRIX", "PARTICIPANT", self.p3.id),
        ]
        self.assertEqual(validate_payload(payload), [])

    def test_grandprix_for_group_rejected(self):
        """Гран-при группе → wrong_subject_type (группы в гран-при отключены)."""
        errors = validate_payload([v("GRANDPRIX", "GROUP", self.group.id)])
        self.assertEqual(
            errors,
            [{"code": "wrong_subject_type", "category": "GRANDPRIX", "subject_id": self.group.id}],
        )

    def test_grandprix_for_participant_ok(self):
        """Гран-при участнику → ошибок нет."""
        self.assertEqual(validate_payload([v("GRANDPRIX", "PARTICIPANT", self.p1.id)]), [])

    def test_group_nomination_for_participant_rejected(self):
        """GROUP-номинация за участника → 422 bad_subject_type; БД отвергает."""
        payload = [v("GROUP", "PARTICIPANT", self.p1.id)]
        errors = validate_payload(payload)
        self.assertEqual(errors[0]["code"], "bad_subject_type")
        voter = factories.make_voter()
        with self.assertRaises(IntegrityError):
            Vote.objects.create(
                voter=voter, category="GROUP", subject_type="PARTICIPANT", participant=self.p1
            )


class SkipNominationsTests(TestCase):
    """Тест 3: пропуск номинаций не мешает отправке остальных."""

    def setUp(self):
        factories.load_state()
        self.p3 = factories.make_participant(number=3, name="Кощей")

    def test_single_vote_passes(self):
        self.assertEqual(validate_payload([v("SCARY", "PARTICIPANT", self.p3.id)]), [])

    def test_two_of_four_pass(self):
        p1 = factories.make_participant(number=1, name="Вдова Мортис")
        payload = [
            v("SCARY", "PARTICIPANT", self.p3.id),
            v("ORIGINAL", "PARTICIPANT", p1.id),
        ]
        self.assertEqual(validate_payload(payload), [])


class SubjectTypeTests(TestCase):
    """Тип кандидата для номинации (план бэкенда §5)."""

    def setUp(self):
        factories.load_state()

    def test_solo_nomination_for_group_rejected(self):
        payload = [v("SCARY", "GROUP", 1)]
        errors = validate_payload(payload)
        self.assertEqual(errors[0]["code"], "bad_subject_type")

    def test_unknown_category_rejected(self):
        payload = [v("BEST_COSTUME", "PARTICIPANT", 1)]
        errors = validate_payload(payload)
        self.assertEqual(errors[0]["code"], "bad_category")


class InactiveSubjectTests(TestCase):
    """Тест 5: голос за неактивного (архивного) кандидата → inactive_subject."""

    @classmethod
    def setUpTestData(cls):
        factories.load_state()
        cls.active = factories.make_participant(number=1, name="Активный")
        cls.inactive = factories.make_participant(number=2, name="Снятый", is_active=False)
        cls.inactive_group = factories.make_group(number=2, name="Распалась", is_active=False)
        cls.active_group = factories.make_group(number=1, name="Живая")

    def test_inactive_participant(self):
        errors = validate_subjects([v("SCARY", "PARTICIPANT", self.inactive.id)])
        self.assertEqual(
            errors,
            [{"code": "inactive_subject", "category": "SCARY", "subject_id": self.inactive.id}],
        )

    def test_nonexistent_subject(self):
        errors = validate_subjects([v("SCARY", "PARTICIPANT", 99999)])
        self.assertEqual(errors[0]["code"], "inactive_subject")

    def test_inactive_group(self):
        errors = validate_subjects([v("GROUP", "GROUP", self.inactive_group.id)])
        self.assertEqual(errors[0]["code"], "inactive_subject")

    def test_active_subjects_pass(self):
        payload = [
            v("SCARY", "PARTICIPANT", self.active.id),
            v("GROUP", "GROUP", self.active_group.id),
        ]
        self.assertEqual(validate_subjects(payload), [])


class EmptyPayloadTests(TestCase):
    """Тест 6: пустой payload → empty_vote."""

    def setUp(self):
        factories.load_state()

    def test_empty_votes_and_no_grandprix(self):
        self.assertEqual(validate_payload([]), [{"code": "empty_vote"}])


class DuplicateCategoryTests(TestCase):
    """Тест 7: дубликат category в payload → duplicate_category."""

    @classmethod
    def setUpTestData(cls):
        factories.load_state()
        cls.p1 = factories.make_participant(number=1)
        cls.p2 = factories.make_participant(number=2)

    def test_duplicate_scary(self):
        payload = [
            v("SCARY", "PARTICIPANT", self.p1.id),
            v("SCARY", "PARTICIPANT", self.p2.id),
        ]
        errors = validate_payload(payload)
        self.assertEqual(errors[0]["code"], "duplicate_category")


class DbConstraintsTests(TestCase):
    """Слой БД: UNIQUE(voter, category) и chk_subject_match."""

    @classmethod
    def setUpTestData(cls):
        factories.load_state()
        cls.p1 = factories.make_participant(number=1)
        cls.p2 = factories.make_participant(number=2)
        cls.group = factories.make_group(number=1)

    def test_unique_voter_category(self):
        voter = factories.make_voter()
        Vote.objects.create(
            voter=voter, category="SCARY", subject_type="PARTICIPANT", participant=self.p1
        )
        with self.assertRaises(IntegrityError):
            Vote.objects.create(
                voter=voter, category="SCARY", subject_type="PARTICIPANT", participant=self.p2
            )

    def test_chk_subject_match_rejects_participant_and_group(self):
        voter = factories.make_voter()
        with self.assertRaises(IntegrityError):
            Vote.objects.create(
                voter=voter,
                category="SCARY",
                subject_type="PARTICIPANT",
                participant=self.p1,
                group=self.group,
            )


class MirrorValidateVotesTests(TestCase):
    """Тест 8: mirror-тест к window.TG_VOTE.validateVotes —
    те же входы → те же ошибки (только conflict-слой, 1-в-1)."""

    @classmethod
    def setUpTestData(cls):
        factories.load_state()

    def test_mirror_same_inputs_same_errors(self):
        payloads = [
            # чистый конфликт FUNNY
            [v("SCARY", "PARTICIPANT", 3), v("FUNNY", "PARTICIPANT", 3)],
            # конфликт ORIGINAL против GROUP — тип не мешает key
            [v("ORIGINAL", "PARTICIPANT", 7), v("GROUP", "GROUP", 7)],
            # без конфликтов
            [v("SCARY", "PARTICIPANT", 1), v("FUNNY", "PARTICIPANT", 2)],
            # «1:1» и «11» — разные key (строчная конкатенация как в JS)
            [v("SCARY", "PARTICIPANT", 1), v("FUNNY", "PARTICIPANT", 11)],
            # тройной конфликт
            [
                v("SCARY", "PARTICIPANT", 5),
                v("FUNNY", "PARTICIPANT", 5),
                v("ORIGINAL", "PARTICIPANT", 5),
            ],
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(validate_payload(payload), js_validate_votes(payload))


class CanVoteForTests(TestCase):
    """Изолированный порт canVoteFor (vote.js прототипа:105–114) —
    UI-логика блокировки: те же входы, что в cardHTML/refreshSelections."""

    def setUp(self):
        self.choices = {"SCARY": {"type": "participant", "id": 3}}

    def test_same_subject_locked_in_other_nominations(self):
        self.assertIsNone(can_vote_for("SCARY", "participant", 3, self.choices))
        self.assertEqual(can_vote_for("FUNNY", "participant", 3, self.choices), "SCARY")
        self.assertEqual(can_vote_for("ORIGINAL", "participant", 3, self.choices), "SCARY")
        self.assertEqual(can_vote_for("GROUP", "group", 3, self.choices), None)

    def test_other_subjects_unlocked(self):
        self.assertIsNone(can_vote_for("FUNNY", "participant", 7, self.choices))

    def test_grandprix_never_locked(self):
        self.assertIsNone(can_vote_for("GRANDPRIX", "participant", 3, self.choices))
        self.assertIsNone(
            can_vote_for(
                "GRANDPRIX",
                "participant",
                3,
                {
                    "SCARY": {"type": "participant", "id": 3},
                    "FUNNY": {"type": "participant", "id": 3},
                    "ORIGINAL": {"type": "participant", "id": 3},
                    "GROUP": {"type": "group", "id": 1},
                },
            )
        )

    def test_string_vs_int_id(self):
        """JS сравнивает String(ch.id) === String(subjectId) — порт делает то же."""
        self.assertEqual(
            can_vote_for("FUNNY", "participant", "3", self.choices), "SCARY"
        )


class SoftIpLimitTests(TestCase):
    """Мягкий IP-лимит (Т2): 0 = выкл, с лимитом — блокировка по ip_hash."""

    @classmethod
    def setUpTestData(cls):
        cls.p1 = factories.make_participant(number=1)

    def test_disabled_by_default(self):
        factories.load_state()
        self.assertFalse(soft_ip_limit_exceeded("ab" * 8))

    def test_enabled_blocks_after_limit(self):
        factories.load_state(soft_ip_limit=2)
        ip_hash = "cd" * 8
        factories.make_voter(voted=True, ip_hash=ip_hash)
        self.assertFalse(soft_ip_limit_exceeded(ip_hash))
        factories.make_voter(voted=True, ip_hash=ip_hash)
        self.assertTrue(soft_ip_limit_exceeded(ip_hash))

    def test_not_voted_voters_do_not_count(self):
        factories.load_state(soft_ip_limit=1)
        ip_hash = "ef" * 8
        factories.make_voter(voted=False, ip_hash=ip_hash)
        self.assertFalse(soft_ip_limit_exceeded(ip_hash))

    def test_empty_ip_hash_never_blocks(self):
        factories.load_state(soft_ip_limit=1)
        self.assertFalse(soft_ip_limit_exceeded(""))
