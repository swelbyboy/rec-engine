"""Unit tests for mind_run_store.py — mocks the Supabase HTTP calls.

This module reads a live external schema (Mind's own mind.* tables); tests
never hit it, mirroring test_live_run_store.py's isolation approach for its
own (filesystem) I/O.
"""
import pytest

import src.mind_run_store as store


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    monkeypatch.setattr(store, "_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(store, "_SERVICE_ROLE_KEY", "test-key")


def _run_row(run_id="run-1", role_id=1650):
    return {
        "run_id": run_id,
        "role_id": role_id,
        "run_started_at": "2026-07-30T09:00:00Z",
        "scorer_version": "v6-all-reasons-gates",
        "created_by": "admin-ui",
    }


def _candidate_row(candidate_id=1, rank=1):
    return {
        "candidate_id": candidate_id,
        "candidate_name": "Jane Doe",
        "reranker_rank": rank,
        "reranker_score": 92,
        "reranker_tier": "Strong Match",
        "reranker_strengths": ["Strong Python background"],
        "reranker_concerns": [],
        "reranker_signals": [],
        "hard_filter_pass": True,
        "candidate_payload": {"id": candidate_id, "title": "Engineer", "yearsExp": 5, "skills": ["Python"]},
    }


def test_list_runs_calls_shortlist_runs_with_role_filter(monkeypatch):
    captured = {}

    def fake_get(url, headers, params, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        return _FakeResponse([_run_row()])

    monkeypatch.setattr(store.httpx, "get", fake_get)

    runs = store.list_runs(1650)

    assert runs == [_run_row()]
    assert captured["url"].endswith("/rest/v1/shortlist_runs")
    assert captured["headers"]["Accept-Profile"] == "mind"
    assert captured["params"]["role_id"] == "eq.1650"
    assert captured["params"]["order"] == "run_started_at.desc"


def test_list_runs_for_role_with_no_history_is_empty(monkeypatch):
    monkeypatch.setattr(store.httpx, "get", lambda *a, **k: _FakeResponse([]))

    assert store.list_runs(9999) == []


def test_get_run_returns_metadata_plus_candidates(monkeypatch):
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append((url, params))
        if url.endswith("/shortlist_runs"):
            return _FakeResponse([_run_row(run_id="run-1")])
        return _FakeResponse([_candidate_row(1, 1), _candidate_row(2, 2)])

    monkeypatch.setattr(store.httpx, "get", fake_get)

    result = store.get_run("run-1")

    assert result["run_id"] == "run-1"
    assert result["scorer_version"] == "v6-all-reasons-gates"
    assert [c["candidate_id"] for c in result["candidates"]] == [1, 2]

    run_call, candidates_call = calls
    assert run_call[1]["run_id"] == "eq.run-1"
    assert candidates_call[0].endswith("/shortlist_run_candidates")
    assert candidates_call[1]["run_id"] == "eq.run-1"
    assert candidates_call[1]["order"] == "reranker_rank.asc"


def test_get_run_unknown_run_id_returns_none(monkeypatch):
    monkeypatch.setattr(store.httpx, "get", lambda *a, **k: _FakeResponse([]))

    assert store.get_run("does-not-exist") is None


def test_get_run_does_not_fetch_candidates_when_run_missing(monkeypatch):
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append(url)
        return _FakeResponse([])

    monkeypatch.setattr(store.httpx, "get", fake_get)

    store.get_run("missing-run")

    assert len(calls) == 1
