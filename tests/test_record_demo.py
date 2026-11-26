import copy

import pytest

from scripts import record_demo as demo


def test_public_recording_filters_private_fields_and_rejects_unexpected_content(tmp_path):
    result = dict(analysis_id="private-id", youtube_video_id="PrivateID00", job_status="finished",
                  analysis_status="partial", verdict_status="abstained", verdict_label=None,
                  reason_code=None, abstention_reason="no_valid_fusion_model", coverage=None,
                  axes={}, explanations=[dict(template_id="ANY", reason_code="secret", message="private")],
                  media_provenance="registered_authorized_source", gate_bypassed=False)
    body = demo.public_result(result)
    assert body["analysis_id"] == "recorded-1" and body["youtube_video_id"] == "recorded"
    assert body["explanations"] == []
    data = demo.recording("a", [{"after_sec": 0, "body": {"job_status": "finished", "stage": None,
                          "completed_stages": []}}], body, "abc1234")
    demo.validate(data)
    for field, unsafe in [("label", "https://youtu.be/PrivateID00"), ("source", "mock")]:
        modified = copy.deepcopy(data)
        modified[field] = unsafe
        with pytest.raises(ValueError):
            demo.validate(modified)
    modified = copy.deepcopy(data)
    modified["result"]["unexpected_image"] = "anything"
    with pytest.raises(ValueError):
        demo.validate(modified)
    with pytest.raises(ValueError):
        demo.public_result(dict(result, gate_bypassed=True))
