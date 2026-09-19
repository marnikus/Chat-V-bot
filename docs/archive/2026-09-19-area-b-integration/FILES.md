# Area B integrated file map — 2026-09-19

| Responsibility | Files |
|---|---|
| Pure payload policy | `bridge/wire_codec.py`, `bridge/wire_db.py`, `bridge/wire_undo.py` |
| QObject adaptation | `bridge/people_bridge.py`, `bridge/history_bridge.py`, `bridge/db_bridge.py`, `bridge/undo_bridge.py` |
| Scheduler and gate | `core/scheduler.py`, `services/world_events.py` |
| Reporting policy | `core/announcer.py`, shared intent constant in `services/undo_apply.py` |
| Wire inventory and diagnostics | `tools/wire_schema.py`, `ui/js/wire-schema.json`, `ui/js/wire_schema.js` |
| Pure and real Qt tests | `tests/unit/bridge_wire/test_{codec,policy,scheduler,qt_free,qt_smoke}.py` |
| Node tests | `tests/test_wire_schema_js.js` |
| Test classification | `pytest.ini`, `tests/conftest.py` |
| Real delete-guard regression | `tests/integration/services/test_services_undo_gaps.py` |
| Quality ownership and narrowed clone inventory | `tools/metrics/rule16_gate.py` |
| Design and verification | This archive, `reports/AREA_B_TRANSFER_2026-09-19.md` |
| Current documentation | `docs/README.md`, `docs/archive/README.md`, `docs/current/SYSTEM_OF_RECORD.md` |

The source manifest's file count is not an integration constraint: existing part
modules were preserved, and test/quality/doc changes are included explicitly.
