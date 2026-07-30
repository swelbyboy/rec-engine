"""Unit tests for live_run_store.py — pure filesystem logic, no API calls."""
import importlib

import pytest

import src.live_run_store as store


@pytest.fixture(autouse=True)
def isolated_runs_dir(tmp_path, monkeypatch):
    """Point the store at a scratch directory so tests never touch real data/live_runs/."""
    monkeypatch.setattr(store, "_RUNS_DIR", tmp_path / "live_runs")
    monkeypatch.setattr(store, "_INDEX_PATH", tmp_path / "live_runs" / "index.json")
    yield


def make_result(title="Test Role", company="Test Co"):
    return {
        "job": {"id": "job-1", "title": title, "company": company},
        "coarse_brief": {"summary": "..."},
        "ranked": [{"candidate_id": "1", "verdict": "strong_match", "rationale": "r"}],
        "eliminated": [],
        "candidates_considered": 100,
        "candidates_indexed": 100,
        "candidates_passed_filter": 10,
        "candidates_reranked": 10,
    }


def test_save_then_get_returns_full_result():
    result = make_result()
    run_id = store.save_run(1650, result)

    fetched = store.get_run(run_id)

    assert fetched == result


def test_get_unknown_run_id_returns_none():
    assert store.get_run("does-not-exist") is None


def test_save_then_list_returns_summary():
    result = make_result(title="Platform Engineer", company="Acme")
    run_id = store.save_run(1650, result)

    runs = store.list_runs(1650)

    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id
    assert runs[0]["job_order_id"] == 1650
    assert runs[0]["title"] == "Platform Engineer"
    assert runs[0]["company"] == "Acme"
    assert runs[0]["candidates_passed_filter"] == 10


def test_list_runs_for_job_with_no_history_is_empty():
    assert store.list_runs(9999) == []


def test_list_runs_only_returns_matching_job():
    store.save_run(1650, make_result())
    store.save_run(1360, make_result())

    runs_1650 = store.list_runs(1650)
    runs_1360 = store.list_runs(1360)

    assert len(runs_1650) == 1
    assert len(runs_1360) == 1
    assert runs_1650[0]["job_order_id"] == 1650
    assert runs_1360[0]["job_order_id"] == 1360


def test_list_runs_is_newest_first():
    first_id = store.save_run(1650, make_result(title="First"))
    second_id = store.save_run(1650, make_result(title="Second"))

    runs = store.list_runs(1650)

    assert [r["run_id"] for r in runs] == [second_id, first_id]


def test_run_id_is_unique_across_saves():
    ids = {store.save_run(1650, make_result()) for _ in range(5)}
    assert len(ids) == 5
