"""BaseAction and the small shared skeleton the blocks are built on.

The registry (actions/registry.py) and the run-time context
(actions/context.py) used to live here with it; they are separate modules
now, so this file holds the interface plus what several blocks genuinely have
in common:

  BaseAction        — what every block must provide (execute, settings
                      round-trip, the panel schema).
  BlockField        — ONE setting, declared once: its panel entry, its
                      cleaning, and which visual-click keyword it feeds.
  DeclaredSettings  — the plumbing that turns a tuple of BlockFields into a
                      constructor, a `to_dict()` and a `config_schema()` that
                      cannot drift apart.
  FindClickBlock    — the family that finds something on the page and clicks
                      it visibly (RULE 1: the clicking is `visual_click`'s).
  MarkerBlock       — the family the engine drives itself.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Optional

_SIGNATURES: dict = {}          # class -> its __init__ parameters, computed once


def ms_floor(value: Any) -> int:
    """A pause from a preset, as a non-negative number of milliseconds.

    `None` and `""` mean 0 — the config panel writes those while a field is
    blank — and a negative pause would have the runner wait before it had even
    drawn anything, which is the opposite of what the outline is for.
    """
    return max(0, int(value or 0))


def _click_runner():
    """The shared visual-confirmation runner (RULE 1), reached lazily.

    `backend.visual_click` imports this module for ActionResult, so importing it
    back at module scope would be a cycle that exists only while Python is
    reading the files — a function-level import is how the block family avoids
    it, and tests can still patch either side.
    """
    from actions.find_click_runner import find_and_click
    return find_and_click

log = logging.getLogger("chatbot")


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
        # 'enabled' and 'pre_delay_ms' may arrive inside kwargs when built
        # from dict (load_stack)
        if "enabled" in kwargs:
            enabled = kwargs.pop("enabled")
        if "pre_delay_ms" in kwargs:
            pre_delay_ms = kwargs.pop("pre_delay_ms")
        self.pre_delay_ms = pre_delay_ms
        self.enabled = bool(enabled) if enabled is not None else True
        self.config = kwargs

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Self-registration: defining a subclass with a block_id IS the
        # registration. (The explicit @ActionRegistry.register decorator
        # exists for aliases and non-inheriting adapters.)
        if cls.block_id:
            from actions.registry import ActionRegistry
            ActionRegistry.register_class(cls)

    @abstractmethod
    async def execute(self, user_nick: str, cdp,
                      engine: Optional[object] = None) -> str:
        """Run this action. Return ActionResult.*

        :param engine: the run context (an ActionContext built by the run
            service, duck-compatible with the historical ActionEngine
            surface). When provided, actions stream step-by-step debugger
            detail through ``engine.report(message, level)`` so every
            element search, clickability check and outcome is visible in
            the log console and written to the run trace.
        """
        ...

    async def pre_delay(self) -> None:
        if self.pre_delay_ms > 0:
            await asyncio.sleep(self.pre_delay_ms / 1000.0)

    def config_schema(self) -> dict:
        return {"pre_delay_ms": {"type": "number", "default": 500,
                                 "label": "Pre-delay (ms)"}}

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
            if key.startswith("_") or key in ("config", "pre_delay_ms",
                                              "enabled"):
                continue
            d[key] = value
        d["pre_delay_ms"] = getattr(self, "pre_delay_ms", 500)
        d["enabled"] = getattr(self, "enabled", True)
        if self.config:
            d.update(self.config)
        return d


# ── the shared skeleton: settings as data ──────────────────────────────
#: "the caller did not pass this setting" — a sentinel of its own because
#: `None` is a value presets legitimately contain.
_UNSET = object()


@dataclass(frozen=True)
class BlockField:
    """One setting of a block, declared once.

    `type`/`label`/`options`/`help` are what the config panel draws; `clean` is
    how a value from a preset becomes the value the block works with;
    `request` names the `visual_click.find_and_click()` keyword the setting is
    handed to, so a block no longer states the same setting in a constructor, a
    schema and an `execute()`.

    `default` normally stays unset: the constructor's own signature is the one
    source of defaults (see `DeclaredSettings._field_default`), and repeating
    the number here is how a schema starts lying about its block.
    """

    name: str
    type: str = "text"
    label: str = ""
    default: Any = _UNSET
    options: tuple = ()
    help: str = ""
    clean: Optional[Callable[[Any], Any]] = None
    request: Optional[str] = None

    def to_schema(self, default: Any = _UNSET) -> dict:
        """The panel's entry for this field — key order is part of the wire."""
        if default is _UNSET:
            default = self.default
        entry: "dict[str, Any]" = {"type": self.type,
                                   "default": None if default is _UNSET
                                   else default,
                                   "label": self.label}
        if self.options:
            entry["options"] = list(self.options)
        if self.help:
            entry["help"] = self.help
        return entry

    def coerce(self, value: Any) -> Any:
        return self.clean(value) if self.clean is not None else value


class DeclaredSettings(BaseAction):
    """A block whose settings are the ``FIELDS`` tuple it declares.

    RULE 3 — "block settings are plain instance attributes" — stays literally
    true: each field ends up as `self.<name>`, `to_dict()` writes the same keys
    in the same order, and `load_stack()` can still build a block from a saved
    dict by keyword.
    """

    FIELDS: ClassVar[tuple] = ()

    def __init__(self, **settings):
        for field in self.FIELDS:
            given = settings.pop(field.name, _UNSET)
            if given is _UNSET:
                given = self._field_default(field)
            setattr(self, field.name, field.coerce(given))
        super().__init__(**settings)

    @classmethod
    def _field_default(cls, field: BlockField) -> Any:
        """The constructor's own default for a field, or the field's fallback.

        Cached per class because `inspect.signature` is not cheap and the panel
        asks for the schema of every block on the screen.
        """
        params = _SIGNATURES.get(cls)
        if params is None:
            params = dict(inspect.signature(cls.__init__).parameters)
            _SIGNATURES[cls] = params
        param = params.get(field.name)
        if param is None or param.default is inspect.Parameter.empty:
            return field.default
        return param.default

    def config_schema(self) -> dict:
        """The inherited entries plus one per declared field, in order."""
        schema = super().config_schema()
        schema.update(self.panel_schema())
        return schema

    def panel_schema(self) -> dict:
        return {field.name: field.to_schema(self._field_default(field))
                for field in self.FIELDS}

    def as_dict(self) -> dict:
        """This block's settings as plain JSON-ready data."""
        return {field.name: getattr(self, field.name) for field in self.FIELDS}


class FindClickBlock(DeclaredSettings):
    """Find it, show it, click it — through the shared visual-confirmation runner.

    Every block that clicks the page belongs here (RULE 1): the RED outline on
    what was detected, the pause to look at it, the ORANGE outline on the click
    target and the click itself are `backend/visual_click.py`'s two phases, so
    a block in this family only says what to look for and what the run console
    should call it.
    """

    #: how the two log lines name the thing being chased; {placeholders} are
    #: this block's own field values
    label_template: ClassVar[str] = "element '{selector}'"
    #: keywords the block adds to every find_and_click() call
    find_defaults: ClassVar[dict] = {}

    def click_runner(self):
        """The runner this block calls: its own module's name if it has one.

        Blocks are tested — and, in one case, patched by the run stack — by
        replacing `find_and_click` where the block imports it, so the lookup goes
        to the block's module first and only falls back to the shared runner
        here. RULE 1 is unaffected: every path leads to `visual_click`.
        """
        module = sys.modules.get(type(self).__module__)
        return getattr(module, "find_and_click", None) or _shared_runner()

    def find_kwargs(self, engine: Optional[object] = None) -> dict:
        """The runner's keyword arguments, read off the declared fields."""
        kwargs = {field.request: getattr(self, field.name)
                  for field in self.FIELDS if field.request}
        kwargs.update(self.find_defaults)
        kwargs["label"] = self.find_label()
        kwargs["engine"] = engine
        return kwargs

    def find_label(self) -> str:
        return self.label_template.format(**self.as_dict())

    def fallback_attempts(self) -> tuple:
        """Extra tries for when the first one fails: `(notice, label, kwargs)`.

        Only blocks with a documented second selector return one; the notice is
        what the user reads while it happens (RULE 5).
        """
        return ()

    async def execute(self, user_nick: str, cdp,
                      engine: Optional[object] = None) -> str:
        find_and_click = self.click_runner()
        await self.pre_delay()
        kwargs = self.find_kwargs(engine)
        outcome = await find_and_click(cdp, **kwargs)
        for notice, extra in self.fallback_attempts():
            if outcome == ActionResult.OK:
                return outcome
            if engine and notice:
                engine.report(notice, "warn")
            retry = dict(kwargs)
            retry.update(extra)
            outcome = await find_and_click(cdp, **retry)
        return outcome


class MarkerBlock(DeclaredSettings):
    """A block the engine drives itself: it is in the stack to be read, not run.

    Saying so in the run console and returning SKIP is the whole behaviour —
    a marker that stayed silent would look like a step that did nothing at all
    (RULE 9). A marker never waits, so `pre_delay_ms` is forced to 0 even when
    an old preset still carries a value for it.
    """

    #: markers that have no settings of their own still show the inherited
    #: pre-delay row; the two that force the delay to 0 drop it, and already
    #: saved stacks are written against exactly that panel
    panel_shows_pre_delay: ClassVar[bool] = False

    def __init__(self, **settings):
        settings.pop("pre_delay_ms", None)
        super().__init__(pre_delay_ms=0, **settings)

    def config_schema(self) -> dict:
        if self.panel_shows_pre_delay:
            return super().config_schema()
        return self.panel_schema()

    def marker_message(self, user_nick: str) -> str:
        return (f"\u23ed {self.name} marker for {user_nick} \u2014 handled by "
                "the engine")

    async def execute(self, user_nick: str, cdp,
                      engine: Optional[object] = None) -> str:
        if engine:
            engine.report(self.marker_message(user_nick), "info")
        return ActionResult.SKIP
