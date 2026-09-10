"""preset_io — the portable stack/block export file format (v1).

Pure module: no Qt, no store. Everything the import path knows about a
file is a function of the file text, so it is testable without a GUI.
Design: docs/STACK_PRESET_EXPORT_IMPORT_DESIGN_2026-09-10.md §3.

Two shapes, distinguished by ``format``:

* ``chat-v-bot/stack-preset`` — the full stack (every parameter of every
  block) plus the whole custom-block library, standalone;
* ``chat-v-bot/action-block`` — one named block.

Import never applies unvalidated data: ``parse_export`` rejects with a
distinct ``Err`` code for every hard failure and collects human-readable
warnings for compatibility problems (version mismatch, unknown block
type, missing selector).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from actions.registry import all_action_ids
from core.result import Err, Result, err, ok
from core.version import APP_VERSION

#: the two known file shapes
STACK_PRESET_FORMAT = "chat-v-bot/stack-preset"
ACTION_BLOCK_FORMAT = "chat-v-bot/action-block"

#: the newest format this app reads (hard reject above, warning below)
FORMAT_VERSION = 1


@dataclass(frozen=True, slots=True)
class PresetPreview:
    """The validated, normalized content of one export file.

    ``kind`` is ``"stack"`` or ``"block"``; ``stack``/``custom_blocks``
    are meaningful for ``"stack"`` and ``block`` for ``"block"`` (the
    unused halves stay empty so the wire shape is one dict either way).
    """

    kind: str
    name: str
    format_version: int
    app_version: str
    exported_at: str
    stack: tuple[dict, ...] = ()
    custom_blocks: tuple[dict, ...] = ()
    block: Optional[dict] = None
    warnings: tuple[str, ...] = ()


# ── builders (export side) ─────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _only_dicts(items: Any) -> list[dict]:
    return [dict(item) for item in (items or []) if isinstance(item, dict)]


def build_stack_export(name: str, stack: Any, custom_blocks: Any,
                       app_version: Optional[str] = None) -> dict:
    """The full stack + whole block library as one standalone payload."""
    name = (name or "").strip()
    if not name:
        raise ValueError("stack export needs a preset name")
    return {
        "format": STACK_PRESET_FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": app_version or APP_VERSION,
        "exported_at": _now(),
        "name": name,
        "stack": _only_dicts(stack),
        "custom_blocks": _only_dicts(custom_blocks),
    }


def build_block_export(name: str, block: Any,
                       app_version: Optional[str] = None) -> dict:
    """One named block as a standalone payload."""
    name = (name or "").strip()
    if not name or not isinstance(block, dict):
        raise ValueError("block export needs a name and a block object")
    return {
        "format": ACTION_BLOCK_FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": app_version or APP_VERSION,
        "exported_at": _now(),
        "name": name,
        "block": dict(block),
    }


def export_text(payload: dict) -> str:
    """Human-readable serialization (indent 2, original scripts kept)."""
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


# ── file IO ────────────────────────────────────────────────────────

def write_export(path: Any, payload: dict) -> Result[None]:
    """Atomic write: a failure never leaves a half-written file behind
    (same tmp+fsync+replace pattern as ``stores.atomic``)."""
    tmp = os.fspath(path) + ".tmp"
    try:
        parent = os.path.dirname(os.path.abspath(os.fspath(path)))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(export_text(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, os.fspath(path))
        return ok(None)
    except (OSError, TypeError, ValueError) as exc:  # noqa: BLE001
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return err("write_failed", str(exc))


def read_export_file(path: Any) -> Result[str]:
    try:
        with open(os.fspath(path), "r", encoding="utf-8") as handle:
            return ok(handle.read())
    except OSError as exc:
        return err("read_failed", str(exc))


# ── parse + validate (import side) ─────────────────────────────────

def _require_name(data: dict) -> "str | Err":
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return err("no_name", "the preset has no name")
    return name.strip()


def _check_version(data: dict, warnings: list[str]) -> "int | Err":
    """Reject a newer format, warn on an older one, note app version."""
    raw = data.get("format_version")
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        return err("bad_version",
                   "format_version must be a positive integer")
    if raw > FORMAT_VERSION:
        return err("unsupported_version",
                   f"file format v{raw} is newer than this app's "
                   f"v{FORMAT_VERSION} — update the app first")
    if raw < FORMAT_VERSION:
        warnings.append(
            f"older file format (v{raw} < v{FORMAT_VERSION}) — "
            "imported as-is")
    exported = data.get("app_version")
    if isinstance(exported, str) and exported and exported != APP_VERSION:
        warnings.append(
            f"exported with app {exported}; this app is {APP_VERSION} — "
            "check compatibility")
    return raw


def _selector_warning(bid: str, block: dict) -> Optional[str]:
    if bid != "CUSTOM_FIND" or _nonempty(block.get("selector")):
        return None
    label = block.get("custom_name")
    label = label if isinstance(label, str) and label else bid
    return f"“{label}” has no selector — it finds nothing on any page"


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _stack_warnings(stack: list[dict]) -> list[str]:
    """RULE 4: the engine drops unknown types SILENTLY, so the import
    must say which blocks will vanish before the user applies."""
    known = set(all_action_ids())
    out: list[str] = []
    for idx, block in enumerate(stack, start=1):
        bid = block.get("block_id")
        if not isinstance(bid, str) or not bid:
            out.append(f"block #{idx} has no block_id — it will be skipped")
            continue
        if bid not in known:
            out.append(f"block #{idx} uses unknown type “{bid}” — "
                       "it will be skipped on import")
            continue
        warning = _selector_warning(bid, block)
        if warning:
            out.append(f"block #{idx}: {warning}")
    return out


def _clean_custom_blocks(raw: Any, warnings: list[str]) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        warnings.append("custom_blocks is not a list — the block "
                        "library was skipped")
        return []
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict) or \
                not isinstance(entry.get("block"), dict):
            warnings.append("a custom block entry is malformed — "
                            "it was skipped")
            continue
        name = entry.get("name")
        if not _nonempty(name):
            warnings.append("a custom block has no name — "
                            "it was skipped")
            continue
        out.append({"name": name.strip(), "block": entry["block"],
                    "updated_at": entry.get("updated_at", "")})
    return out


def _parse_stack(data: dict) -> Result[PresetPreview]:
    name = _require_name(data)
    if isinstance(name, Err):
        return name
    warnings: list[str] = []
    version = _check_version(data, warnings)
    if isinstance(version, Err):
        return version
    stack = data.get("stack")
    if not isinstance(stack, list) or \
            not all(isinstance(b, dict) for b in stack):
        return err("bad_stack",
                   "“stack” must be a list of block objects")
    warnings.extend(_stack_warnings(stack))
    custom = _clean_custom_blocks(data.get("custom_blocks"), warnings)
    return ok(PresetPreview(
        kind="stack", name=name, format_version=version,
        app_version=str(data.get("app_version") or ""),
        exported_at=str(data.get("exported_at") or ""),
        stack=tuple(stack), custom_blocks=tuple(custom),
        warnings=tuple(warnings)))


def _block_warning(bid: Any, block: dict) -> Optional[str]:
    """The compatibility problem of one standalone block, if any."""
    if not isinstance(bid, str) or not bid:
        return "block has no block_id — it cannot run"
    if bid not in set(all_action_ids()):
        return f"block uses unknown type “{bid}” — it cannot run " \
               "in this app"
    return _selector_warning(bid, block)


def _parse_block(data: dict) -> Result[PresetPreview]:
    name = _require_name(data)
    if isinstance(name, Err):
        return name
    warnings: list[str] = []
    version = _check_version(data, warnings)
    if isinstance(version, Err):
        return version
    block = data.get("block")
    if not isinstance(block, dict):
        return err("bad_block", "“block” must be a block object")
    warning = _block_warning(block.get("block_id"), block)
    if warning:
        warnings.append(warning)
    return ok(PresetPreview(
        kind="block", name=name, format_version=version,
        app_version=str(data.get("app_version") or ""),
        exported_at=str(data.get("exported_at") or ""),
        block=block, warnings=tuple(warnings)))


def parse_export(text: str) -> Result[PresetPreview]:
    """Parse + validate one export file. A hard failure is a typed
    ``Err`` with a stable code; soft problems become warnings."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return err("not_json", "the file is not valid JSON")
    if not isinstance(data, dict):
        return err("bad_shape", "the file is not a preset object")
    fmt = data.get("format")
    if fmt == STACK_PRESET_FORMAT:
        return _parse_stack(data)
    if fmt == ACTION_BLOCK_FORMAT:
        return _parse_block(data)
    return err("unknown_format",
               f"unknown format {fmt!r} — expected one of "
               f"{STACK_PRESET_FORMAT!r}, {ACTION_BLOCK_FORMAT!r}")


def preview_dict(preview: PresetPreview) -> dict:
    """The JSON-serialisable wire shape the UI preview consumes."""
    return {
        "kind": preview.kind,
        "name": preview.name,
        "format_version": preview.format_version,
        "app_version": preview.app_version,
        "exported_at": preview.exported_at,
        "stack": list(preview.stack),
        "custom_blocks": list(preview.custom_blocks),
        "block": preview.block,
        "warnings": list(preview.warnings),
    }
