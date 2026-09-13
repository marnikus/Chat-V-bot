# AI connections, prompt presets, history scope (2026-09-13)

Fourth round on the AI Bot Chat feature. Five items:

1. Move the API fields out of the Prompt Editor into their own window.
2. An **AI connection** dropdown in the editor.
3. **Prompt presets**: save / select / update / delete, surviving restart.
4. The editor holds prompt controls only.
5. Bot Chat: a "today only" checkbox; unchecked means the person's full history.

---

## 1. The one decision that shapes the rest: connection ≠ provider

Last round I built **providers** — a fixed table of two (Grok, Google), each
with one key and one model. This spec asks for **connections**, and the
difference is not cosmetic:

> *List all configured connections, not only providers* … *Grok — grok-4.3*,
> *Google AI — Gemini model*, *Additional configured connections*

A provider is a vendor's API shape. A connection is a **named, user-created
instance** of one: "Grok grok-4.3", "Grok grok-2 (cheap)", "work Gemini".
The user can have several per provider, names them, and the Prompt Editor
picks one. The screenshot's model field reading `grok-4.3` — a model my
hard-coded default does not contain — is the same point: the user chooses,
the app does not dictate.

So `bot_providers` stays exactly as it is (it describes the two wire
formats, which is real and unchanged) and a new concept sits on top:

```
ProviderSpec   how to talk to a vendor   (code, fixed: grok | google)
Connection     a named configured instance (user data, unlimited)
```

A connection is `{id, title, provider, api_key, model, url}`. This is
strictly more general than the current per-provider bucket, and the old
shape migrates into it — see §4.

### Rejected: keep the provider table and just rename the UI

Tempting (zero migration) but it cannot express "two Grok connections with
different models", which is the explicit ask. Renaming a thing without
changing what it can represent is the kind of change that looks like
progress and delivers none.

---

## 2. Storage: `PresetStore`, not a new file

Both new features are "named things the user creates, edits, deletes, and
expects back after a restart". The repo already has exactly one mechanism
for that — `config/presets.json` via `PresetStore`, reached through
`ConfigManager.named_get/named_set/named_delete/named_all`, already routed
by `_SECTION_ROUTES` and already used by `stack_presets` and
`template_presets`.

Two new sections join it:

| Section | Holds |
|---|---|
| `ai_connections` | `{id: {title, provider, api_key, model, url}}` |
| `prompt_presets` | `{id: {title, template, text}}` |

Adding a section is two lines (`_SECTION_ROUTES` + `PresetStore.SECTIONS`)
and inherits atomic writes, the per-path instance cache (so two writers
cannot clobber each other) and restart persistence. Writing a bespoke store
would duplicate all of that — and RULE 5's "one way to do a thing" is the
rule I already broke once this feature, which is what caused the GIF bug.

**Secrets caveat, stated plainly:** connection keys move from
`config/settings.json` to `config/presets.json`. Both are plaintext on the
same machine, so this is not a downgrade, but `presets.json` is a file users
are more likely to share when exporting presets. The export path is not
touched here; I note it as a known edge rather than claim it is handled.

---

## 3. Where things live after this round

| Window | Contains |
|---|---|
| AI Bot Chat | chat, verification flow, **today-only checkbox**, ⚙ → AI Connections |
| Prompt Editor | template tabs, **preset bar**, **connection dropdown**, text, variables, preview, Save/Cancel |
| AI Connections | the connection list + key/model/endpoint/test — **and nothing else** |

The editor's `.bot-conn` block (API key + model + Save connection) is
deleted outright. Acceptance says "API settings are absent from the Prompt
Editor body", and leaving it hidden-but-present would be a lie the next
reader has to discover.

The existing `bot_connection` / `bot_save_connection` slots go with it.
They are the last round's write-only-key shortcut and their only caller is
the block being deleted; keeping unused slots on a bridge is dead wire.

### Which connection runs a prompt

One active connection, stored as `grok.connection` (an id). The dropdown in
the editor sets it. `client_for` resolves it to a `Connection` and falls
back to the legacy provider settings when no connection exists, so an
install that never opens the new window keeps working.

An invalid connection — no key, or a provider id the app does not know — is
listed with a warning marker and is **not** silently skipped: the user chose
it, so they get told why it will not run rather than a silent no-op.

---

## 4. Migration

On first read, if `ai_connections` is empty and legacy settings hold a key,
one connection is synthesised per configured provider and the active one is
preserved. It runs through the same code path as a user-created connection,
so there is no second shape to maintain.

Not destructive: the legacy keys stay where they are. If this round is ever
reverted, the old settings still work.

---

## 5. Item 5 — the history scope checkbox

`today()` becomes `load(nick, scope)` where scope is `"today"` or `"all"`:

* `today` — unchanged behaviour, `items_of_day` filter.
* `all` — the same `HistoryQuery.page` read without the day filter, still
  capped at `CONTEXT_LIMIT` newest messages.

The cap stays for both. "Full history" means "not restricted to today", not
"send four thousand messages to a paid API" — an uncapped transcript is a
bill and a context-window error, not a feature. The window says how many
messages it is actually using so the cap is visible rather than surprising.

The checkbox state persists per session via `get_state`/`set_state`, like
other UI toggles in this app.

`today()` is kept as a thin wrapper — it is called from four places and the
rename buys nothing.

---

## 6. Sizes, and what that forces

`BotPromptBridge` is at 12 methods of RULE 16's 15. Presets need four slots
(list/save/delete/select) and connections need five. Both cannot go there.

* **Connections** → `BotSettingsBridge` (already the settings wire; its
  provider slots are replaced, not added to, so it stays at 8).
* **Presets** → `BotPromptBridge`, which is where prompt things belong. Four
  slots takes it to 16 — one over. So `bot_connection` and
  `bot_save_connection`, both being deleted anyway, bring it back to 14.

That is genuinely tight. If it breaches, the split is presets into their own
service + bridge, not a raised limit.

---

## 7. Order

1. Storage (`bot_connections.py` + the two `PresetStore` sections) — everything else depends on it.
2. Connections window + editor dropdown; delete `.bot-conn`.
3. Presets.
4. The scope checkbox.

Gates: full suite, all JS suites, `rule16_gate.py --with-clones`, coverage at
or above this round's 97% on the feature, RULE 18 re-measure, frozen
`backend`/`stores` API snapshots untouched.
