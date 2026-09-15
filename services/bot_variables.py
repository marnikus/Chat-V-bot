"""The prompt variables a template may use, and how they are resolved.

The Prompt Editor lists these so the user can see what exists instead of
guessing; `render` in `bot_prompts` fills them in.

Why a regex and not `str.format`
--------------------------------
Two reasons, both of which `str.format` cannot meet:

1. `{last_x_messages}` is *parameterised* — the user writes `{last_5_messages}`
   and means "the last five". `str.format` has no way to express that.
2. `str.format` raises on any field it does not know, and the old
   `is_usable()` turned that raise into "fall back to the shipped default".
   So the moment a user typed `{tone}` while drafting, their whole template
   was silently discarded. Here an unknown placeholder is left standing in
   the text and reported as a warning — visible, not destructive (RULE 4:
   unknown is not the same as broken).

Privacy
-------
A resolver only ever sees the context dict `BotChatService` builds from the
day's messages. There is no variable that can reach the config, the
filesystem, another person's history or an API key, because the resolver is
never handed them — the boundary is the argument list, not a blocklist.
"""

from __future__ import annotations

import re

#: a placeholder: lowercase word characters between braces
PATTERN = re.compile(r"\{([a-z][a-z0-9_]*)\}")

#: `{last_5_messages}` — the number is part of the name
COUNTED = re.compile(r"^last_(\d+)_messages$")

#: how many messages `{last_x_messages}` means when the user writes the
#: literal `x` rather than a number
DEFAULT_COUNT = 5

#: the biggest slice a counted variable may ask for, so one prompt cannot
#: quietly grow into the whole archive
MAX_COUNT = 50


class Variable:
    """One documented placeholder: what it is called and what it means."""

    def __init__(self, name: str, description: str, example: str) -> None:
        self.name = name
        self.description = description
        self.example = example

    def as_dict(self) -> dict:
        """The shape the Prompt Editor lists (RULE 12: the UI gets data)."""
        return {"name": self.name, "token": "{%s}" % self.name,
                "description": self.description, "example": self.example}


VARIABLES: tuple[Variable, ...] = (
    Variable("msg", "The message being worked on — your custom text when "
                    "there is one, otherwise the person's last message.",
             "see you tomorrow!"),
    Variable("last_msg", "The last message the other person sent.",
             "sounds good, when?"),
    Variable("all_msg", "The whole of today's conversation, oldest first, "
                        "as \"Name: text\" lines.",
             "Anna: hi\nme: hey there"),
    Variable("last_x_messages", "The last few messages — write the number "
                                "you want, e.g. {last_5_messages}.",
             "Anna: hi\nme: hey there"),
    Variable("person_name", "The name of the person you are chatting with.",
             "Anna"),
    Variable("reaction_label", "The reaction label currently set on this "
                               "person, or empty when none is set.",
             "Positive first reaction"),
)

#: The names the first version shipped with. Templates already saved in a
#: user's config still contain them, so they keep resolving forever — a
#: rename that breaks stored data is not a rename, it is data loss.
ALIASES = {"nick": "person_name", "conversation": "all_msg",
           "last_message": "last_msg"}

NAMES = frozenset(v.name for v in VARIABLES) | frozenset(ALIASES)


def catalog() -> list[dict]:
    """Every variable, for the editor's library panel."""
    return [v.as_dict() for v in VARIABLES]


def count_of(name: str) -> int:
    """How many messages a counted placeholder asks for, clamped."""
    match = COUNTED.match(name)
    if not match:
        return DEFAULT_COUNT
    return max(1, min(MAX_COUNT, int(match.group(1))))


def is_known(name: str) -> bool:
    """Whether `name` is a placeholder this app resolves."""
    return name in NAMES or bool(COUNTED.match(name))


def tail(context: dict, count: int) -> str:
    """The last `count` lines of the transcript in `context`."""
    lines = str(context.get("all_msg", "") or "").splitlines()
    return "\n".join(lines[-count:]) if lines else ""


def resolve(name: str, context: dict) -> str:
    """The value of one placeholder, given today's conversation."""
    name = ALIASES.get(name, name)
    if name == "last_x_messages" or COUNTED.match(name):
        return tail(context, count_of(name))
    return str(context.get(name, "") or "")


def fill(text: str, context: dict) -> str:
    """Replace every KNOWN placeholder; leave the rest of the text alone.

    An unrecognised `{word}` survives into the prompt verbatim. That is
    deliberate: the user can see what they typed and fix it, which beats
    both a crash and a silent revert to the default.
    """
    def swap(match: re.Match) -> str:
        name = match.group(1)
        return resolve(name, context) if is_known(name) else match.group(0)

    return PATTERN.sub(swap, text or "")


def unknown_names(text: str) -> list[str]:
    """The placeholders in `text` this app cannot resolve, in order."""
    seen, out = set(), []
    for name in PATTERN.findall(text or ""):
        if not is_known(name) and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def malformed(text: str) -> list[str]:
    """Bracket typos: `{unclosed`, `}stray{`, `{Bad-Name}`.

    Reported separately from unknown names because the fix is different —
    one is a spelling mistake, the other is broken syntax.
    """
    stripped = PATTERN.sub("", text or "")
    out = []
    if stripped.count("{") != stripped.count("}"):
        out.append("unbalanced braces")
    for bad in re.findall(r"\{([^{}]*)\}", stripped):
        out.append("{%s}" % bad)
    return out


def validate(text: str) -> dict:
    """What the editor shows under the template: known, unknown, malformed."""
    used = [name for name in PATTERN.findall(text or "") if is_known(name)]
    unknown = unknown_names(text)
    bad = malformed(text)
    return {"used": sorted(set(used)), "unknown": unknown, "malformed": bad,
            "ok": not unknown and not bad}
