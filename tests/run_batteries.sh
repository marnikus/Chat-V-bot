#!/usr/bin/env bash
# Tiered test battery for Chat-V-bot (2026-09-15).
#
# The old story was one 6-minute `pytest tests/` command for everything.
# That forced every small change to pay for the subprocess-heavy quality
# gates and the whole-repo Node coverage run. The battery is now tiers:
#
#   fast     unit tests only, parallel            (~40-60 s)
#   medium   every Python test except the gates,  (~2-3 min)
#            parallel via pytest-xdist
#   gates    the subprocess-heavy quality gates   (~35 s)
#            (js_gate runs the Node suites under
#             V8 coverage; rule16 runs vulture /
#             pylint / the AST clone scan)
#   js       the Node suites, parallel            (~5 s)
#   full     js + medium + gates — the complete
#            battery, what a commit must pass     (~3 min)
#
# Usage:
#   tests/run_batteries.sh [fast|medium|gates|js|full] [extra pytest args]
#
# The Node suites are independent processes (each one owns its globals),
# so they run with xargs -P. pytest runs are parallel with `-n auto`;
# the suites are isolation-checked for this (per-test tempfile dirs, no
# fixed paths, no sockets — see docs/current/TEST_BATTERY_TIERS_2026-09-15.md).
set -u

cd "$(dirname "$0")/.."
PY=".venv/bin/python"
run_pytest() { "$PY" -m pytest "$@"; }
LIBS="/tmp/stublibs"
if [ -d "$LIBS" ]; then
    export LD_LIBRARY_PATH="$LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

run_js() {
    # 41 independent Node suites — parallel, one line each on failure.
    local jobs="${JOBS:-$(nproc)}"
    local fail=0
    if command -v xargs >/dev/null 2>&1; then
        local out
        out=$(ls tests/test_*.js | xargs -P "$jobs" -I{} sh -c \
            'node {} >/dev/null 2>&1 || echo FAIL {}' )
        if [ -n "$out" ]; then
            fail=1
            echo "$out" | sed 's/^/  /'
        fi
    else
        local f
        for f in tests/test_*.js; do
            node "$f" >/dev/null 2>&1 || { echo "  FAIL $f"; fail=1; }
        done
    fi
    echo "js: node suites $([ $fail -eq 0 ] && echo OK || echo FAILED)"
    return $fail
}

# Tests that run external scanners (pylint / vulture / V8 coverage) —
# parallelising them would only multiply the subprocess work.
GATES=(tests/test_js_gate.py tests/test_rule16_new_code.py)
WEBENGINE=tests/test_sash_webengine.py   # real QWebEngine; runs on demand

run_py() {  # $1 = label, rest = pytest args
    local label=$1; shift
    echo "── $label ──"
    run_pytest -q -n auto "$@" && return 0
    return 1
}

case "${1:-full}" in
    js)
        run_js
        ;;
    fast)
        run_py "fast (unit, parallel)" tests/unit "${@:2}"
        ;;
    medium)
        run_py "medium (all Python except gates, parallel)" \
            tests/ \
            --ignore="$WEBENGINE" \
            --deselect=tests/test_js_gate.py \
            --deselect=tests/test_rule16_new_code.py \
            "${@:2}"
        ;;
    gates)
        run_py "gates (serial)" "${GATES[@]}" "${@:2}"
        ;;
    full)
        rc=0
        run_js || rc=1
        run_pytest -q -n auto tests/ \
            --ignore="$WEBENGINE" \
            --deselect=tests/test_js_gate.py \
            --deselect=tests/test_rule16_new_code.py "${@:2}" || rc=1
        run_py "gates (serial)" "${GATES[@]}" || rc=1
        echo
        if [ $rc -eq 0 ]; then
            echo "full battery: GREEN (js + python parallel + gates)"
        else
            echo "full battery: RED — see above"
        fi
        exit $rc
        ;;
    *)
        echo "usage: $0 [fast|medium|gates|js|full]" >&2
        exit 2
        ;;
esac
