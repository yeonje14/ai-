"""백로그 4번 완료 조건: 등록 ID 완료 / 미등록 ID 보류 / 422 / 404."""

from server.schemas import STAGE_ORDER
from tests.conftest import OTHER_TOKEN, REGISTERED_ID, UNREGISTERED_ID


def _submit(client, video_id):
    r = client.post(
        "/api/v1/analyses", json={"url": f"https://www.youtube.com/watch?v={video_id}"}
    )
    assert r.status_code == 202
    return r.json()


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_registered_id_runs_to_finished_with_contract_result(client, run_worker, settings):
    created = _submit(client, REGISTERED_ID)
    assert created["youtube_video_id"] == REGISTERED_ID
    assert created["job_status"] == "queued"
    aid = created["analysis_id"]

    # API 핸들러는 분석하지 않는다. Worker가 돌기 전에는 queued이고 결과도 비어 있다.
    assert client.get(f"/api/v1/analyses/{aid}").json() == {
        "analysis_id": aid,
        "job_status": "queued",
        "stage": None,
        "completed_stages": [],
    }
    pending = client.get(f"/api/v1/analyses/{aid}/result")
    assert pending.status_code == 202
    assert pending.json() == {"job_status": "queued", "stage": None}

    run_worker()

    assert client.get(f"/api/v1/analyses/{aid}/result").status_code == 200

    status = client.get(f"/api/v1/analyses/{aid}").json()
    assert status["job_status"] == "finished"
    assert status["completed_stages"] == STAGE_ORDER

    result = client.get(f"/api/v1/analyses/{aid}/result").json()
    assert set(result) == {
        "analysis_id", "youtube_video_id", "job_status", "analysis_status",
        "verdict_status", "verdict_label", "overall_score", "abstention_reason", "reason_code",
        "media_provenance", "coverage", "axes", "explanations",
    }
    assert result["analysis_id"] == aid
    assert result["youtube_video_id"] == REGISTERED_ID
    assert result["job_status"] == "finished"
    assert result["analysis_status"] == "partial"
    assert result["verdict_status"] == "abstained"
    assert result["overall_score"] is None
    assert result["abstention_reason"] == "no_valid_fusion_model"
    assert result["media_provenance"] == "registered_authorized_source"
    assert set(result["coverage"]) == {
        "video_duration_sec", "eligible_duration_sec", "analyzed_duration_sec",
        "full_video_coverage", "eligible_coverage", "analyzed_segments",
    }
    assert set(result["axes"]) == {"signal", "physics", "alignment"}
    # stub은 점수를 만들지 않는다.
    assert result["axes"]["signal"]["raw_score"] is None
    assert result["axes"]["physics"]["raw_score"] is None
    assert result["axes"]["alignment"]["lse_c"] is None
    assert result["axes"]["alignment"]["lse_d"] is None
    assert result["axes"]["alignment"]["included_in_fusion"] is False
    assert result["explanations"][0]["reason_code"] == "no_valid_fusion_model"
    # 임시 작업 폴더는 남지 않는다.
    assert not (settings.runtime_dir / aid).exists()


def test_unregistered_id_is_analysis_unavailable(client, run_worker):
    aid = _submit(client, UNREGISTERED_ID)["analysis_id"]
    run_worker()

    status = client.get(f"/api/v1/analyses/{aid}").json()
    assert status["job_status"] == "finished"
    assert status["completed_stages"] == ["validating", "access_check", "finalizing"]

    result = client.get(f"/api/v1/analyses/{aid}/result").json()
    assert result["job_status"] == "finished"
    assert result["analysis_status"] == "analysis_unavailable"
    assert result["verdict_status"] == "abstained"
    assert result["overall_score"] is None
    assert result["reason_code"] == "access_not_authorized"
    assert result["media_provenance"] is None
    assert result["axes"]["signal"]["raw_score"] is None
    assert result["axes"]["physics"]["raw_score"] is None
    assert result["axes"]["alignment"]["lse_c"] is None
    assert result["axes"]["alignment"]["lse_d"] is None
    for axis in result["axes"].values():
        assert axis["status"] != "completed"


def test_invalid_url_is_422(client):
    for body in (
        {"url": "https://evil.example/watch?v=dQw4w9WgXcQ"},
        {"url": "http://127.0.0.1/watch?v=dQw4w9WgXcQ"},
        {"url": "file:///etc/passwd"},
        {"url": "not a url"},
        {"url": ""},
        {},
    ):
        assert client.post("/api/v1/analyses", json=body).status_code == 422


def test_unknown_job_is_404(client):
    missing = "00000000-0000-4000-8000-000000000000"
    assert client.get(f"/api/v1/analyses/{missing}").status_code == 404
    assert client.get(f"/api/v1/analyses/{missing}/result").status_code == 404


def test_other_owner_gets_404(client):
    aid = _submit(client, REGISTERED_ID)["analysis_id"]
    other = {"X-Client-Token": OTHER_TOKEN}
    assert client.get(f"/api/v1/analyses/{aid}", headers=other).status_code == 404
    assert client.get(f"/api/v1/analyses/{aid}/result", headers=other).status_code == 404


def test_missing_token_is_401(client):
    client.headers.pop("X-Client-Token")
    r = client.post(
        "/api/v1/analyses", json={"url": f"https://youtu.be/{REGISTERED_ID}"}
    )
    assert r.status_code == 401


def test_queue_full_is_429(client, settings):
    for _ in range(settings.max_queued):
        _submit(client, REGISTERED_ID)
    r = client.post(
        "/api/v1/analyses", json={"url": f"https://youtu.be/{REGISTERED_ID}"}
    )
    assert r.status_code == 429


def test_only_contract_routes_exist_and_no_upload(client):
    spec = client.app.openapi()
    assert set(spec["paths"]) == {
        "/api/v1/health",
        "/api/v1/analyses",
        "/api/v1/analyses/{analysis_id}",
        "/api/v1/analyses/{analysis_id}/result",
    }
    assert "multipart" not in str(spec)


def test_result_of_processing_job_is_202_with_status_and_stage_only(client):
    aid = _submit(client, REGISTERED_ID)["analysis_id"]
    queue = client.app.state.queue
    queue.claim("w1", 30, 2)
    queue.advance_stage(aid, "w1", "waverep", ["validating"], 30)

    r = client.get(f"/api/v1/analyses/{aid}/result")
    assert r.status_code == 202
    assert r.json() == {"job_status": "processing", "stage": "waverep"}


def test_result_of_failed_job_is_200_with_reason_and_no_scores(client):
    aid = _submit(client, REGISTERED_ID)["analysis_id"]
    queue = client.app.state.queue
    queue.claim("w1", 30, 2)
    queue.fail(aid, "w1", "timeout")

    r = client.get(f"/api/v1/analyses/{aid}/result")
    assert r.status_code == 200
    body = r.json()
    assert body["job_status"] == "failed"
    assert body["reason_code"] == "timeout"
    assert body["analysis_status"] is None
    assert body["verdict_status"] is None
    assert body["overall_score"] is None
    assert body["axes"] is None
