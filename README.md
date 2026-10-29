# CSE 291A StateGuard

**Failure Propagation and State-Consistent Recovery in Multi-Agent Systems**

[![Tests](https://github.com/ashley-tech628/CSE291A-StateGuard/actions/workflows/tests.yml/badge.svg)](https://github.com/ashley-tech628/CSE291A-StateGuard/actions/workflows/tests.yml)

StateGuard is a research prototype for studying how failures propagate through tool-using multi-agent systems and how affected work can be recovered without discarding valid computation or overwriting legitimate external changes.

The project is developed for CSE 291A Option 5. It combines agent provenance, versioned shared state, controlled side effects, fault injection, and reproducible evaluation in a small software-deployment workflow.

## Research Problem

Multi-agent systems pass intermediate results through messages, delegated tasks, and shared state. An incorrect or malicious result can influence a planner, trigger tool calls, and produce persistent changes before the original failure is detected.

Recovery is difficult because the environment may continue changing. Another agent may complete independent work, an administrator may update the same service, or a tool action may commit even when its acknowledgment is lost. Restoring an old snapshot can therefore erase valid work, while replaying every action can repeat non-idempotent side effects.

StateGuard investigates the following questions:

1. How do faulty results propagate through message dependencies, state reads, and tool actions?
2. Which completed results remain valid after a fault is identified?
3. Can dependency-aware, state-aware recovery reduce recomputation while preserving correctness and legitimate external updates?
4. What latency, inference cost, and tracking overhead are introduced by more precise recovery?

## System Overview

The experimental workflow models a small software deployment:

    Config Agent --------\
    Dependency Agent -----+--> Planner --> Executor --> Controlled Tools
    Resource Agent -------/                         |
                                                     v
                                          Versioned Shared State
                                                     |
                                                     v
                                             Correctness Checker

The agents inspect service configuration, compatibility, and resource constraints. The planner combines their structured outputs into a deployment plan. The executor performs version-checked tool actions against an SQLite state store.

StateGuard records four types of execution objects:

- Agent results, including consumed upstream result IDs and state versions
- Tool actions, including expected versions, write sets, and effect classes
- State events, including before and after versions
- External events, including legitimate administrator or concurrent-agent updates

Together, these objects form a typed execution graph with consumes, reads-from, produces-write, and triggers relationships.

## Key Design Principles

### Explicit provenance

Dependencies are recorded during execution rather than inferred afterward by an LLM. A result identifies the specific upstream results and field versions it actually used.

### Field-level state versions

Each mutable field has its own version. Independent updates can therefore be distinguished from conflicting updates without invalidating an entire configuration object.

### Transactional event recording

A controlled state write, its version transition, and its committed event are stored in one SQLite transaction. The state and trace cannot silently diverge.

### Idempotent tool execution

Stable action IDs prevent duplicate writes when a tool commits successfully but its acknowledgment is lost. Reusing an action ID with different arguments is rejected.

### Conservative recovery

Missing provenance, conflicting versions, and irreversible side effects are reported explicitly. Recovery outcomes are classified as complete, partial, or blocked rather than treating recomputation alone as successful recovery.

## Project Phases

### Phase 1: Failure Propagation and Baselines

Phase 1 establishes a clean workflow, injects controlled faults, records their propagation, and compares baseline policies.

Fault classes include:

- Incorrect intermediate results
- Stale results based on outdated state or documentation
- Timeouts and lost acknowledgments
- Adversarial intermediate messages

Accidental and adversarial faults are reported separately. A fault counts as propagated only when a downstream stage actually consumes it.

The Phase 1 comparison includes:

- No recovery
- Full restart with valid external-event replay
- Always verify with bounded retry

### Phase 2: Selective Recovery

Phase 2 will implement and compare two selective recovery policies:

- Dependency-only replay, which invalidates downstream results using result dependencies
- State-aware selective recovery, which also validates field versions, tool effects, external updates, and action-ledger state

The planned recovery procedure is:

1. Receive the known faulty result ID from the experiment harness.
2. Traverse downstream result and state dependencies.
3. Identify committed actions and potentially affected fields.
4. Compare recorded reads and writes with the current environment.
5. Reuse results whose required dependencies remain valid.
6. Recompute invalid results and generate actions against the current state.
7. Execute conditional writes with expected versions and stable action IDs.
8. Run the final task and safety checkers.
9. Report complete, partial, or blocked recovery with supporting trace evidence.

Fault detection is intentionally separated from recovery in the core evaluation. Automated detection is an optional extension and must report false positives and missed faults independently.

## Current Implementation Status

| Component | Status |
| --- | --- |
| Shared result, action, event, and fault schemas | Implemented |
| SQLite field-level versions | Implemented |
| Atomic state and event transactions | Implemented |
| Action ledger and idempotent retries | Implemented |
| Config, Dependency, and Resource agents | Deterministic implementation |
| Planner and Executor | Deterministic implementation |
| Controlled authorization checks | Implemented |
| Incorrect, stale, timeout, and adversarial injection | Implemented |
| No-recovery baseline | Implemented |
| Full-restart baseline with external-event replay | Implemented |
| Always-verify baseline | Implemented |
| Trace, SQLite, CSV, and JSON export | Implemented |
| Real LLM adapter and structured-output validation | Planned |
| End-to-end lost-acknowledgment experiment | Planned |
| Dependency topology expansion | Planned |
| Dependency-only selective recovery | Phase 2 |
| State-aware selective recovery | Phase 2 |
| Recovery ablations and conflict-density experiments | Phase 2 |

## Deterministic Pilot

The current deterministic pilot validates the experiment harness before real model inference is introduced.

It runs:

- 8 deployment task variants
- 1 clean condition
- 4 injected fault conditions
- 3 baseline policies
- 120 total experiment runs

For seed 7:

- All 24 clean runs succeeded.
- Incorrect ports and stale protocols caused failures under no recovery.
- Timeout faults stopped at the Config Agent.
- All adversarial protected-field writes were rejected by the tool layer.
- Full restart produced a correct final state in all 32 fault scenarios and preserved the administrator update.
- Always verify corrected all 32 faults before planner consumption.
- Unauthorized committed actions were zero under every policy.
- The repository contains 17 passing automated tests.

The deterministic backend uses fixed structured outputs. The simulated token values are cost units for testing metrics and are not measured LLM tokens or evidence of model performance.

## Evaluation

The full evaluation will measure:

| Category | Metrics |
| --- | --- |
| Task quality | Clean success, recovered correctness, invariant satisfaction |
| Propagation | Consumed faults, affected results, affected fields, committed actions |
| Safety | Unauthorized attempts, unauthorized commits, residual effects |
| Recovery precision | Necessary invalidations, stale reuse, retained valid work |
| Cost | Recomputed stages, model calls, tokens, tool calls, wall-clock latency |
| Overhead | Clean-run tracking latency, log size, version checks |
| Conflict handling | Prevented lost updates, replanning, partial and blocked recoveries |

Real LLM experiments will use fixed model configurations and multiple seeds. Results will report means, failure details, confidence intervals, and p50/p95 latency.

## Installation

StateGuard requires Python 3.11 or later.

### Windows PowerShell

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    .\.venv\Scripts\python.exe -m pytest -q

### macOS and Linux

    python3.11 -m venv .venv
    .venv/bin/python -m pip install -e ".[dev]"
    .venv/bin/python -m pytest -q

## Running the Current Experiment

Run the deterministic experiment matrix:

    stateguard-experiment --output results/phase1-pilot --seed 7

Alternatively:

    python scripts/run_phase1.py --output results/phase1-pilot --seed 7

The runner cleans only output directories that contain a StateGuard ownership marker. It refuses to clean a nonempty directory that it did not create.

## Experiment Artifacts

A complete run produces:

- <code>summary.csv</code>: per-run task, propagation, safety, and cost metrics
- <code>report.json</code>: aggregate metrics grouped by policy
- <code>runs/&lt;scenario&gt;/trace.json</code>: results, dependencies, verification decisions, actions, state events, final state, and checker output
- <code>runs/&lt;scenario&gt;/*.sqlite3</code>: versioned state and action ledger for each attempt

The central trace chain is:

    faulty AgentResult
      -> Planner.parent_result_ids
      -> ToolAction.parent_result_ids
      -> StateEvent(action_id, before_version, after_version)
      -> final checker

The <code>fault_consumed</code> metric is true only when the planner actually uses the faulty result.

## Repository Structure

- <code>src/stateguard/schemas.py</code>: shared data contracts
- <code>src/stateguard/state.py</code>: versioned SQLite state, events, and idempotency
- <code>src/stateguard/workflow.py</code>: agents, planner, executor, faults, and checkers
- <code>src/stateguard/experiment.py</code>: workloads, baselines, metrics, and artifact export
- <code>scripts/run_phase1.py</code>: experiment entry point
- <code>tests/test_state.py</code>: state version and idempotency tests
- <code>tests/test_experiment.py</code>: propagation, authorization, baseline, and matrix tests
- <code>.github/workflows/tests.yml</code>: continuous integration

## Roadmap

### Near-term Phase 1 work

- Add a real model adapter and structured-output validation
- Record prompts, responses, model configuration, actual tokens, and retries
- Add planner faults, executor faults, tool failures, and lost acknowledgments
- Add chain, fan-out, diamond, independent-branch, and ignored-result workflows
- Run multiple seeds and produce the Phase 1 analysis and figures

### Phase 2 work

- Build the typed dependency graph and impact analyzer
- Implement dependency-only replay
- Implement version validation and state-aware reuse
- Add safe replay, conditional compensation, and blocked-recovery reporting
- Compare policies under unrelated updates, same-field conflicts, and shared-resource conflicts
- Measure invalidation precision, retained valid work, stale reuse, and recovery overhead
- Run ablations for provenance precision, version checks, and action-ID deduplication

## Team Workstreams

| Workstream | Primary responsibilities |
| --- | --- |
| Model and workflow | Model adapter, prompts, structured results, and workflow integration |
| Faults and evaluation | Workloads, fault schedules, checkers, metrics, plots, and analysis |
| Runtime and recovery | State versions, provenance, action ledger, baselines, selective recovery, and integration |

The team should review the shared schemas and a representative trace before developing separate branches. Schema changes must update the runner, checker, trace format, and tests together.

## Scope

StateGuard is a research prototype, not a production deployment system. The core implementation uses controlled tools and SQLite so that dependencies, side effects, and recovery decisions remain programmatically checkable. Docker-based service validation, additional models, automated fault detection, browser rollback, and microVM snapshots are optional extensions rather than prerequisites for the core study.
