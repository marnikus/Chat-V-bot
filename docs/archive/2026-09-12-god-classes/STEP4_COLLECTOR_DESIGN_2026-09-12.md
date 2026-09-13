# Step 4 — extract the `Collector` god class into `services/collector/`

Done 2026-09-12. Target: the round plan's step 4 — `services/collector_service.py`
(**593 LOC**, one `Collector(QObject)` class with **39 methods / 518 LOC of class
body, LCOM\* 0.93**). The plan's success metric: *class 518/39 → ≤150/≤15*.

## Why it is one step

`Collector` is the least-cohesive god class in the tree (LCOM\* 0.93 — its 39
methods share almost no state). It already lost its heartbeat body to
`services/collector_tick.py` in the AREA C round, so what remains is five
clearly separable jobs:

* **lifecycle** — start/stop/pause/resume, reset-on-db-swap, run throttling,
  probe-duration backoff, the heartbeat interval;
* **heartbeat** — the `run` loop and the `tick` gate (which delegates to
  `collector_tick`);
* **live push** — the in-page observer channel (`handle_push` and its gate,
  append, announce, payload/record normalisation);
* **archive** — `_sync`, `_remember_partner`, manual backfill, the refuse/gate
  helpers;
* **status** — the JSON status payload, the emit dedup, the log and
  people-changed signals.

The class is a §16.5 landmine (pinned behaviour-by-behaviour by
`tests/test_collector_state.py`, `tests/test_collector_gaps.py`,
`tests/test_collector_tick_phases.py`, `tests/test_recollect_after_clear.py`,
`tests/test_media_recovery_e2e.py`), so the split is a pure relocation: every
method body is copied verbatim, and the emitted status payloads stay
byte-identical.

## The seam to preserve (the one risk)

Three importers read the collector through `services.collector_service`:

* `services/history/__init__.py` — `from services.collector_service import Collector, DEFAULTS as COLLECTOR_DEFAULTS`;
* `backend/collector.py` — the compat shim `from services.collector_service import Collector, CollectorState, DEFAULTS`;
* `services/collector_tick.py` — `from services.collector_service import CollectorState`.

`services/collector_service.py` therefore becomes a 3-line re-export shim over
the new `services/collector/` package, so none of those importers changes.
`collector_tick` mutates the host (`host._settings`, `host._nick`,
`host._gate_status`, `host._refuse`, `host._sync`, `host._no_new_text`,
`host._set`, `host._notify_appended`, …) — every name stays on the `Collector`
instance via the mixins' MRO, so the tick state machine is untouched.

The stores-import invariant (`tests/unit/stores/test_stores_public_api.py`,
count 42) is preserved: `HistoryRepo` (facade type hint) and `UserRecord`
(archive mixin) are the same two `from stores` lines, relocated; the dead
`UserMemory` docstring import is dropped (no line added or lost).

## The split

| Module | Owns | Methods | LOC |
|---|---|---:|---:|
| `constants.py` | `CollectorState`, `IDLE_STATES`, `DEFAULTS`, `MAX_PROBE_PENALTY` | — | ~50 |
| `lifecycle.py` | `LifecycleMixin`: start/stop/pause/resume, reset, throttle, backoff, interval | 10 | ~130 |
| `heartbeat.py` | `HeartbeatMixin`: `run`, `tick`, `_tick` | 3 | ~55 |
| `push.py` | `PushMixin`: `handle_push` + gate/append/announce/payload/records | 7 | ~110 |
| `archive.py` | `ArchiveMixin`: `_sync`, `_remember_partner`, `backfill_older`, `_refuse`, `_gate_status` | 5 | ~110 |
| `status.py` | `StatusMixin`: `_log`, `_notify_people`, `state_payload`, `_no_new_text`, `_set`, `_emit` | 6 | ~90 |
| `collector.py` | `Collector(QObject, …)` facade: signals, `__init__`, `configure`, `settings`, 5 properties | 8 | ~110 |
| `__init__.py` | frozen seam re-exports | — | ~10 |

`Collector` composes the five mixins; the mixins own no state and never import
`collector.py`, so the facade is the only module that imports them (the
`services/run/` and `backend/scroll_parser/` precedent).

## Rejected dishonest reductions

* **Keeping `collector_service.py` as the facade and only adding sibling
  mixin modules** was rejected: the `services/run/` precedent puts the facade
  inside its package with `__init__` re-exporting, and a package is the only
  honest way to meet "class ≤150 / ≤15" without scattering half the class
  across bare `services/` modules.
* **Folding lifecycle + heartbeat into one mixin** was rejected: the heartbeat
  loop (`run`/`tick`) is the supervisor; the lifecycle knobs are the
  supervisor's controls. They are two responsibilities even though both are
  small.
* **Splitting the 5 callbacks/signals off the facade** was rejected: Qt
  `Signal` attributes must live on the `QObject` subclass, so they belong on
  the facade by construction, not by choice.

## Gates

* `radon cc -s services/collector/` — worst ≤ 9 (A).
* `tools/metrics/rule16_gate.py` clean.
* `tests/test_collector_state.py`, `tests/test_collector_gaps.py` (the
  `test_services_collector_gaps.py` + `test_history_service_contract.py`
  seams), `tests/test_collector_tick_phases.py`,
  `tests/test_recollect_after_clear.py`, `tests/test_media_recovery_e2e.py`,
  and the `test_stores_public_api.py` stores-count gate — green.
