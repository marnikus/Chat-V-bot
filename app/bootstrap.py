from __future__ import annotations

import os
from datetime import datetime

from backend.cdp_client import CDPClient
from backend.config_manager import ConfigManager
from backend.criteria_engine import CriteriaEngine
from backend.bridge import Bridge
from core.di import Container
from core.events import EventBus
from services.history import HistoryService
from services.run import ActionEngine
from stores.user_memory import UserMemory


def queue_path(config: ConfigManager) -> str:
    legacy = "chatbot.db"
    world = str(config.get("history", "db_path", default="history.db"))
    return legacy if os.path.exists(legacy) else world


def create_container() -> Container:
    container = Container()
    container.register("config", lambda _c: ConfigManager())
    container.register("bus", lambda _c: EventBus())
    container.register("cdp", lambda c: CDPClient(
        host=c.get("config").get("chrome", "host", default="127.0.0.1"),
        port=c.get("config").get("chrome", "port", default=9222)))
    container.register("memory", lambda c: UserMemory(queue_path(c.get("config"))))
    container.register("criteria", lambda _c: CriteriaEngine())
    container.register("engine", lambda c: ActionEngine(
        cdp=c.get("cdp"), memory=c.get("memory"), criteria=c.get("criteria"),
        bus=c.get("bus")))
    container.register("history", lambda c: HistoryService(
        cdp=c.get("cdp"), config=c.get("config"),
        session_id=datetime.now().strftime("%Y%m%d-%H%M%S"),
        memory=c.get("memory")))
    container.register("bridge", lambda c: Bridge(
        cdp=c.get("cdp"), memory=c.get("memory"), criteria=c.get("criteria"),
        engine=c.get("engine"), config=c.get("config")))
    return container
