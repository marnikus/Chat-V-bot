"""History query — merge helpers (H-C5 split)

Merge dicts and media/preview settings, ≤80 LOC.
"""

from __future__ import annotations

import copy
import json


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def _merge_media_settings(data: dict, media: dict) -> None:
    if "media_max_file_mb" in data:
        media["max_file_mb"] = float(data["media_max_file_mb"])
    if "media_max_cache_mb" in data:
        media["max_cache_mb"] = float(data["media_max_cache_mb"])


def _merge_preview_settings(data: dict, preview: dict) -> dict:
    if "preview" not in data:
        return preview
    stored = json.loads(str(data["preview"]))
    return _merge(preview, stored) if isinstance(stored, dict) else preview
