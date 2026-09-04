"""CSV export/import of the user table (F-MS-05)."""
from __future__ import annotations

import csv

from .repo_status import StatusRepo
from .repo_users import UserRepo

HEADERS = ["nickname", "gender", "registered", "status", "first_seen",
           "last_seen", "messaged_at", "message_count", "notes"]
_STATUSES = {"NEW", "QUEUED", "MESSAGED", "SKIPPED"}
_GENDERS = {"FEMALE", "MALE", "UNKNOWN"}


def export_users(repo: UserRepo, path: str) -> int:
    records = repo.all_records()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        for u in records:
            w.writerow([u.nickname, u.gender, int(u.registered), u.status,
                        u.first_seen, u.last_seen, u.messaged_at or "",
                        u.message_count, u.notes])
    return len(records)


def import_users(status_repo: StatusRepo, path: str) -> dict:
    records: list[dict] = []
    errors = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nick = (row.get("nickname") or "").strip()
            if not nick:
                errors += 1
                continue
            status = (row.get("status") or "NEW").strip().upper()
            if status not in _STATUSES:
                status = "NEW"
            gender = (row.get("gender") or "UNKNOWN").strip().upper()
            if gender not in _GENDERS:
                gender = "UNKNOWN"
            try:
                count = int(row.get("message_count") or 0)
            except ValueError:
                count = 0
            records.append({"nickname": nick, "gender": gender,
                            "registered": row.get("registered") in ("1", "true", "True"),
                            "status": status, "first_seen": row.get("first_seen") or None,
                            "messaged_at": row.get("messaged_at") or None,
                            "message_count": count, "notes": row.get("notes") or ""})
    inserted = status_repo.import_records(records)
    return {"imported": inserted, "errors": errors}
