# 🧪 Core Layer Uncovered Design — Real Path Tests (No Fakes)

> **Rule:** Every assertion must verify a real behavior path (method call, identity, exception, contract satisfaction).  
> **Modules:** `core/result.py` (verify full branch), `core/interfaces.py` (full protocol contracts + fakes), integration (`di` + `events` + `result` + `interfaces` together).

---

## 1. Understand — What's Missing in `core/`

From matrix + `test_core_contracts.py` audit:

| Module | Covered by existing | Still missing |
|---|---|---|
| `core/result.py` | Starter (`test_core_logic_coverage.py`) + contracts | Verify all `Err` branches (unwrap raises message, unwrap_or, map pass-through, err()), generic `Result[int]` usage, frozen slots |
| `core/di.py` | `test_di.py` (9 tests) + contracts | Integration with events/result (dependency injection of event bus + result factory) |
| `core/events.py` | `test_events.py` (9 tests) + contracts | Integration with result (emit events carrying `Result` payloads); subscription snapshot with unsubscribe during emit already covered but can link to result |
| `core/interfaces.py` | Contracts test partial (only `FakeSettings` + 5 proto checks) | `BookmarkStoreProto`, `BlockStoreProto`, `SessionStoreProto`, `UndoStoreProto`, `PeopleRepoProto`, `UserRecordProto` — full fake implementations + method-level assertions; `runtime_checkable` verified with each |

---

## 2. Design — Specific Paths

### 2.1 `core/result.py` — Verify every branch (already 100% from starter; add integration layer)

- `Ok.unwrap()` → value; `Err.unwrap()` → raises with code + detail in message
- `Ok.map()` transforms; `Err.map()` identity preserved (not calling fn)
- `of()` 3 exception types + default code + success
- `aof()` async success + fail + default
- Generic `Result[int]` / `Result[str]` used at runtime
- Frozen slots prevent mutation
- Integration: `EventBus.emit(Result)` or `Container.get("handler")` returning `Result`

### 2.2 `core/interfaces.py` — Protocol Contract Paths

For each protocol, build a `DictBackedFake` that implements every method, then assert:
- `isinstance(fake, Protocol)` is `True` (`runtime_checkable`)
- Each method callable with correct args
- Method returns correct default type (list, dict, bool, None)
- Protocol method signatures match (no `TypeError` when calling)

Protocols to fully cover:
- `SettingsStoreProto` (already partial; complete with `section`, `set` with `save` flag)
- `PresetStoreProto` (all save/load/list/delete for stacks and templates)
- `BookmarkStoreProto` (`all`, `add`, `remove`)
- `BlockStoreProto` (`all`, `save`, `delete`)
- `SessionStoreProto` (`get` with default, `set` with `save` + `**updates`)
- `UndoStoreProto` (`load_state` returns tuple, `save_state` accepts list + int)
- `PeopleRepoProto` (`db_path`, async `get_all`, `get_queue`, `get_stats`)
- `UserRecordProto` (dataclass fields — assert attribute access)

### 2.3 Integration — Core Layer Together

- `Container` registers `EventBus` instance → `get("bus")` returns same object
- `Container` registers `Result.ok()` factory → `get("result_factory")` returns callable that produces `Ok`
- `EventBus.subscribe` handler that takes `Result` payload — emit `Result` through bus
- Protocol fake used inside container injection (e.g., `Container.register("store", FakeSettings)`)

---

## 3. Implementation Order

1. Design doc (this file) — done
2. `test_interfaces_full.py` — all protocol fakes + assertions
3. `test_core_integration.py` — container + bus + result + protocols together
4. Report — `reports/CORE_LAYER_COVERAGE_REPORT.md`
