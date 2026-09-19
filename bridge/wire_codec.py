"""Pure JSON/request translation shared by humble QObject adapters."""
import json

from backend.history_query_request import DEFAULT_LIMIT, DEFAULT_SORT, PersonPageRequest


def object_arg(raw, default=None) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return dict(default or {})
    return data if isinstance(data, dict) else dict(default or {})


def clean_nick(nick) -> str:
    return " ".join(str(nick or "").split()).strip()


def message_id(raw) -> int:
    try:
        return int(str(raw or "0").strip() or 0)
    except (TypeError, ValueError):
        return 0


def selection(raw) -> tuple:
    try:
        values = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return None, "❌ Delete aborted: bad selection payload"
    if not isinstance(values, list):
        return None, "❌ Delete aborted: selection is not a list"
    return [str(value) for value in values], None


def person_request(opts: dict) -> PersonPageRequest:
    return PersonPageRequest(
        q=str(opts.get("q") or ""),
        limit=int(opts.get("limit") or DEFAULT_LIMIT),
        offset=int(opts.get("offset") or 0),
        sort=str(opts.get("sort") or DEFAULT_SORT),
        dir=str(opts.get("dir") or ""),
        include_deleted=bool(opts.get("include_deleted")))


def people_payload(result) -> tuple | None:
    if result.is_err:
        return None
    payload = result.value
    return (json.dumps(payload["users"], ensure_ascii=False),
            json.dumps(payload["stats"]))
