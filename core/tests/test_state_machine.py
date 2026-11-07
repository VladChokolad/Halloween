"""Статус-машина (план бэкенда §12, тесты 9–12).

Все допустимые переходы, терминальность FINISHED (E8), AdminLog,
серверная проверка контрольной фразы (ТЗ §13).
"""
from django.test import TestCase

from core.models import AdminLog, State
from core.services.state_machine import (
    TRANSITIONS,
    apply_transition,
    expected_phrase,
)

from . import factories


class TransitionsTableTests(TestCase):
    """Таблица переходов соответствует плану §6."""

    def test_transitions_table(self):
        self.assertEqual(
            TRANSITIONS,
            {
                "NOT_STARTED": {"ACTIVE"},
                "ACTIVE": {"PAUSED", "FINISHED"},
                "PAUSED": {"ACTIVE", "FINISHED"},
                "FINISHED": set(),
            },
        )

    def test_phrases(self):
        self.assertEqual(expected_phrase("NOT_STARTED", "ACTIVE"), "НАЧАТЬ")
        self.assertEqual(expected_phrase("ACTIVE", "PAUSED"), "ПАУЗА")
        self.assertEqual(expected_phrase("PAUSED", "ACTIVE"), "ПРОДОЛЖИТЬ")
        self.assertEqual(expected_phrase("ACTIVE", "FINISHED"), "ЗАВЕРШИТЬ")
        self.assertEqual(expected_phrase("PAUSED", "FINISHED"), "ЗАВЕРШИТЬ")


class AllowedTransitionsTests(TestCase):
    """Тест 9: все допустимые переходы проходят."""

    def setUp(self):
        factories.load_state()  # NOT_STARTED

    def _log(self):
        return list(AdminLog.objects.order_by("id"))

    def test_not_started_to_active(self):
        state = apply_transition("ACTIVE", "НАЧАТЬ")
        self.assertEqual(state.state, "ACTIVE")
        self.assertEqual(State.objects.get(pk=1).state, "ACTIVE")

    def test_active_to_paused_and_back(self):
        apply_transition("ACTIVE", "НАЧАТЬ")
        state = apply_transition("PAUSED", "ПАУЗА")
        self.assertEqual(state.state, "PAUSED")
        state = apply_transition("ACTIVE", "ПРОДОЛЖИТЬ")
        self.assertEqual(state.state, "ACTIVE")

    def test_active_to_finished(self):
        apply_transition("ACTIVE", "НАЧАТЬ")
        state = apply_transition("FINISHED", "ЗАВЕРШИТЬ")
        self.assertEqual(state.state, "FINISHED")

    def test_paused_to_finished(self):
        apply_transition("ACTIVE", "НАЧАТЬ")
        apply_transition("PAUSED", "ПАУЗА")
        state = apply_transition("FINISHED", "ЗАВЕРШИТЬ")
        self.assertEqual(state.state, "FINISHED")


class ForbiddenTransitionsTests(TestCase):
    """Тест 10: FINISHED терминален (E8); NOT_STARTED — только в ACTIVE."""

    def setUp(self):
        factories.load_state()

    def test_finished_to_active_rejected(self):
        apply_transition("ACTIVE", "НАЧАТЬ")
        apply_transition("FINISHED", "ЗАВЕРШИТЬ")
        with self.assertRaises(Exception) as ctx:
            apply_transition("ACTIVE", "НАЧАТЬ")
        self.assertEqual(ctx.exception.code, "invalid_transition")
        self.assertEqual(State.objects.get(pk=1).state, "FINISHED")

    def test_finished_to_paused_rejected(self):
        apply_transition("ACTIVE", "НАЧАТЬ")
        apply_transition("FINISHED", "ЗАВЕРШИТЬ")
        with self.assertRaises(Exception) as ctx:
            apply_transition("PAUSED", "ПАУЗА")
        self.assertEqual(ctx.exception.code, "invalid_transition")

    def test_not_started_to_paused_rejected(self):
        with self.assertRaises(Exception) as ctx:
            apply_transition("PAUSED", "ПАУЗА")
        self.assertEqual(ctx.exception.code, "invalid_transition")
        self.assertEqual(State.objects.get(pk=1).state, "NOT_STARTED")

    def test_not_started_to_finished_rejected(self):
        with self.assertRaises(Exception) as ctx:
            apply_transition("FINISHED", "ЗАВЕРШИТЬ")
        self.assertEqual(ctx.exception.code, "invalid_transition")

    def test_not_started_to_active_without_phrase_rejected(self):
        with self.assertRaises(Exception) as ctx:
            apply_transition("ACTIVE", "")
        self.assertEqual(ctx.exception.code, "bad_phrase")


class AdminLogTests(TestCase):
    """Тест 11: каждый переход попадает в AdminLog."""

    def setUp(self):
        factories.load_state()

    def test_log_written_per_transition(self):
        apply_transition("ACTIVE", "НАЧАТЬ")
        apply_transition("PAUSED", "ПАУЗА")
        logs = list(AdminLog.objects.order_by("id"))
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].action, "state_changed")
        self.assertEqual(logs[0].details["from"], "NOT_STARTED")
        self.assertEqual(logs[0].details["to"], "ACTIVE")
        self.assertEqual(logs[1].details["from"], "ACTIVE")
        self.assertEqual(logs[1].details["to"], "PAUSED")

    def test_failed_transition_not_logged(self):
        with self.assertRaises(Exception):
            apply_transition("PAUSED", "ПАУЗА")
        self.assertEqual(AdminLog.objects.count(), 0)


class PhraseTests(TestCase):
    """Тест 12: неверная контрольная фраза → отказ (серверная проверка)."""

    def setUp(self):
        factories.load_state()

    def test_wrong_phrase_rejected(self):
        with self.assertRaises(Exception) as ctx:
            apply_transition("ACTIVE", "ОТКРЫТЬ")
        self.assertEqual(ctx.exception.code, "bad_phrase")
        self.assertEqual(State.objects.get(pk=1).state, "NOT_STARTED")
        self.assertEqual(AdminLog.objects.count(), 0)

    def test_phrase_casefold_and_strip(self):
        state = apply_transition("ACTIVE", "  НачАтЬ ")
        self.assertEqual(state.state, "ACTIVE")

    def test_exact_phrase_passes(self):
        state = apply_transition("ACTIVE", "НАЧАТЬ")
        self.assertEqual(state.state, "ACTIVE")
