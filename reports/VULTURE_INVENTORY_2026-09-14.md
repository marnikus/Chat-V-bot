# Dead-code inventory — Round I step I1

Measured on branch `arena/01a09b51-chat-v-bot` with:

```
vulture --min-confidence 90 core actions backend bridge services stores app main.py
```

The Round I audit (F7) found **7** findings tree-wide: 1 genuinely dead import
plus 6 it judged protocol-allowed. This step removed the dead import and one
dead parameter, leaving **5**. Each survivor is listed with the reason it is
required to exist, so a future round can tell "allowed" from "not yet looked
at" without re-deriving the argument.

## Removed in I1

| Finding | Action |
|---|---|
| `actions/registry.py:18` unused import `Iterator` | Deleted. Nothing in the module referenced the name (checked over the full source text, not just AST `Name` nodes). |
| `services/run/coordinator.py:62` unused parameter `scroll_parser` | Deleted, with the now-unused `TYPE_CHECKING` import of `ScrollParser`. It was unused in the body; the only production caller (`bridge/stack_bridge.py:96`) already passed nothing; 9 test files passed a literal `None` and were migrated to `execute()`. |

## Remaining 5 — all required by a protocol, none removable

| Location | Finding | Why it must stay |
|---|---|---|
| `backend/cdp_client.py:35` | unused variable `exc_type` | Python's async context-manager protocol fixes the signature `__aexit__(self, exc_type, exc, tb)`. The lease releases unconditionally and swallows nothing, so it reads none of the three. Renaming to `_exc_type` would silence vulture but break nothing and gain nothing; the name documents the protocol. |
| `backend/cdp_client.py:35` | unused variable `tb` | Same `__aexit__` signature. |
| `services/run/hooks.py:95` | unused parameter `coordinator` (`pre_run`) | `RunHooks` is the no-op BASE of the hook protocol. Subclasses receive and use `coordinator`; the base must accept it to be substitutable (LSP). Deleting it from the base would break every override. |
| `services/run/hooks.py:98` | unused parameter `coordinator` (`post_run`) | Same base-class protocol. |
| `services/run/hooks.py:101` | unused parameter `coordinator` (`on_action_complete`) | Same base-class protocol. |

## Note on what vulture cannot see

None of these tools could have found the defect this step's main fix addressed:
`backend/dom_highlight.py` defined `ElementMatch` and `Overlay` **twice each**,
the second definition silently shadowing the first. Vulture sees the surviving
definition as used; the clone scanner is cross-file; coverage marks both
`class` statements executed. That gap is now closed by
`tests/unit/test_no_duplicate_definitions.py`, which is proved non-vacuous by
reintroducing a copy and observing the failure.
