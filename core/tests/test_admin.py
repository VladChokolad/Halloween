"""Тесты админки (план бэкенда §12, test_admin 22–28): auth + троттлинг,
переходы с фразой, CRUD, фото-ресайз, E9, мягкое удаление, дубликат номера.
"""
import io
import os
import uuid

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from PIL import Image

from core.models import AdminLog, Group, Participant, State, Voter, Vote
from core.tests.factories import load_state, make_group, make_participant, make_voter

ADMIN = {"ADMIN_LOGIN": "max", "ADMIN_PASSWORD": "pumpkin-spice"}


def noise_jpeg() -> bytes:
    """Шумный JPEG: сжимается плохо, получается «тяжёлым» (для теста ресайза).
    Гарантируем размер: тяжёлый, но в пределах лимита PHOTO_MAX_MB=5."""
    for side in (2400, 2000, 1600, 1200, 900):
        w = h = side
        img = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        data = buf.getvalue()
        if len(data) < 5 * 1024 * 1024:
            return data
    raise RuntimeError("не удалось сгенерировать тяжёлый JPEG <5 МБ")


def heavy_jpeg(min_mb: float = 6.0) -> bytes:
    """Валидный шумный JPEG больше min_mb — для теста отказа по размеру."""
    for side in (2200, 2600, 3000, 3400):
        w = h = side
        img = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=100)
        data = buf.getvalue()
        if len(data) > min_mb * 1024 * 1024:
            return data
    raise RuntimeError("не удалось сгенерировать JPEG >6 МБ")


class AdminAuthBase(TestCase):
    def setUp(self):
        cache.clear()
        load_state(state="NOT_STARTED")

    def login(self, password="pumpkin-spice"):
        client = Client()
        return client.post(
            "/admin/login/",
            {"login": "max", "password": password},
        ), client


@override_settings(**ADMIN)
class LoginTests(AdminAuthBase):
    def test_login_success_creates_session(self):
        response, client = self.login()
        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)
        page = client.get("/admin/")
        self.assertEqual(page.status_code, 200)

    def test_wrong_password_rejected(self):
        response, client = self.login(password="wrong")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Неверный логин или пароль")
        page = client.get("/admin/")
        self.assertEqual(page.status_code, 302)  # redirect на /admin/login/

    def test_five_failures_lock_for_10_minutes(self):
        """22: логин неверный пароль ×5 → лок; верный пароль в лок-окно
        тоже отклоняется."""
        for _ in range(5):
            response, client = self.login(password="wrong")
            self.assertEqual(response.status_code, 200)
        response, client = self.login(password="pumpkin-spice")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Слишком много попыток", response.content.decode("utf-8"))
        self.assertEqual(client.get("/admin/").status_code, 302)


class ProtectedPagesTests(TestCase):
    """23: все страницы /admin/* без сессии → redirect на /admin/login/."""

    PAGES = [
        "/admin/",
        "/admin/participants/",
        "/admin/participants/new/",
        "/admin/groups/",
        "/admin/groups/new/",
        "/admin/results/",
        "/admin/charts/scary/",
        "/admin/export/votes/",
        "/admin/danger/",
        "/admin/qr/",
    ]

    def test_all_admin_pages_redirect_to_login(self):
        for url in self.PAGES:
            with self.subTest(url=url):
                response = Client().get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/admin/login"))


@override_settings(**ADMIN)
class AuthenticatedAdminBase(AdminAuthBase):
    def setUp(self):
        super().setUp()
        self.admin = Client()
        self.admin.post("/admin/login/", {"login": "max", "password": "pumpkin-spice"})


class StateTransitionTests(AuthenticatedAdminBase):
    def test_state_post_without_phrase_rejected(self):
        """24a: POST /admin/state/ без фразы → отказ."""
        response = self.admin.post("/admin/state/", {"state": "ACTIVE", "phrase": ""})
        self.assertEqual(State.load().state, "NOT_STARTED")

    def test_state_post_wrong_phrase_rejected(self):
        """24b: с неправильной фразой → отказ, сервер не доверяет клиенту."""
        response = self.admin.post("/admin/state/", {"state": "ACTIVE", "phrase": "СТАРТ"})
        self.assertEqual(State.load().state, "NOT_STARTED")

    def test_state_post_with_phrase_transitions(self):
        """24c: с правильной фразой → переход + запись в AdminLog."""
        response = self.admin.post("/admin/state/", {"state": "ACTIVE", "phrase": "НАЧАТЬ"})
        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)
        self.assertEqual(State.load().state, "ACTIVE")
        self.assertTrue(
            AdminLog.objects.filter(
                action="state_changed", details__to="ACTIVE"
            ).exists()
        )

    def test_state_post_phrase_any_case_accepted(self):
        """Регрессия: серверная нормализация casefold+strip — фраза принимается
        в любом регистре («НАЧАТЬ»/«Начать»/«начать») и с пробелами по краям."""
        for phrase in ("НАЧАТЬ", "Начать", "начать", "  начать "):
            load_state(state="NOT_STARTED")
            response = self.admin.post("/admin/state/", {"state": "ACTIVE", "phrase": phrase})
            self.assertRedirects(response, "/admin/", fetch_redirect_response=False)
            self.assertEqual(State.load().state, "ACTIVE", msg=f"фраза {phrase!r} отклонена")


class RawTemplateTextRegressionTests(AuthenticatedAdminBase):
    """Регрессия: сырые шаблонные конструкции не должны попадать в HTML
    страниц. Раньше include-теги и комментарий confirm_modal.html были
    разбиты на несколько строк — лексер Django не распознаёт многострочные
    теги/комментарии и выводил их сырым текстом (8 include на
    /admin/participants/, 2 на /admin/danger/, шапка комментария)."""

    def _assert_no_raw_template_text(self, url: str):
        response = self.admin.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertNotIn("{%", html, f"сырой шаблонный тег на {url}")
        self.assertNotIn("{#", html, f"сырой шаблонный комментарий на {url}")
        return html

    def test_guest_page_has_no_raw_template_text(self):
        """Гостевая / — нет сырых тегов и сырого текста документации."""
        html = self._assert_no_raw_template_text("/")
        self.assertNotIn("confirm_modal.html — общий partial", html)

    def test_participants_page_renders_modals_not_raw_includes(self):
        """Участники: модалы подтверждения удаления отрендерены, не сырой include."""
        make_participant(number=1, name="Призрак")
        html = self._assert_no_raw_template_text("/admin/participants/")
        self.assertIn('id="confirm-del-1"', html)
        self.assertIn('id="trigger-del-1"', html)
        self.assertIn("<h3", html)
        self.assertNotIn("confirm_modal.html", html)

    def test_danger_page_renders_modals_not_raw_includes(self):
        """Опасная зона: оба модала (сброс голосов и полный сброс) отрендерены."""
        html = self._assert_no_raw_template_text("/admin/danger/")
        self.assertIn('id="confirm-reset-votes"', html)
        self.assertIn('id="confirm-full-reset"', html)
        self.assertIn('id="trigger-reset-votes"', html)
        self.assertIn('id="trigger-full-reset"', html)
        self.assertNotIn("confirm_modal.html", html)

    def test_confirm_modal_phrase_input_has_name_attribute(self):
        """Регрессия: у поля контрольной фразы должен быть атрибут name="phrase" —
        без него браузер не отправляет фразу в POST и сервер всегда отвечает
        «Отказ: Неверная контрольная фраза»."""
        html = self._assert_no_raw_template_text("/admin/danger/")
        self.assertIn('name="phrase"', html)
        self.assertGreaterEqual(html.count('name="phrase"'), 2)


class DashboardModalTests(AuthenticatedAdminBase):
    """Регрессия 27: кнопка «▶ Начать голосование» на дашборде должна
    открывать модал подтверждения (панель/confirm_modal.html).
    Ранее include не рендерился: (а) тег был разбит на несколько строк —
    лексер Django не распознаёт многострочные теги и выводил его сырым
    текстом; (б) в однострочном комментарии confirm_modal.html стояли
    шаблонные теги — они вырывались из комментария и ломали компиляцию
    шаблона. Симптом: клик по кнопке «ничего не делает»."""

    def test_dashboard_renders_state_confirm_modal(self):
        page = self.admin.get("/admin/")
        self.assertEqual(page.status_code, 200)
        html = page.content.decode("utf-8")
        # кнопка-триггер и модал отрендерены (не сырой include-текст)
        self.assertContains(page, 'id="trigger-state-ACTIVE"')
        self.assertContains(page, 'id="confirm-state-ACTIVE"')
        self.assertNotIn("{% include", html)
        self.assertNotIn("{%", html)
        # модал содержит форму POST с csrf и подсказку контрольной фразы
        self.assertContains(page, 'name="csrfmiddlewaretoken"')
        self.assertContains(page, "НАЧАТЬ")
        self.assertContains(page, 'action="/admin/state/"')
        # скрипт-обработчик клика, открывающий модал
        self.assertIn("modal.classList.add('open')", html)


class PhotoTests(AuthenticatedAdminBase):
    def test_oversized_photo_rejected(self):
        """25a: фото 6 МБ → вежливый отказ валидации формы."""
        big = heavy_jpeg(6.0)
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.admin.post(
            "/admin/participants/new/",
            {
                "number": 1,
                "name": "Большой призрак",
                "description": "",
                "photo": SimpleUploadedFile("big.jpg", big, content_type="image/jpeg"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Participant.objects.filter(name="Большой призрак").exists())
        self.assertContains(response, "5 МБ")

    def test_large_photo_resized_and_served(self):
        """25b: фото ~4 МБ (<лимита) → ресайз ≤640 px, bytes в БД, отдаётся
        через /photo/p/<id>.jpg."""
        raw = noise_jpeg()
        self.assertLess(raw.__len__(), 5 * 1024 * 1024)
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.admin.post(
            "/admin/participants/new/",
            {
                "number": 1,
                "name": "Кощей",
                "description": "Смерть на игле",
                "photo": SimpleUploadedFile("photo.jpg", raw, content_type="image/jpeg"),
            },
        )
        self.assertRedirects(response, "/admin/participants/", fetch_redirect_response=False)
        participant = Participant.objects.get(name="Кощей")
        self.assertTrue(participant.photo_data)
        self.assertLess(len(participant.photo_data), raw.__len__())
        with Image.open(io.BytesIO(participant.photo_data)) as img:
            self.assertLessEqual(max(img.size), 640)

        served = Client().get(f"/photo/p/{participant.pk}.jpg")
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served["Content-Type"], "image/jpeg")
        self.assertIn("ETag", served)
        self.assertIn("max-age=86400", served["Cache-Control"])


class GroupTests(AuthenticatedAdminBase):
    def test_participant_in_two_active_groups_rejected(self):
        """26: участник в двух активных группах → ошибка валидации E9."""
        member = make_participant(number=1, name="Гомункул")
        group_a = make_group(number=1, name="Семейка Аддамс")
        group_a.participants.add(member)

        response = self.admin.post(
            "/admin/groups/new/",
            {"number": 2, "name": "Кладбищенский хор", "participants": [member.pk]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Group.objects.filter(number=2).exists())
        self.assertContains(response, "E9")

    def test_participant_can_be_in_active_and_archived_groups(self):
        member = make_participant(number=1)
        archived = make_group(number=1, is_active=False)
        archived.participants.add(member)
        response = self.admin.post(
            "/admin/groups/new/",
            {"number": 2, "name": "Новая", "participants": [member.pk]},
        )
        self.assertRedirects(response, "/admin/groups/", fetch_redirect_response=False)


class ParticipantCrudTests(AuthenticatedAdminBase):
    def test_duplicate_number_rejected(self):
        """28: номер-дубликат → отказ валидации."""
        make_participant(number=7, name="Первый")
        response = self.admin.post(
            "/admin/participants/new/",
            {"number": 7, "name": "Второй", "description": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Participant.objects.filter(name="Второй").exists())
        self.assertContains(response, "уже существует")

    def test_soft_delete_keeps_votes_and_marks_snyato(self):
        """27: мягкое удаление участника с голосами: голоса в итогах остаются,
        карточка «(снято)»; фильтр архива + восстановление."""
        load_state(state="FINISHED")
        participant = make_participant(number=3, name="Зомби-фитнес")
        voter = make_voter(voted=True)
        Vote.objects.create(
            voter=voter, category="SCARY", subject_type="PARTICIPANT", participant=participant
        )

        response = self.admin.post(f"/admin/participants/{participant.pk}/delete/")
        self.assertRedirects(response, "/admin/participants/", fetch_redirect_response=False)
        participant.refresh_from_db()
        self.assertFalse(participant.is_active)
        self.assertEqual(Vote.objects.filter(participant=participant).count(), 1)

        results_page = self.admin.get("/admin/results/")
        self.assertContains(results_page, "(снято)")

        # архив-фильтр показывает снятого
        archive = self.admin.get("/admin/participants/?filter=archive")
        self.assertContains(archive, "Зомби-фитнес")
        active = self.admin.get("/admin/participants/")
        self.assertNotContains(active, "Зомби-фитнес")

        # восстановление
        self.admin.post(f"/admin/participants/{participant.pk}/restore/")
        participant.refresh_from_db()
        self.assertTrue(participant.is_active)

    def test_auto_number_suggested(self):
        make_participant(number=4, name="Четыре")
        page = self.admin.get("/admin/participants/new/")
        self.assertEqual(page.status_code, 200)
        self.assertTrue(Participant.objects.filter(number=4).exists())


@override_settings(**ADMIN)
class PublishGateTests(AdminAuthBase):
    def test_publish_toggle_only_at_finished(self):
        """Публикация результатов доступна только при FINISHED (E10)."""
        client = Client()
        client.post("/admin/login/", {"login": "max", "password": "pumpkin-spice"})
        load_state(state="ACTIVE")
        response = client.post("/admin/publish/")
        state = State.load()
        self.assertFalse(state.publish_results)
        load_state(state="FINISHED")
        client.post("/admin/publish/")
        state.refresh_from_db()
        self.assertTrue(state.publish_results)
