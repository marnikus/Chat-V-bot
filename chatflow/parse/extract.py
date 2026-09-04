"""Extract user rows from the viewport DOM (single JS eval per pass)."""
from __future__ import annotations

from ..browser import selectors as sel
from ..core.models import Gender, UserRow
from ..engine.errors import OpError


def row_from_js(d: dict) -> UserRow:
    cls = frozenset(d.get("classes") or [])
    if "female-avatar" in cls:
        gender = Gender.FEMALE.value
    elif "male-avatar" in cls:
        gender = Gender.MALE.value
    else:
        gender = Gender.UNKNOWN.value
    return UserRow(
        nickname=(d.get("nickname") or "").strip(),
        gender=gender,
        registered="registered-badge" in cls,
        is_guest="anonymous-badge" in cls,
        classes=cls,
    )


async def extract_rows(ops) -> list[UserRow]:
    """All currently rendered user rows (header rows excluded by JS)."""
    try:
        raw = await ops.eval_js(sel.ROWS_JS)
    except OpError:
        return []
    out: list[UserRow] = []
    for d in raw or []:
        row = row_from_js(d)
        if row.nickname:
            out.append(row)
    return out
