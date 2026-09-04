"""Service container (DI) + QWebChannel wiring.

Everything the UI/worker/repos need hangs off one `Services` object —
no globals, easy to fake in tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWebChannel import QWebChannel

from ..bridge.api import ChatFlowApi
from ..bridge.signals import wire
from ..core.config import Settings
from ..core.logconf import setup_logging
from ..engine.worker import Worker
from ..memory.db import Database, SettingsRepo
from ..memory.repo_filters import FilterRuleRepo
from ..memory.repo_presets import PresetRepo
from ..memory.repo_status import StatusRepo
from ..memory.repo_users import UserRepo


@dataclass
class Services:
    settings: Settings
    settings_path: Path
    db: Database
    users: UserRepo
    status_repo: StatusRepo
    presets: PresetRepo
    filters: FilterRuleRepo
    app_settings: SettingsRepo
    worker: Worker
    api: ChatFlowApi
    window: object = None  # MainWindow, set after construction


def build_services(settings: Settings, data_root: Path) -> Services:
    settings.log_dir = str(data_root / "logs")
    setup_logging(settings.log_dir, settings.log_level, settings.retention_days)
    settings_path = data_root / "settings.json"
    settings = Settings.load(settings_path)
    db = Database(data_root / "chatflow.db")
    users = UserRepo(db)
    status_repo = StatusRepo(db)
    presets = PresetRepo(db)
    filters = FilterRuleRepo(db)
    filters.seed_defaults()
    worker = Worker(settings)
    sv = Services(settings, settings_path, db, users, status_repo, presets,
                  filters, SettingsRepo(db), worker, None)
    sv.api = ChatFlowApi(sv)
    return sv


def make_channel(sv: Services, webview) -> QWebChannel:
    channel = QWebChannel()
    channel.registerObject("chatflow", sv.api)
    webview.page().setWebChannel(channel)
    wire(sv.worker, sv.window, webview)
    return channel
