# History push lifecycle safety — split plan (H1/H2/H3)

Date: 2026-09-10. Status: planned, not implemented.
Design: `docs/HISTORY_PUSH_LIFECYCLE_DESIGN_2026-09-10.md` (read first;
it defines the contracts each area relies on).

Goal: three areas that can be implemented on **separate branches in
parallel** and merged in any order. Independence is by file/method
ownership (table below) plus contract-first interfaces — no area
imports or assumes another area's new code.

## Ownership table (normative — do not edit outside your column)

| File / region | H1 subscription | H2 in-flight | H3 shutdown |
|---|---|---|---|
| `services/history/runtime.py` `PushBindings` | owns | — | — |
| `services/history/runtime.py` `CollectorRuntime`/`WorldSwitcher` | — | owns | — |
| `services/history/export.py` `init`/`close`/push wiring | owns | — | — |
| `services/history/__init__.py` attrs | owns | — | — |
| `services/collector_service.py` `handle_push`/drain | — | owns | — |
| `app/lifecycle.py` | — | — | owns |
| `tests/integration/history_push/test_subscription_lifecycle.py` | owns | — | — |
| `tests/integration/history_push/test_push_isolation.py` | — | owns | — |
| `tests/integration/history_push/test_shutdown.py` | — | — | owns |
| Everything else (incl. `backend/cdp_client.py`, `services/db_lifecycle.py`, `stores/*`, `bridge/*`) | frozen | frozen | frozen |

`tests/integration/history_push/__init__.py`: whoever lands first
creates the empty file; the others rebase around a one-line add.

## Contracts between areas (from the design doc)

- H1 → all: after `close()` returns, zero history listeners remain on
  the CDP client and no Qt reconnect handler survives. `_on_binding`
  semantics unchanged.
- H2 → all: when `stop()`/`detach_db()`/`switch_db()`/`close()`
  return, zero push tasks are in flight and `_push_open` reflects
  readiness. `close()` needs no edit: drain rides inside the existing
  `_stop_collector()` call.
- H1+H2 → H3: `close()` is idempotent, unsubscribes, drains, flushes,
  closes. H3 builds against this contract (fakes allowed) and never
  reaches into push internals.

## H1 — Push subscription lifecycle (P1, the confirmed bug)

Branch: `arena/h1-push-subscription` (suggested). Base: `main` (+A/C
as available; no dependency on H2/H3).

1. `PushBindings`: split install into browser-binding ensure +
   once-only subscription ensure; `rebind()` reinstalls the browser
   binding only; add idempotent `uninstall()` via `off_event`.
2. `init()` idempotent (named `_on_connected` slot, connect-once
   guards); `close()` unsubscribes + Qt-disconnects first.
3. Tests (fail-before/pass-after): install + N rebinds → exactly 1
   listener; one push event → exactly 1 `handle_push` after reconnects;
   close removes listener + Qt handlers; init→close→init clean;
   double close safe; duck-typed CDP without `on_event`/`off_event`
   still works.
4. Acceptance: new tests green; full Python suite green; JS gate
   unchanged; owned-region coverage ≥90% line / ≥85% branch.

## H2 — In-flight push isolation (P1 investigation + fix)

Branch: `arena/h2-push-isolation` (suggested). Base: same as H1; no
dependency on H1/H3 (works with or without them; combined merge is
verified by integration).

1. `Collector`: `_inflight` set + `_push_open` gate + `_world_gen`
   (all state on the Collector — `HistoryService.__init__` untouched);
   register/discard in `handle_push` via `asyncio.current_task()`;
   gate closed → silent `return 0`.
2. `Collector.drain_pushes(timeout)`: close gate, bounded wait, cancel
   leftovers, log counts. Called first in `CollectorRuntime.stop()`;
   gate re-opened in `restart()`/`start()` on actual restart.
3. Tests (fail-before/pass-after): mid-`append` push across
   `switch_db` writes nothing into the new world; push across
   `detach_db`/`close` never touches a closed DB and `close()` returns
   with zero in flight; stuck push is cancelled after timeout and the
   switch proceeds; stop-then-no-restart silences pushes; restart
   re-enables them.
4. Acceptance: the wrong-world failing-before test demonstrated;
   new tests green; full suite green; owned-region coverage targets as H1.

## H3 — Shutdown path hardening (P2)

Branch: `arena/h3-shutdown-order` (suggested). Base: same as H1/H2;
builds against the documented `close()` contract.

1. `app/lifecycle.py` only: persist-first order (engine stop →
   history.close → memory.close → bounded straggler-cancel →
   cdp.disconnect → quit); per-stage `wait_for` timeouts with named
   stuck-stage logs; quit never hangs.
2. Tests with fakes + a real ordered integration test: stage order
   asserted; hung history close → timeout + proceed + quit; close
   raising → warning + proceed; double shutdown → single run.
3. Acceptance: new tests green; full suite green; shutdown paths
   covered (previously weak — report before/after numbers).

## Merge / integration

- Any merge order works; suggested H1 → H2 → H3 (defect first).
- After each merge: run all three areas' tests together plus the
  complete suite and the JS gate. Never resolve a conflict by deleting
  coverage or weakening an assertion.
- Integration check (whoever merges last): combined run of
  `tests/integration/history_push/` + full suite + JS gate, and a
  combined reconnect-during-switch stress test (reconnect storm while
  switching worlds: exactly-once subscription, zero cross-world
  writes) — owned by the integrator, not by any single area.

## Explicitly deferred

- `media_fetch.py` attach/detach audit (same bug class, already paired
  correctly at a glance — needs its own reproduction, not assumed).
- Write-side world token inside `repo.append` (rejected: touches
  frozen store code; drain + gates suffice).
- P3 complexity refactors (`_item`, `score_tab`, large classes).
