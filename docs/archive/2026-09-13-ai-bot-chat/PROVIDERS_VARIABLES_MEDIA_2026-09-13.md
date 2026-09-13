# Multi-provider settings, variable library, media in Bot Chat (2026-09-13)

Third round on the AI Bot Chat feature. Two new features and one bug:

1. **Multi-provider AI settings** — a Settings dialog, Grok + Google, test
   connection, one active provider, masked keys.
2. **Prompt variable library** — browsable placeholders with descriptions,
   click-to-insert, validation, resolved preview.
3. **Bug: no GIFs/media in Bot Chat** — media messages render blank.

---

## 1. Research: what already exists

Reading before designing found that **two of the three are mostly reuse, not
new code**, and that the bug has a single root cause worth naming precisely.

### 1.1 The media bug is a duplicated query, not a missing renderer

The DB/history window already has the whole stack:

| Layer | What it already does |
|---|---|
| `backend/history_query.py` `_item_media` | joins `media`, resolves `cache_path`, downgrades a cached row whose file vanished to `state="missing"` |
| `HistoryQuery.page` / `_SELECT` | `LEFT JOIN media md ON md.id = m.media_id`, returns the documented item shape |
| `ui/js/history-model.js` `toRow` | bridge item → view row, builds `media.src` via `fileUrl()` |
| `ui/js/history-view.js` `mediaNode` | `<img>` for cached, restore-marker for failed/missing/evicted, images-off state |

The Bot Chat window renders none of it because `BotChatService.today()`
**hand-wrote its own SQL**:

```sql
SELECT m.direction, m.from_nick, m.text, m.ts_display FROM messages m ...
```

Four columns, no join, no `media_id`. So a GIF row arrives with `text=""` and
nothing else — hence the blank message. The renderer was never the problem;
the query was a second, worse copy of one that already existed.

That is a **RULE 5 violation I committed** in round one: "one way to do a
thing". The fix is not to add media handling to my SQL — it is to delete my
SQL and call `HistoryQuery.page`, which is the repo's one archive read and is
frozen by the AREA D API snapshot precisely so it stays the one.

Consequence for the AI context (acceptance: "do not silently drop media-only
messages"): `as_transcript` skips any item whose `text` is blank, so a
GIF-only day currently reaches Grok as an empty transcript. With media in the
item, a media message becomes a visible `[GIF]` / `[image]` line instead.

### 1.2 The provider work is an interface extraction

`GrokClient` already has the right shape — `complete(prompt) -> Result[str]`,
typed errors, injected `session_factory`. Google differs in exactly three
places:

| | Grok | Google |
|---|---|---|
| URL | `…/v1/chat/completions` (fixed) | `…/v1beta/models/{model}:generateContent` (model in path) |
| auth | `Authorization: Bearer <key>` | `x-goog-api-key: <key>` |
| body | `{model, messages:[{role,content}]}` | `{contents:[{parts:[{text}]}]}` |
| reply | `choices[0].message.content` | `candidates[0].content.parts[0].text` |

Verified against `ai.google.dev` (Sept 2026), not assumed.

Everything else — timeout, empty-prompt guard, missing-key guard, exception →
`Err`, the `_post` shape — is identical. So the design is **one `GrokClient`
generalised into a transport that takes a provider spec**, not two parallel
clients. Four small functions differ; the ~60 lines of error handling do not.

### 1.3 Variables: the library must not fork the renderer

`PromptLibrary.render` fills `{nick} {conversation} {last_message}` via
`str.format`. The new spec asks for six variables including
`{last_x_messages}` — which is *parameterised*, and `str.format` cannot
express `{last_5_messages}` without a custom parser.

`is_usable()` also currently *rejects* any template containing an unknown
field, so the moment a user inserts `{msg}` the template would silently fall
back to the default. The variable library is therefore not additive: it
changes what a valid template is.

---

## 2. Design

### 2.1 Providers — `services/bot_providers.py` (new)

A provider is **data, not a class hierarchy**: a frozen spec plus two pure
functions. Adding a third provider is then a table entry, which is what
"architecture must allow more providers later" actually requires.

```python
PROVIDERS = {
  "grok":   ProviderSpec(id, title, url_template, auth_header, default_model, …),
  "google": ProviderSpec(...),
}
```

* `request_of(spec, settings, prompt) -> (url, headers, body)` — the three
  things that differ.
* `reply_of(spec, body) -> Result[str]` — dispatches to the two extractors
  (`choices[0].message.content` / `candidates[0].content.parts[0].text`),
  each already a tiny function.

`services/bot_grok.py` keeps its name and its public surface (`GrokClient`,
`GrokSettings`, `client_for`, `reply_text`) — renaming would churn the bridge,
four test files and the RULE 16 OWNED table for no behavioural gain — but it
gains `provider` awareness and delegates the three differing pieces. Its
docstring records that the file is now the generic transport.

**Keys are per provider.** `grok.api_key` stays where it is (existing installs
keep working); a new provider stores under `grok.providers.<id>.api_key`. The
active provider is `grok.provider`. Changing provider touches neither
`grok.prompts` nor any other provider's key — acceptance: "changing provider
does not delete prompt templates".

**Masking** is already right in principle (`state()` returns `has_key`, never
the key). It grows a `masked` field (`xai-…last4`) so the dialog can *show*
that a key is stored without being able to leak it.

**Test connection** is `complete("ping")` against the saved settings with a
short prompt, reported as `{ok, detail}`. It reuses the one transport, so a
green test means the real path works — a separate probe could pass while the
real call fails, which is the failure mode worth designing out.

### 2.2 Variables — `services/bot_variables.py` (new)

The library is a table of six specs (`id, label, description, example`) plus a
resolver, and `render` moves from `str.format` to one regex pass.

Why a regex rather than `str.format`: `{last_x_messages}` needs an argument
(`{last_5_messages}`), and `str.format` raises on any unknown field — which is
how a user's `{msg}` would currently destroy their template. A single
`re.sub` over `\{([a-z_0-9]+)\}` resolves what it knows and **leaves unknown
placeholders untouched** rather than exploding or silently defaulting.

`validate(text) -> list[warning]` returns unknown/malformed names for the
editor to show. It is a *warning*, not a refusal: a prompt that mentions
`{tone}` because the user is drafting is not a broken prompt, and RULE 4 says
empty/unknown is not broken.

Privacy (acceptance: "keep private/system data out"): the resolver is given a
context dict built by `BotChatService` from the day's items only. There is no
path from a variable to the config, the filesystem or another person — the
resolver cannot reach them because it is never handed them.

### 2.3 Where the UI goes

* **Settings dialog** — a modal in the Bot Chat window (`ui/js/bot-settings.js`),
  opened by a ⚙ icon in the title bar. Not a grid window: it is a modal
  configuration dialog the spec calls a *dialog*, it is opened rarely, and two
  more grid windows would push `sash-core` past the point where the default
  layout is usable. Grid layout stays v4.
* **Variable library** — a panel inside the existing Prompt Editor window,
  which is where the spec puts it.

### 2.4 Rejected

* **A `BotProvider` ABC with two subclasses.** Two implementations differing in
  four expressions do not need dynamic dispatch; the spec table is shorter,
  testable as data, and makes "add a provider" a diff a reader can see whole.
* **Adding `day=` to `HistoryQuery.page`.** It is frozen by the AREA D
  snapshot. Filtering the returned items by day in `BotChatService` costs one
  list comprehension and keeps the frozen surface frozen.
* **Keeping the hand-written SQL and adding a media join to it.** That is the
  duplication the bug came from.
* **Storing keys in the OS keyring.** No such dependency exists in this repo
  and adding one is out of scope; `settings.json` is where every other secret
  already lives. "Securely" is honoured as: never echoed back over the bridge,
  never logged, masked in the UI. Recorded as a limitation rather than
  silently claimed as solved.

---

## 3. Implementation order

1. Media bug — delete the duplicate SQL, call `HistoryQuery.page` (smallest,
   and it un-breaks the AI context the other two build on).
2. Variables — `bot_variables.py`, `render`/`validate`, editor panel.
3. Providers — `bot_providers.py`, transport generalisation, settings dialog.

Gates: full suite, all JS suites, `rule16_gate.py` with the OWNED table
updated, coverage at or above 91.01 / 87.11, RULE 18 re-measure, and the
frozen `backend`/`stores` API snapshots must stay untouched.

---

## 4. Outcome

All three shipped. What the implementation changed relative to §2, and why.

### 4.1 The media bug

Root cause as predicted: `today()` had its own four-column SELECT with no
`media` join. It now reads through `HistoryQuery.page` — the archive's one
read — and filters to the current day in `items_of_day`, because `page()` is
frozen by the AREA D snapshot and takes no `day=`.

The window draws media with `HistoryView.mediaNode`, the DB window's own
renderer, which had to be exported (it was private). Bot Chat therefore
inherits every state the database has — cached, pending, failed, missing,
evicted, images-off — including the clickable "restore" marker, wired to the
same `media_restore` slot the DB window uses. A message is never blank: with
no renderer at all a `[gif]` note is drawn instead.

`as_transcript` no longer drops text-less messages; `item_text` turns a GIF
into a visible `[gif]` line, so a day of nothing but stickers reaches the
model as a conversation rather than an empty string.

**The fix that mattered most was to the test doubles.** `FakeArchive` in both
suites now exposes the REAL `HistoryQuery` over the same handle. A stub would
have hidden precisely this bug — which is how it survived round one.

### 4.2 Variables

`bot_variables.py`: six documented variables, a regex resolver, and
`validate`. Two behaviour changes worth naming:

* **`is_usable` no longer rejects unknown placeholders.** It used to, and
  `text()` fell back to the shipped default when it did — so typing `{tone}`
  silently destroyed the user's template. Unknown placeholders now survive
  into the prompt verbatim and are reported as a warning. Saving is not
  validation.
* **The old names are aliases, not removals.** `{nick}`, `{conversation}` and
  `{last_message}` are sitting in users' configs today; `ALIASES` keeps them
  resolving forever. A rename that breaks stored data is data loss.

`BotChatService.context_of` is the one place a prompt's context is built, so
the editor's preview cannot drift from what is actually sent. Privacy is
structural: the resolver only ever receives that dict, so no variable can
reach the config, a key, the filesystem or another person.

### 4.3 Providers

`bot_providers.py` holds the two specs as data. `GrokClient` kept its name and
public surface and became the generic transport; only URL, auth header, body
shape and reply path vary. Gemini's `finishReason` is read, so a `SAFETY`
refusal is reported as a refusal instead of "empty answer".

Keys are per provider: Grok keeps the original flat keys (existing installs
keep working), others live under `grok.providers.<id>`. Switching providers
writes only `grok.provider` — tested directly against both acceptance
criteria (templates survive; the other provider's key survives).

**Deviation from §2.3: the settings got their own bridge.** Folding them into
`BotPromptBridge` pushed it to 154 LOC / 18 methods, over RULE 16's 150/15.
The gate caught it. `BotSettingsBridge` now owns the dialog, and the wiring
both side windows share (`__init__` + `_chat_bridge`) moved into a
`BotSideBridge` base — which the clone scanner insisted on after flagging the
copy twice.

### 4.4 Limitations, stated rather than hidden

* **Keys are stored in plaintext in `settings.json`**, like every other secret
  in this repo. "Securely" is honoured as: never echoed back over the bridge,
  masked in the UI, never logged. An OS keyring would need a new dependency
  and is out of scope — recorded here rather than quietly claimed as done.
* **`{last_x_messages}` slices the transcript by line**, so a message
  containing a newline counts as more than one. Capped at 50.
* The day-boundary caveat from the previous round is unchanged: `today()` uses
  the process clock while rows are dated from page stamps.

### 4.5 Closing gates

| Gate | Result |
|---|---|
| Full suite | 2950 passed, 2 skipped, 1 xfailed, 897 subtests; only the pre-existing `test_engine_standalone_run.py` failure |
| JS suites | all green; `test_bot_chat_js.js` 47 passed |
| `rule16_gate.py --with-clones` | clean: all owned functions fit, ratchet intact, 0 new clone groups |
| Coverage (feature) | 97% overall; `bot_variables` / `bot_providers` / `bot_prompts` / `bot_prompt_bridge` at 100% |
| Frozen API snapshots | `backend_api_snapshot.json`, `api_baseline.json` untouched |
| RULE 18 | largest file `ui/js/bot-chat.js` 389 (declared reason); `bot_chat.py` 256 after extracting `bot_transcript.py`; `services/bot_*` 7 files, `bridge/` 17 |
| Mutation checks | reverting the per-provider key lookup, the Google auth header, the media block or `item_text` each fails tests |
