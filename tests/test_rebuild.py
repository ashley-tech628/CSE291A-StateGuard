"""Re-grading saved runs must reproduce a live run, and must not trust the file."""

import json

import pytest

from stateguard.fault_runner import run_paired, write_paired_artifacts
from stateguard.faults import get_case
from stateguard.metrics import paired_row
from stateguard.rebuild import load_pair, paired_files, rebuild_pair, rebuild_run
from stateguard.workloads import default_task

CASE_IDS = ("incorrect-db-port-3306", "timeout-config-agent", "ignored-resource-cpu-count")


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    """A saved run laid out exactly as the experiment script writes it."""
    root = tmp_path_factory.mktemp("saved-run")
    task = default_task()
    live = {}
    for case_id in CASE_IDS:
        workdir = root / "pairs" / case_id
        result = run_paired(
            task=task, case=get_case(case_id), policy="no_recovery", seed=7,
            workdir=workdir,
        )
        write_paired_artifacts(result, workdir)
        live[case_id] = paired_row(result)
    return root, live


def test_finds_every_saved_pair(run_dir):
    root, live = run_dir
    assert len(paired_files(root)) == len(live)


def test_rebuilt_rows_match_the_live_rows(run_dir):
    root, live = run_dir
    rows, _, changes = rebuild_run(root, with_figures=False)
    assert changes == [], "re-grading unchanged data must change nothing"
    for row in rows:
        expected = live[row["case_id"]]
        for field in ("propagation_verdict", "fault_consumed", "fault_exposed",
                      "clean_success", "fault_success", "pair_valid",
                      "changed_state_keys", "unauthorized_attempts"):
            assert row[field] == expected[field], field


def test_rebuild_writes_summary_and_report(tmp_path, run_dir):
    root, _ = run_dir
    rows, report, _ = rebuild_run(root, outdir=tmp_path, with_figures=False)
    assert (tmp_path / "summary.csv").exists()
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()
    assert report["pairs"] == len(rows)


def test_verdict_is_recomputed_not_read_from_the_file(run_dir):
    """The stored verdict is stale data; grading must ignore it."""
    root, _ = run_dir
    path = next(p for p in paired_files(root) if "timeout" in str(p))
    payload = load_pair(path)
    payload["fault"]["propagation_verdict"] = "consumed"
    payload["clean"]["propagation_verdict"] = "consumed"

    result = rebuild_pair(payload)
    assert result.comparison["propagation_verdict"] == "blocked"


def test_rebuild_reports_verdicts_that_changed(tmp_path, run_dir):
    root, _ = run_dir
    path = next(p for p in paired_files(root) if "ignored-resource" in str(p))
    payload = load_pair(path)
    payload["fault"]["propagation_verdict"] = "consumed"
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        _, _, changes = rebuild_run(root, outdir=tmp_path, with_figures=False)
        assert changes == [
            {"case_id": "ignored-resource-cpu-count", "was": "consumed", "now": "ignored"}
        ]
    finally:
        payload["fault"]["propagation_verdict"] = "ignored"
        path.write_text(json.dumps(payload), encoding="utf-8")


def test_rebuild_applies_the_current_validity_rule(tmp_path, run_dir):
    """An injected provider error invalidates the pair even though the old run passed."""
    root, _ = run_dir
    path = next(p for p in paired_files(root) if "ignored-resource" in str(p))
    payload = load_pair(path)
    payload["clean"]["trace"]["model_calls"] = [
        {"agent_id": "config", "error": "API request failed: RateLimitError",
         "status": "error", "http_status": 429}
    ]
    result = rebuild_pair(payload)
    assert not result.comparison["pair_valid"]
    assert result.comparison["invalid_reason"] == "api_errors_in_clean_run"


def test_missing_pairs_directory_is_an_explicit_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        rebuild_run(tmp_path)


# --- Re-grading in place keeps the files and the report in agreement --------


def test_in_place_rebuild_refreshes_the_stored_verdict(run_dir):
    root, _ = run_dir
    path = next(p for p in paired_files(root) if "timeout" in str(p))
    payload = load_pair(path)
    payload["fault"]["propagation_verdict"] = "consumed"
    payload["comparison"]["propagation_verdict"] = "consumed"
    path.write_text(json.dumps(payload), encoding="utf-8")

    rebuild_run(root, with_figures=False)

    refreshed = load_pair(path)
    assert refreshed["fault"]["propagation_verdict"] == "blocked"
    assert refreshed["comparison"]["propagation_verdict"] == "blocked"
    assert refreshed["comparison"]["pair_valid"] is True


def test_in_place_rebuild_never_edits_a_trace(run_dir):
    root, _ = run_dir
    path = paired_files(root)[0]
    before = {label: json.dumps(load_pair(path)[label]["trace"], sort_keys=True)
              for label in ("clean", "fault")}

    rebuild_run(root, with_figures=False)

    after = {label: json.dumps(load_pair(path)[label]["trace"], sort_keys=True)
             for label in ("clean", "fault")}
    assert after == before


def test_rebuild_to_an_output_directory_leaves_the_source_alone(tmp_path, run_dir):
    root, _ = run_dir
    path = paired_files(root)[0]
    payload = load_pair(path)
    payload["fault"]["propagation_verdict"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        rebuild_run(root, outdir=tmp_path, with_figures=False)
        assert load_pair(path)["fault"]["propagation_verdict"] == "tampered"
    finally:
        rebuild_run(root, with_figures=False)


def test_stored_checker_result_is_refreshed_too(run_dir):
    root, _ = run_dir
    path = next(p for p in paired_files(root) if "incorrect" in str(p))
    payload = load_pair(path)
    payload["fault"]["checker"] = {"success": True}
    path.write_text(json.dumps(payload), encoding="utf-8")

    rebuild_run(root, with_figures=False)

    checker = load_pair(path)["fault"]["checker"]
    assert checker["success"] is False
    assert "task_goal" in checker["violations"]


def test_a_rebuilt_outcome_can_still_be_serialised(run_dir):
    """as_dict must work on an outcome whose trace came from a file."""
    root, _ = run_dir
    result = rebuild_pair(load_pair(paired_files(root)[0]))
    payload = result.fault.as_dict()
    assert payload["trace"]["results"]
    assert json.dumps(payload)


@pytest.mark.parametrize("policy", ["full_restart", "selective_recovery"])
def test_rebuild_preserves_recovery_attempts_and_final_check(tmp_path, policy):
    task = default_task()
    case = get_case("incorrect-db-port-persistent")
    workdir = tmp_path / "pairs" / case.case_id
    live = run_paired(
        task=task, case=case, policy=policy, seed=7, workdir=workdir,
    )
    write_paired_artifacts(live, workdir)

    rebuilt = rebuild_pair(load_pair(workdir / "paired.json"))
    assert len(rebuilt.fault.recovery_attempts) == 1
    assert rebuilt.fault.check.as_dict() == live.fault.check.as_dict()
    assert rebuilt.comparison == live.comparison
    assert paired_row(rebuilt) == paired_row(live)
