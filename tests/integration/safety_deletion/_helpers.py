"""Independent local fixtures for AREA A safety-deletion tests.

Temp dirs, real SQLite, real DbManager/DbLifecycle. No import from
tests/conftest.py or other area fixtures. Fault injection only at explicit
boundaries (os.unlink, service methods, config.save, scans).
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.config_manager import ConfigManager  # noqa: E402
from services.db_service import DbManager  # noqa: E402
from services.history import HistoryService  # noqa: E402


async def wait_for(box, timeout=5.0):
    step, waited = 0.01, 0.0
    while not box and waited < timeout:
        await asyncio.sleep(step)
        waited += step
    return box


def make_config(tmpdir: str) -> ConfigManager:
    cfg = ConfigManager(os.path.join(tmpdir, "config.json"))
    media_cfg = dict(cfg.get("history", "media", default={}) or {})
    media_cfg["cache_dir"] = os.path.join(tmpdir, "saved_media")
    cfg.set("history", "media", media_cfg)
    return cfg


async def make_service(cfg: ConfigManager, db_path: str) -> HistoryService:
    svc = HistoryService(cdp=None, config=cfg, db_path=db_path)
    await svc.init()
    return svc


def make_manager(cfg, svc, root: str) -> DbManager:
    return DbManager(config=cfg, service=svc, root=root)


async def close_service(svc) -> None:
    try:
        await svc.close()
    except Exception:
        pass


def write_file(path: str, data: bytes = b"x") -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def read_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


async def insert_media_row(svc: HistoryService, url: str, cache_path: str,
                           owner: str = "Nick") -> None:
    """Insert one cached media row via the live service connection."""
    await svc.db.execute(
        "INSERT INTO media(url, state, cache_path, owner) VALUES(?,?,?,?)",
        (url, "cached", cache_path, owner))
    await svc.db.commit()


def insert_media_row_sync(db_path: str, url: str, cache_path: str,
                          owner: str = "Nick") -> None:
    """Insert via an independent sqlite3 connection (for non-active worlds)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO media(url, state, cache_path, owner) VALUES(?,?,?,?)",
            (url, "cached", cache_path, owner))
        conn.commit()
    finally:
        conn.close()


def fetch_media_rows_sync(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT url, cache_path FROM media")
        return list(cur.fetchall())
    finally:
        conn.close()


def count_rows_sync(db_path: str, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


class TempWorld:
    """Two-or-more real worlds in a temp dir with a live service on world A."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="safety_del_")
        self.cfg = make_config(self.dir)
        self.svc: HistoryService | None = None
        self.manager: DbManager | None = None
        self.world_a = os.path.join(self.dir, "history.db")
        self.world_b = ""
        self.world_c = ""

    async def setup(self, with_b: bool = True, with_c: bool = False):
        self.svc = await make_service(self.cfg, self.world_a)
        self.manager = make_manager(self.cfg, self.svc, self.dir)
        if with_b:
            res = await self.manager.create("work")
            assert res.get("ok"), res
            self.world_b = res["path"]
            # leave active on A for deterministic tests
            back = await self.manager.load(self.world_a)
            assert back.get("ok"), back
        if with_c:
            res = await self.manager.create("other")
            assert res.get("ok"), res
            self.world_c = res["path"]
            back = await self.manager.load(self.world_a)
            assert back.get("ok"), back
        return self

    async def teardown(self):
        if self.svc is not None:
            await close_service(self.svc)

    @property
    def media_base(self) -> str:
        assert self.manager is not None
        return os.path.abspath(self.manager.media_base_dir())

    def media_dir_for(self, world_path: str) -> str:
        assert self.manager is not None
        return os.path.abspath(self.manager.media_dir(world_path))
