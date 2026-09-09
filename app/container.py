"""DI container — ~80 lines, no third-party, 12 keys ( <150 )."""

import os
from datetime import datetime

from backend.config_manager import ConfigManager
from backend.cdp_client import CDPClient
from backend.user_memory import UserMemory
from backend.criteria_engine import CriteriaEngine
from backend.action_engine import ActionEngine
try:
    from bridge import Router as Bridge  # type: ignore
except Exception:  # noqa: BLE001
    from backend.bridge import Bridge  # type: ignore

from services.history_service import HistoryService
from services.media_service import MediaService
from services.db_service import DbService
from services.collector_service import CollectorService
from core.di import Container
from core.events import EventBus
from stores.atomic import AtomicJsonStore
from stores.settings_store import SettingsStore


def build_container(config: ConfigManager | None = None) -> Container:
    """Arrows: main -> bridge/router -> services(Result) -> stores(atomic)."""
    c = Container()
    cfg = config or ConfigManager()
    c.register_instance("config", cfg)
    c.register_instance("event_bus", EventBus())
    c.register("atomic_store", lambda cont: AtomicJsonStore(cfg._path if hasattr(cfg, "_path") else "config.json"))
    c.register("settings_store", lambda cont: SettingsStore(cont.resolve("atomic_store")))
    c.register("cdp", lambda cont: CDPClient(host=cont.resolve("config").get("chrome", "host", default="127.0.0.1"),
                                             port=cont.resolve("config").get("chrome", "port", default=9222)))

    def _memory_factory(cont: Container) -> UserMemory:
        legacy_queue = "chatbot.db"
        world_path = str(cont.resolve("config").get("history", "db_path", default="history.db"))
        queue_path = legacy_queue if os.path.exists(legacy_queue) else world_path
        return UserMemory(queue_path)

    c.register("memory", _memory_factory)
    c.register("criteria", lambda cont: CriteriaEngine())
    c.register("engine", lambda cont: ActionEngine(cdp=cont.resolve("cdp"),
                                                   memory=cont.resolve("memory"),
                                                   criteria=cont.resolve("criteria")))

    def _history_factory(cont: Container) -> HistoryService:
        return HistoryService(cdp=cont.resolve("cdp"), config=cont.resolve("config"),
                             session_id=datetime.now().strftime("%Y%m%d-%H%M%S"),
                             memory=cont.resolve("memory"))

    c.register("history_service", _history_factory)
    c.register("media_service", lambda cont: MediaService(cont.resolve("history_service")))
    c.register("db_service", lambda cont: DbService(cont.resolve("history_service")))
    c.register("collector_service", lambda cont: CollectorService(cont.resolve("history_service")))

    def _bridge_factory(cont: Container):  # type: ignore
        br = Bridge(cdp=cont.resolve("cdp"), memory=cont.resolve("memory"),
                    criteria=cont.resolve("criteria"), engine=cont.resolve("engine"),
                    config=cont.resolve("config"))
        hist = cont.resolve("history_service")
        try:
            br.attach_history(hist)
        except Exception:  # noqa: BLE001
            pass
        try:
            cont.resolve("engine").history = hist
        except Exception:  # noqa: BLE001
            pass
        return br

    c.register("bridge", _bridge_factory)
    return c
