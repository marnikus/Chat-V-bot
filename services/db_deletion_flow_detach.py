"""Switch and detach phases of the deletion flow (family file 2).

Phase 3 moves the active-world pointer off the victim when it was
active; phase 4 detaches lingering live handles (the service DB and the
user-memory store). Verbatim moves out of ``services.db_deletion_flow``
(Round G3, RULE 18); only the orchestrator seam imports this module.
"""

from __future__ import annotations

import asyncio
import os

from services.db_deletion_flow_state import raise_refusal

# ── phase 3: switch (only when the victim was active) ───────────────

async def _switch(lifecycle, st) -> None:
    if not (st.was_active and lifecycle._service is not None):
        return
    fallback = lifecycle._pick_fallback(st.target)
    if not fallback:
        raise_refusal(st, "switch", "no other database to switch to")
    try:
        opened = await lifecycle._load_unlocked(fallback)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise_refusal(st, "switch", str(exc) or "cannot switch away")
    if not (opened or {}).get("ok"):
        raise_refusal(
            st, "switch",
            str((opened or {}).get("error", "cannot switch away")))
    st.world_changed = True


# ── phase 4: detach lingering handles on the victim ─────────────────

async def _detach(lifecycle, st) -> None:
    service = lifecycle._service
    if service is None:
        return
    await _detach_service_db(st, service)
    memory = getattr(service, "memory", None)
    if memory is not None:
        await _close_memory(st, memory)


async def _detach_service_db(st, service) -> None:
    try:
        svc_path = os.path.abspath(service.db.path)
    except Exception:  # noqa: BLE001
        svc_path = ""
    if svc_path and svc_path == st.target_abs:
        try:
            await service.detach_db()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise_refusal(st, "detach", str(exc))
        # Detaching changes live state → refresh required.
        st.world_changed = True


async def _close_memory(st, memory) -> None:
    try:
        mem_path = os.path.abspath(
            getattr(memory, "db_path", "") or "")
    except Exception:  # noqa: BLE001
        mem_path = ""
    if mem_path and mem_path == st.target_abs:
        try:
            await memory.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise_refusal(st, "detach", str(exc))
