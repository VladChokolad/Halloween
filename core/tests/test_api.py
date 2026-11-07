"""Тесты API-контрактов (план бэкенда §12, test_api 13–21):
200/409/422/400/429, honeypot, CSRF, токен cookie vs X-Voter-Token,
гонка двойной отправки, rate-limit, /api/v1/stats.
"""
import json
import uuid

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from core.models import Group, Participant, State, Voter, Vote
from core.tests.factories import load_state, make_group, make_participant


def vote_payload(votes, grandprix=None, token=None, website=""):
    return {
        "token": token,
        "votes": votes,
        "grandprix": grandprix,
        "website": website,
    }


class ApiVoteBase(TestCase):
    def setUp(self):
        cache.clear()
        load_state(state="ACTIVE")
        self.p1 = make_participant(number=1, name="Кощей")
        self.p2 = make_participant(number=2, name="Тыква-босс")
        self.g1 = make_group(number=1, name="Семейка Аддамс")

    def post_vote(self, client, payload, **extra):
        return client.post(
            "/api/v1/vote",
            data=json.dumps(payload),
            content_type="application/json",
            **extra,
        )


class SuccessfulVoteTests(ApiVoteBase):
    def test_correct_vote_returns_200_and_records(self):
        """13: POST корректного голоса → 200, Vote записаны, voted_at
        установлен, cookie выдана."""
        client = Client()
        token = str(uuid.uuid4())
        response = self.post_vote(
            client,
            vote_payload(
                votes=[
                    {"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk},
                    {"category": "GROUP", "subject_type": "GROUP", "subject_id": self.g1.pk},
                ],
                grandprix={"subject_type": "PARTICIPANT", "subject_id": self.p2.pk},
                token=token,
            ),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["voters_total"], 1)
        voter = Voter.objects.get(pk=token)
        self.assertIsNotNone(voter.voted_at)
        self.assertEqual(Vote.objects.count(), 3)
        self.assertIn("voter_token", response.cookies)

    def test_get_index_creates_voter_cookie(self):
        """/ без cookie ставит voter-cookie (тест 34, подробно — в test_public)."""
        client = Client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("voter_token", response.cookies)


class DoubleSubmitTests(ApiVoteBase):
    def test_double_send_same_token_returns_409_no_duplicates(self):
        """14: двойная отправка одного токена → второй 409 already_voted,
        дублей в БД нет (E4: voted_at-проверка + UNIQUE + select_for_update)."""
        client = Client()
        token = str(uuid.uuid4())
        payload = vote_payload(
            votes=[{"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk}],
            token=token,
        )
        first = self.post_vote(client, payload)
        self.assertEqual(first.status_code, 200)
        second = self.post_vote(client, payload)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"], "already_voted")
        self.assertEqual(Vote.objects.count(), 1)


class StateGateTests(ApiVoteBase):
    def test_paused_returns_409_paused(self):
        """15a: POST при PAUSED → 409 paused."""
        load_state(state="PAUSED")
        response = self.post_vote(
            Client(),
            vote_payload(
                votes=[{"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk}],
                token=str(uuid.uuid4()),
            ),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "paused")

    def test_not_started_returns_409_not_active(self):
        """15b: POST при NOT_STARTED → 409 not_active."""
        load_state(state="NOT_STARTED")
        response = self.post_vote(
            Client(),
            vote_payload(
                votes=[{"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk}],
                token=str(uuid.uuid4()),
            ),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "not_active")

    def test_finished_returns_409_not_active(self):
        """15c: POST при FINISHED → 409 not_active."""
        load_state(state="FINISHED")
        response = self.post_vote(
            Client(),
            vote_payload(
                votes=[{"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk}],
                token=str(uuid.uuid4()),
            ),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "not_active")


class HoneypotAndRequestTests(ApiVoteBase):
    def test_honeypot_returns_400_no_records(self):
        """16: honeypot website непустой → 400, записей нет."""
        response = self.post_vote(
            Client(),
            vote_payload(
                votes=[{"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk}],
                token=str(uuid.uuid4()),
                website="http://spam.example",
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "honeypot")
        self.assertEqual(Vote.objects.count(), 0)
        self.assertEqual(Voter.objects.count(), 0)

    def test_missing_csrf_returns_400_json(self):
        """17a: отсутствие CSRF → 400 bad_request (не HTML)."""
        strict = Client(enforce_csrf_checks=True)
        response = self.post_vote(
            strict,
            vote_payload(
                votes=[{"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk}],
                token=str(uuid.uuid4()),
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "bad_request")

    def test_invalid_json_returns_400(self):
        """17b: невалидный JSON → 400."""
        response = Client().post("/api/v1/vote", data="{not json", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "bad_request")


class TokenResolutionTests(ApiVoteBase):
    def setUp(self):
        super().setUp()
        self.client_first = Client()
        self.token = str(uuid.uuid4())
        first = self.post_vote(
            self.client_first,
            vote_payload(
                votes=[{"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk}],
                token=self.token,
            ),
        )
        assert first.status_code == 200

    def test_cookie_vs_header_token_both_resolve(self):
        """18/19: «очистка cookie, живой localStorage» → X-Voter-Token
        узнаёт voter → 409 already_voted (FR-V-02)."""
        fresh = Client()  # без voter-cookie
        response = self.post_vote(
            fresh,
            vote_payload(
                votes=[{"category": "FUNNY", "subject_type": "PARTICIPANT", "subject_id": self.p2.pk}],
                token=None,
            ),
            HTTP_X_VOTER_TOKEN=self.token,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "already_voted")
        # и без дублей в БД
        self.assertEqual(Vote.objects.count(), 1)


class RateLimitTests(ApiVoteBase):
    def test_11th_post_within_minute_returns_429(self):
        """20: 11-й POST за минуту → 429 rate_limited."""
        client = Client()
        for i in range(10):
            response = self.post_vote(
                client,
                vote_payload(
                    votes=[{"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk}],
                    token=str(uuid.uuid4()),
                ),
            )
            # 1-й — 200, остальные 9 — 409 already_voted; важно не 429
            self.assertNotEqual(response.status_code, 429)
        eleventh = self.post_vote(
            client,
            vote_payload(
                votes=[{"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk}],
                token=str(uuid.uuid4()),
            ),
        )
        self.assertEqual(eleventh.status_code, 429)
        self.assertEqual(eleventh.json()["error"], "rate_limited")


class StatsTests(ApiVoteBase):
    def test_stats_shape(self):
        """21: GET /api/v1/stats → {voters_total, state}."""
        load_state(state="PAUSED")
        response = Client().get("/api/v1/stats")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["voters_total"], 0)
        self.assertEqual(body["state"], "PAUSED")


class ValidationTests(ApiVoteBase):
    def test_conflict_between_nominations_422(self):
        response = self.post_vote(
            Client(),
            vote_payload(
                votes=[
                    {"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk},
                    {"category": "FUNNY", "subject_type": "PARTICIPANT", "subject_id": self.p1.pk},
                ],
                token=str(uuid.uuid4()),
            ),
        )
        self.assertEqual(response.status_code, 422)
        codes = [e["code"] for e in response.json()["errors"]]
        self.assertIn("conflict", codes)

    def test_empty_payload_422(self):
        response = self.post_vote(Client(), vote_payload(votes=[], token=str(uuid.uuid4())))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["errors"][0]["code"], "empty_vote")

    def test_grandprix_group_returns_422(self):
        """Гран-при группе → 422 wrong_subject_type (grandprix_includes_groups=False)."""
        response = self.post_vote(
            Client(),
            vote_payload(
                votes=[],
                grandprix={"subject_type": "GROUP", "subject_id": self.g1.pk},
                token=str(uuid.uuid4()),
            ),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["errors"][0]["code"], "wrong_subject_type")
        self.assertEqual(Vote.objects.count(), 0)

    def test_grandprix_participant_returns_200(self):
        """Гран-при участнику → 200, голос записан."""
        response = self.post_vote(
            Client(),
            vote_payload(
                votes=[],
                grandprix={"subject_type": "PARTICIPANT", "subject_id": self.p2.pk},
                token=str(uuid.uuid4()),
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(Vote.objects.count(), 1)
        self.assertEqual(Vote.objects.filter(category="GRANDPRIX", subject_type="PARTICIPANT").count(), 1)

    def test_inactive_subject_422(self):
        """5 (план §12): голос за архивного кандидата → 422 inactive_subject."""
        archived = make_participant(number=9, name="Снятый", is_active=False)
        response = self.post_vote(
            Client(),
            vote_payload(
                votes=[{"category": "SCARY", "subject_type": "PARTICIPANT", "subject_id": archived.pk}],
                token=str(uuid.uuid4()),
            ),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["errors"][0]["code"], "inactive_subject")
