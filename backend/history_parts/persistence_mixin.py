"""Persistence — app_settings + gaze (<150)."""
import asyncio, json, logging, os
from datetime import datetime
from .base import _merge, MAX_FILE_MB_DEFAULT
log = logging.getLogger("chatbot")
class HistoryPersistenceMixin:
    def _persist_app_settings(self) -> None:
        if not self.db.is_open: return
        stamp = datetime.now().isoformat(timespec="seconds")
        rows = [("my_nick", json.dumps(self.collector.my_nick or "")), ("media_max_file_mb", json.dumps(self._settings["media"].get("max_file_mb", MAX_FILE_MB_DEFAULT))), ("media_max_cache_mb", json.dumps(self._settings["media"].get("max_cache_mb", 200))), ("preview", json.dumps(self._settings.get("preview") or {}))]
        async def work():
            try:
                for k, v in rows: await self.db.execute("INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (k, v, stamp))
                await self.db.commit()
            except Exception as exc: log.debug("persist app settings failed: %s", exc)
        try: asyncio.get_running_loop().create_task(work())
        except RuntimeError: return
    async def load_app_settings(self) -> None:
        rows = await self.db.fetchdicts("SELECT key, value FROM app_settings"); data = {r["key"]: r["value"] for r in rows}
        m = dict(self._settings.get("media") or {}); p = dict(self._settings.get("preview") or {})
        try:
            if "my_nick" in data:
                n = json.loads(str(data["my_nick"])); 
                if isinstance(n, str): self.collector.configure(my_nick=n)
            if "media_max_file_mb" in data: m["max_file_mb"] = float(data["media_max_file_mb"])
            if "media_max_cache_mb" in data: m["max_cache_mb"] = float(data["media_max_cache_mb"])
            if "preview" in data:
                s = json.loads(str(data["preview"]))
                if isinstance(s, dict): p = _merge(p, s)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError): pass
        self._settings["media"] = m; self._settings["preview"] = p
        self.media.max_file_bytes = int(float(m.get("max_file_mb", MAX_FILE_MB_DEFAULT)) * 1024 * 1024); self.media.max_cache_bytes = int(float(m.get("max_cache_mb", 200)) * 1024 * 1024)
    async def seed_app_settings(self) -> None:
        have = {r["key"] for r in await self.db.fetchdicts("SELECT key FROM app_settings")}; stamp = datetime.now().isoformat(timespec="seconds"); m = self._settings.get("media") or {}
        rows = [("my_nick", json.dumps(self.collector.my_nick or "")), ("media_max_file_mb", json.dumps(m.get("max_file_mb", MAX_FILE_MB_DEFAULT))), ("media_max_cache_mb", json.dumps(m.get("max_cache_mb", 200))), ("preview", json.dumps(self._settings.get("preview") or {}))]
        for k, v in rows:
            if k in have: continue
            await self.db.execute("INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?)", (k, v, stamp))
        await self.db.commit()
    async def load_gaze(self) -> None:
        try: rows = await self.db.fetchdicts("SELECT key, value FROM gaze_data")
        except Exception as exc: log.debug("gaze load skipped: %s", exc); return
        data = {r["key"]: r["value"] for r in rows}
        if not data: return
        partner = str(data.get("partner") or "")
        if partner: self.collector._nick = partner
        for f in ("added", "total", "last_sync_added", "last_sync_count"):
            try: setattr(self.collector, "_" + f, int(data.get(f)))
            except (TypeError, ValueError): continue
        if data.get("last_sync_reason"): setattr(self.collector, "_last_sync_reason", str(data["last_sync_reason"]))
    async def save_gaze(self) -> None:
        if not self.db.is_open: return
        nick = str(getattr(self.collector, "_nick", "") or "")
        if not nick: return
        stamp = datetime.now().isoformat(timespec="seconds")
        rows = [("partner", nick), ("added", str(int(getattr(self.collector, "_added", 0) or 0))), ("total", str(int(getattr(self.collector, "_total", 0) or 0))), ("last_sync_reason", str(getattr(self.collector, "_last_sync_reason", "") or "")), ("last_sync_added", str(int(getattr(self.collector, "_last_sync_added", 0) or 0))), ("last_sync_count", str(int(getattr(self.collector, "_last_sync_count", 0) or 0)))]
        try:
            for k, v in rows: await self.db.execute("INSERT INTO gaze_data(key, value, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (k, v, stamp))
            await self.db.commit()
        except Exception as exc: log.debug("gaze save failed: %s", exc)
