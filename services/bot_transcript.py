"""How the archive's messages become the text an AI model reads.

Split out of `bot_chat` so the service is about USE CASES and this is about
turning rows into a transcript — and because `bot_chat` had grown past
RULE 18's 300-line ideal, which is the signal that two things were sharing
one file.

Media matters here: a GIF row carries no text at all, and a transcript that
silently skipped it would hand the model a conversation with holes in it.

ideal-size: 63 lines reason=under RULE 18's 150-line floor because it is
exactly one idea — rows in, transcript out. Padding it, or folding it back
into `bot_chat` to make both files "the right size", would trade a clear
seam for an arbitrary one.
"""

from __future__ import annotations

from datetime import date

def today_key() -> str:
    """The archive's `day` value for today (messages store `YYYY-MM-DD`)."""
    return date.today().isoformat()


def item_text(item: dict) -> str:
    """What one archived message says, media included.

    A GIF or an image row carries no text at all. Skipping it would hand the
    model a conversation with holes in it — or, on a day of nothing but
    stickers, an empty transcript — so media becomes a short visible marker
    instead (acceptance: "do not silently drop media-only messages").
    """
    text = str(item.get("text") or "").strip()
    if text:
        return text
    media = item.get("media") or {}
    kind = str(media.get("kind") or item.get("kind") or "").strip()
    return f"[{kind}]" if kind and kind != "text" else ""


def as_transcript(items: list) -> str:
    """The day's messages as the plain "Nick: text" block Grok reads."""
    lines = []
    for item in items:
        who = item.get("from") or ("me" if item.get("dir") == "out" else "them")
        text = item_text(item)
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


def items_of_day(items, day: str) -> list:
    """Just the items the archive dated `day`, oldest first.

    `HistoryQuery.page` returns a whole screen of the conversation; the Bot
    Chat window is about the current session, so the day filter lives here
    rather than in the frozen query surface.
    """
    return [item for item in (items or []) if item.get("day") == day]


def last_inbound(items: list) -> dict:
    """The person's own last message of the day, or an empty dict."""
    for item in reversed(items):
        if item.get("dir") != "out" and item_text(item):
            return item
    return {}
