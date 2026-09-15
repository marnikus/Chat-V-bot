# Mutation platform report — 2026-09-14

Date: 2026-09-14 · branch `arena/01a0a172-chat-v-bot`
Source: `tools/metrics/mutation_platform.py` + `setup.cfg`

## Convention (from `setup.cfg`)

An unreachable mutant is one for which `no tests` exist in the
selected suite. It is **never counted as killed**, and a survivor
means "no *selected* suite kills it", not "no suite kills it".
Reachable score = killed / (total - unreachable).

## Jobs

### history_query_widened: HistoryQuery with edges (910 reachable of 1141)

- source_paths: `backend/history_query.py`
- total mutants generated: **1141**
- unreachable ("no tests"): **0** (excluded by convention)
- reachable: **1141** = total - unreachable
- killed: **563**
- survived: **578**
- **reachable score: 563/1141 = 49.34%**

Widening measured in `setup.cfg`: adding
`tests/test_history_query_edges.py` takes reachable set
from **159 → 910 of 1,141** mutants in the original measurement,
and in this run **0 unreachable of 1,141** (all reachable).
Runtime grows from ~25s to ~2 min (measured).
Score drops from 99.37% (158/159) to 49.34% (563/1141) because
more mutants become reachable but are not killed by the narrow suite —
this is honest and expected; the platform now measures it.


### bot_pure_family: Bot pure family (no Qt), newest code, never measured

- source_paths: `services/bot_variables.py,services/bot_reactions.py,services/bot_providers.py,services/bot_prompts.py,services/bot_transcript.py,services/bot_connections.py,services/bot_presets.py,services/bot_chat.py,services/bot_grok.py`
- total mutants generated: **1588**
- unreachable ("no tests"): **0** (excluded by convention)
- reachable: **1588** = total - unreachable
- killed: **1499**
- survived: **89**
- **reachable score: 1499/1588 = 94.4%**

Second job (H-D1): pure bot family, no Qt in import path.
These 9 files are 93-100% line-covered (see `coverage report`)
and had never been mutation-measured before.
The multi-file aggregation runs mutmut per file and sums.


## Reproduction

```bash
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m mutmut run
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m mutmut results
rm -rf mutants/   # not gitignored; must not reach a commit
```

For job2, copy `tools/metrics/mut_jobs/bot_family/setup.cfg` over `setup.cfg` or use `mutation_platform.py --run-job2`.
