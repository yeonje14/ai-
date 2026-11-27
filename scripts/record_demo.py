"""본인 촬영 영상의 실제 로컬 분석 응답을 공개 가능한 재생 자료로 변환한다."""
import argparse
from datetime import date
from getpass import getpass
from http.client import HTTPConnection
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "app/assets/replay"
LABELS = {key: f"본인 촬영 영상 {key.upper()}" for key in ("a", "b", "e")}
STAGES = "validating access_check preprocessing waverep motionphys syncnet fusion finalizing".split()
REASONS = set("""insufficient_evidence unvalidated_condition no_valid_fusion_model assessed
    speaker_unconfirmed media_unreadable audio_missing no_speech_detected no_mouth_movement
    no_face_detected low_resolution face_too_small too_blurry segment_too_short mouth_unmeasurable
    gate_error gate_timeout gate_bypassed tracking_failed insufficient_motion occluded_mouth
    inference_error model_unavailable timeout no_segments insufficient_frames insufficient_input
    insufficient_tracks insufficient_trajectories unsupported_input out_of_distribution
    no_valid_tracks no_valid_segments no_classifier untrained_classifier""".split())
NUM = r"[0-9]{1,7}(?:\.[0-9]{1,6})?"
SPAN = rf"{NUM}~{NUM}초"
QUALITY = rf"(?:; 얼굴 높이 중앙값 {NUM}px, 짧은 변 대비 {NUM}, 선명도 중앙값 {NUM}, 영상 짧은 변 {NUM}px, 품질 표본 {NUM}프레임)?"
MESSAGES = {
    "ANALYSIS_WINDOW": rf"전체 {NUM}분 {NUM}초 중 {SPAN}를 분석했습니다\.",
    "GATE_MEDIA": rf"Gate 입력: {NUM}×{NUM}px, {NUM}fps, {NUM}초\.",
    "GATE_ELIGIBLE_SEGMENT": rf"Gate 적합 구간: {SPAN}{QUALITY}\.",
    "GATE_EXCLUDED_SEGMENT": rf"Gate 제외 구간: {SPAN}{QUALITY}\.",
}


def require(condition):
    if not condition:
        raise ValueError("녹화 허용 형식 또는 본인 영상 조건을 확인하세요.")


def choice(value, allowed):
    require(value in allowed)
    return value


def number(value):
    require(type(value) in (int, float) and math.isfinite(value) and 0 <= value < 1e8)
    return value


def public_status(raw):
    stages = raw["completed_stages"]
    require(isinstance(stages, list))
    return {"job_status": choice(raw["job_status"], ("queued", "processing", "finished")),
            "stage": choice(raw["stage"], [None, *STAGES]),
            "completed_stages": [choice(stage, STAGES) for stage in stages]}


def public_result(raw):
    require(raw["media_provenance"] == "registered_authorized_source" and raw["gate_bypassed"] is False)
    result = {"analysis_id": "recorded-1", "youtube_video_id": "recorded",
              "job_status": choice(raw["job_status"], ["finished"]),
              "media_provenance": raw["media_provenance"], "gate_bypassed": False}
    for key, allowed in {
        "analysis_status": "completed partial out_of_scope unsupported insufficient_quality analysis_unavailable".split(),
        "verdict_status": "assessed abstained not_applicable".split(),
        "verdict_label": [None, "suspicious_signals", "low_suspicion"],
        "reason_code": REASONS | {None}, "abstention_reason": REASONS | {None},
    }.items():
        result[key] = choice(raw[key], allowed)
    coverage = raw["coverage"]
    if coverage is not None:
        times = {}
        for key in ("video_duration_sec", "eligible_duration_sec", "analyzed_duration_sec"):
            times[key] = None if coverage[key] is None else number(coverage[key])
        times["analyzed_segments"] = [{k: number(s[k]) for k in ("start_sec", "end_sec")}
                                      for s in coverage["analyzed_segments"]]
        coverage = times
    result["coverage"] = coverage
    result["axes"] = {}
    for key, axis in raw["axes"].items():
        choice(key, ("signal", "physics", "alignment"))
        result["axes"][key] = {
            "status": choice(axis["status"], "completed insufficient_input unsupported_input out_of_distribution error".split()),
            "reason_code": choice(axis["reason_code"], REASONS | {None})}
    result["explanations"] = []
    for entry in raw["explanations"]:
        template = entry["template_id"]
        if template in MESSAGES:
            message = entry["message"]
            # 제외 사유는 별도 reason_code로 표시한다. 자유 문장은 배포하지 않는다.
            if template == "GATE_EXCLUDED_SEGMENT":
                message = message.split(". ", 1)[0].rstrip(".") + "."
            require(re.fullmatch(MESSAGES[template], message))
            result["explanations"].append({"template_id": template,
                "message": message, "reason_code": choice(entry["reason_code"], REASONS)})
    return result


def recording(name, sequence, result, commit):
    return {"schema": 1, "label": LABELS[name], "recorded": {"date": date.today().isoformat(),
            "server_commit": commit, "gate_version": "gate-v2"}, "source": "real_run",
            "status_sequence": sequence, "result": result}


def validate(data):
    require(set(data) == {"schema", "label", "recorded", "source", "status_sequence", "result"})
    require(type(data["schema"]) is int and data["schema"] == 1 and data["source"] == "real_run")
    choice(data["label"], LABELS.values())
    meta = data["recorded"]
    require(set(meta) == {"date", "server_commit", "gate_version"})
    date.fromisoformat(meta["date"])
    require(meta["gate_version"] == "gate-v2" and re.fullmatch(r"[0-9a-f]{7,10}", meta["server_commit"]))
    previous = 0
    seq = data["status_sequence"]
    require(isinstance(seq, list) and seq and seq[0]["after_sec"] == 0)
    for row in seq:
        require(set(row) == {"after_sec", "body"} and previous <= number(row["after_sec"]))
        previous = row["after_sec"]
        require(public_status(row["body"]) == row["body"])
    require(seq[-1]["body"]["job_status"] == "finished")
    require(public_result(data["result"]) == data["result"])


def check_directory(directory):
    require(not directory.is_symlink() and not (directory / "index.json").is_symlink())
    index = json.loads((directory / "index.json").read_text())
    require(type(index) is list and all(name in {k + ".json" for k in LABELS} for name in index))
    require(len(set(index)) == len(index))
    require({p.name for p in directory.iterdir()} == {"index.json", *index})
    for name in index:
        path = directory / name
        require(not path.is_symlink())
        data = json.loads(path.read_text())
        validate(data)
        require(data["label"] == LABELS[path.stem])
    return index


def capture(name, port):
    check_directory(DIRECTORY)
    output = DIRECTORY / (name + ".json")
    require(not output.exists())
    require(sys.stdin.isatty())
    token = getpass("로컬 서버 계정 키: ")
    video = getpass("등록된 본인 촬영 영상의 YouTube 링크: ")
    conn = HTTPConnection("127.0.0.1", port, timeout=15)
    def request(method, suffix, expected, body=None):
        headers = {"Authorization": "Bearer " + token}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Idempotency-Key": str(uuid4())})
        conn.request(method, "/api/v1/analyses" + suffix, json.dumps(body) if body else None, headers)
        response = conn.getresponse()
        require(response.status == expected)
        return json.loads(response.read())
    try:
        created = request("POST", "", 202, {"url": video})
        suffix = "/" + str(UUID(created["analysis_id"]))
        sequence = []
        start = time.monotonic()
        while True:
            status = public_status(request("GET", suffix, 200))
            if not sequence or sequence[-1]["body"] != status:
                sequence.append({"after_sec": round(time.monotonic() - start, 2) if sequence else 0,
                                 "body": status})
            if status["job_status"] == "finished":
                break
            time.sleep(1)
        raw = request("GET", suffix + "/result", 200)
        require(raw["analysis_id"] == created["analysis_id"] and raw["youtube_video_id"] == created["youtube_video_id"])
        result = public_result(raw)
    finally:
        conn.close()
    commit = subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=ROOT, text=True).strip()
    data = recording(name, sequence, result, commit)
    validate(data)
    index = check_directory(DIRECTORY)
    with output.open("x") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
    temp = DIRECTORY / ".index.tmp"
    temp.write_text(json.dumps([*index, output.name]) + "\n")
    temp.replace(DIRECTORY / "index.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--record", choices=LABELS)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        if args.check:
            check_directory(DIRECTORY)
        else:
            capture(args.record, args.port)
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        parser.exit(1, "녹화 자료 또는 서버 응답을 확인하세요.\n")
