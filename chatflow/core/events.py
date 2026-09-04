"""Bridge event names and payload builders (wire format, see docs §7.2)."""
from __future__ import annotations

STATUS = "status"
LOG = "log"
USERS_FOUND = "users_found"
USERS_COUNTED = "users_counted"
USERS_UPDATED = "users_updated"
TARGET_PICKED = "target_picked"
MESSAGE_SENT = "message_sent"
ERROR = "error"
CONNECTION_LOST = "connection_lost"
RUN_SUMMARY = "run_summary"
TAB_CANDIDATES = "tab_candidates"
TEST_RESULT = "test_result"

ALL = (STATUS, LOG, USERS_FOUND, USERS_COUNTED, USERS_UPDATED, TARGET_PICKED,
       MESSAGE_SENT, ERROR, CONNECTION_LOST, RUN_SUMMARY, TAB_CANDIDATES, TEST_RESULT)


def status(state: str, detail: str = "") -> dict:
    return {"state": state, "detail": detail}


def log(level: str, msg: str, icon: str = "") -> dict:
    return {"level": level, "msg": msg, "icon": icon}


def error(code: str, msg: str) -> dict:
    return {"code": code, "msg": msg}


def row_dict(r) -> dict:
    return {"nickname": r.nickname, "gender": r.gender, "registered": r.registered,
            "is_guest": r.is_guest}


def run_summary(sent: int, passes: int, errors: int, new_users: int,
                elapsed: float) -> dict:
    return {"sent": sent, "passes": passes, "errors": errors,
            "new_users": new_users, "elapsed": round(elapsed, 1)}
