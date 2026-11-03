# Runtime and Recovery Work

This document records the current C workstream and its verification boundary.
The fault identity is supplied by the experiment harness. StateGuard does not
claim to detect arbitrary faulty agents automatically.

## What is implemented

- Each analysis and planner result is saved in SQLite with its result ID,
  parent result IDs, read set, status, token count, and latency. Tool writes,
  action-ledger entries, and state events already commit transactionally.
- `build_provenance` constructs typed edges for result consumption, field-version
  reads, tool triggers, committed events, and produced state versions. It reports
  missing parents and unobserved read versions instead of fabricating edges.
- `impacted_by(faulty_result_id)` traverses downstream nodes and reports the
  affected results, actions, events, and field versions.
- `assess_recovery` compares recorded read versions to the current SQLite state,
  invalidates descendants, identifies reusable results, and flags a later write
  to a field touched by an affected action. It also identifies irreversible
  actions so a corrected final state can be reported as partial recovery.
  Passing preflight permits an attempted conditional replay; it is not evidence
  of completed recovery.
- `scripts/inspect_provenance.py` exports the graph, impact set, and (when the
  attempt database is present) the recovery preflight from a paired experiment.
- `recover_selectively` reuses valid analysis results, recomputes invalid agents
  and the planner, and writes only changed fields. Versions are captured before
  planning and passed to conditional SQLite updates. A concurrent change or
  same-field administrator update yields `blocked` without overwriting it.
  The final checker sees both the original attempt and recovery actions.
- The paired `full_restart` policy now performs a second clean attempt in a
  fresh database. It replays the actual external events recorded by the first
  attempt in order, checks each event's old value and version, and includes
  both attempts in cost metrics. A changed replay precondition is `blocked`.

The graph is deliberately conservative at result granularity. The planner
records all three input result IDs, so a change to an unused field may still
invalidate the planner. This can reduce retained work; it cannot be interpreted
as precise field-level semantic use without additional instrumentation.

## Reproduce the example

```bash
python -m pip install -e '.[dev]'
python -m pip install -r requirements-eval.txt
pytest -q
python scripts/run_paired_experiment.py --output results/paired --seed 7
python scripts/inspect_provenance.py results/paired/pairs/incorrect-db-port-3306__no_recovery__seed-7/paired.json --output results/paired/incorrect-port-impact.json
python scripts/run_paired_experiment.py --policy full_restart --cases incorrect-db-port-3306 --output results/full-restart --no-figures
python scripts/run_paired_experiment.py --policy selective_recovery --cases incorrect-db-port-3306 --output results/selective --no-figures
```

The incorrect-port case should invalidate the Config result and Planner, link
four executor actions to the plan, and leave the independent administrator
worker-scale event outside that impact set. The preflight retains the
Dependency and Resource results while their recorded read versions remain
current. A later administrator write to `api.db_port` causes a same-field
conflict; the preflight will decline automatic replay.

Generated `results/` files and SQLite databases are ignored by Git. Share an
experiment artifact separately when another team member must audit it.

## Custom external event schedule

Pass `--external-events schedule.json` to the paired runner. The file contains
an ordered list, for example:

```json
[
  {"key": "worker.replicas", "value": 3, "actor": "admin"},
  {"key": "api.replicas", "value": 4, "actor": "admin"}
]
```

The runner applies these updates after the deployment attempt and records the
actual value/version transitions. Full restart replays those recorded events,
not the input list alone. Early blocked attempts under a recovery policy still
record the scheduled administrator updates. An event whose original pre-state
cannot be reproduced stops replay, and the final checker reports failure.

## Limits

This is a controlled SQLite workflow. Conditional writes do not undo an
irreversible external service action. Such effects remain visible and recovery
is reported as partial if the final task can otherwise be corrected. The default
workload only performs reversible configuration writes. The
planner names whole analysis results as parents, so invalidation can be
conservative when only an unused field is faulty. Arbitrary browser state,
remote APIs, and automatic fault detection remain outside this implementation.
