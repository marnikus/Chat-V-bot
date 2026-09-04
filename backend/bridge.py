"""QWebChannel bridge: routes calls between JS and Python backend."""
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

    def __init__(self, cdp, memory, criteria, engine, config, parent=None):
        super().__init__(parent)
        self._cdp, self._memory = cdp, memory
        self._criteria, self._engine = criteria, engine
        self._config, self._message_text = config, ""
        self._cdp.connected.connect(lambda: self.connection_status.emit("connected"))
        self._cdp.disconnected.connect(lambda: self.connection_status.emit("disconnected"))
        self._cdp.error.connect(lambda e: self.connection_status.emit("error"))
        self._engine.step_complete.connect(self.step_complete.emit)
        self._engine.stack_complete.connect(self.stack_complete.emit)
        self._engine.log_msg.connect(lambda m: self.log_message.emit(m, "info"))

    @Slot(result=str)
    def get_tabs(self):
        asyncio.ensure_future(self._fetch_tabs()); return "pending"

    async def _fetch_tabs(self):
        tabs = await self._cdp.fetch_tabs()
        self.tabs_received.emit(json.dumps([{"id":t.id,"title":t.title,"url":t.url,"ws_url":t.ws_url} for t in tabs], ensure_ascii=False))

    @Slot(str)
    def connect_tab(self, ws_url):
        asyncio.ensure_future(self._do_connect(ws_url))

    async def _do_connect(self, ws_url):
        if await self._cdp.connect(ws_url):
            self.log_message.emit("🔗 Connected", "info"); await self._refresh_users()

    @Slot(str)
    def run_stack(self, stack_json):
        if self._engine.is_running: self.log_message.emit("⚠ Already running","warn"); return
        try: blocks = json.loads(stack_json); self._engine.load_stack(blocks)
        except json.JSONDecodeError: self.log_message.emit("❌ Bad JSON","error"); return
        from backend.scroll_parser import ScrollParser
        sp = ScrollParser(cdp=self._cdp, criteria=self._criteria,
            viewport_sel=self._config.get("scroll","viewport_selector",
                default="cdk-virtual-scroll-viewport.users-list-viewport"),
            scroll_dy=self._config.get("scroll","scroll_delta_y",default=300),
            pause_ms=self._config.get("scroll","scroll_pause_ms",default=800),
            stall_threshold=self._config.get("scroll","stall_threshold",default=3),
            max_scrolls=self._config.get("scroll","max_scrolls",default=50))
        asyncio.ensure_future(self._engine.execute(sp))

    @Slot()
    def stop_stack(self): self._engine.stop()
    @Slot()
    def pause_stack(self): self._engine.pause()
    @Slot()
    def resume_stack(self): self._engine.resume()

    @Slot(str)
    def save_message(self, text): self._message_text = text
    @Slot(result=str)
    def get_message(self): return self._message_text

    @Slot(str)
    def save_criteria(self, j):
        self._criteria.load_json(j); self.log_message.emit("💾 Criteria saved","info")

    @Slot(result=str)
    def get_criteria(self): return self._criteria.to_json()

    @Slot()
    def reset_messaged(self): asyncio.ensure_future(self._do_reset())
    @Slot()
    def clear_memory(self): asyncio.ensure_future(self._do_clear())

    async def _do_reset(self):
        c = await self._memory.reset_messaged()
        self.log_message.emit(f"🔄 Reset {c} users","info"); await self._refresh_users()

    async def _do_clear(self):
        c = await self._memory.clear_all()
        self.log_message.emit(f"🗑 Cleared {c} users","warn"); await self._refresh_users()

    @Slot(result=str)
    def get_settings(self): return self._config.to_dict()

    @Slot(str)
    def save_settings(self, j):
        try:
            for sec, vals in json.loads(j).items():
                if isinstance(vals, dict):
                    for k, v in vals.items(): self._config.set(sec, k, v)
            self._config.save(); self.log_message.emit("💾 Settings saved","info")
        except Exception as e: self.log_message.emit(f"❌ Settings error: {e}","error")

    @Slot(str)
    def save_stack_preset(self, name): asyncio.ensure_future(self._save_preset(name))
    @Slot(str)
    def load_stack_preset(self, name): asyncio.ensure_future(self._load_preset(name))
    @Slot(result=str)
    def get_stack_json(self): return json.dumps(self._engine.get_stack())

    async def _save_preset(self, name):
        import aiosqlite
        db = await aiosqlite.connect("chatbot.db")
        await db.execute("CREATE TABLE IF NOT EXISTS stacks (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "name TEXT UNIQUE,blocks TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        await db.execute("INSERT OR REPLACE INTO stacks(name,blocks) VALUES(?,?)",
            (name, json.dumps(self._engine.get_stack(), ensure_ascii=False)))
        await db.commit(); await db.close()
        self.log_message.emit(f"💾 Preset saved: {name}","info")

    async def _load_preset(self, name):
        import aiosqlite
        db = await aiosqlite.connect("chatbot.db")
        cur = await db.execute("SELECT blocks FROM stacks WHERE name=?",(name,))
        row = await cur.fetchone(); await db.close()
        if row: self._engine.load_stack(json.loads(row[0])); self.log_message.emit(f"📂 Loaded: {name}","info")

    async def _refresh_users(self):
        users = await self._memory.get_all()
        self.users_updated.emit(json.dumps([{"nick":u.nick,"gender":u.gender,
            "registered":u.registered,"anonymous":u.anonymous,"guest":u.guest,
            "messaged":u.messaged,"first_seen":u.first_seen,"last_messaged":u.last_messaged}
            for u in users], ensure_ascii=False))
        self.stats_updated.emit(json.dumps(await self._memory.get_stats()))
