import pytest

from stateguard.analysis import analyse, render_markdown
from stateguard.fault_runner import run_paired
from stateguard.faults import get_case
from stateguard.metrics import (
    ROW_FIELDS,
    build_report,
    paired_row,
    read_summary_csv,
    write_summary_csv,
)
from stateguard.workloads import default_task

CASE_IDS = (
    "incorrect-db-port-3306",
    "adversarial-disable-auth",
    "timeout-config-agent",
    "ignored-resource-cpu-count",
)


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    task = default_task()
    workdir = tmp_path_factory.mktemp("pairs")
    return [
        paired_row(
            run_paired(
                task=task, case=get_case(case_id), policy="no_recovery", seed=7,
                workdir=workdir / case_id,
            )
        )
        for case_id in CASE_IDS
    ]


def test_row_has_exactly_the_declared_fields(rows):
    for row in rows:
        assert set(row) == set(ROW_FIELDS)


def test_row_carries_the_workload_version(rows):
    assert all(row["task_version"] and row["knowledge_version"] for row in rows)


def test_row_separates_exposure_from_consumption(rows):
    ignored = next(r for r in rows if r["case_id"] == "ignored-resource-cpu-count")
    consumed = next(r for r in rows if r["case_id"] == "incorrect-db-port-3306")
    assert ignored["fault_exposed"] and not ignored["fault_consumed"]
    assert consumed["fault_exposed"] and consumed["fault_consumed"]


def test_row_reports_cost_and_latency(rows):
    for row in rows:
        assert row["inference_calls_clean"] > 0
        assert row["latency_ms_clean"] >= 0 and row["latency_ms_fault"] >= 0


def test_report_keeps_accidental_and_adversarial_apart(rows):
    report = build_report(rows)
    assert set(report["by_fault_class"]) == {"accidental", "adversarial"}
    assert report["by_fault_class"]["adversarial"]["unauthorized_commits"] == 0
    assert report["by_fault_class"]["adversarial"]["unauthorized_attempts"] >= 1


def test_report_counts_the_three_propagation_verdicts(rows):
    overall = build_report(rows)["overall"]
    assert overall["consumed"] >= 1
    assert overall["ignored"] >= 1
    assert overall["blocked"] >= 1
    assert overall["pairs"] == len(rows)


def test_report_flags_the_control_cases_as_proven(rows):
    controls = build_report(rows)["control_cases"]
    assert controls["count"] == 1
    assert controls["proven_ignored"] == 1


def test_report_has_no_expectation_mismatches(rows):
    assert build_report(rows)["expectation_mismatches"] == []


def test_clean_runs_all_succeed(rows):
    assert build_report(rows)["overall"]["clean_success_rate"] == 1.0


def test_summary_csv_round_trips(tmp_path, rows):
    path = tmp_path / "summary.csv"
    write_summary_csv(rows, path)
    restored = read_summary_csv(path)
    assert len(restored) == len(rows)
    assert restored[0]["case_id"] == rows[0]["case_id"]
    assert restored[0]["clean_success"] is rows[0]["clean_success"]
    assert restored[0]["changed_state_keys"] == rows[0]["changed_state_keys"]


def test_markdown_report_names_the_control_cases(rows):
    text = render_markdown(build_report(rows), rows)
    assert "ignored-resource-cpu-count" in text
    assert "Control cases" in text


def test_analyse_writes_report_and_figures(tmp_path, rows):
    pytest.importorskip("matplotlib")
    analyse(rows, tmp_path)
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()
    figures = sorted(p.name for p in (tmp_path / "figures").glob("*.png"))
    assert figures == ["cost.png", "propagation.png", "safety.png", "success_rate.png"]


def test_analyse_works_without_plotting(tmp_path, rows):
    report = analyse(rows, tmp_path, with_figures=False)
    assert report["pairs"] == len(rows)
    assert not (tmp_path / "figures").exists()


# --- Invalid pairs are excluded, not averaged in ----------------------------


def invalidated(row, reason="clean_control_failed"):
    bad = dict(row)
    bad.update(pair_id="excluded-pair", pair_valid=False, invalid_reason=reason)
    return bad


def test_all_deterministic_pairs_are_valid(rows):
    assert all(row["pair_valid"] for row in rows)
    assert build_report(rows)["invalid_pairs"]["count"] == 0


def test_report_excludes_invalid_pairs_from_every_statistic(rows):
    report = build_report(list(rows) + [invalidated(rows[0])])
    assert report["pairs_run"] == len(rows) + 1
    assert report["pairs"] == len(rows)
    assert report["overall"]["pairs"] == len(rows)
    assert report["invalid_pairs"]["count"] == 1
    assert report["invalid_pairs"]["reasons"] == {"clean_control_failed": 1}
    assert report["invalid_pairs"]["pair_ids"] == ["excluded-pair"]


def test_invalid_pair_cannot_count_as_an_expectation_mismatch(rows):
    bad = invalidated(rows[0], reason="api_errors_in_fault_run")
    bad["matches_expectation"] = False
    assert build_report(list(rows) + [bad])["expectation_mismatches"] == []


def test_intervention_policy_does_not_count_as_schedule_mismatch(rows):
    row = dict(rows[0], policy="always_verify", matches_expectation=False)
    report = build_report([row])
    assert report["expectation_mismatches"] == []
    assert report["overall"]["expectation_match_rate"] is None


def test_invalid_control_pair_is_not_counted_as_proven(rows):
    control = next(r for r in rows if r["expected_propagation"] == "ignored")
    others = [r for r in rows if r is not control]
    report = build_report(others + [invalidated(control)])
    assert report["control_cases"]["count"] == 0


def test_report_counts_the_refused_verdict(rows):
    refused = dict(rows[0], propagation_verdict="refused", pair_id="refused-pair")
    overall = build_report(list(rows) + [refused])["overall"]
    assert overall["refused"] == 1


def test_markdown_warns_about_excluded_pairs(rows):
    text = render_markdown(build_report(list(rows) + [invalidated(rows[0])]), rows)
    assert "excluded" in text
    assert "clean_control_failed" in text


def test_validity_round_trips_through_csv(tmp_path, rows):
    path = tmp_path / "summary.csv"
    write_summary_csv(list(rows) + [invalidated(rows[0])], path)
    restored = read_summary_csv(path)
    assert restored[-1]["pair_valid"] is False
    assert restored[-1]["invalid_reason"] == "clean_control_failed"
    assert all(row["pair_valid"] is True for row in restored[:-1])
