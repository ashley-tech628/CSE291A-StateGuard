# StateGuard LLM integration update

This update targets the original Phase 1 repository and Jingwen's optional Config/Dependency adapters. It enables all three analysis agents and Planner through one adapter. Executor, SQLite state, authorization and final checker remain Python implementations.

## Install on the AWS machine

Place `StateGuard-LLM-update.zip` in `/home/ubuntu/stateguard-jingwen` using VS Code Remote SSH. In that project directory run:

```bash
python3 -m zipfile -e StateGuard-LLM-update.zip .
.venv/bin/python -m pip install -r requirements-llm.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/run_llm_phase1.py --suite clean
```

Keep the API environment variables configured in the same terminal. No credentials are included in these files. If a new terminal needs them:

```bash
export OPENAI_BASE_URL="https://tritonai-api.ucsd.edu/v1"
read -r -s -p "API key: " OPENAI_API_KEY
export OPENAI_API_KEY
printf '\n'
```

The archive overwrites `src/stateguard/workflow.py` and `src/stateguard/model_adapter.py`, and adds the runner, tests, requirements and this guide. It does not overwrite `schemas.py`, `state.py`, `experiment.py`, the project README, or previous results. Apply it in your personal checkout, and review the diff before merging team work.

## Commands

One clean task, four model stages:

```bash
.venv/bin/python scripts/run_llm_phase1.py --suite clean
```

Eight small integration scenarios (around 37 requests without retries):

```bash
.venv/bin/python scripts/run_llm_phase1.py --suite smoke
```

Smoke scenarios: clean/no recovery; incorrect/no recovery; incorrect/always verify; incorrect/full restart; stale/no recovery; stale/always verify; adversarial/no recovery; timeout/no recovery.

An incorrect or stale no-recovery run can legitimately FAIL. An adversarial instruction can be ignored by the model: inspect exposure and matching-write evidence rather than assuming attack propagation. Safe refusal can still fail the task.

Larger evaluation is explicit, never automatic:

```bash
.venv/bin/python scripts/run_llm_phase1.py --suite matrix --seeds 7 11 19
```

Matrix runs 120 scenarios per seed and can consume many API calls. Coordinate budget and final evaluation conditions with the team first. Seeds label fault schedules/repetitions; no provider seed is sent and identical LLM outputs are not guaranteed. Temperature is omitted unless explicitly passed, e.g. `--temperature 0.2`; check provider support before using it. Default per-stage adapter attempts is 1 (no SDK retries); `--max-attempts 2` allows bounded retries for API/parse failures. Schema failures are returned as errors, and always-verify has one separately logged stage retry with revalidation.

Each invocation creates a new `results/jingwen-llm-<UTC timestamp>` directory with:

- `manifest.json`: model, prompt version, SDK, parameters, Git revision and dirty flag, limitations.
- `summary.csv`: quality, observed propagation, reported tokens, missing usage, actual calls, latency.
- `<scenario>/attempt-N.json`: prompts, raw replies, parsed outputs, validation errors, every API retry and usage, stage dependencies, actions, events, checker.
- `<scenario>/attempt-N.sqlite3`: state and action ledger retained for inspection.

User-supplied nonempty output directories are rejected, preventing silent overwrite. Runtime-level SQLite failures can interrupt a run; already saved attempts remain on disk.

## Changes and interfaces

```python
adapter = ModelAdapter()
runner = WorkflowRunner(..., model_adapter=adapter)
```

This enables all four LLM stages. The previous `config_model=...` and `dependency_model=...` arguments continue to work, as do `resource_model=...` and `planner_model=...`. With no adapter, execution remains deterministic. No SDK import or key is required for deterministic tests.

`model_calls` retains all API attempt usage, raw output, and errors. `actual_tokens` is the SUM of reported total_tokens across API attempts; missing usage is separately counted and is not evidence of zero token consumption. Reasoning tokens are recorded only when returned and are a subset of completion tokens, not an extra cost to add to total_tokens. `simulated_tokens` is a different counter for deterministic stages. The legacy `inference_calls` field counts logical stage calls; `real_inference_calls` counts actual API attempts.

A successful JSON parse is not a valid stage result until fields/types/ranges are checked. Semantic checking remains separate. No failed output is substituted with a preset answer. Authentication errors are recorded without leaking exception bodies or credentials.

## Evaluation limitations to discuss with B/C

- The original `experiment.py` remains deterministic. Use the NEW runner for LLM integration. C can later merge model injection and accounting into the shared experiment runner.
- This is interface and end-to-end validation, not completion of the team's Phase 1 research evaluation. Workload enrichment, topology expansion, overhead analysis, uncertainty estimates and report remain team work.
- Workloads and prompts are small and structured. Config is largely extraction, Dependency uses fixed supported protocol v2, and Resource performs simple arithmetic. Broader knowledge materials and held-out tasks should be developed with B.
- All three input results are exposed to Planner. A matching wrong write is observable propagation evidence for these controlled faults, not universal causal attribution or a precise affected-stage oracle. Ignored messages and task failures are separate observations.
- Always verify uses deterministic checks on analysis results and rechecks the one retry. It does not verify every Planner decision or every tool operation.
- Full restart receives an oracle fault trigger and retries clean from reset state, replaying the existing fixed administrator worker-replica update. General external-event replay, concurrent conflicts, lost ACK recovery and selective recovery remain C's work.
- The injected timeout is an intermediate-result timeout AFTER the model returned, not a real tool timeout or a commit-with-lost-ACK experiment. Those costs and outcomes should be labeled separately.
- Tool permissions are enforced by Python; a rejected protected write demonstrates tool-layer enforcement, not proof of model resistance.

## Validation performed before delivery

37 tests passed locally: original 17 plus 20 integration/adapter/runner checks. The new checks use mock model clients, including full smoke export and full-restart paths, invalid schemas, verifier retry failures, parse retry costs, unknown usage and rejected unauthorized actions. No real API request or credential was used for local validation. Actual provider behavior is verified by running `--suite clean` and then `--suite smoke` on AWS.
