"""Gate를 실제 미디어로 돌리는 테스트.

입력: data/research/samples/의 허가 영상(저장소 소유자 본인 촬영)과,
테스트 중 FFmpeg로 만든 변형(오디오 제거본, 검은 화면본, 무음 오디오본).
변형은 임시 폴더에 만들고 테스트가 끝나면 지운다.

변형에 쓰는 원본에는 발화가 없다(야외 촬영, 저장소 소유자 확인). 얼굴은 하나 나온다.
그래서 이 영상에는 적합 구간이 없어야 한다.

발화 테스트는 실내 촬영 A·B·E와 speaking/에 별도로 둔 허가 영상을 사용한다.
해당 샘플이나 Gate 실행에 필요한 의존성이 없으면 관련 테스트를 건너뛴다.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from server.config import Settings
from server.gate import run_gate
from server.gate.types import (
    AUDIO_MISSING,
    MEDIA_UNREADABLE,
    NO_FACE_DETECTED,
    NO_SPEECH_DETECTED,
    NO_SPEECH_FAMILY,
)
from server.ingest.media_resolver import AuthorizedMediaRegistry

from tests.conftest import REPO_ROOT

SAMPLE_ROOT = REPO_ROOT / "data/research/samples"
SAMPLES = sorted(SAMPLE_ROOT.glob("*.mp4"))
INDOOR_SPEAKING = (SAMPLE_ROOT / name for name in ("A.MOV", "B.MOV", "E.MOV"))
SPEAKING = list(INDOOR_SPEAKING) + sorted(
    path for path in (SAMPLE_ROOT / "speaking").glob("*")
    if path.is_file() and path.suffix.lower() in {".mov", ".mp4"}
)
MODEL_DIR = REPO_ROOT / Settings().gate_model_dir
MISSING = [
    name
    for name, ok in {
        "Gate 의존성(requirements-gate.txt)": all(
            importlib.util.find_spec(m) for m in ("cv2", "mediapipe", "webrtcvad")
        ),
        "얼굴 검출 모델 파일(data/models/gate/)": any(MODEL_DIR.glob("*.tflite")),
        "얼굴 특징점 모델 파일(data/models/gate/face_landmarker.task)": (
            MODEL_DIR / "face_landmarker.task"
        ).is_file(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
    }.items()
    if not ok
]
pytestmark = pytest.mark.skipif(bool(MISSING), reason="없음: " + ", ".join(MISSING))


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", *args],
        check=True, capture_output=True, timeout=120,
    )


@pytest.fixture(scope="module")
def media(monkeypatch_module):
    """원본과 변형 세 개. 변형은 끝나면 삭제한다."""
    if not SAMPLES:
        pytest.skip("무발화 허가 샘플 없음(data/research/samples/*.mp4)")
    monkeypatch_module.chdir(REPO_ROOT)
    src = SAMPLES[0]
    work = Path(tempfile.mkdtemp(prefix="trinity-gate-test-"))
    try:
        no_audio, black, silent = work / "no_audio.mp4", work / "black.mp4", work / "silent.mp4"
        _ffmpeg("-i", str(src), "-c:v", "copy", "-an", str(no_audio))
        # 소프트웨어 인코더(libx264)만 쓴다
        _ffmpeg("-i", str(src), "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", str(black))
        _ffmpeg("-i", str(src), "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest",
                str(silent))
        yield {"original": src, "no_audio": no_audio, "black": black, "silent": silent, "dir": work}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    assert not work.exists()


@pytest.fixture(scope="module")
def monkeypatch_module():
    patch = pytest.MonkeyPatch()
    yield patch
    patch.undo()


@pytest.fixture(scope="module")
def results(media):
    return {name: run_gate(media[name]) for name in ("original", "no_audio", "black", "silent")}


def test_sample_without_speech_has_no_eligible_segment(results):
    """발화가 없는 영상이다. VAD가 주변 소리를 음성으로 판정해도 입이 움직이지 않으면 걸러야 한다.

    (이전 테스트는 이 영상에 적합 구간이 있다고 기대했다. 기대값이 틀렸다.)
    """
    result = results["original"]
    assert result.eligible_segments == ()
    assert result.eligible_duration_sec == 0.0
    assert result.reason_code in NO_SPEECH_FAMILY
    assert all(s.reason_code in NO_SPEECH_FAMILY for s in result.excluded_segments)
    # 얼굴은 보였고 입 벌림도 쟀다. 못 재서 걸러진 것이 아니다.
    assert result.mouth_summary["measured"] > 0
    assert result.mouth_active_segments == ()
    assert result.speaking_video_validated is False


def test_audio_removed_video_is_audio_missing(results):
    result = results["no_audio"]
    assert result.media.has_audio is False
    assert result.reason_code == AUDIO_MISSING
    assert result.eligible_segments == ()


def test_black_video_is_no_face_detected(results):
    result = results["black"]
    assert result.speech_segments  # 음성은 그대로 있다
    assert result.reason_code == NO_FACE_DETECTED
    assert result.eligible_segments == ()


def test_silent_audio_track_is_no_speech_detected(results):
    result = results["silent"]
    assert result.media.has_audio is True
    assert result.reason_code == NO_SPEECH_DETECTED
    assert result.eligible_segments == ()


def test_reason_codes_are_all_distinct(results):
    codes = [results[name].reason_code for name in ("no_audio", "black", "silent")]
    assert len(set(codes)) == 3


def test_segments_cover_whole_video_and_coverage_shape(results):
    for result in results.values():
        segs = sorted(
            result.eligible_segments + result.excluded_segments, key=lambda s: s.start_sec
        )
        assert segs[0].start_sec == 0.0
        assert segs[-1].end_sec == pytest.approx(result.media.duration_sec, abs=0.05)
        for prev, cur in zip(segs, segs[1:]):
            assert cur.start_sec == pytest.approx(prev.end_sec, abs=1e-3)
        coverage = result.coverage()
        assert coverage["video_duration_sec"] == result.media.duration_sec
        assert coverage["analyzed_duration_sec"] is None
        assert coverage["full_video_coverage"] is None


def test_probe_reads_basic_properties(results):
    info = results["original"].media
    assert info.duration_sec > 0 and info.fps > 0
    assert min(info.width, info.height) > 0


def test_unreadable_inputs(media):
    assert run_gate(media["dir"] / "missing.mp4").reason_code == MEDIA_UNREADABLE
    junk = media["dir"] / "junk.mp4"
    junk.write_bytes(b"not a video")
    result = run_gate(junk)
    assert result.reason_code == MEDIA_UNREADABLE
    assert result.coverage()["video_duration_sec"] is None


@pytest.mark.skipif(not SPEAKING, reason="말하는 허가 영상 없음(실내 A·B·E 또는 samples/speaking/). 미검증")
@pytest.mark.parametrize("path", SPEAKING, ids=lambda p: p.name)
def test_speaking_video_has_eligible_segment(path, tmp_path, monkeypatch):
    """한 사람이 화면을 보고 말하는 영상에는 적합 구간이 있어야 한다."""
    if not path.is_file():
        pytest.skip(f"말하는 허가 영상 없음: {path.name}. 미검증")
    monkeypatch.chdir(REPO_ROOT)
    video_id = "GateSmoke0A"
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({"authorized_media": [{
        "youtube_video_id": video_id,
        "local_path": path.relative_to(SAMPLE_ROOT).as_posix(),
    }]}), encoding="utf-8")
    registry = AuthorizedMediaRegistry.from_file(registry_path, SAMPLE_ROOT)
    authorized = registry.resolve(video_id)
    assert authorized is not None and authorized.local_path is not None

    result = run_gate(authorized.local_path)
    assert result.reason_code is None, result.to_dict()
    assert result.eligible_duration_sec > 0
    assert result.mouth_active_segments

