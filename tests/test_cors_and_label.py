"""CORS 출처 제한과 verdict_label 계약 (README §9, 백로그 13번 앞부분)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.api import create_app
from server.config import DEFAULT_CORS_ORIGINS, Settings, parse_cors_origins
from server.schemas import AnalysisResult
from tests.conftest import REGISTERED_ID, TOKEN, UNREGISTERED_ID

PREFLIGHT = {"Access-Control-Request-Method": "POST",
             "Access-Control-Request-Headers": "content-type,x-client-token"}


def test_default_origins_are_localhost_only():
    assert DEFAULT_CORS_ORIGINS == ("http://localhost:8080", "http://127.0.0.1:8080")


@pytest.mark.parametrize("text, expected", [
    ("http://localhost:5000", ("http://localhost:5000",)),
    (" http://127.0.0.1:3000 , https://localhost ", ("http://127.0.0.1:3000", "https://localhost")),
    ("", ()),
])
def test_parse_cors_origins_accepts_localhost(text, expected):
    assert parse_cors_origins(text) == expected


@pytest.mark.parametrize("bad", [
    "*", "http://*", "http://localhost:*", "https://example.com", "http://localhost.evil.com",
    "http://192.168.0.10:8080", "http://localhost:8080/", "http://localhost:8080/path",
    "localhost:8080", "file:///tmp/x", "http://user@localhost:8080", "null",
])
def test_parse_cors_origins_rejects_wildcards_and_other_hosts(bad):
    with pytest.raises(ValueError):
        parse_cors_origins(bad)
    with pytest.raises(ValueError):
        replace(Settings(), cors_origins=(bad,))


def test_env_overrides_origins(monkeypatch):
    monkeypatch.setenv("TRINITY_CORS_ORIGINS", "http://localhost:9999")
    assert Settings.from_env().cors_origins == ("http://localhost:9999",)
    monkeypatch.setenv("TRINITY_CORS_ORIGINS", "*")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_allowed_origin_gets_cors_headers(client):
    origin = "http://localhost:8080"
    pre = client.options("/api/v1/analyses", headers={"Origin": origin, **PREFLIGHT})
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == origin
    assert "x-client-token" in pre.headers["access-control-allow-headers"].lower()
    assert "DELETE" not in pre.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in pre.headers
    got = client.get("/api/v1/health", headers={"Origin": origin})
    assert got.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["https://example.com", "http://localhost:9000", "null"])
def test_other_origins_get_no_cors_headers(client, origin):
    pre = client.options("/api/v1/analyses", headers={"Origin": origin, **PREFLIGHT})
    assert pre.status_code == 400
    assert "access-control-allow-origin" not in pre.headers
    got = client.get("/api/v1/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in got.headers


def test_empty_origins_disable_cors(settings):
    c = TestClient(create_app(replace(settings, cors_origins=())), headers={"X-Client-Token": TOKEN})
    got = c.get("/api/v1/health", headers={"Origin": "http://localhost:8080"})
    assert got.status_code == 200 and "access-control-allow-origin" not in got.headers


@pytest.mark.parametrize("video_id", [REGISTERED_ID, UNREGISTERED_ID])
def test_server_never_sets_verdict_label_without_a_validated_model(client, run_worker, video_id):
    created = client.post("/api/v1/analyses", json={"url": f"https://www.youtube.com/watch?v={video_id}"})
    assert created.status_code == 202
    assert run_worker().returncode == 0
    result = client.get(f"/api/v1/analyses/{created.json()['analysis_id']}/result").json()
    assert "verdict_label" in result and result["verdict_label"] is None
    assert result["verdict_status"] == "abstained" and result["overall_score"] is None


def test_verdict_label_requires_assessed():
    base = {"analysis_id": "a", "youtube_video_id": "b", "job_status": "finished"}
    with pytest.raises(ValidationError):
        AnalysisResult(**base, verdict_status="abstained", verdict_label="low_suspicion")
    with pytest.raises(ValidationError):
        AnalysisResult(**base, verdict_label="suspicious_signals")
    with pytest.raises(ValidationError):
        AnalysisResult(**base, verdict_status="assessed", verdict_label="real")
    ok = AnalysisResult(**base, verdict_status="assessed", verdict_label="low_suspicion")
    assert ok.verdict_label.value == "low_suspicion"
