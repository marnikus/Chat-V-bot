#!/usr/bin/env python3
"""Rebuild the gcc stub libraries that let PySide6 import headless on a
system without GL / NSS / ALSA / dbus / X (apt not available or blocked).

Everything is derived from the venv's own ELF binaries — no hardcoding:

  1. scan every ELF under PySide6/shiboken6 for NEEDED sonames that
     cannot be resolved anywhere;
  2. for each missing soname, collect the UNDEFINED dynamic symbols all
     consumers import, together with their ELF version nodes (readelf -V
     ``File:`` / ``Name:`` lines map every node to its provider);
  3. emit one stub .c per soname and compile it with a version script
     declaring EVERY version node the consumers need.

Hard-won gotchas (2026-09-09, Chat-V-bot sandbox):
  * a versioned consumer MUST NOT be satisfied by a stub lacking the
    matching version script — ld.so aborts with the dl-lookup.c
    assertion otherwise;
  * symbol lists must come from ALL consumers of a soname, not one;
  * never shadow glibc/Qt: stub only sonames that are missing AND only
    the symbols actually imported from them (version-node mapping);
  * an empty stub (no symbols) is still needed for pure NEEDED
    resolution — a genuinely called symbol then surfaces as a clear
    "undefined symbol" error that can be mapped and re-stubbed.

Usage:  python3 tools/build_stubs.py [venv_dir] [out_dir]
        export LD_LIBRARY_PATH=<out_dir>
"""
import os
import re
import subprocess
import sys
from collections import defaultdict

VENV = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".venv")
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/stublibs"

SEARCH_DIRS = [
    "/lib/x86_64-linux-gnu", "/usr/lib/x86_64-linux-gnu",
    "/lib", "/usr/lib", "/usr/local/lib", OUT,
]

# fallback prefix map for UNVERSIONED undefined symbols
PREFIX_MAP = [
    ("snd_", "libasound.so.2"),
    ("glX", "libGL.so.1"), ("gl", "libGL.so.1"), ("GL", "libGL.so.1"),
    ("egl", "libEGL.so.1"), ("EGL", "libEGL.so.1"),
    ("xkb_", "libxkbcommon.so.0"), ("xkbcommon", "libxkbcommon.so.0"),
    ("Xkb", "libxkbfile.so.1"),
    ("XFixes", "libXfixes.so.3"),
    ("XDamage", "libXdamage.so.1"),
    ("XComposite", "libXcomposite.so.1"),
    ("XRR", "libXrandr.so.2"), ("Xrandr", "libXrandr.so.2"),
    ("XTest", "libXtst.so.6"), ("Xtst", "libXtst.so.6"),
    ("xcb_dri3", "libxcb-dri3.so.0"),
    ("dbus_", "libdbus-1.so.3"),
    ("PR_", "libnspr4.so"), ("PL_", "libnspr4.so"),
    ("gbm", "libgbm.so.1"),
    ("NSS_", "libnss3.so"),
    ("NSSUTIL", "libnssutil3.so"), ("_NSSUTIL", "libnssutil3.so"),
    ("SMIME_", "libsmime3.so"),
]


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def elf_files(root):
    for base, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(base, f)
            if os.path.isfile(p) and os.access(p, os.X_OK | os.R_OK):
                with open(p, "rb") as fh:
                    if fh.read(4) == b"\x7fELF":
                        yield p


def resolvable(soname, extra_dirs):
    for d in list(SEARCH_DIRS) + extra_dirs:
        if os.path.exists(os.path.join(d, soname)):
            return True
    return False


def main():
    site = os.path.join(VENV, "lib", "python3.11", "site-packages")
    roots = [os.path.join(site, "PySide6"),
             os.path.join(site, "shiboken6")]
    elves = [p for r in roots if os.path.isdir(r) for p in elf_files(r)]
    print(f"scanning {len(elves)} ELF files under {site}")

    # every directory under site-packages may hold the venv's own libs
    sp_dirs = sorted({os.path.dirname(p) for p in elves})
    needed = set()
    for p in elves:
        for m in re.finditer(r"NEEDED\s+(\S+)", run(["objdump", "-p", p])):
            needed.add(m.group(1))
    missing = sorted(s for s in needed if not resolvable(s, sp_dirs))
    print(f"missing sonames: {len(missing)}")
    if not missing:
        print("nothing to stub")
        return

    # node -> soname (from every consumer's version-need table) and
    # soname -> {node -> set(symbols)} from undefined dynsyms
    node_to_soname = {}
    stub_syms = defaultdict(lambda: defaultdict(set))

    for p in elves:
        out = run(["readelf", "-V", "-W", p])
        # .gnu.version_r blocks:
        #   000000: Version: 1  File: libdbus-1.so.3  Cnt: 2
        #   0x0010:   Name: LIBDBUS_1_3   Flags: none  Version: 11
        current_file = None
        for line in out.splitlines():
            m = re.search(r"File:\s+(\S+)", line)
            if m:
                current_file = m.group(1)
                continue
            m = re.search(r"Name:\s+(\S+)\s+Flags:", line)
            if m and current_file:
                node_to_soname.setdefault(m.group(1), current_file)

        syms = run(["readelf", "--dyn-syms", "-W", p])
        for line in syms.splitlines():
            m = re.match(
                r"\s*\d+:\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+UND\s+(\S+)", line)
            if not m:
                continue
            sym = m.group(1)
            if "@" in sym:
                base, node = sym.split("@", 1)
                node = node.split(" ")[0]
                soname = node_to_soname.get(node)
                if soname not in missing and not (
                        node.startswith(("NSSUTIL", "SMIME", "LIBDBUS"))):
                    continue
                if soname is None:
                    # node names often encode the provider
                    if node.startswith("NSSUTIL"):
                        soname = "libnssutil3.so"
                    elif node.startswith("NSS"):
                        soname = "libnss3.so"
                    elif node.startswith("SMIME"):
                        soname = "libsmime3.so"
                    elif node.startswith("NSPR"):
                        soname = "libnspr4.so"
                    elif node.startswith("ALSA"):
                        soname = "libasound.so.2"
                    elif node.startswith("V_"):
                        soname = "libxkbcommon.so.0"
                    elif node.startswith("XKB"):
                        soname = "libxkbcommon.so.0"
                    elif node.startswith("LIBDBUS"):
                        soname = "libdbus-1.so.3"
                    elif node.startswith("XTEST"):
                        soname = "libXtst.so.6"
                    else:
                        continue
                stub_syms[soname][node].add(base)
            else:
                # unversioned: match by prefix (never shadow glibc — only
                # prefixes nobody else serves)
                for prefix, soname in PREFIX_MAP:
                    if sym.startswith(prefix) and soname in missing:
                        stub_syms[soname][""].add(sym)
                        break

    # every truly-missing soname gets a stub — with symbols when we
    # collected them, empty otherwise (satisfies NEEDED resolution)
    for soname in missing:
        stub_syms.setdefault(soname, defaultdict(set))
    os.makedirs(OUT, exist_ok=True)
    for soname in sorted(s for s in stub_syms if s in missing):
        nodes = stub_syms[soname]
        base = soname.split(".so")[0]
        c_path = os.path.join(OUT, base + "_stub.c")
        ver_path = os.path.join(OUT, base + ".ver")
        all_syms = sorted(s for syms in nodes.values() for s in syms)
        with open(c_path, "w") as fh:
            fh.write("/* generated stub */\n")
            fh.write("#include <stdlib.h>\n")
            for s in all_syms:
                fh.write(f"void {s}(void) {{ abort(); }}\n")
        script_lines = []
        for node in sorted(nodes):
            if not node:
                continue
            syms = sorted(nodes[node])
            script_lines.append(
                f"{node} {{\n  global: " + "; ".join(syms) + ";\n};")
        with open(ver_path, "w") as fh:
            fh.write("\n".join(script_lines) + ("\n" if script_lines else ""))
        cmd = ["gcc", "-shared", "-fPIC", "-o", os.path.join(OUT, soname),
               "-Wl,-soname," + soname, c_path]
        if script_lines:
            cmd += ["-Wl,--version-script=" + ver_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        status = "OK" if r.returncode == 0 else "FAIL " + r.stderr[:200]
        n_nodes = len([n for n in nodes if n])
        print(f"  {soname:22s} {len(all_syms):3d} syms / {n_nodes} nodes "
              f"-> {status}")
    print("done →", OUT)


if __name__ == "__main__":
    main()
