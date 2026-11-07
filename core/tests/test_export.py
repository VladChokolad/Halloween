"""Тесты экспорта (план бэкенда §12, test_export 29–31): CSV/JSON, BOM,
колонки, кириллица, доступ только с админ-сессией.
"""
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from core.models import Vote
from core.tests.factories import load_state, make_group, make_participant, make_voter

ADMIN = {"ADMIN_LOGIN": "max", "ADMIN_PASSWORD": "pumpkin-spice"}


@override_settings(**ADMIN)
class ExportTests(TestCase):
    def setUp(self):
        cache.clear()
        load_state(state="FINISHED")
        self.admin = Client()
        self.admin.post("/admin/login/", {"login": "max", "password": "pumpkin-spice"})

        self.p1 = make_participant(number=1, name="Кощей")
        self.p2 = make_participant(number=2, name="Тыква-босс")
        self.g1 = make_group(number=1, name="Семейка Аддамс")
        voter = make_voter(voted=True)
        Vote.objects.create(
            voter=voter, category="SCARY", subject_type="PARTICIPANT", participant=self.p1
        )
        Vote.objects.create(
            voter=voter, category="GROUP", subject_type="GROUP", group=self.g1
        )

    def test_votes_csv_bom_columns_cyrillic(self):
        """29: votes.csv — колонки, UTF-8 BOM в первых байтах, кириллица."""
        response = self.admin.get("/admin/export/votes/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", response["Content-Disposition"])
        raw = response.content
        self.assertEqual(raw[:3], b"\xef\xbb\xbf")  # UTF-8 BOM
        text = raw.decode("utf-8-sig")
        header = text.splitlines()[0]
        for column in ["timestamp_utc", "category", "subject_type", "subject_name", "subject_number", "token_hash"]:
            self.assertIn(column, header)
        self.assertIn("Кощей", text)
        self.assertIn("SCARY", text)

    def test_participants_and_groups_csv_structure(self):
        """30a: participants.csv/groups.csv — структура."""
        participants = self.admin.get("/admin/export/participants/")
        self.assertEqual(participants.status_code, 200)
        text = participants.content.decode("utf-8-sig")
        self.assertIn("id,number,name,description,is_active,created_at", text)
        self.assertIn("Кощей", text)

        groups = self.admin.get("/admin/export/groups/")
        self.assertEqual(groups.status_code, 200)
        gtext = groups.content.decode("utf-8-sig")
        self.assertIn("id,number,name,is_active,members", gtext)
        self.assertIn("Семейка Аддамс", gtext)

    def test_results_summary_and_json(self):
        """30b: results-summary.csv и results.json — структура."""
        summary = self.admin.get("/admin/export/results-summary/")
        self.assertEqual(summary.status_code, 200)
        stext = summary.content.decode("utf-8-sig")
        self.assertIn("category,place,subject,votes,pct_of_voters", stext)
        self.assertIn("SCARY", stext)

        results = self.admin.get("/admin/export/results.json/")
        self.assertEqual(results.status_code, 200)
        data = results.json()
        self.assertEqual(data["meta"]["state"], "FINISHED")
        self.assertEqual(data["meta"]["voters_total"], 1)
        self.assertEqual(data["results"]["SCARY"][0]["name"], "Кощей")
        self.assertEqual(data["results"]["GROUP"][0]["name"], "Семейка Аддамс")
        self.assertTrue(any(p["name"] == "Тыква-босс" for p in data["participants"]))

    def test_export_requires_admin_session(self):
        """31: экспорт недоступен без админ-сессии."""
        anonymous = Client()
        for what in ["votes", "participants", "groups", "results-summary", "results.json"]:
            with self.subTest(what=what):
                response = anonymous.get(f"/admin/export/{what}/")
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/admin/login"))
