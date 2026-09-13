# F5: Parameter Objects for Wide-Parameter Functions

**Date:** 2026-09-13  
**Status:** In Progress (pattern established, partial implementation)  
**Design Reference:** ROUND_F_DESIGN_2026-09-12.md §6, RULE 19.4

## Overview

F5 addresses the 70+ functions across the codebase that have more than 4 parameters (RULE 16 limit). The approach follows §19.4: use parameter objects (dataclasses) to group related parameters, following the pattern established by `PersonPageRequest` in `backend/history_query.py`.

## Progress

### Completed (F8 → F5b stores/ half)
- Moved `history_*` family (9 files) to `stores/history/` sub-package (F8)
- This reduced `stores/` from 37 to 28 files
- Created `stores/history/history_requests.py` with `AppendRequest` parameter object
- Added `append_v2()` method to `AppendPlanner` demonstrating the pattern

### Remaining for F5b (stores/ half - ~26 functions)
The following functions in `stores/` (including `stores/history/`) have > 4 parameters and need parameter objects:

#### stores/history/history_repo.py (10 functions)
1. `append` - 13 params → Use `AppendRequest`
2. `_prepend` - 11 params → Use `PrependRequest` (to be created)
3. `rename_if_same_conversation` - 8 params → Use `RenameRequest`
4. `_after_write` - 8 params → Use `WriteContext`
5. `recover_media` - 6 params → Use `MediaRecoveryRequest`
6. `_touch_cursor` - 6 params → Use `CursorUpdate`
7. `_take_empty_slot` - 5 params → Use `SlotFillRequest`
8. `_ui_record` - 5 params → Use `UIRecordRequest`

#### stores/history/history_repo_append.py (9 functions)
1. `append` - 13 params → Use `AppendRequest` (already created)
2. `_prepend` - 11 params → Use `PrependRequest`
3. `_write_rows` - 8 params → Use `WriteRowsRequest`
4. `_insert_message` - 8 params → Use `MessageInsertRequest`
5. `_report_unchanged` - 7 params → Use `UnchangedReport`
6. `_collect` - 6 params → Use `CollectRequest`
7. `_align` - 5 params → Use `AlignRequest`
8. `_take_empty_slot` - 5 params → Use `SlotFillRequest`
9. `_align` - 5 params → Use `AlignRequest`

#### stores/history/history_repo_identity.py (3 functions)
1. `rename_if_same_conversation` - 8 params
2. `_same_conversation` - 6 params
3. `_ui_record` - 5 params

#### stores/history/history_repo_lifecycle.py (3 functions)
1. `_after_write` - 8 params
2. `_touch_cursor` - 6 params
3. `_resequence` - needs review

#### stores/history/history_repo_media.py (2 functions)
1. `__init__` - 8 params
2. `recover_media` - 6 params

#### stores/history/history_models.py (2 functions)
1. `fingerprint` - 6 params
2. `dedupe_key` - 5 params

#### stores/media_store.py (1 function)
1. `__init__` - 6 params → Use `MediaStoreConfig`

### F5a (neutral files - ~36 functions)
Functions in other directories (services/, backend/, etc.) also need parameter objects. These are parallel-safe and can be done independently.

## Pattern to Follow

### 1. Create Parameter Object
```python
@dataclass
class OperationRequest:
    """Parameters for [operation]."""
    param1: type = default
    param2: type = default
    # ... all parameters from the function signature
```

### 2. Add New Method
```python
async def operation_v2(self, request: OperationRequest) -> Result:
    """New API using parameter object. Old method preserved for compatibility."""
    # Use request.param1, request.param2, etc.
```

### 3. Update Call Sites (Optional)
- Gradually migrate call sites from `operation()` to `operation_v2()`
- Old method can be deprecated once all call sites are updated

### 4. Remove Old Method (Future)
- Once all call sites use the new API, the old method can be removed
- This reduces parameter count without breaking existing code

## Example: AppendRequest

See `stores/history/history_requests.py` for the `AppendRequest` implementation.

## Next Steps

1. **F5b Priority 1:** Create parameter objects for the 5 worst offenders in `stores/history/` (append, _prepend, rename_if_same_conversation, _after_write, recover_media)
2. **F5b Priority 2:** Update the remaining functions in `stores/history/`
3. **F5b Priority 3:** Address `stores/media_store.py`
4. **F5a:** Address functions in services/, backend/, and other directories

## Files Modified
- `stores/history/history_requests.py` - NEW (parameter objects)
- `stores/history/history_repo_append.py` - Added `append_v2()` method
- All imports updated from `stores.history_*` to `stores.history.history_*`

## Verification
Run the following to verify F8 is complete:
```bash
python -m unittest tests.unit.stores.test_stores_structure.TestFileSize
```

Expected: All tests pass, stores/ has 28 files.
