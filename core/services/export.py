"""CSV/JSON-экспортеры (план бэкенда §10, FR-E-01).

CSV — UTF-8 с BOM (\ufeff в начале строки), чтобы Excel без кракозябр
(чек-лист ТЗ §11). Функции возвращают готовое содержимое; view этапа 2
оборачивает их в HttpResponse с attachment.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict

from core.models import Group, Participant, State, Vote
from core.services.rules import ALL_CATEGORIES

CSV_PREFIX = "\ufeff"  # UTF-8 BOM


def _csv_string(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return CSV_PREFIX + buf.getvalue()


def _subject_name_number(vote: Vote) -> tuple[str, object]:
    if vote.subject_type == "GROUP":
        group = vote.group
        return (group.name if group else "?", group.number if group else "?")
    participant = vote.participant
    return (participant.name if participant else "?", participant.number if participant else "?")


def _token_hash8(token) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:8]


def votes_csv() -> str:
    """timestamp_utc (ISO), category, subject_type, subject_name,
    subject_number, token_hash (sha256(token)[:8])."""
    rows = []
    for vote in Vote.objects.select_related("voter", "participant", "group").order_by("created_at"):
        name, number = _subject_name_number(vote)
        rows.append(
            [
                vote.created_at.isoformat(),
                vote.category,
                vote.subject_type,
                name,
                number,
                _token_hash8(vote.voter.pk),
            ]
        )
    return _csv_string(
        ["timestamp_utc", "category", "subject_type", "subject_name", "subject_number", "token_hash"],
        rows,
    )


def participants_csv() -> str:
    rows = [
        [p.id, p.number, p.name, p.description, p.is_active, p.created_at.isoformat()]
        for p in Participant.objects.order_by("number")
    ]
    return _csv_string(
        ["id", "number", "name", "description", "is_active", "created_at"], rows
    )


def groups_csv() -> str:
    rows = []
    for g in Group.objects.prefetch_related("participants").order_by("number"):
        members = ";".join(m.name for m in g.participants.all())
        rows.append([g.id, g.number, g.name, g.is_active, members])
    return _csv_string(["id", "number", "name", "is_active", "members"], rows)


def _category_tallies() -> dict[str, list[dict]]:
    """Голоса по каждой категории, отсортированные по убыванию."""
    tallies: dict[str, dict[tuple, int]] = defaultdict(lambda: defaultdict(int))
    for vote in Vote.objects.select_related("participant", "group"):
        if vote.subject_type == "GROUP":
            if vote.group:
                tallies[vote.category][("GROUP", vote.group_id, vote.group.name, vote.group.number)] += 1
        elif vote.participant:
            tallies[vote.category][
                ("PARTICIPANT", vote.participant_id, vote.participant.name, vote.participant.number)
            ] += 1
    result = {}
    for category, subjects in tallies.items():
        ordered = sorted(subjects.items(), key=lambda item: (-item[1], item[0][3]))
        result[category] = [
            {"subject_type": t, "subject_id": sid, "name": name, "number": num, "votes": n}
            for (t, sid, name, num), n in ordered
        ]
    return result


category_tallies = _category_tallies  # публичный алиас для views (этап 2)


def voters_total() -> int:
    from core.models import Voter

    return Voter.objects.filter(voted_at__isnull=False).count()


def results_summary_csv() -> str:
    """По категориям: category, place, subject, votes, pct_of_voters."""
    voters = voters_total()
    tallies = _category_tallies()
    rows = []
    for category in ALL_CATEGORIES:
        for place, item in enumerate(tallies.get(category, []), start=1):
            pct = round(item["votes"] / voters * 100, 1) if voters else 0
            rows.append(
                [
                    category,
                    place,
                    f"№{item['number']} {item['name']}",
                    item["votes"],
                    pct,
                ]
            )
    return _csv_string(["category", "place", "subject", "votes", "pct_of_voters"], rows)


def results_json() -> str:
    """Всё вместе: meta (state, totals), results по 5 категориям, справочники."""
    voters = voters_total()
    tallies = _category_tallies()
    results = {}
    for category in ALL_CATEGORIES:
        results[category] = [
            {
                "place": place,
                "subject_type": item["subject_type"],
                "subject_id": item["subject_id"],
                "name": item["name"],
                "number": item["number"],
                "votes": item["votes"],
                "pct_of_voters": round(item["votes"] / voters * 100, 1) if voters else 0,
            }
            for place, item in enumerate(tallies.get(category, []), start=1)
        ]
    payload = {
        "meta": {
            "state": State.load().state,
            "voters_total": voters,
            "votes_total": Vote.objects.count(),
        },
        "results": results,
        "participants": [
            {
                "id": p.id,
                "number": p.number,
                "name": p.name,
                "is_active": p.is_active,
            }
            for p in Participant.objects.order_by("number")
        ],
        "groups": [
            {"id": g.id, "number": g.number, "name": g.name, "is_active": g.is_active}
            for g in Group.objects.order_by("number")
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
