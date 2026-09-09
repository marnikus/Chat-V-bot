"""HistoryBridge — Person History / User Database (async, Result-wrapped)."""
from __future__ import annotations
import asyncio, json, logging
from PySide6.QtCore import QObject, Signal, Slot
try:
    from qasync import asyncSlot
except Exception:
    asyncSlot = lambda *a, **kw: (lambda f: f)
log = logging.getLogger("chatbot")
class HistoryBridge(QObject):
    history_page_ready = Signal(str, str)
    history_search_ready = Signal(str, str)
    history_stats_ready = Signal(str, str)
    userdb_page_ready = Signal(str, str)
    userdb_changed = Signal(str)
    history_error = Signal(str, str)
    log_message = Signal(str, str)
    media_ready = Signal(str, str)
    def __init__(self, ctx: dict, parent=None):
        super().__init__(parent)
        self._history = None
        self._config = ctx.get("config")
        self._memory = ctx.get("memory")
    def attach_history(self, service):
        self._history = service
        if service and hasattr(service, "collector"):
            try: service.collector.history_appended.connect(lambda p: self.userdb_changed.emit(p))
            except Exception: pass
    @property
    def _archive(self): return self._history
    def _need(self, scope, req_id=""):
        if self._history is None:
            self.history_error.emit(scope, "archive not running"); return False
        return True
    def _run(self, scope, coro):
        async def guarded():
            try: await coro
            except Exception as exc:  # noqa: BLE001
                log.warning("archive %s failed: %s", scope, exc)
                self.history_error.emit(scope, str(exc))
        try: asyncio.ensure_future(guarded())
        except RuntimeError: coro.close()
    @Slot(str, str, str)
    def history_open(self, req_id, nick, options_json):
        if not self._need("history_open"): return
        opts=json.loads(options_json or "{}") if options_json else {}
        self._run("history_open", self._page(req_id, nick, opts))
    @Slot(str, str, str)
    def history_page(self, req_id, nick, anchor_json):
        if not self._need("history_page"): return
        opts=json.loads(anchor_json or "{}") if anchor_json else {}
        self._run("history_page", self._page(req_id, nick, opts))
    async def _page(self, req_id, nick, opts):
        svc=self._history
        limit=int(opts.get("limit") or svc.preview_settings().get("page_size",50))
        if opts.get("around") is not None:
            payload=await svc.query.around(nick,int(opts["around"]),radius=int(opts.get("radius") or 25))
            payload["stats"]=await svc.query.person_stats(nick); payload["my_nick"]=svc.my_nick
        else:
            payload=await svc.page(nick, before_ord=(int(opts["before_ord"]) if opts.get("before_ord") is not None else None), after_ord=(int(opts["after_ord"]) if opts.get("after_ord") is not None else None), limit=limit)
        payload["req_id"]=req_id; payload["preview"]=svc.preview_settings()
        self.history_page_ready.emit(req_id, json.dumps(payload, ensure_ascii=False))
    @Slot(str, str)
    def history_search(self, req_id, query_json):
        if not self._need("history_search"): return
        opts=json.loads(query_json or "{}") if query_json else {}
        self._run("history_search", self._search(req_id, opts))
    async def _search(self, req_id, opts):
        svc=self._history; q=str(opts.get("q") or opts.get("query") or ""); limit=int(opts.get("limit") or 100)
        if str(opts.get("scope") or "person")=="person":
            payload=await svc.query.search_person(str(opts.get("nick") or ""), q, limit=limit, offset=int(opts.get("offset") or 0)); payload["scope"]="person"
        else:
            payload=await svc.query.search_global(q, limit=limit); payload["scope"]="global"
        payload["req_id"]=req_id
        self.history_search_ready.emit(req_id, json.dumps(payload, ensure_ascii=False))
    @Slot(str, str)
    def history_stats(self, req_id, nick):
        if not self._need("history_stats"): return
        async def work():
            payload=await self._history.query.person_stats(nick); payload["req_id"]=req_id
            self.history_stats_ready.emit(req_id, json.dumps(payload, ensure_ascii=False))
        self._run("history_stats", work())
    @Slot(str, str)
    def userdb_page(self, req_id, query_json):
        if not self._need("userdb_page"): return
        opts=json.loads(query_json or "{}") if query_json else {}
        async def work():
            payload=await self._history.query.list_persons(q=str(opts.get("q") or ""), limit=int(opts.get("limit") or 50), offset=int(opts.get("offset") or 0), sort=str(opts.get("sort") or "recent"))
            payload["req_id"]=req_id; payload["my_nick"]=self._history.my_nick
            self.userdb_page_ready.emit(req_id, json.dumps(payload, ensure_ascii=False))
        self._run("userdb_page", work())
    @Slot(str)
    def userdb_stats(self, req_id):
        if not self._need("userdb_stats"): return
        async def work():
            payload=await self._history.query.db_stats(); payload["req_id"]=req_id
            payload.update(await self._history.media.cache_usage())
            self.userdb_page_ready.emit(req_id, json.dumps(payload, ensure_ascii=False))
        self._run("userdb_stats", work())
    @Slot(str, bool, result=bool)
    def history_delete_person(self, nick, hard=False):
        nick=" ".join(str(nick or "").split()).strip()
        if not nick or self._history is None: return False
        async def work():
            repo=self._history.repo; token=repo.new_op_token()
            ok=await repo.delete_person(nick, hard=bool(hard), token=token)
            self.userdb_changed.emit(json.dumps({"action":"deleted","nick":nick,"hard":bool(hard),"ok":ok},ensure_ascii=False))
        self._run("delete_person", work()); return True
    @Slot(str, result=bool)
    def history_clear_person(self, nick):
        nick=" ".join(str(nick or "").split()).strip()
        if not nick or self._history is None: return False
        async def work():
            token=await self._history.repo.soft_delete_history(nick)
            self.userdb_changed.emit(json.dumps({"action":"cleared","nick":nick,"ok":bool(token)},ensure_ascii=False))
        self._run("clear_person", work()); return True
    @Slot(str, str, result=bool)
    def history_delete_message(self, nick, message_id):
        nick=" ".join(str(nick or "").split()).strip()
        try: mid=int(str(message_id or "0").strip() or 0)
        except: mid=0
        if not nick or mid<=0 or self._history is None: return False
        async def work():
            token=await self._history.repo.soft_delete_message(nick, mid)
            self.userdb_changed.emit(json.dumps({"action":"message_deleted","nick":nick,"id":mid},ensure_ascii=False))
        self._run("delete_message", work()); return True
