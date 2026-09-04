"""QWebChannel bridge: routes calls between JS and Python backend."""
import asyncio, json, logging, sqlite3
from PySide6.QtCore import QObject, Signal, Slot
from backend.cdp_client import CDPClient
from backend.user_memory import UserMemory
from backend.criteria_engine import CriteriaEngine
from backend.action_engine import ActionEngine
from backend.config_manager import ConfigManager
log = logging.getLogger("chatbot")


class Bridge(QObject):
    users_updated = Signal(str)
    step_complete = Signal(str, str)
    stack_complete = Signal()
    stack_loaded = Signal(str)
    stack_presets_updated = Signal(str)
    log_message = Signal(str, str)
    connection_status = Signal(str)
    stats_updated = Signal(str)
    tabs_received = Signal(str)
    url_presets_updated = Signal(str)
    finder_presets_updated = Signal(str)

    def __init__(self, cdp, memory, criteria, engine, config, parent=None):
        super().__init__(parent)
        self._cdp, self._memory = cdp, memory
        self._criteria, self._engine = criteria, engine
        self._config, self._message_text = config, ""
        self._db_path = "chatbot.db"
        self._ensure_preset_tables()
        self._cdp.connected.connect(lambda: self.connection_status.emit("connected"))
        self._cdp.disconnected.connect(lambda: self.connection_status.emit("disconnected"))
        self._cdp.error.connect(lambda e: self.connection_status.emit("error"))
        self._engine.step_complete.connect(self.step_complete.emit)
        self._engine.stack_complete.connect(self.stack_complete.emit)
        self._engine.log_msg.connect(lambda m: self.log_message.emit(m, "info"))

    # ── sqlite preset helpers ────────────────────────────────────
    def _ensure_preset_tables(self) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            have_finder = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='finder_presets'"
            ).fetchone()[0] > 0
            conn.execute(
                "CREATE TABLE IF NOT EXISTS stacks ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, "
                "blocks TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS finder_presets ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, "
                "config TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            if not have_finder:
                conn.execute(
                    "INSERT INTO finder_presets(name, config) VALUES(?,?)",
                    ("Find Main Tab", json.dumps({
                        "name": "Find Main Tab",
                        "selector": "div[role='tab'].tab-item",
                        "child_selector": "p.chat-title",
                        "text": "",
                        "click": True,
                        "click_index": 0,
                        "pre_delay_ms": 300,
                    }, ensure_ascii=False)))
            conn.commit()
            conn.close()
        except Exception as e:
            log.error("Preset table init failed: %s", e)

    @staticmethod
    def _close(conn):
        try:
            conn.close()
        except Exception:
            pass

    # ── tabs ─────────────────────────────────────────────────────
    @Slot(result=str)
    def get_tabs(self):
        asyncio.ensure_future(self._fetch_tabs()); return "pending"

    async def _fetch_tabs(self):
        tabs = await self._cdp.fetch_tabs()
        self.tabs_received.emit(json.dumps([{"id": t.id, "title": t.title, "url": t.url,
                                             "ws_url": t.ws_url} for t in tabs],
                                           ensure_ascii=False))

    @Slot(str)
    def connect_tab(self, ws_url):
        asyncio.ensure_future(self._do_connect(ws_url))

    async def _do_connect(self, ws_url):
        if await self._cdp.connect(ws_url):
            self.log_message.emit("🔗 Connected", "info"); await self._refresh_users()

    # ── stack execution ──────────────────────────────────────────
    @Slot(str)
    def run_stack(self, stack_json):
        if self._engine.is_running:
            self.log_message.emit("⚠ Already running", "warn"); return
        try:
            blocks = json.loads(stack_json)
            if not isinstance(blocks, list):
                self.log_message.emit("❌ Stack JSON must be an array", "error"); return
            self._engine.load_stack(blocks)
        except json.JSONDecodeError:
            self.log_message.emit("❌ Bad JSON", "error"); return
        from backend.scroll_parser import ScrollParser
        sp = ScrollParser(cdp=self._cdp, criteria=self._criteria,
            viewport_sel=self._config.get("scroll", "viewport_selector",
                default="cdk-virtual-scroll-viewport.users-list-viewport"),
            scroll_dy=self._config.get("scroll", "scroll_delta_y", default=300),
            pause_ms=self._config.get("scroll", "scroll_pause_ms", default=800),
            stall_threshold=self._config.get("scroll", "stall_threshold", default=3),
            max_scrolls=self._config.get("scroll", "max_scrolls", default=50))
        asyncio.ensure_future(self._engine.execute(sp))

    @Slot()
    def stop_stack(self): self._engine.stop()
    @Slot()
    def pause_stack(self): self._engine.pause()
    @Slot()
    def resume_stack(self): self._engine.resume()

    @Slot(result=str)
    def get_stack_json(self): return json.dumps(self._engine.get_stack(), ensure_ascii=False)

    # ── stack presets (full action stack list) ─────────────────────
    @Slot(str, str)
    def save_stack_preset(self, name, stack_json):
        name = (name or "").strip()
        if not name:
            self.log_message.emit("❌ Preset name is empty", "error"); return
        try:
            blocks = json.loads(stack_json)
            if not isinstance(blocks, list):
                raise ValueError("blocks must be an array")
            self._engine.load_stack(blocks)  # keep engine + UI in sync
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT INTO stacks(name, blocks) VALUES(?,?) "
                "ON CONFLICT(name) DO UPDATE SET blocks=excluded.blocks",
                (name, json.dumps(blocks, ensure_ascii=False)))
            conn.commit(); self._close(conn)
            self.stack_presets_updated.emit(self.list_stack_presets())
            self.log_message.emit(f"💾 Stack preset saved: {name} "
                                  f"({len(blocks)} blocks)", "info")
        except Exception as e:
            self.log_message.emit(f"❌ Save stack preset error: {e}", "error")

    @Slot(result=str)
    def list_stack_presets(self):
        try:
            conn = sqlite3.connect(self._db_path)
            cur = conn.execute("SELECT name, blocks FROM stacks ORDER BY name")
            rows = cur.fetchall(); self._close(conn)
            out = []
            for name, blocks in rows:
                arr = json.loads(blocks) if isinstance(blocks, str) else []
                out.append({"name": name, "block_count": len(arr), "blocks": arr})
            return json.dumps(out, ensure_ascii=False)
        except Exception as e:
            log.error("List stack presets error: %s", e)
            return json.dumps([])

    @Slot(str)
    def load_stack_preset(self, name):
        try:
            conn = sqlite3.connect(self._db_path)
            cur = conn.execute("SELECT blocks FROM stacks WHERE name=?", (name,))
            row = cur.fetchone(); self._close(conn)
            if not row:
                self.log_message.emit(f"❌ Stack preset not found: {name}", "error")
                return
            blocks = json.loads(row[0])
            self._engine.load_stack(blocks)
            self.stack_loaded.emit(json.dumps(blocks, ensure_ascii=False))
            self.log_message.emit(f"📂 Loaded stack preset: {name} "
                                  f"({len(blocks)} blocks)", "info")
        except Exception as e:
            self.log_message.emit(f"❌ Load stack preset error: {e}", "error")

    @Slot(str)
    def delete_stack_preset(self, name):
        try:
            conn = sqlite3.connect(self._db_path)
            cur = conn.execute("DELETE FROM stacks WHERE name=?", (name,))
            conn.commit(); self._close(conn)
            self.stack_presets_updated.emit(self.list_stack_presets())
            self.log_message.emit(f"🗑 Deleted stack preset: {name}", "warn")
        except Exception as e:
            self.log_message.emit(f"❌ Delete stack preset error: {e}", "error")

    # ── element / finder presets ───────────────────────────────────
    @Slot(str, str)
    def save_finder_preset(self, name, data_json):
        name = (name or "").strip()
        if not name:
            self.log_message.emit("❌ Element preset name is empty", "error"); return
        try:
            config = json.loads(data_json)
            if not isinstance(config, dict):
                raise ValueError("config must be an object")
            config["name"] = config.get("name") or name
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT INTO finder_presets(name, config) VALUES(?,?) "
                "ON CONFLICT(name) DO UPDATE SET config=excluded.config",
                (name, json.dumps(config, ensure_ascii=False)))
            conn.commit(); self._close(conn)
            self.finder_presets_updated.emit(self.list_finder_presets())
            self.log_message.emit(f"💾 Element preset saved: {name}", "info")
        except Exception as e:
            self.log_message.emit(f"❌ Save element preset error: {e}", "error")

    @Slot(result=str)
    def list_finder_presets(self):
        try:
            conn = sqlite3.connect(self._db_path)
            cur = conn.execute("SELECT name, config FROM finder_presets ORDER BY name")
            rows = cur.fetchall(); self._close(conn)
            out = []
            for name, cfg in rows:
                data = json.loads(cfg) if isinstance(cfg, str) else {}
                out.append({"name": name, "config": data})
            return json.dumps(out, ensure_ascii=False)
        except Exception as e:
            log.error("List finder presets error: %s", e)
            return json.dumps([])

    @Slot(result=str)
    def get_finder_preset(self, name):
        try:
            conn = sqlite3.connect(self._db_path)
            cur = conn.execute("SELECT config FROM finder_presets WHERE name=?", (name,))
            row = cur.fetchone(); self._close(conn)
            if not row:
                self.log_message.emit(f"❌ Element preset not found: {name}", "error")
                return json.dumps({})
            return row[0] if isinstance(row[0], str) else json.dumps({})
        except Exception as e:
            self.log_message.emit(f"❌ Get element preset error: {e}", "error")
            return json.dumps({})

    @Slot(str)
    def delete_finder_preset(self, name):
        try:
            conn = sqlite3.connect(self._db_path)
            cur = conn.execute("DELETE FROM finder_presets WHERE name=?", (name,))
            conn.commit(); self._close(conn)
            self.finder_presets_updated.emit(self.list_finder_presets())
            self.log_message.emit(f"🗑 Deleted element preset: {name}", "warn")
        except Exception as e:
            self.log_message.emit(f"❌ Delete element preset error: {e}", "error")
    # ── URL presets (tab auto-select by URL) ───────────────────────
    def _get_url_presets(self) -> list[dict]:
        value = self._config.get("url_presets", default=[])
        if isinstance(value, list):
            return [p for p in value
                    if isinstance(p, dict) and p.get("name") and p.get("pattern")]
        return []

    @Slot(result=str)
    def get_url_presets(self):
        return json.dumps(self._get_url_presets(), ensure_ascii=False)

    @Slot(str, str)
    def save_url_preset(self, name, pattern):
        name = (name or "").strip(); pattern = (pattern or "").strip()
        if not name or not pattern:
            self.log_message.emit("❌ URL preset needs a name and pattern", "error")
            return
        presets = self._get_url_presets()
        presets = [p for p in presets if p.get("name") != name]
        presets.append({"name": name, "pattern": pattern})
        self._config.set("url_presets", presets)
        self._config.save()
        self.url_presets_updated.emit(json.dumps(presets, ensure_ascii=False))
        self.log_message.emit(f"💾 URL preset saved: {name} → {pattern}", "info")

    @Slot(str)
    def delete_url_preset(self, name):
        presets = self._get_url_presets()
        presets = [p for p in presets if p.get("name") != name]
        self._config.set("url_presets", presets)
        self._config.save()
        self.url_presets_updated.emit(json.dumps(presets, ensure_ascii=False))
        self.log_message.emit(f"🗑 Deleted URL preset: {name}", "warn")

    # ── message / criteria ────────────────────────────────────────
    @Slot(str)
    def save_message(self, text): self._message_text = text
    @Slot(result=str)
    def get_message(self): return self._message_text

    @Slot(str)
    def save_criteria(self, j):
        self._criteria.load_json(j); self.log_message.emit("💾 Criteria saved", "info")

    @Slot(result=str)
    def get_criteria(self): return self._criteria.to_json()

    @Slot()
    def reset_messaged(self): asyncio.ensure_future(self._do_reset())
    @Slot()
    def clear_memory(self): asyncio.ensure_future(self._do_clear())

    async def _do_reset(self):
        c = await self._memory.reset_messaged()
        self.log_message.emit(f"🔄 Reset {c} users", "info"); await self._refresh_users()

    async def _do_clear(self):
        c = await self._memory.clear_all()
        self.log_message.emit(f"🗑 Cleared {c} users", "warn"); await self._refresh_users()

    # ── settings ──────────────────────────────────────────────────
    @Slot(result=str)
    def get_settings(self): return self._config.to_dict()

    @Slot(str)
    def save_settings(self, j):
        try:
            for sec, vals in json.loads(j).items():
                if isinstance(vals, dict):
                    for k, v in vals.items():
                        self._config.set(sec, k, v)
            self._config.save(); self.log_message.emit("💾 Settings saved", "info")
        except Exception as e:
            self.log_message.emit(f"❌ Settings error: {e}", "error")

    async def _refresh_users(self):
        users = await self._memory.get_all()
        self.users_updated.emit(json.dumps([{"nick": u.nick, "gender": u.gender,
            "registered": u.registered, "anonymous": u.anonymous, "guest": u.guest,
            "messaged": u.messaged, "first_seen": u.first_seen,
            "last_messaged": u.last_messaged} for u in users], ensure_ascii=False))
        self.stats_updated.emit(json.dumps(await self._memory.get_stats()))
