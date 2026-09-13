"""services/run/hooks — what the run coordinator tells the world it is doing.

Owns the run's *outward* surface, as opposed to its control flow (`coordinator`)
or its counters (`progress`):

  * `RunTracer`   — the per-run JSONL trace file in `logs/`, one line per event;
  * `RunHooks`    — the no-op extension point a caller subclasses to observe a
                    run without the coordinator knowing who is watching;
  * `RunHooksMixin` — the reporting half of the coordinator: `report`,
                    `person_collected`, `unmessaged_nicks` and friends, mixed in
                    rather than inherited so the coordinator stays one class;
  * the two normalisers, `normalize_blocks` and `norm_level`.

Imports point one way: this module is imported BY `coordinator`, and imports
nothing from `services/run/` itself.

Two behaviours here are deliberate and look like bugs if you do not know:

* every observation is wrapped in a `try` that logs and continues. Tracing,
  upserting a collected person, reading un-messaged nicks — none of it may
  abort the run. A run that dies because its *logging* failed is strictly
  worse than a run with a gap in its log.
* `RunTracer.note` flushes on every line. Traces are read while the run is
  still going (that is their purpose), and a crashed run must leave the events
  that led up to the crash on disk.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
from datetime import datetime

log = logging.getLogger("chatbot")

USER_SCOPED_BLOCKS = frozenset({
    "SCROLL_PARSE", "CONDITIONAL_SKIP", "CLICK_USER",
    "TYPE_MESSAGE", "CLICK_SEND", "ATTACH_IMAGE",
})
STANDALONE_NICK = "—"
RETIRED_BLOCK_KEYS = frozenset({
    "use_panel_filters", "skip_if_backlog", "backlog_threshold",
})
_LEVEL_MAP = {
    "ok": "success", "success": "success", "done": "success",
    "info": "info", "debug": "info", "warn": "warn",
    "warning": "warn", "error": "error", "fail": "error",
}


def normalize_blocks(blocks) -> list[dict]:
    clean = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        item = {k: v for k, v in block.items()
                if k not in RETIRED_BLOCK_KEYS and not str(k).startswith("_")}
        item.setdefault("enabled", True)
        if item["enabled"] is None:
            item["enabled"] = True
        clean.append(item)
    return clean


def norm_level(level: str) -> str:
    return _LEVEL_MAP.get((level or "info").lower(), "info")


class RunTracer:
    def __init__(self, run_id: str, log_dir: str = "logs"):
        os.makedirs(log_dir, exist_ok=True)
        self.run_id = run_id
        self.path = os.path.join(log_dir, f"run_trace_{run_id}.jsonl")
        self._fh = open(self.path, "a", encoding="utf-8")

    def note(self, record: dict) -> None:
        try:
            stamp = datetime.now().isoformat(timespec="milliseconds")
            self._fh.write(json.dumps({"ts": stamp, "run_id": self.run_id,
                                       **record}, ensure_ascii=False) + "\n")
            self._fh.flush()
        except OSError as exc:
            log.error("Trace write failed: %s", exc)

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


class RunHooks:
    def pre_run(self, coordinator) -> None:
        return None

    def post_run(self, coordinator, outcome: str) -> None:
        return None

    def on_action_complete(self, coordinator, block, nick: str, status: str) -> None:
        return None


async def maybe_await(value) -> None:
    if inspect.isawaitable(value):
        await value


class RunHooksMixin:
    def report(self, message: str, level: str = "info") -> None:
        level = norm_level(level)
        self.debug_msg.emit(f"      {message}", level)
        if self._tracer is not None:
            self._tracer.note({"type": "detail", "level": level,
                               "message": message, **self._ctx})

    async def person_collected(self, record, collected: list) -> None:
        try:
            await self._memory.upsert_user(record)
        except Exception as exc:
            log.warning("Live upsert failed for %s: %s", record.nick, exc)
        payload = {"nick": record.nick, "gender": record.gender,
                   "registered": bool(record.registered),
                   "anonymous": bool(record.anonymous),
                   "guest": bool(record.guest),
                   "messaged": bool(record.messaged),
                   "collected": len(collected)}
        self.person_found.emit(json.dumps(payload, ensure_ascii=False))
        if self._tracer is not None:
            self._tracer.note({"type": "person_collected", **payload})

    async def unmessaged_nicks(self) -> set[str]:
        try:
            return {u.nick for u in await self._memory.get_all() if not u.messaged}
        except Exception as exc:
            log.warning("Un-messaged read failed (collecting instead): %s", exc)
            return set()

    def is_stopping(self) -> bool:
        return self._stop_requested

    async def person_rejected(self, record, reason: str) -> bool:
        try:
            deleter = getattr(self._memory, "delete_user", None)
            removed = bool(await deleter(record.nick)) if deleter else False
        except Exception as exc:
            log.warning("Purge failed for %s: %s", record.nick, exc)
            return False
        if not removed:
            return False
        payload = {"nick": record.nick, "reason": reason}
        self.person_removed.emit(json.dumps(payload, ensure_ascii=False))
        self.debug_msg.emit(f"      🗑 Removed “{record.nick}” — {reason}", "warn")
        if self._tracer is not None:
            self._tracer.note({"type": "person_purged", **payload})
        return True

    def note_selected(self, nick: str) -> None:
        if not nick:
            return
        self.selected_nick = nick
        if self._tracer is not None:
            self._tracer.note({"type": "nick_selected", "nick": nick})

    def _expand_nick_on_block(self, block, nick: str) -> dict:
        changed = {}
        for key, value in vars(block).items():
            if key.startswith("_") or not isinstance(value, str) or "{{nick}}" not in value:
                continue
            changed[key] = value
            setattr(block, key, value.replace("{{nick}}", nick))
        return changed

    @staticmethod
    def _restore_block_attrs(block, originals: dict) -> None:
        for key, value in originals.items():
            setattr(block, key, value)
