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
  to a field touched by an affected action. It also flags irreversible actions.
  Passing preflight permits an attempted conditional replay; it is not evidence
  of completed recovery.
- `scripts/inspect_provenance.py` exports the graph, impact set, and (when the
  attempt database is present) the recovery preflight from a paired experiment.

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
```

The incorrect-port case should invalidate the Config result and Planner, link
four executor actions to the plan, and leave the independent administrator
worker-scale event outside that impact set. The preflight retains the
Dependency and Resource results while their recorded read versions remain
current. A later administrator write to `api.db_port` causes a same-field
conflict; the preflight will decline automatic replay.

Generated `results/` files and SQLite databases are ignored by Git. Share an
experiment artifact separately when another team member must audit it.

## Next implementation boundary

The selective replay executor still needs to recompute invalid results, issue
new conditional tool writes, validate side effects and external updates, and
run the final checker before reporting complete, partial, or blocked recovery.
The current full-restart baseline replays one fixed worker-scale event; a
general external-event schedule and replay mechanism remains to be built.
