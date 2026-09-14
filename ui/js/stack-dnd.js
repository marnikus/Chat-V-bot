/* stack-dnd.js — Action Stack editor facade (Round H, H-A4)

Owns the block catalog (BUILTIN_BLOCKS / RETIRED_KEYS), the stack
state, and the thin lifecycle surface. Behaviour lives in the part
files (loaded before this one — see index.html):
  stack-dnd-history.js  block migration + undo/redo history
  stack-dnd-render.js   stack list render + drag reorder + selection
  stack-dnd-menu.js     + menu, run/save/export buttons, custom presets
  stack-dnd-config.js   Block Config pin / keep-open
  stack-dnd-form.js     Tune panel row-builder table + Speed Multiplier

Parts are merged onto this host with UIHelpers.mergeParts: every part
method binds `this` to the StackDnD facade, so all `this.*` access
(state + sibling methods + the shared BUILTIN_BLOCKS catalog) resolves
exactly as before the split. Public API unchanged (StackDnD.*).
*/

'use strict';

const RETIRED_KEYS = [
  'use_panel_filters',  // duplicate of the four filter selects
  'skip_if_backlog',    // replaced by the scroll_only seek mode
  'backlog_threshold',
];

const BUILTIN_BLOCKS = [
  { block_id:'CUSTOM_FIND',    name:'Find & Click',     icon:'🔎',
    defaults:{custom_name:'', selector:"div[role='tab'].tab-item", label_selector:'p.chat-title', match_text:'', click_enabled:true, click_selector:'', highlight_enabled:true, confirm_pause_ms:700, highlight_ms:1200, pre_delay_ms:500, enabled:true},
    labels:{custom_name:'Block name (shown in stack & logs)',
            selector:'① Element to find — the clickable box (CSS)',
            label_selector:'② Separate text element inside it to confirm (CSS)',
            match_text:'Text it must contain (empty = first match) — {{nick}} = selected user',
            click_enabled:'Click after found',
            click_selector:'Or click this inner element instead (CSS, optional)',
            highlight_enabled:'Visual confirmation — 🟥 red outline on found, 🟧 orange on click target',
            confirm_pause_ms:'Pause after found, to eyeball the red outline (ms)',
            highlight_ms:'How long each outline stays visible (ms)',
            pre_delay_ms:'Pre-delay (ms)',
            enabled:'Enabled (on/off toggle bar)'} },
  { block_id:'CLICK_MAIN_TAB', name:'Click Main Tab',   icon:'🏠',
    defaults:{selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', highlight_enabled:true, confirm_pause_ms:700, pre_delay_ms:500, enabled:true},
    labels:{selector:'Tab element selector', child_selector:'Child text selector', tab_name:'Tab name (text match) — {{nick}} = selected user', highlight_enabled:'Visual confirmation outlines', confirm_pause_ms:'Pause after found (ms)', pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'SCROLL_PARSE',   name:'Scroll & Parse',    icon:'📜',
    defaults:{max_scrolls:50, scroll_pause_ms:800, scroll_delta_y:300,
              viewport_selector:'cdk-virtual-scroll-viewport.users-list-viewport',
              load_timeout_ms:2500, stall_threshold:3, min_new_users:1,
              person_selector:'user-item', nick_selector:'.primary-text',
              highlight_enabled:true, highlight_ms:900, confirm_pause_ms:500,
              purge_rejected:true, scroll_only:false,
              filter_female:'yes', filter_registered:'no', filter_guest:'yes',
              filter_anonymous:'no', pre_delay_ms:300, enabled:true},
    options:{filter_female:['any','yes','no'], filter_registered:['any','yes','no'],
             filter_guest:['any','yes','no'], filter_anonymous:['any','yes','no']},
    labels:{max_scrolls:'Max scrolls (safety cap)',
            scroll_pause_ms:'Pause after each scroll (ms)',
            scroll_delta_y:'Scroll step (px)',
            viewport_selector:'Scroll viewport (CSS)',
            load_timeout_ms:'Max wait for lazy load (ms)',
            stall_threshold:'Scrolls with no new people = end',
            min_new_users:'Finish after N new un-messaged (0 = all)',
            person_selector:'Person row selector (CSS)',
            nick_selector:'Nickname element inside (CSS)',
            highlight_enabled:'🟢 Highlight each detected person',
            highlight_ms:'Highlight duration (ms)',
            confirm_pause_ms:'Pause after detecting a person (ms)',
            purge_rejected:'🗑 Remove people that fail the filter',
            scroll_only:'🔎 Only scroll, no people adding (find existing un-messaged person)',
            filter_female:'① Female', filter_registered:'② Registered',
            filter_guest:'③ Guest', filter_anonymous:'④ Anonymous',
            pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'CONDITIONAL_SKIP',name:'If Messaged → Skip',icon:'🔀', defaults:{enabled:true}, labels:{enabled:'Enabled'} },
  { block_id:'CLICK_USER',     name:'Click User',        icon:'👤',
    defaults:{selector:'user-item', label_selector:'.primary-text',
              click_selector:'.user-container',
              tab_selector:"div[role='tab'].tab-item",
              tab_title_selector:'p.chat-title', verify_new_tab:true,
              tab_pause_ms:800, highlight_enabled:true, confirm_pause_ms:700,
              respect_order:false, use_person_from_memory:false,
              pre_delay_ms:1000, enabled:true},
    labels:{selector:'Person row selector (CSS)',
            label_selector:'Nickname element inside (CSS)',
            click_selector:'Element to click inside (CSS)',
            tab_selector:'Chat tab selector (for verification)',
            tab_title_selector:'Tab title element (CSS)',
            verify_new_tab:'Confirm a new tab opened',
            tab_pause_ms:'Pause after click, before check (ms)',
            highlight_enabled:'Visual confirmation outlines',
            confirm_pause_ms:'Pause after found (ms)',
            respect_order:'Respect the Order (#) column — message people 1, 2, 3… N in list order',
            use_person_from_memory:'Use Person from Memory — click the person saved as {{nick}} this run, not the user list (Pick Person / an earlier Click User must save the nick first)',
            pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'WAIT_PAGE_LOAD', name:'Wait for Page',     icon:'⏳',
    defaults:{target_selector:"textarea[placeholder='Сообщение']",timeout_ms:5000,pre_delay_ms:200, enabled:true},
    labels:{target_selector:'Target CSS selector',timeout_ms:'Timeout (ms)',pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'TYPE_MESSAGE',   name:'Type Message',      icon:'⌨️',
    defaults:{message:'',use_composer:false,typing_speed_ms:30,pre_delay_ms:500, enabled:true},
    labels:{message:'Message text — {{nick}} = selected user',use_composer:'Use text from the Message Composer window',
            typing_speed_ms:'Typing speed (ms)',pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'CLICK_SEND',     name:'Click Send',        icon:'📨',
    defaults:{selector:"button[type='submit']",
              fallback_selector:'button:has(mat-icon)', fallback_text:'send',
              highlight_enabled:true, confirm_pause_ms:700, pre_delay_ms:300,
              enabled:true},
    labels:{selector:'Send button selector (CSS)',
            fallback_selector:'Fallback button selector (CSS)',
            fallback_text:'Fallback icon text',
            highlight_enabled:'Visual confirmation outlines',
            confirm_pause_ms:'Pause after found (ms)',
            pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'ATTACH_IMAGE',   name:'Attach Image',      icon:'🖼️',
    defaults:{folder_path:'',file_pattern:'*.jpg, *.jpeg, *.png, *.gif',
              rotation_mode:'sequential', simulate_dialog:true,
              highlight_enabled:true, confirm_pause_ms:700,
              verify_timeout_ms:8000, pre_delay_ms:500, enabled:true},
    options:{rotation_mode:['sequential','random']},
    labels:{folder_path:'Image folder path',
            file_pattern:'Image formats (comma separated — e.g. jpg, jpeg, png, gif)',
            rotation_mode:'Pick order',
            simulate_dialog:'Open the upload dialog first (click the image button, like a human)',
            highlight_enabled:'Draw confirmation outlines (red = found, orange = click)',
            confirm_pause_ms:'Pause after found (ms)',
            verify_timeout_ms:'Wait for the image to send (ms, 0 = skip)',
            pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'CLICK_BACK',     name:'Return to Main',    icon:'🔙',
    defaults:{selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', highlight_enabled:true, confirm_pause_ms:700, pre_delay_ms:800, enabled:true},
    labels:{selector:'Tab element selector', child_selector:'Child text selector', tab_name:'Tab name — {{nick}} = selected user', highlight_enabled:'Visual confirmation outlines', confirm_pause_ms:'Pause after found (ms)', pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'PAUSE',          name:'Custom Pause',      icon:'⏸️',
    defaults:{duration_ms:1000, enabled:true},
    labels:{duration_ms:'Duration (ms)', enabled:'Enabled'} },
  { block_id:'SPEED_MULTIPLIER', name:'Speed Multiplier', icon:'⏩',
    defaults:{multiplier:1.0, enabled:true},
    labels:{multiplier:'Speed coefficient — 1.0 = normal, 0.5 = 2× faster, 2.0 = 2× slower',
            enabled:'Enabled'} },
  { block_id:'TAKE_PERSON',    name:'Pick Person',       icon:'🎯',
    defaults:{pick_mode:'random_new', enabled:true},
    radios:{pick_mode:['random_new','random_done','order_first']},
    radio_labels:{pick_mode:{
        random_new:'Any random un-messaged person (Status New)',
        random_done:'Any random already-messaged person (Status Done)',
        order_first:'The first person in Order (#) — exactly #1'}},
    labels:{pick_mode:'Pick a person from the list and remember its nick:',
            enabled:'Enabled'} },
  { block_id:'SEARCH_USERS',   name:'Search Users',      icon:'🔍',
    defaults:{text:'',pre_delay_ms:500, enabled:true},
    labels:{text:'Search text — {{nick}} = selected user (types into the users-list “Поиск” box, focus + text verified)',
            pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'MARK_MESSAGED',  name:'Mark Person as Messaged', icon:'✅',
    defaults:{pre_delay_ms:300, enabled:true},
    labels:{pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'COLLECT_HISTORY', name:'Collect Message History', icon:'🗃',
    defaults:{target:'active', mode:'incremental', require_private:true,
              max_messages:0, chunk_size:80, chunk_pause_ms:40,
              download_media:true, fail_if_empty:false, pre_delay_ms:300,
              enabled:true},
    options:{target:['active','memory_nick'], mode:['incremental','full']},
    labels:{target:'Archive for — active tab, or the {{nick}} in memory',
            mode:'Mode — incremental (new lines only) or full re-read',
            require_private:'Only private (1-to-1) chats',
            max_messages:'Max messages (0 = the whole visible conversation)',
            chunk_size:'Messages read per chunk',
            chunk_pause_ms:'Pause between chunks (ms) — keeps the UI smooth',
            download_media:'Cache images / GIFs to disk',
            fail_if_empty:'Fail the block when nothing new was found',
            pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'REPEAT_LOOP',    name:'Repeat Loop',       icon:'🔁',
    defaults:{repeat_count:2, enabled:true},
    labels:{repeat_count:'Number of loop cycles (whole run repeats N times, 1 = once)',
            enabled:'Enabled'} },
];


const StackDnD = {
  stack: [],
  selectedIdx: -1,
  customBlocks: [],       // reusable Find & Click presets: [{name, block, updated_at}]
  CONFIG_PIN_STORAGE_KEY: 'chatbot.blockConfigPin.v1',
  // Block Config "Pin" toggle: while true the Tune panel stays open even
  // when no Action Block is selected (empty state), instead of closing on
  // deselect. Persisted in localStorage and, when the desktop bridge is
  // present, in config.json so it survives app restarts.
  configPinned: false,
  _inited: false,
  _running: false,
  _runningIdx: -1,
  _paused: false,
  _restoring: false,
  _snapshotTimer: null,

  // ── History (Feature #1) ─────────────────────────────────────
  history: [],
  historyIndex: -1,
  MAX_HISTORY: 100,
  _isRestoringHistory: false,
  _historySaveTimer: null,

  init() {
    if (this._inited) return;
    this._inited = true;
    this._initDefaultStack();
    this._renderStack();
    this._setupAddMenu();
    this._loadConfigPin();
    this._setupConfigPin();
    this._setupButtons();
    this._setupKeyboardReorder();
    this._setupHistoryButtons();
    this.updateHistoryButtons();
    this._updateConfigPinButton();
    // Toast-style hint is deliberate: a previously pinned panel reopens empty
    // (no selection after startup), showing the empty-state hint.
    this._updateConfigVisibility(this.stack[this.selectedIdx]);
  },
  _migrateBlock(b) {
    if (!b || typeof b !== 'object' || Array.isArray(b)) return null;
    const meta = BUILTIN_BLOCKS.find((x) => x.block_id === b.block_id);
    const defaults = (meta && meta.defaults) || null;
    const nb = defaults ? {...defaults, ...b} : {...b};
    RETIRED_KEYS.forEach((k) => { delete nb[k]; });
    if (nb.enabled === undefined || nb.enabled === null) nb.enabled = true;
    else nb.enabled = !!nb.enabled;
    if (typeof nb.pre_delay_ms !== 'number') nb.pre_delay_ms = 500;
    return nb;
  },
  setStack(blocks, opts) {
    if (!Array.isArray(blocks)) return;
    opts = opts || {};
    const prev = this._restoring;
    if (opts.silent) this._restoring = true;
    // Migrate every block: strip retired keys, back-fill missing defaults.
    this.stack = blocks
      .map((b) => this._migrateBlock(b))
      .filter(Boolean);
    this.selectedIdx = -1;
    this._runningIdx = -1;
    this._renderStack();
    // Respect the pin: an unpinned panel closes on deselect; a pinned panel
    // stays open showing its empty-state hint.
    this._updateConfigVisibility(this.stack[this.selectedIdx]);
    if (opts.silent) {
      this._restoring = prev;
    } else {
      if (!opts.isHistory) {
        this.pushHistory(this.stack, {force: opts.forceHistory});
      }
      this.notifyEdited();
    }
  },
  notifyEdited() {
    if (this._running || this._restoring || this._isRestoringHistory || !App.bridge) return;
    clearTimeout(this._snapshotTimer);
    this._snapshotTimer = setTimeout(() => {
      if (!this._running && App.bridge) {
        App.bridge.snapshot_stack(JSON.stringify(this.stack));
      }
    }, 800);
  },
  refreshPresets() {
    if (typeof PresetsUI !== 'undefined' && App.bridge) {
      App.bridge.list_stack_presets((json) => PresetsUI.setStackPresets(json));
    }
  },};

UIHelpers.mergeParts(StackDnD,
  StackDnDMigration, StackDnDHistory, StackDnDRender, StackDnDListOps,
  StackDnDMenu, StackDnDConfig, StackDnDConfigRows, StackDnDSpeed);

(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready(() => StackDnD.init());
