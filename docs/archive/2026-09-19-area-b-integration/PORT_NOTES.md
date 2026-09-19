# Area B port notes — 2026-09-19

The user supplied a 21-file implementation manifest for
`seam/bridge-humble-shell`. This checkout already has later HistoryBridge part
modules and undo-service decomposition. The transferred ideas were reconstructed
against those implementations rather than overwriting them with incomplete files.
The supplied 2026-09-14 archive's metrics were treated as source targets, not
measurements of this branch; no historical archive was fabricated from them.

## Reconciliation decisions

- Preserve all HistoryBridge slots, including open/copy media, clipboard text,
  settings get/save and nick detection. Preserve class `_json_arg` and module
  `_person_request` aliases used by current collaborators.
- Preserve UndoBridge `_global_payload` alias, legacy projection `null` behavior,
  normalization through `_clean_history` **before** capping/saving, and existing
  refusal tuple `(False, parsed_non_list)` rather than the conflicting pasted
  test's `(False, None)` expectation.
- Preserve world-event function signatures, patchable module WAIT_S and callback
  `(scope, message)`. No-store and timeout still run the work so its own failure
  can reach the UI. Cancellation propagates; pre-start coroutine is closed on
  wait failure/cancellation. Nonpositive/NaN steps refuse rather than spin forever.
- People scheduler is keyword-only and a falsey scheduler is not discarded.
  Manual sleeps advance logical time and yield once; no 15-second real sleep.
- Keep the distinction between DB success, offline/unchanged outcome and partial
  world change. Delete never records undo. The result's path supplies success text.
- Share `INTENT_ONLY` at module level with undo_apply; do not invent an absent
  `Announcer.INTENT_ONLY` class attribute or claim every emitter is centralized.
- Generate every real Router method/signal and compare exact artifact bytes.
  Include return types in addition to source arity/parameter types. Fail on
  overloaded names rather than silently drop an overload. The current Router
  has no overload collision. Do not commit the source's partial P0 snapshot.
- JS diagnostics still forward calls, preserve `this`, and allow the optional
  trailing QWebChannel result callback. They are tooling, not installed UI policy.
- Use `asyncio.run` with bounded scenarios, not unclosed test event loops.
  `needs_qt` marks actual adapter/schema tests; explicit pure markers are respected
  before the old root conftest's filename heuristic.
- Replace one stale delete-guard source search with a stronger real-bridge
  behavioral assertion. Frozen API snapshots and coverage floors are unchanged.

## Final included mutation survivors

All remain in denominators. This is a review queue, not an equivalence waiver.

```
bridge.wire_codec.x_message_id__mutmut_5
bridge.wire_codec.x_people_payload__mutmut_3
bridge.wire_undo.x_global_payload__mutmut_15
bridge.wire_undo.x_kind_value__mutmut_24
core.announcer.xǁAnnouncerǁreport_intent__mutmut_14
core.scheduler.x_poll__mutmut_5
services.world_events.xǁWorldGateǁrun__mutmut_1
services.world_events.xǁWorldGateǁrun__mutmut_4
services.world_events.xǁWorldGateǁrun__mutmut_5
services.world_events.xǁWorldGateǁrun__mutmut_12
services.world_events.xǁWorldGateǁrun__mutmut_20
services.world_events.x_wait_for_world_open__mutmut_1
services.world_events.x_announce_world_live__mutmut_8
services.world_events.x_announce_world_live__mutmut_10
services.world_events.x_announce_world_live__mutmut_16
services.world_events.x__announce_labels__mutmut_5
services.world_events.x__announce_labels__mutmut_10
services.world_events.x__announce_labels__mutmut_12
services.world_events.x__announce_labels__mutmut_13
```

Measured verification and reproduction: [report](../../../reports/AREA_B_TRANSFER_2026-09-19.md).
