"""Тесты опасной зоны (план бэкенда §12, test_danger 32–33): сброс голосов
(справочники целы, State=NOT_STARTED, AdminLog) и полный сброс (БД пуста).
"""
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from core.models import AdminLog, Group, Participant, State, Voter, Vote
from core.tests.factories import load_state, make_group, make_participant, make_voter

ADMIN = {"ADMIN_LOGIN": "max", "ADMIN_PASSWORD": "pumpkin-spice"}


@override_settings(**ADMIN)
class DangerBase(TestCase):
    def setUp(self):
        cache.clear()
        load_state(state="FINISHED")
        self.admin = Client()
        self.admin.post("/admin/login/", {"login": "max", "password": "pumpkin-spice"})

        self.p1 = make_participant(number=1, name="Кощей")
        self.p2 = make_participant(number=2, name="Тыква-босс")
        self.g1 = make_group(number=1, name="Семейка Аддамс")
        self.g1.participants.add(self.p1)
        for _ in range(2):
            voter = make_voter(voted=True)
            Vote.objects.create(
                voter=voter, category="SCARY", subject_type="PARTICIPANT", participant=self.p1
            )


class ResetVotesTests(DangerBase):
    def test_reset_votes_with_phrase(self):
        """32: сброс голосов — Vote=0, voted_at=null, справочники целы,
        State=NOT_STARTED, AdminLog-запись есть."""
        response = self.admin.post(
            "/admin/danger/action/", {"action": "reset_votes", "phrase": "СБРОС ГОЛОСОВ"}
        )
        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)
        self.assertEqual(Vote.objects.count(), 0)
        self.assertEqual(Voter.objects.filter(voted_at__isnull=False).count(), 0)
        self.assertEqual(Voter.objects.count(), 2)  # гости остались, но «обнулены»
        self.assertEqual(Participant.objects.count(), 2)
        self.assertEqual(Group.objects.count(), 1)
        state = State.load()
        self.assertEqual(state.state, "NOT_STARTED")
        self.assertFalse(state.publish_results)
        self.assertTrue(AdminLog.objects.filter(action="reset_votes").exists())

    def test_reset_votes_case_insensitive_phrase(self):
        response = self.admin.post(
            "/admin/danger/action/", {"action": "reset_votes", "phrase": "  сброс голосов "}
        )
        self.assertEqual(Vote.objects.count(), 0)

    def test_reset_votes_wrong_phrase_rejected(self):
        response = self.admin.post(
            "/admin/danger/action/", {"action": "reset_votes", "phrase": "СБРОС"}, follow=True
        )
        self.assertContains(response, "неверная контрольная фраза")
        self.assertEqual(Vote.objects.count(), 2)
        self.assertEqual(State.load().state, "FINISHED")

    def test_danger_requires_admin(self):
        response = Client().get("/admin/danger/")
        self.assertEqual(response.status_code, 302)


class FullResetTests(DangerBase):
    def test_full_reset_purges_db(self):
        """33: полный сброс — БД пуста (кроме State), фраза обязательна."""
        response = self.admin.post(
            "/admin/danger/action/", {"action": "full_reset", "phrase": "ПОЛНЫЙ СБРОС"}
        )
        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)
        self.assertEqual(Vote.objects.count(), 0)
        self.assertEqual(Voter.objects.count(), 0)
        self.assertEqual(Participant.objects.count(), 0)
        self.assertEqual(Group.objects.count(), 0)
        self.assertEqual(AdminLog.objects.count(), 0)  # журнал очищен последним
        self.assertEqual(State.load().state, "NOT_STARTED")

    def test_full_reset_wrong_phrase_rejected(self):
        self.admin.post("/admin/danger/action/", {"action": "full_reset", "phrase": "полный"})
        self.assertEqual(Participant.objects.count(), 2)
        self.assertEqual(Vote.objects.count(), 2)
