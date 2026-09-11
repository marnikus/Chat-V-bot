"""The bus events that announce a LIVE world.

One `.db` file is one complete world: its people queue, its messages, its
labels and its undo timeline. Every window that caches any of that has to be
told to reload whenever the *live* world changes — at boot (the page is up
before the archive is open), on a switch, and after a db command is undone.

ONE emitter serves both entry points, so a boot and a switch can never drift
into two different payloads:

* `announce_world_live` — the emitter (PeopleChanged + UserDbChanged, plus
  LabelsChanged when a label store is given);
* `services.undo_service.restart_world` calls it after the world switched;
* the boot reaches it through `Router.announce_world_ready()`, called once
  `ApplicationLifecycle.startup` finished opening the world.

Imports point down only: stdlib and `core.events` — no Qt, no bridges, no
other service, so either layer may call it.
"""

from __future__ import annotations

import json
import logging

from core.events import (EventBus, LabelsChanged, PeopleChanged,
                         UserDbChanged)

log = logging.getLogger("chatbot")


def announce_world_live(bus: EventBus, labels=None,
                        reason: str = "db_switch") -> None:
    """Tell every world-bound window to reload from the world live now.

    `reason` travels in the payload as the action the JS windows report;
    each window reacts to the event itself — `userdb_changed` reloads the
    Full User Database and the DB Connection panels, `people_changed`
    re-renders User Memory, `labels_changed` the label pills.
    """
    bus.emit(PeopleChanged(reason=reason))
    bus.emit(UserDbChanged(payload=json.dumps(
        {"action": reason, "ok": True}, ensure_ascii=False)))
    _announce_labels(bus, labels)


def _announce_labels(bus: EventBus, labels) -> None:
    """A broken label store must not cost the other two announcements."""
    if labels is None:
        return
    try:
        bus.emit(LabelsChanged(
            payload=json.dumps(labels.state(), ensure_ascii=False)))
    except Exception as exc:                            # noqa: BLE001
        log.warning("label state not announced: %s", exc)
