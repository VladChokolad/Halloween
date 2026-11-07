"""Тесты публичных страниц (план бэкенда §12, test_public 34–36): / (cookie,
bootstrap, экраны состояний), /results (гейт FINISHED+publish), /photo/*
(плейсхолдер), /healthz, /django-admin/ бэкдор.
"""
from django.core.cache import cache
from django.test import Client, TestCase

from core.models import Voter
from core.tests.factories import load_state, make_group, make_participant, make_voter


class IndexTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_first_visit_creates_voter_and_sets_cookie(self):
        """34a: / без cookie создаёт Voter и ставит cookie."""
        response = Client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("voter_token", response.cookies)
        self.assertEqual(Voter.objects.count(), 1)

    def test_bootstrap_contains_state_and_catalog(self):
        """34b: bootstrap-JSON содержит state/voted/voters_total/categories/
        participants/groups/csrfToken (§7.3)."""
        load_state(state="ACTIVE")
        make_participant(number=1, name="Кощей")
        make_group(number=1, name="Семейка Аддамс")
        import json
        import re

        response = Client().get("/")
        content = response.content.decode("utf-8")
        self.assertIn('id="tg-bootstrap"', content)
        match = re.search(
            r'<script id="tg-bootstrap" type="application/json">(.+?)</script>',
            content,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        bootstrap = json.loads(match.group(1))
        self.assertEqual(bootstrap["state"], "ACTIVE")
        self.assertFalse(bootstrap["voted"])
        self.assertEqual(bootstrap["voters_total"], 0)
        self.assertEqual(bootstrap["participants"][0]["name"], "Кощей")
        self.assertEqual(bootstrap["groups"][0]["name"], "Семейка Аддамс")
        self.assertIn("csrfToken", bootstrap)
        self.assertEqual(len(bootstrap["categories"]), 5)
        # cookie csrftoken выдана
        self.assertIn("csrftoken", response.cookies)

    def test_state_screens_in_bootstrap(self):
        """34c: экраны состояний NOT_STARTED/PAUSED/FINISHED корректны
        (состояние приходит в bootstrap, vote.js рендерит экран)."""
        for state, marker in [
            ("NOT_STARTED", '"state": "NOT_STARTED"'),
            ("PAUSED", '"state": "PAUSED"'),
            ("FINISHED", '"state": "FINISHED"'),
        ]:
            with self.subTest(state=state):
                load_state(state=state)
                response = Client().get("/")
                self.assertContains(response, marker, status_code=200)

    def test_voted_flag_in_bootstrap(self):
        """34d: проголосовавший гость получает voted=true."""
        voter = make_voter(voted=True)
        client = Client()
        client.cookies["voter_token"] = str(voter.pk)
        response = client.get("/")
        self.assertContains(response, '"voted": true')


class ResultsPublicTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_results_gated_without_finished(self):
        """35a: /results без FINISHED+publish → redirect на /."""
        load_state(state="ACTIVE")
        response = Client().get("/results")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")

    def test_results_gated_without_publish(self):
        """35b: FINISHED, но publish_results=False → redirect."""
        load_state(state="FINISHED")
        self.assertEqual(Client().get("/results").status_code, 302)

    def test_results_public_summary_only(self):
        """35c: FINISHED + publish → сводные данные без токенов."""
        load_state(state="FINISHED", publish_results=True)
        participant = make_participant(number=3, name="Кощей")
        voter = make_voter(voted=True)
        from core.models import Vote

        Vote.objects.create(
            voter=voter, category="SCARY", subject_type="PARTICIPANT", participant=participant
        )
        response = Client().get("/results")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Кощей", content)
        self.assertIn("Итоги вечера", content)
        self.assertNotIn(str(voter.pk), content)  # без токенов


class PhotoTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_photo_served_from_db(self):
        participant = make_participant(number=1, name="С фото")
        participant.photo_data = b"\xff\xd8\xff\xe0fake"
        participant.photo_mime = "image/jpeg"
        participant.photo_etag = "abc123"
        participant.save()
        response = Client().get(f"/photo/p/{participant.pk}.jpg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn('"abc123"', response["ETag"])
        self.assertIn("max-age=86400", response["Cache-Control"])
        # условный запрос → 304
        conditional = Client().get(
            f"/photo/p/{participant.pk}.jpg", HTTP_IF_NONE_MATCH='"abc123"'
        )
        self.assertEqual(conditional.status_code, 304)

    def test_photo_missing_returns_ghost_placeholder(self):
        """36: 404/без фото → SVG-плейсхолдер призрака."""
        for url in ["/photo/p/999.jpg", "/photo/g/999.jpg"]:
            with self.subTest(url=url):
                response = Client().get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "image/svg+xml")
                self.assertIn(b"<svg", response.content)


class HealthzTests(TestCase):
    def test_healthz_ok(self):
        """36: /healthz → 200 ok, no-store."""
        response = Client().get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(response["Cache-Control"], "no-store")


class DjangoAdminBackdoorTests(TestCase):
    def test_django_admin_available(self):
        """/django-admin/ — аварийный бэкдор (страница логина Django)."""
        response = Client().get("/django-admin/login/")
        self.assertEqual(response.status_code, 200)
