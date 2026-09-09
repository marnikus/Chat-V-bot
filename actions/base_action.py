"""Abstract base class for all action blocks."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")

# Registry of all action classes keyed by block_id.
# ONE registry, two documented ways into it: the @register decorator and the
# __init_subclass__ hook below. actions.registry re-exports these helpers, so
# the palette the UI asks for and the palette the engine builds blocks from
# can never drift apart again.
_REGISTRY: dict[str, type] = {}


def _register_class(block_id: str, cls: type) -> type:
    """Put `cls` in the registry under `block_id`, loudly on a collision."""
    if not block_id:
        raise ValueError("register: block_id must be non-empty")
    previous = _REGISTRY.get(block_id)
    if previous is not None and previous is not cls:
        # Shadowing a live block changes what every preset that names it
        # will run — never do that silently.
        log.warning("Block id %s re-registered: %s replaces %s", block_id,
                    getattr(cls, "__name__", cls),
                    getattr(previous, "__name__", previous))
    _REGISTRY[block_id] = cls
    cls.block_id = block_id  # type: ignore[attr-defined]
    return cls


def register(block_id: str):
    """Decorator: @register(\"BLOCK_ID\") registers the action class.

    Writes into the same registry as :meth:`BaseAction.__init_subclass__`,
    so both documented registration mechanisms fill one palette.
    """

    def decorator(cls: type) -> type:
        return _register_class(block_id, cls)

    return decorator


class ActionResult:
    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"


class BaseAction(ABC):
    """Every action block inherits this and implements execute()."""
    block_id: str = ""
    name: str = ""
    icon: str = ""

    def __init__(self, pre_delay_ms: int = 500, enabled: bool = True, **kwargs):
        # 'enabled' and 'pre_delay_ms' may arrive inside kwargs when built from dict (load_stack)
        if "enabled" in kwargs:
            enabled = kwargs.pop("enabled")
        if "pre_delay_ms" in kwargs:
            pre_delay_ms = kwargs.pop("pre_delay_ms")
        self.pre_delay_ms = pre_delay_ms
        self.enabled = bool(enabled) if enabled is not None else True
        self.config = kwargs

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Only a block that DECLARES an id joins the palette: a subclass that
        # merely inherits one (a variant, a test double) must not silently
        # replace its parent in the registry.
        if cls.__dict__.get("block_id"):
            _register_class(cls.__dict__["block_id"], cls)

    @abstractmethod
    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        """Run this action. Return ActionResult.*

        :param engine: the running ActionEngine (optional). When provided,
            actions stream step-by-step debugger detail through
            ``engine.report(message, level)`` so every element search,
            clickability check and outcome is visible in the log console
            and written to the run trace.
        """
        ...

    async def pre_delay(self) -> None:
        if self.pre_delay_ms > 0:
            await asyncio.sleep(self.pre_delay_ms / 1000.0)

    def config_schema(self) -> dict:
        return {"pre_delay_ms": {"type": "number", "default": 500, "label": "Pre-delay (ms)"}}

    @property
    def display_name(self) -> str:
        """Name shown in the stack/logs: custom block name if set."""
        custom = getattr(self, "custom_name", None)
        if isinstance(custom, str) and custom.strip():
            return custom.strip()
        return self.name

    def to_dict(self) -> dict:
        """Serialize the block with ALL of its settings (round-trip safe)."""
        d: dict[str, Any] = {"block_id": self.block_id}
        for key, value in vars(self).items():
            if key.startswith("_") or key in ("config", "pre_delay_ms", "enabled"):
                continue
            d[key] = value
        d["pre_delay_ms"] = getattr(self, "pre_delay_ms", 500)
        d["enabled"] = getattr(self, "enabled", True)
        if self.config:
            d.update(self.config)
        return d


NICK_PLACEHOLDER = "{{nick}}"


def resolve_nick(text, user_nick: str = "", engine: Optional[object] = None):
    """Expand ``{{nick}}`` inside a block setting.

    The person remembered for this run (``engine.selected_nick``, written by
    Pick Person / Click User) wins; the queued user of this step is the
    fallback. Anything that is not a string is returned untouched.

    Every config panel that advertises "{{nick}} = selected user" has to go
    through here — a label the block does not honour makes the user type a
    literal ``{{nick}}`` into the page (BUG-04).
    """
    if not isinstance(text, str) or NICK_PLACEHOLDER not in text:
        return text
    nick = (getattr(engine, "selected_nick", "") or "").strip() \
        if engine is not None else ""
    return text.replace(NICK_PLACEHOLDER, nick or (user_nick or ""))


def get_action_class(block_id: str) -> Optional[type]:
    return _REGISTRY.get(block_id)


def all_action_ids() -> list[str]:
    return list(_REGISTRY.keys())
