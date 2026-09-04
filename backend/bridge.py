"""QWebChannel bridge: JS ↔ Python."""
import asyncio, json, logging
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
    log_message = Signal(str, str)
    connection_status = Signal(str)
    stats_updated = Signal(str)
    tabs_received = Signal(str)
    presets_loaded = Signal(str)
    stack_loaded = Signal(str)

    def __init__(self, cdp, memory, criteria, engine, config, parent=None):
        super().__init__(parent)
        self._cdp, self._memory = cdp, memory
        self._criteria, self._engine = criteria, engine
        self._config, self._msg = config, ""
        cdp.connected.connect(lambda: self.connection_status.emit("connected"))
        cdp.disconnected.connect(lambda: self.connection_status.emit("disconnected"))
        cdp.error.connect(lambda e: self.connection_status.emit("error"))
        engine.step_complete.connect(self.step_complete.emit)
        engine.stack_complete.connect(self.stack_complete.emit)
        engine.log_msg.connect(lambda m: self.log_message.emit(m, "info"))

    @Slot(result=str)
    def get_tabs(self):
        asyncio.ensure_future(self._fetch_tabs())
        return "pending"

    async def _fetch_tabs(self):
        tabs = await self._cdp.fetch_tabs()
        data = [{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs]
        self.tabs_received.emit(json.dumps(data, ensure_ascii=False))
        auto = self._config.get("chrome", "auto_connect_url", default="")
        if auto and not self._cdp.is_connected:
            for t in tabs:
                if auto.lower() in t.url.lower():
                    self.log_message.emit(f"🔗 Auto-connect: {t.title}", "info")
                    await self._do_connect(t.ws_url)
                    return

    @Slot(str)
    def connect_tab(self, ws_url):
        asyncio.ensure_future(self._do_connect(ws_url))

    async def _do_connect(self, ws_url):
        if await self._cdp.connect(ws_url):
            self.log_message.emit("🔗 Connected", "info")
            await self._refresh_users()

    @Slot(str)
    def run_stack(self, sj):
        if self._engine.is_running:
            self.log_message.emit("⚠ Already running", "warn")
            return
        try:
            self._engine.load_stack(json.loads(sj))
        except json.JSONDecodeError:
            self.log_message.emit("❌ Bad JSON", "error")
            return
        from backend.scroll_parser import ScrollParser
        c = self._config
        sp = ScrollParser(cdp=self._cdp, criteria=self._criteria,
            viewport_sel=c.get("scroll", "viewport_selector",
                default="cdk-virtual-scroll-viewport.users-list-viewport"),
            scroll_dy=c.get("scroll", "scroll_delta_y", default=300),
            pause_ms=c.get("scroll", "scroll_pause_ms", default=800),
            stall_threshold=c.get("scroll", "stall_threshold", default=3),
            max_scrolls=c.get("scroll", "max_scrolls", default=50))
        asyncio.ensure_future(self._engine.execute(sp))

    @Slot()
    def stop_stack(self): self._engine.stop()
    @Slot()
    def pause_stack(self): self._engine.pause()
    @Slot()
    def resume_stack(self): self._engine.resume()
    @Slot(str)
    def save_message(self, t): self._msg = t
    @Slot(result=str)
    def get_message(self): return self._msg
    @Slot(result=str)
    def get_criteria(self): return self._criteria.to_json()

    @Slot(str)
    def save_criteria(self, j):
        self._criteria.load_json(j)
        self.log_message.emit("💾 Criteria saved", "info")

    @Slot()
    def reset_messaged(self): asyncio.ensure_future(self._do_mem(True))
    @Slot()
    def clear_memory(self): asyncio.ensure_future(self._do_mem(False))

    async def _do_mem(self, reset):
        if reset:
            c = await self._memory.reset_messaged()
            self.log_message.emit(f"🔄 Reset {c}", "info")
        else:
            c = await self._memory.clear_all()
            self.log_message.emit(f"🗑 Cleared {c}", "warn")
        await self._refresh_users()

    @Slot(result=str)
    def get_settings(self): return self._config.to_dict()

    @Slot(str)
    def save_settings(self, j):
        try:
            for sec, vals in json.loads(j).items():
                if isinstance(vals, dict):
                    for k, v in vals.items():
                        self._config.set(sec, k, v)
            self._config.save()
            self.log_message.emit("💾 Settings saved", "info")
        except Exception as e:
            self.log_message.emit(f"❌ {e}", "error")

    @Slot(str)
    def save_stack_preset(self, n): asyncio.ensure_future(self._preset_op("save", n))
    @Slot(str)
    def load_stack_preset(self, n): asyncio.ensure_future(self._preset_op("load", n))
    @Slot(str)
    def delete_stack_preset(self, n): asyncio.ensure_future(self._preset_op("del", n))
    @Slot()
    def get_preset_list(self): asyncio.ensure_future(self._preset_op("list", ""))
    @Slot(result=str)
    def get_stack_json(self): return json.dumps(self._engine.get_stack())

    async def _preset_op(self, op, name):
        import aiosqlite
        db = await aiosqlite.connect("chatbot.db")
        await db.execute("CREATE TABLE IF NOT EXISTS stacks ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, blocks TEXT,"
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        if op == "save":
            data = json.dumps(self._engine.get_stack(), ensure_ascii=False)
            await db.execute("INSERT OR REPLACE INTO stacks(name,blocks) VALUES(?,?)", (name, data))
            await db.commit(); await db.close()
            self.log_message.emit(f"💾 Preset: {name}", "info")
        elif op == "load":
            cur = await db.execute("SELECT blocks FROM stacks WHERE name=?", (name,))
            row = await cur.fetchone(); await db.close()
            if row:
                bl = json.loads(row[0])
                self._engine.load_stack(bl)
                self.stack_loaded.emit(json.dumps(bl, ensure_ascii=False))
                self.log_message.emit(f"📂 Loaded: {name} ({len(bl)} blocks)", "info")
            else:
                self.log_message.emit(f"❌ Not found: {name}", "error")
            return
        elif op == "del":
            await db.execute("DELETE FROM stacks WHERE name=?", (name,))
            await db.commit(); await db.close()
            self.log_message.emit(f"🗑 Deleted: {name}", "warn")
        else:
            cur = await db.execute(
                "SELECT name,blocks,created_at FROM stacks ORDER BY created_at DESC")
            rows = await cur.fetchall(); await db.close()
            ps = [{"name": r[0], "blocks": json.loads(r[1]), "created": r[2]} for r in rows]
            self.presets_loaded.emit(json.dumps(ps, ensure_ascii=False))
            return
        await self._preset_op("list", "")

    async def _refresh_users(self):
        users = await self._memory.get_all()
        self.users_updated.emit(json.dumps([{
            "nick": u.nick, "gender": u.gender,
            "registered": u.registered, "anonymous": u.anonymous,
            "guest": u.guest, "messaged": u.messaged,
            "first_seen": u.first_seen, "last_messaged": u.last_messaged
        } for u in users], ensure_ascii=False))
        self.stats_updated.emit(json.dumps(await self._memory.get_stats()))
