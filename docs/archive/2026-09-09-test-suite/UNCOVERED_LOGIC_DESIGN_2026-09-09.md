# 🧪 Uncovered Logic Design — Phase 3 Extension (Real Tests, Real Paths)

> **Rule:** No "comfortable" pass-through tests. Every test must assert a real path (success, error, boundary, cycle, missing, corrupt, concurrent, state transition).  
> **Rule:** Design doc first. Implement second. Report last.  
> **Date:** 2026-09-09

---

## 1. Understand — What Is Uncovered?

From `TEST_COVERAGE_MODULE_MATRIX.md` (P0 / critical uncovered):

| Module | Why Uncovered | Key Paths to Verify |
|---|---|---|
| `core/di.py` | No direct test | Register, replace, get (lazy + cached), cycle detection, missing key, register_value, clear |
| `core/events.py` | No direct test | Subscribe, unsubscribe, emit (success + handler exception), handlers_of, typed events (frozen dataclass) |
| `backend/criteria_engine.py` | No direct test | Operators (`==`, `!=`, `in`, `contains`, `>`, `<`), compound (`and`/`or`), empty criteria = match all |
| `backend/config_manager.py` | No direct test | Load file, merge, validate, missing file (defaults), invalid JSON, sensitive masking |
| `bridge/router.py` | Partial | All routing rules (exact, pattern, priority), fallback when no match, circular route detection, destination selection |
| `services/run_service.py` | Large / complex | State machine (`init`→`run`→`pause`→`stop`), step execution, error recovery, trace write, normalize_blocks (retired keys, enabled default), norm_level map |
| `main.py` | No test | Import order, dependency init, config load, registry scan, DB init, graceful exit (smoke) |

---

## 2. Design — Real Path Tests (Not Fake)

### 2.1 `core/di.py` — Dependency Injection

**Paths:**
- `register` new → `get` builds via factory (lazy) → `get` again returns cached instance (same identity)
- `register` replace=False raises `ValueError`; replace=True allows overwrite → instance cache cleared
- `register_value` skips factory → `get` returns value directly; `register_value` removes factory
- `get` missing → `KeyError` with exact message containing name
- `get` cycle → `ValueError` with chain string `a -> b -> a`
- `clear` → `has` false, `get` raises
- `__contains__` true/false

**Assertion style:** `self.assertIs(instance, instance2)` for cache; `self.assertIn("cycle", msg)`; `self.assertRaises(ValueError)` not just `Exception`.

---

### 2.2 `core/events.py` — Event Bus

**Paths:**
- Subscribe type A → emit A → handler called with correct event instance
- Subscribe same handler twice → emit → handler called once (no duplicate)
- Unsubscribe → emit → handler NOT called
- Subscribe handler that raises → emit → other handlers still called; exception logged (not raised to emitter)
- `handlers_of` returns copy (modification doesn't affect internal)
- Frozen dataclass events (PeopleChanged, LogMessage, etc.) — emit works, attributes immutable

**Assertion style:** `mock_handler.assert_called_once_with(event)`; `self.assertEqual(len(handlers), expected)`; check `assertLogs` for exception case.

---

### 2.3 `backend/criteria_engine.py` — Filter Engine

**Paths:**
- Simple equality (`==`) with string, int, bool
- `!=` false / true
- `in` (list membership), `contains` (substring for strings)
- `>` / `<` numeric comparison
- Compound `and`: both true = true, one false = false
- Compound `or`: one true = true, both false = false
- Empty criteria (None / `{}` / `[]`) = match all (design contract: no filter = pass)
- Invalid operator → handled gracefully or raises specifically (check design)

**Assertion style:** `assertTrue(engine.matches(data))` / `assertFalse`; compound combinations; boundary values (empty string, zero, negative).

---

### 2.4 `backend/config_manager.py` — Config

**Paths:**
- Load valid JSON → dict returned; file exists; keys preserved
- Load missing file → default config returned (not crash)
- Invalid JSON → specific exception (`json.JSONDecodeError`) caught and handled (or raised clearly)
- Merge two configs: second overrides first; nested merge if design requires
- Validation: required keys present; invalid type raises `ValueError`
- Sensitive masking: keys like `token`, `password` masked in `str()` / log output
- Replace / update partial config

**Assertion style:** `assertTrue(os.path.exists(path))`; `assertIn("key", cfg)`; `assertRaises(ValueError)`; check masked string contains `***` not real secret.

---

### 2.5 `bridge/router.py` — Routing

**Paths:**
- Exact match → correct destination
- Pattern match (regex/glob) → correct destination
- Priority order → highest priority wins when multiple match
- No match → fallback destination or `None` (design contract — verify)
- Circular dependency / loop in routing rules → detected and prevented (or raises)
- Route with parameters → parameters extracted correctly

**Assertion style:** `assertEqual(router.resolve("exact"), dest)`; `assertIsNone(router.resolve("unknown"))`; check priority with multiple rules.

---

### 2.6 `services/run_service.py` — Execution Engine

**Paths:**
- `normalize_blocks`: non-dict dropped; retired keys (`use_panel_filters`, etc.) removed; missing `enabled` defaults to `True`; dict preserved
- `norm_level`: all mapped levels (`ok`→`success`, `warn`→`warn`, `error`→`error`, unknown→`info`)
- `RunTracer`: writes JSON line with `ts`, `run_id`, record fields; `close` safe after write; `OSError` on write logged not raised
- `ActionEngine` state: `init` → `run` (step complete signals emitted); pause stops; resume continues; stop terminates
- Step execution: block found by `get_action_class`; failure stops sequence; trace notes written per step
- `USER_SCOPED_BLOCKS`: only these blocks require user; standalone run uses `STANDALONE_NICK`

**Assertion style:** `assertEqual(len(clean), expected_after_filter)`; `assertIn("run_id", trace_line)`; mock signals (`step_complete.emit.assert_called`) for state transitions.

---

### 2.7 `main.py` — Entry / Smoke

**Paths:**
- Import succeeds (no exception on load); dependency init completes
- Registry scan finds at least base actions
- Config loaded (or default created)
- DB initialized (or created)
- Graceful exit (no unclosed resources / exceptions on shutdown)

**Assertion style:** Subprocess run `python -c "import main; print('ok')"` or use `importlib.import_module`; check exit code 0; verify files created.

---

## 3. Implementation Order (Real, Not Pass-Through)

1. Design doc (this file) — done
2. Implement `core/di`, `core/events`, `backend/criteria`, `backend/config`, `bridge/router`, `run_service` paths, `main` smoke — with assertions
3. Run all — must pass
4. Write `reports/UNCOVERED_TEST_REPORT_2026-09-09.md` — what paths verified, what remains

---

## 4. Quality Gate (From Master Plan Phase 8)

- [ ] No `assertTrue(True)` or empty pass-through tests
- [ ] Every covered path has a specific assertion on output/state/exception
- [ ] Boundary cases included (empty, corrupt, missing, cycle, max)
- [ ] All new tests pass before report
- [ ] Report lists verified paths explicitly
