"""Sequence preset persistence (main thread)."""
from __future__ import annotations

import json

from ..core.models import Block, now_iso
from .db import Database


class PresetRepo:
    def __init__(self, db: Database):
        self._db = db

    def list(self) -> list[dict]:
        rows = self._db.query(
            "SELECT id, name, description, created_at, updated_at "
            "FROM presets ORDER BY name COLLATE NOCASE")
        return [dict(r) for r in rows]

    def get(self, name: str) -> dict | None:
        rows = self._db.query(
            "SELECT * FROM presets WHERE name=?", (name,))
        if not rows:
            return None
        r = rows[0]
        return {"id": r["id"], "name": r["name"], "description": r["description"],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
                "blocks": json.loads(r["blocks_json"])}

    def save(self, name: str, description: str, blocks: list[dict]) -> dict:
        ts = now_iso()
        existing = self.get(name)
        payload = json.dumps(blocks, ensure_ascii=False)
        if existing:
            self._db.execute(
                "UPDATE presets SET description=?, blocks_json=?, updated_at=? "
                "WHERE id=?", (description, payload, ts, existing["id"]))
        else:
            self._db.execute(
                "INSERT INTO presets(name, description, blocks_json, created_at, updated_at) "
                "VALUES(?,?,?,?,?)", (name, description, payload, ts, ts))
        return {"ok": True, "name": name}

    def delete(self, name: str) -> dict:
        self._db.execute("DELETE FROM presets WHERE name=?", (name,))
        return {"ok": True}

    @staticmethod
    def blocks_to_dicts(blocks: list[Block]) -> list[dict]:
        return [b.to_dict() for b in blocks]
