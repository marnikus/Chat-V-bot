# Area D Design — backend and action pipeline

**Date:** 2026-09-09  
**Scope:** `backend/**` and `actions/**` only. UI, stores, services, bridge, app,
compatibility shims, `cdp_client.py`, and frozen history schemas are out of scope.

## Problem

Area D has several high-risk functions with large parameter lists and mixed
responsibilities. The most severe is `sync_conversation` (14 options and the
chat gate, scrolling, parsing, persistence, and progress reporting in one
function). `ScrollParser` has 20 constructor arguments. Media attachment and
visual clicking repeat the same parameter plumbing. This makes callers fragile:
old presets and tests can silently pass a value into the wrong position.

## Target structure

The first slice introduces typed option objects without changing wire or public
function compatibility:

- `ChatSyncOptions`: all optional sync controls; legacy keyword arguments remain
  accepted and are normalized once at the boundary.
- `ScrollOptions`: parser viewport, timing, selection, highlighting, and callback
  configuration; `ScrollParser(..., options=...)` remains compatible with the
  legacy constructor.
- `AttachmentOptions` and `ClickOptions`: stable parameter objects for future
  extraction of the attachment and visual-click phases.
- `ConfigManager` uses defensive section traversal and guard clauses, so a
  migrated scalar or malformed JSON value cannot call `.get` on a string.

The implementation deliberately does not rename symbols, change return values,
or touch frozen collaborators. This permits the subsequent extraction of
`SyncPlanner`, `ChunkReader`, `DeltaAligner`, and `SyncPersister` behind these
stable boundaries.

## Tests written before implementation

`tests/test_area_d_options.py` specifies normalization, precedence, defensive
configuration reads, and constructor compatibility. Existing Area D tests
continue to exercise the real pipelines and their public contracts.

## Acceptance criteria

1. Existing callers using legacy keywords behave identically.
2. New option objects are immutable and validate/clamp user-facing numbers.
3. Malformed/scalar config sections return defaults rather than raising.
4. No files outside Area D (and this design/test documentation) are changed.
5. Compile and Area D tests pass.
