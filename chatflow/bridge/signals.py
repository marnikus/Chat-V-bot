"""Worker -> UI event forwarding (main thread).

One channel in each direction:
  JS  -> Python : ChatFlowApi slots (bridge/api*.py)
  Python -> JS  : worker.event signal -> webview.call_js("onEvent", json)
"""
from __future__ import annotations

from .util import jdump

# events mirrored to the native status bar
_STATUS_LABELS = {"IDLE": "Ready", "CONNECTING": "Connecting…",
                  "RUNNING": "Running", "PAUSED": "Paused",
                  "STOPPING": "Stopping…", "ERROR": "Error",
                  "DEGRADED": "Connection lost"}


def wire(worker, window, webview) -> None:
    def forward(name: str, payload) -> None:
        try:
            webview.call_js("onEvent", jdump({"name": name, "payload": payload}))
        except Exception:  # noqa: BLE001 — UI push must never crash the app
            pass
        mirror_to_status_bar(window, name, payload)

    worker.event.connect(forward)


def mirror_to_status_bar(window, name: str, payload) -> None:
    if name == "status":
        state = (payload or {}).get("state", "")
        window.set_status(_STATUS_LABELS.get(state, state))
    elif name in ("users_found", "users_counted", "message_sent"):
        try:
            window.set_counts(window.sv.users.counts())
        except Exception:  # noqa: BLE001
            pass
    elif name == "connection_lost":
        window.set_status("Connection lost — reconnect?")
    elif name == "test_result":
        if (payload or {}).get("ok"):
            detail = "chat tab found" if payload.get("chat_tab_found") else "no tab matched"
            window.set_status(f"Test: OK — {payload.get('pages', 0)} pages, {detail}")
        else:
            window.set_status("Test: FAIL — " + str(payload.get("error", "?"))[:90])
