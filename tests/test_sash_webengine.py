"""Integration test for the sash-layout grid in a REAL Qt WebEngine.

Loads the actual ui/index.html into an offscreen QWebEngineView (Chromium),
wires a fake QWebChannel bridge, and then exercises the grid through the
exact public JS API the UI uses:

  * the page renders 7 windows + sashes, header/toolbar stay pinned
  * no JS console errors on load
  * SashGrid.simulateDrop()  → the tree AND the rendered DOM change correctly
    (windows re-parented, no duplicates, rects actually side-by-side)
  * SashGrid.simulateResize() → sizes commit to the tree and to localStorage
  * SashGrid.setLayout('c')   → the spec "side column" layout: log spans the
    hero rows, and its rendered rect is taller than each hero window
  * a full page RELOAD restores the persisted layout

Skips itself (instead of failing) when PySide6/QtWebEngine is not installed
or cannot load (no GL in the environment), so the suite stays green on
minimal machines.

Run with:  python3 tests/test_sash_webengine.py
"""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML = os.path.join(ROOT, "ui", "index.html")

HAVE_QT = False
QT_IMPORT_ERROR = ""
try:
    from PySide6.QtCore import QObject, QUrl, Signal, Slot
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAVE_QT = True
except Exception as e:  # ImportError or missing system libs
    QT_IMPORT_ERROR = str(e)


class _FakeBridge(QObject):
    """Stand-in for backend.bridge.Bridge — every slot the UI may call."""

    users_updated = Signal(str)
    step_complete = Signal(str, str)
    step_started = Signal(int, str, str)
    stack_complete = Signal()
    log_message = Signal(str, str)
    connection_status = Signal(str)
    stats_updated = Signal(str)
    tabs_received = Signal(str)
    preset_list_updated = Signal(str)
    template_list_updated = Signal(str)
    url_presets_updated = Signal(str)
    custom_blocks_updated = Signal(str)
    tab_match_result = Signal(str, str)
    users_deleted = Signal(str, int)
    person_found = Signal(str)
    stack_loaded = Signal(str, str)
    template_loaded = Signal(str, str)

    def __init__(self):
        super().__init__()

    # ── callback-style slots return JSON (QWebChannel routes the return
    #    value to the JS callback) — signatures mirror backend/bridge.py ──
    @Slot(result=str)
    def get_app_state(self):
        return json.dumps({"url_presets": [], "custom_blocks": [],
                           "stack_presets": [], "template_presets": [],
                           "state": {}})

    @Slot(result=str)
    def get_tabs(self): return '[]'

    @Slot(result=str)
    def get_criteria(self): return '[]'

    @Slot(result=str)
    def get_url_presets(self): return '[]'

    @Slot(result=str)
    def list_stack_presets(self): return '[]'

    @Slot(result=str)
    def list_template_presets(self): return '[]'

    @Slot(result=str)
    def list_custom_blocks(self): return '[]'

    @Slot(result=str)
    def get_message(self): return ''

    @Slot(result=str)
    def get_stack_json(self): return '[]'

    # ── no-op slots ─────────────────────────────────────────────
    @Slot(str)
    def set_last_url_preset(self, _u): pass
    @Slot(str)
    def snapshot_stack(self, _j): pass
    @Slot(str)
    def connect_tab(self, _u): pass
    @Slot(str)
    def find_tab_by_url(self, _q): pass
    @Slot(str)
    def run_stack(self, _j): pass
    @Slot()
    def stop_stack(self): pass
    @Slot()
    def pause_stack(self): pass
    @Slot()
    def resume_stack(self): pass
    @Slot(str)
    def save_message(self, _t): pass
    @Slot(str)
    def save_criteria(self, _j): pass
    @Slot()
    def reset_messaged(self): pass
    @Slot()
    def clear_memory(self): pass
    @Slot()
    def refresh_users(self): pass
    @Slot(str)
    def delete_user(self, _n): pass
    @Slot(str)
    def delete_users(self, _j): pass
    @Slot(str, bool)
    def set_user_messaged(self, _n, _m): pass
    @Slot(str, str)
    def save_stack_preset(self, _n, _j): pass
    @Slot(str, result=str)
    def load_stack_preset(self, _n): return 'null'
    @Slot(str)
    def delete_stack_preset(self, _n): pass
    @Slot(str, str)
    def save_template_preset(self, _n, _b): pass
    @Slot(str, result=str)
    def load_template_preset(self, _n): return 'null'
    @Slot(str)
    def delete_template_preset(self, _n): pass
    @Slot(str)
    def add_url_preset(self, _u): pass
    @Slot(str)
    def remove_url_preset(self, _u): pass
    @Slot(str, str)
    def save_custom_block(self, _n, _j): pass
    @Slot(str)
    def delete_custom_block(self, _n): pass


@unittest.skipUnless(HAVE_QT, "PySide6/QtWebEngine not available: " + QT_IMPORT_ERROR)
class TestSashWebEngine(unittest.TestCase):

    def test_grid_in_real_webengine(self):
        if not os.path.exists(INDEX_HTML):
            self.skipTest("ui/index.html not found")

        app = QApplication.instance() or QApplication(sys.argv)
        console = []          # [level, message]
        state = {"loaded": False}

        class Page(QWebEnginePage):
            def javaScriptConsoleMessage(self, level, msg, _line, _src):
                console.append((level, msg))

        view = QWebEngineView()
        view.setPage(Page(view))
        view.resize(1400, 900)
        view.show()  # offscreen: give the widget a real viewport size

        bridge = _FakeBridge()
        channel = QWebChannel()
        channel.registerObject("bridge", bridge)
        view.page().setWebChannel(channel)

        def on_loaded(ok):
            state["loaded"] = ok

        view.loadFinished.connect(on_loaded)
        view.load(QUrl.fromLocalFile(os.path.abspath(INDEX_HTML)))

        # ── step runner: execute a JS snippet, return its JSON result ──
        def run_js(js, timeout_ms=8000):
            result = {"done": False}

            def cb(value):
                result["done"] = True
                result["value"] = value
            view.page().runJavaScript(
                "(function(){ try { " + js +
                " return JSON.stringify(__r); } catch(e) { return JSON.stringify({error: e.message}); } })()",
                cb)
            import time
            t0 = time.time()
            while not result["done"] and (time.time() - t0) * 1000 < timeout_ms:
                app.processEvents()
                time.sleep(0.01)
            self.assertTrue(result["done"], "JS evaluation timed out: " + js[:80])
            val = result["value"]
            if isinstance(val, str):
                try:
                    data = json.loads(val)
                except json.JSONDecodeError:
                    self.fail("JS returned non-JSON: %r — in: %s" % (val[:200], js[:120]))
            else:
                data = val
            if isinstance(data, dict) and "error" in data:
                self.fail("JS error: " + data["error"] + " — in: " + js[:120])
            return data

        # wait for the page (poll loadFinished with the event loop)
        import time
        t0 = time.time()
        while not state["loaded"] and time.time() - t0 < 30:
            app.processEvents()
            time.sleep(0.02)
        self.assertTrue(state["loaded"], "page did not load in 30s")
        time.sleep(0.3)  # let DOMContentLoaded handlers + WebChannel settle
        app.processEvents()

        # ── 1. grid basics ──────────────────────────────────────────
        r = run_js(r"""
            __r = {
              windows: document.querySelectorAll('.sash-window').length,
              visible: Array.from(document.querySelectorAll('.sash-window'))
                         .filter(w => w.offsetWidth > 0).length,
              panelsAllInGrid: ['winStats','winFilters','winStack','blockConfigPanel',
                                'winComposer','winPeople','winLog']
                         .every(id => {
                           const p = document.getElementById(id);
                           return p && p.closest('.sash-window') !== null;
                         }),
              sashes: document.querySelectorAll('.sash').length,
              headerPinned: document.querySelector('.app-header') !== null &&
                            !document.getElementById('sashGrid')
                             .contains(document.querySelector('.app-header')),
              toolbarPinned: !document.getElementById('sashGrid')
                             .contains(document.getElementById('urlToolbar')),
              headerAboveGrid: document.querySelector('.app-header').getBoundingClientRect().bottom <=
                               document.getElementById('sashGrid').getBoundingClientRect().top + 1,
              treeValid: SashCore.validate(SashGrid.getTree()) === null,
            };
        """)
        self.assertEqual(r["windows"], 7, "7 windows rendered")
        self.assertEqual(r["visible"], 6, "Block Config hidden by default")
        self.assertTrue(r["panelsAllInGrid"], "all persistent panels live in the grid")
        self.assertGreaterEqual(r["sashes"], 6, "sashes rendered between siblings")
        self.assertTrue(r["headerPinned"], "header outside the grid")
        self.assertTrue(r["toolbarPinned"], "URL toolbar outside the grid")
        self.assertTrue(r["headerAboveGrid"], "header physically above the grid")
        self.assertTrue(r["treeValid"])

        # ── 2. drop: composer onto the LEFT edge of people ──────────
        r = run_js(r"""
            SashGrid.simulateDrop('composer', 'people', 'left');
            const t = SashGrid.getTree();
            const f = SashCore.findNode(t, 'people');
            const row = SashCore.findNode(t, 'log').parent;   // bottom row
            __r = {
              valid: SashCore.validate(t) === null,
              oneComposer: SashCore.leafIds(t).filter(x => x === 'composer').length === 1,
              parentDir: f.parent ? f.parent.dir : null,
              order: f.parent ? f.parent.children.map(c => c.id) : null,
              sizes: f.parent ? f.parent.sizes : null,
              rowDir: row ? row.dir : null,
              rowFirstGroup: SashCore.isSplit(row.children[0])
                             ? row.children[0].children.map(c => c.id) : null,
              rowSecond: SashCore.isLeaf(row.children[1]) ? row.children[1].id : null,
            };
        """)
        self.assertTrue(r["valid"], "tree validates after drop")
        self.assertTrue(r["oneComposer"], "move, not copy")
        self.assertEqual(r["parentDir"], "row")
        # the edge drop SPLIT people's cell: composer | people, 50/50
        self.assertEqual(r["order"], ["composer", "people"])
        self.assertEqual(r["sizes"], [50, 50])
        # log stayed as the next sibling in the bottom row
        self.assertEqual(r["rowDir"], "row")
        self.assertEqual(r["rowFirstGroup"], ["composer", "people"])
        self.assertEqual(r["rowSecond"], "log")

        # the rendered DOM actually shows them side by side
        r = run_js(r"""
            const a = document.querySelector('.sash-window[data-win="composer"]')
                       .getBoundingClientRect();
            const b = document.querySelector('.sash-window[data-win="people"]')
                       .getBoundingClientRect();
            const c = document.querySelector('.sash-window[data-win="log"]')
                       .getBoundingClientRect();
            __r = {
              sameRow: Math.abs(a.top - b.top) < 2 && Math.abs(a.bottom - b.bottom) < 2,
              leftOf: a.right <= b.left + 8,          // a few px: the sash
              logRightOf: c.left >= b.right - 8,      // log kept its right slot
              logSameBand: Math.abs(c.top - b.top) < 8 && Math.abs(c.bottom - b.bottom) < 8,
              widths: [a.width, b.width],
            };
        """)
        self.assertTrue(r["sameRow"], "composer and people share a row (real layout)")
        self.assertTrue(r["leftOf"], "composer is to the left of people")
        self.assertTrue(r["logRightOf"], "log kept its right-side slot")
        self.assertTrue(r["logSameBand"], "log spans the same vertical band")
        self.assertGreater(r["widths"][0], 100, "composer has real width")
        self.assertGreater(r["widths"][1], 100, "people has real width")

        # ── 3. resize the row and check persistence ─────────────────
        r = run_js(r"""
            const t = SashGrid.getTree();
            const f = SashCore.findNode(t, 'people');
            const path = SashCore.parentPath(t, 'people');
            SashGrid.simulateResize(path.join('-'), 30);
            const t2 = SashGrid.getTree();
            const f2 = SashCore.findNode(t2, 'people');
            const stored = localStorage.getItem('chatbot.sashLayout.v1');
            const parsed = stored ? JSON.parse(stored) : null;
            __r = {
              newSizes: f2.parent.sizes,
              storedValid: parsed && SashCore.deserialize(stored).ok === true,
              storedMatches: parsed && JSON.stringify(parsed.tree) ===
                             JSON.stringify(t2),
              rect: document.querySelector('.sash-window[data-win="composer"]')
                    .getBoundingClientRect().width,
            };
        """)
        self.assertAlmostEqual(r["newSizes"][0], 30, delta=0.5)
        self.assertTrue(r["storedValid"], "layout persisted to localStorage")
        self.assertTrue(r["storedMatches"], "stored tree == live tree")
        self.assertLess(r["rect"], 700, "composer got visibly narrower (1400px window)")

        # ── 4. preset Layout C: log spans the hero rows ─────────────
        r = run_js(r"""
            SashGrid.setLayout('c');
            const t = SashGrid.getTree();
            const hero = t.children[0];
            const logRect = document.querySelector('.sash-window[data-win="log"]')
                             .getBoundingClientRect();
            const compRect = document.querySelector('.sash-window[data-win="composer"]')
                              .getBoundingClientRect();
            const pplRect = document.querySelector('.sash-window[data-win="people"]')
                             .getBoundingClientRect();
            __r = {
              valid: SashCore.validate(t) === null,
              heroDir: hero.dir,
              heroRight: SashCore.isLeaf(hero.children[1]) ? hero.children[1].id : 'group',
              heroLeft: SashCore.isSplit(hero.children[0])
                        ? hero.children[0].children.map(c => c.id) : 'leaf',
              logTall: logRect.height >= compRect.height + pplRect.height - 8,
              logRight: logRect.left >= compRect.right - 8,
            };
        """)
        self.assertTrue(r["valid"])
        self.assertEqual(r["heroDir"], "row")
        self.assertEqual(r["heroRight"], "log")
        self.assertEqual(r["heroLeft"], ["composer", "people"])
        self.assertTrue(r["logTall"],
                        "log window spans BOTH hero rows (real rendered height)")
        self.assertTrue(r["logRight"], "log is the right side column")

        # ── 5. REAL pointer drag & drop (dispatched PointerEvents) ──
        # reset to the default layout, then drag the Log Console title bar
        # to the LEFT edge of the Action Stack through the actual engine
        r = run_js(r"""
            SashGrid.setLayout('default');
            const title = document.querySelector('.sash-window[data-win="log"] .win-title');
            const target = document.querySelector('.sash-window[data-win="stack"]')
                           .getBoundingClientRect();
            const tr = title.getBoundingClientRect();
            const down = {
              clientX: tr.left + tr.width / 2, clientY: tr.top + tr.height / 2,
              button: 0, pointerId: 7, bubbles: true,
            };
            title.dispatchEvent(new PointerEvent('pointerdown', down));
            // move in small steps to cross the 4px threshold
            const midX = tr.left + tr.width / 2, midY = tr.top + tr.height / 2;
            const leftX = target.left + 6, leftY = target.top + target.height / 2;
            const steps = 8;
            for (let i = 1; i <= steps; i++) {
              document.dispatchEvent(new PointerEvent('pointermove', {
                clientX: midX + (leftX - midX) * i / steps,
                clientY: midY + (leftY - midY) * i / steps,
                button: 0, pointerId: 7, bubbles: true,
              }));
            }
            const during = {
              dragging: document.body.classList.contains('sash-dragging'),
              hasVisual: !!document.querySelector('.sash-drag-clone, .sash-drag-ghost'),
              hasIndicator: !!document.querySelector('.sash-drop-indicator') &&
                            document.querySelector('.sash-drop-indicator').style.display !== 'none',
              sourceMarked: document.querySelector('.sash-window[data-win="log"]')
                            .classList.contains('sash-drag-source'),
              badge: document.querySelector('.sash-drag-badge') ?
                     document.querySelector('.sash-drag-badge').textContent : null,
            };
            document.dispatchEvent(new PointerEvent('pointerup', {
              clientX: leftX, clientY: leftY, button: 0, pointerId: 7, bubbles: true,
            }));
            const t = SashGrid.getTree();
            const f = SashCore.findNode(t, 'stack');
            __r = {
              during,
              valid: SashCore.validate(t) === null,
              oneLog: SashCore.leafIds(t).filter(x => x === 'log').length === 1,
              splitDir: f.parent ? f.parent.dir : null,
              order: f.parent ? f.parent.children.map(c => c.id) : null,
              cleanup: !document.body.classList.contains('sash-dragging') &&
                       !document.querySelector('.sash-drag-clone, .sash-drag-ghost, .sash-drop-indicator'),
            };
        """)
        self.assertTrue(r["during"]["dragging"], "dragging state was active")
        self.assertTrue(r["during"]["hasVisual"], "clone/ghost followed the cursor")
        self.assertTrue(r["during"]["hasIndicator"], "drop indicator was visible")
        self.assertTrue(r["during"]["sourceMarked"], "source window dimmed")
        self.assertIn("Log Console", r["during"]["badge"])
        self.assertIn("Action Stack", r["during"]["badge"])
        self.assertTrue(r["valid"])
        self.assertTrue(r["oneLog"])
        self.assertEqual(r["splitDir"], "row")
        self.assertEqual(r["order"], ["log", "stack"])
        self.assertTrue(r["cleanup"], "all drag visuals removed after drop")

        # ── 5b. Escape cancels a drag ─────────────────────────────
        r = run_js(r"""
            const before = SashCore.serialize(SashGrid.getTree());
            const title = document.querySelector('.sash-window[data-win="composer"] .win-title');
            const tr = title.getBoundingClientRect();
            const midX = tr.left + tr.width / 2, midY = tr.top + tr.height / 2;
            title.dispatchEvent(new PointerEvent('pointerdown',
              { clientX: midX, clientY: midY, button: 0, pointerId: 9, bubbles: true }));
            document.dispatchEvent(new PointerEvent('pointermove',
              { clientX: midX + 30, clientY: midY + 30, button: 0, pointerId: 9, bubbles: true }));
            const active = document.body.classList.contains('sash-dragging');
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
            const after = SashCore.serialize(SashGrid.getTree());
            __r = {
              active,
              cancelled: !document.body.classList.contains('sash-dragging') &&
                         after === before &&
                         !document.querySelector('.sash-drag-clone, .sash-drag-ghost'),
            };
        """)
        self.assertTrue(r["active"], "drag became active before Escape")
        self.assertTrue(r["cancelled"], "Escape cancelled the drag, layout unchanged")

        # ── 5c. REAL sash resize (pointer events on the separator) ──
        r = run_js(r"""
            SashGrid.setLayout('default');
            // bottom row of the default layout: [people | log], root path "2"
            const split = document.querySelector('.sash-split[data-path="2"]');
            const sash = split.querySelector('.sash');
            const r1 = sash.getBoundingClientRect();
            const r2 = split.getBoundingClientRect();
            sash.dispatchEvent(new PointerEvent('pointerdown', {
              clientX: r1.left + r1.width / 2, clientY: r1.top + r1.height / 2,
              button: 0, pointerId: 11, bubbles: true }));
            // drag the boundary to ~35% of the row width
            const targetX = r2.left + r2.width * 0.35;
            for (let i = 1; i <= 6; i++) {
              const x = (r1.left + r1.width/2) + (targetX - (r1.left + r1.width/2)) * i / 6;
              document.dispatchEvent(new PointerEvent('pointermove', {
                clientX: x, clientY: r1.top + r1.height / 2,
                button: 0, pointerId: 11, bubbles: true }));
            }
            document.dispatchEvent(new PointerEvent('pointerup', {
              clientX: targetX, clientY: r1.top + r1.height / 2,
              button: 0, pointerId: 11, bubbles: true }));
            const t = SashGrid.getTree();
            const row = SashCore.findNode(t, 'people').parent;
            const ppl = document.querySelector('.sash-window[data-win="people"]')
                        .getBoundingClientRect().width;
            const logW = document.querySelector('.sash-window[data-win="log"]')
                        .getBoundingClientRect().width;
            const pplBefore = ppl; // (post-resize) — compare the two windows instead
            __r = {
              resizingCursor: 'checked-below',
              sizes: row.sizes,
              ratio: ppl / (ppl + logW),
              pplWidth: ppl, logWidth: logW,
            };
        """)
        self.assertAlmostEqual(r["ratio"], 0.35, delta=0.03,
                               msg="sash drag moved the boundary to ~35% (real layout)")
        self.assertAlmostEqual(r["sizes"][0], 35, delta=3,
                               msg="committed size matches the pointer fraction")
        self.assertGreater(r["pplWidth"], 100)
        self.assertGreater(r["logWidth"], 100)

        # double-click the sash → the split resets to even sizes
        r = run_js(r"""
            const split = document.querySelector('.sash-split[data-path="2"]');
            const sash = split.querySelector('.sash');
            const r1 = sash.getBoundingClientRect();
            sash.dispatchEvent(new MouseEvent('dblclick', {
              clientX: r1.left + r1.width / 2, clientY: r1.top + r1.height / 2,
              bubbles: true }));
            const row = SashCore.findNode(SashGrid.getTree(), 'people').parent;
            __r = { sizes: row.sizes };
        """)
        self.assertAlmostEqual(r["sizes"][0], 50, delta=0.5, msg="dblclick resets to even")

        # ── 6. reload → persisted layout must be restored ───────────
        before = run_js("__r = SashCore.serialize(SashGrid.getTree());")
        view.reload()
        t0 = time.time()
        state["loaded"] = False
        while not state["loaded"] and time.time() - t0 < 30:
            app.processEvents()
            time.sleep(0.02)
        self.assertTrue(state["loaded"], "reload failed")
        time.sleep(0.5)
        app.processEvents()
        after = run_js("__r = SashCore.serialize(SashGrid.getTree());")
        self.assertEqual(after, before, "persisted layout survives a reload")

        # ── 7. hidden windows release their space; grid always fills ──
        # (regression: with the hidden Block Config window as the only
        #  "wide" child, the root split shrank to content width and left a
        #  fixed empty gap on the right)
        r = run_js(r"""
            const grid = document.getElementById('sashGrid');
            const rootEl = grid.firstElementChild;
            const cfg = document.querySelector('.sash-window[data-win="config"]');
            const stackSash = cfg.parentElement.querySelector('.sash');
            __r = {
              gridW: grid.offsetWidth,
              rootW: rootEl.offsetWidth,
              cfgW: cfg.offsetWidth,
              cfgHiddenClass: cfg.classList.contains('sash-win-hidden'),
              cfgDisplay: getComputedStyle(cfg).display,
              cfgSashHidden: stackSash.classList.contains('sash-hidden'),
              stackW: document.querySelector('.sash-window[data-win="stack"]').offsetWidth,
            };
        """)
        self.assertAlmostEqual(r["rootW"], r["gridW"], delta=2,
                               msg="root split fills the grid (default layout)")
        self.assertEqual(r["cfgW"], 0, "hidden Block Config takes no space")
        self.assertTrue(r["cfgHiddenClass"], "wrapper marked sash-win-hidden")
        self.assertEqual(r["cfgDisplay"], "none")
        self.assertTrue(r["cfgSashHidden"], "sash next to the hidden window is hidden")
        self.assertGreater(r["stackW"], 700,
                           "stack absorbed the hidden config's share (1400px window)")

        # the user's repro: root row [ log | config(hidden) ] — the log must
        # fill the whole grid, no gap
        r = run_js(r"""
            SashGrid.root = SashCore.split('row',
              [SashCore.leaf('log'), SashCore.leaf('config')], [50, 50]);
            SashGrid.render();
            const grid = document.getElementById('sashGrid');
            __r = {
              gridW: grid.offsetWidth,
              rootW: grid.firstElementChild.offsetWidth,
              logW: document.querySelector('.sash-window[data-win="log"]').offsetWidth,
              cfgW: document.querySelector('.sash-window[data-win="config"]').offsetWidth,
              sashHidden: document.querySelector('.sash').classList.contains('sash-hidden'),
            };
        """)
        self.assertAlmostEqual(r["rootW"], r["gridW"], delta=2,
                               msg="root fills the grid even when the only wide child is hidden")
        self.assertAlmostEqual(r["logW"], r["gridW"], delta=10,
                               msg="visible window expands to the full width — no fixed gap")
        self.assertEqual(r["cfgW"], 0, "hidden window collapsed")
        self.assertTrue(r["sashHidden"], "sash touching the hidden window is gone")

        # showing Block Config gives it back its stored share (50%) and the
        # sash reappears (MutationObserver — wait for the microtask)
        run_js("__r = (document.getElementById('blockConfigPanel').classList.remove('hidden'), 'ok');")
        time.sleep(0.15)
        app.processEvents()
        r = run_js(r"""
            const grid = document.getElementById('sashGrid');
            const sash = document.querySelector('.sash');
            __r = {
              gridW: grid.offsetWidth,
              logW: document.querySelector('.sash-window[data-win="log"]').offsetWidth,
              cfgW: document.querySelector('.sash-window[data-win="config"]').offsetWidth,
              cfgHiddenClass: document.querySelector('.sash-window[data-win="config"]')
                              .classList.contains('sash-win-hidden'),
              sashHidden: sash.classList.contains('sash-hidden'),
              sashDisplay: getComputedStyle(sash).display,
            };
        """)
        half = r["gridW"] / 2
        self.assertAlmostEqual(r["cfgW"], half, delta=half * 0.05,
                               msg="shown config regained its stored 50% share")
        self.assertAlmostEqual(r["logW"], half, delta=half * 0.05,
                               msg="log shrank to give the config its share")
        self.assertFalse(r["cfgHiddenClass"], "wrapper no longer marked hidden")
        self.assertFalse(r["sashHidden"], "sash back between the two visible windows")
        self.assertEqual(r["sashDisplay"], "block")

        # hiding it again releases the space once more
        run_js("__r = (document.getElementById('blockConfigPanel').classList.add('hidden'), 'ok');")
        time.sleep(0.15)
        app.processEvents()
        r = run_js(r"""
            const grid = document.getElementById('sashGrid');
            __r = {
              gridW: grid.offsetWidth,
              rootW: grid.firstElementChild.offsetWidth,
              logW: document.querySelector('.sash-window[data-win="log"]').offsetWidth,
              cfgW: document.querySelector('.sash-window[data-win="config"]').offsetWidth,
              sashHidden: document.querySelector('.sash').classList.contains('sash-hidden'),
            };
        """)
        self.assertAlmostEqual(r["logW"], r["gridW"], delta=10,
                               msg="hiding the window releases its space again")
        self.assertEqual(r["cfgW"], 0)
        self.assertTrue(r["sashHidden"])

        # restore the default layout for a clean final state
        run_js("__r = SashGrid.setLayout('default');")

        # ── 6. no JS errors ─────────────────────────────────────────
        js_errors = [m for lvl, m in console if "Uncaught" in m]
        self.assertEqual(js_errors, [], "JS console errors: " + repr(js_errors))


if __name__ == '__main__':
    unittest.main(verbosity=2)
