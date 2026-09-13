"""`StackBridge` — the facade over the action-stack domain's surfaces.

The class owns the Qt signals and the construction (the context, the
composer's draft text, the two bus subscriptions and the engine relay);
the behaviour lives one responsibility per mixin:

    wiring        engine signals, preset events, log, schedule, normalise
    run_control   run / stop / pause / resume, current stack, snapshot
    composer      the message draft
    criteria      the Filter panel's criteria JSON
    presets       named stack presets (+ the undo step each one records)
    templates     reusable message bodies
    blocks        custom Find & Click block presets

Runs go through the engine (`services/run/`); stack and template presets
through the preset store; custom blocks through the block store.

The mixins are PLAIN classes, not QObject subclasses, and that is load
bearing: `bridge/router.py` builds the QWebChannel class from each
bridge's metaobject starting at `methodOffset()`, so a signal or slot
inherited from a QObject *base* would sit below the offset and silently
vanish from the wire API. Mixins that only inherit `object` are scanned
into this class's own metaobject section, so the published surface is
unchanged (the step-4 `Collector(QObject, LifecycleMixin, …)` precedent).

Layout: the mixins own no state and never import this module, so the
facade is the only module that imports them.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from core.events import PresetsChanged, StackLoaded

from .blocks import CustomBlockMixin
from .composer import ComposerMixin
from .criteria import CriteriaMixin
from .presets import StackPresetMixin
from .run_control import RunControlMixin
from .templates import TemplatePresetMixin
from .wiring import WiringMixin


class StackBridge(QObject, WiringMixin, RunControlMixin,
                    ComposerMixin, CriteriaMixin, StackPresetMixin,
                    TemplatePresetMixin, CustomBlockMixin):
    """Run control, presets, composer, criteria."""

    step_complete = Signal(str, str)
    step_started = Signal(int, str, str)     # index, block_id, user_nick
    stack_complete = Signal()
    preset_list_updated = Signal(str)        # JSON: stack presets
    template_list_updated = Signal(str)      # JSON: template presets
    custom_blocks_updated = Signal(str)      # JSON: custom block presets
    template_loaded = Signal(str, str)       # name, body
    stack_loaded = Signal(str, str)          # name, JSON blocks

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._message_text = ""
        ctx.bus.subscribe(PresetsChanged, self._on_presets)
        ctx.bus.subscribe(StackLoaded,
                          lambda e: self.stack_loaded.emit(e.name, e.payload))
        engine = ctx.engine
        if engine is not None:
            self._connect_engine(engine)
