import sys, os, subprocess, glob
ROOT="/home/user/Chat-V-bot"
files=[]
for pat in ("tests/integration/services/*.py","tests/unit/backend/*.py","tests/unit/core/*.py","tests/*.py"):
    files += sorted(glob.glob(os.path.join(ROOT,pat)))
files=[f for f in files if f.endswith(".py") and not f.endswith("test_run_service_paths.py")]
mods=[]
for f in files:
    rel=os.path.relpath(f,ROOT)
    mods.append(rel[:-3].replace("/","."))
probe = '''
import sys, os, tempfile, types
sys.path.insert(0, %r)
from PySide6.QtCore import QObject
from backend.bridge import Bridge
from backend.config_manager import ConfigManager
tmp = tempfile.mkdtemp(); cfg = ConfigManager(os.path.join(tmp, "config.json"))
br = Bridge.__new__(Bridge)
QObject.__init__(br)
br._config = cfg
br._engine = types.SimpleNamespace(load_stack=lambda _b: None)
try:
    br.get_grid_layout()
    print("PROBE_OK")
except Exception as e:
    print("PROBE_FAIL", type(e).__name__, str(e)[:110])
''' % ROOT

# cumulative import bisect
lo, hi = 0, len(mods)
def works(n):
    pre = "\n".join("import %s" % m for m in mods[:n])
    code = "import sys, os\nsys.path.insert(0, %r)\nsys.path.insert(0, %r)\n" % (ROOT, os.path.join(ROOT,"tests"))
    code += pre + "\n" + probe
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={**os.environ, "QT_QPA_PLATFORM":"offscreen", "LD_LIBRARY_PATH":"/tmp/stublibs"})
    out = p.stdout.strip().splitlines()
    return ("PROBE_OK" in (out[-1] if out else "")), (out[-1] if out else p.stderr.strip().splitlines()[-1] if p.stderr else "?")
print("imports 0 ->", works(0))
# linear scan in steps of 5, then refine
n=0
bad=None
while n <= len(mods):
    ok,msg = works(n)
    if not ok:
        bad=n; print("BREAKS at %d imports: %s" % (n,msg)); break
    n+=5
if bad is None:
    print("never breaks with all", len(mods))
else:
    for k in range(bad-5, bad+1):
        ok,msg = works(k)
        print(k, "OK" if ok else "FAIL", mods[k-1] if not ok else "", msg[:80])
