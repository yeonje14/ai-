"""오디오 트랙 선택 규칙(server/gate/audio_track.py).

규칙: 디코딩할 수 있는 오디오 중 default 표시가 있는 것(여럿이면 index가 가장 작은 것),
없으면 디코딩할 수 있는 것 중 index가 가장 작은 것. 없으면 None.
"""
import importlib
import shutil
import subprocess
from pathlib import Path

import pytest

from server.gate import audio_track
from server.gate.audio_track import AudioTrackError, choose, parse_decodable_audio_codecs

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg/ffprobe가 없다")
DECODABLE = frozenset({"aac", "pcm_s16le", "opus"})


def st(index, codec, default=False, channels=2):
    return {"index": index, "codec_name": codec, "default": default, "channels": channels}


@pytest.mark.parametrize("streams, expected", [
    ([st(1, "aac", True), st(2, None)], 1),                          # 원본 A~E 모양(두 번째는 Apple APAC)
    ([st(1, "aac"), st(2, "aac", True, 4)], 2),                      # default가 첫 트랙이 아니다
    ([st(1, "pcm_s16le", True), st(2, "aac")], 1),                   # default가 AAC가 아니어도 고른다
    ([st(1, "aac"), st(2, "aac", channels=6)], 1),                   # default가 없으면 채널 수가 아니라 첫 번째
    ([st(1, None, True), st(2, "aac"), st(3, "aac", True)], 3),      # 디코딩할 수 없는 default는 건너뛴다
    ([st(1, None, True), st(2, "opus"), st(3, "aac")], 2),           # 디코딩 가능한 default가 없다 → 첫 디코딩 가능
    ([st(1, "aac", True), st(2, "aac", True)], 1),                   # default가 여럿이면 index가 작은 것
    ([st(3, "aac", True), st(1, "aac", True)], 1),                   # 목록 순서가 아니라 index 순서
    ([st(1, None), st(2, "apac_unknown", True)], None),              # 디코딩할 수 있는 트랙이 없다
    ([], None),
])
def test_rule(streams, expected):
    chosen = choose(streams, DECODABLE)
    assert (None if chosen is None else chosen["index"]) == expected


CODECS_TEXT = """Codecs:
 D..... = Decoding supported
 .E.... = Encoding supported
 ..A... = Audio codec
 -------
 D.VI.S 012v                 Uncompressed 4:2:2 10-bit
 DEA.L. aac                  AAC (Advanced Audio Coding) (decoders: aac aac_fixed aac_at)
 D.AI.S apac                 Marian's A-pac audio
 .EA.L. encode_only          Encoder without decoder
 DEAI.S pcm_s16le            PCM signed 16-bit little-endian
 DES... subrip               SubRip subtitle
"""


def test_codec_list_keeps_decodable_audio_only():
    assert parse_decodable_audio_codecs(CODECS_TEXT) == {"aac", "apac", "pcm_s16le"}
    # 범례 줄("D..... = Decoding supported")은 목록이 아니다
    assert parse_decodable_audio_codecs("Codecs:\n D..... = Decoding supported\n") == set()


def test_apple_apac_is_judged_by_codec_name_not_tag():
    # -codecs의 "apac"(Marian's A-pac)이 있어도 ffprobe가 codec_name을 주지 않는 Apple APAC은 고르지 않는다
    decodable = parse_decodable_audio_codecs(CODECS_TEXT)
    apple = {"index": 2, "codec_name": None, "codec_tag_string": "apac", "default": True}
    assert choose([apple], decodable) is None


def test_probe_failure_is_an_error(tmp_path):
    missing = tmp_path / "없는 파일.mov"
    with pytest.raises(AudioTrackError):
        audio_track.probe_audio_streams(missing, ffprobe=str(tmp_path / "no-ffprobe"))
    audio_track.decodable_audio_codecs.cache_clear()
    with pytest.raises(AudioTrackError):
        audio_track.decodable_audio_codecs(str(tmp_path / "no-ffmpeg"))


@needs_ffmpeg
def test_real_ffmpeg_lists_aac_and_pcm():
    codecs = audio_track.decodable_audio_codecs()
    assert {"aac", "pcm_s16le"} <= codecs


# ---------- 세 경로가 같은 트랙을 읽는다 (합성 사인파 영상, 실제 미디어 아님) ----------
# 트랙마다 주파수가 달라(440Hz·880Hz) 디코딩한 PCM으로 어느 트랙을 읽었는지 가린다.
# (트랙1 코덱, 채널, default), (트랙2 ...), 컨테이너, 규칙이 고를 stream index
CASES = {
    "c1": (("aac", "stereo", True), ("aac", "quad", False), "mov", 1),          # 원본 A~E와 같은 모양
    "c2": (("aac", "stereo", False), ("aac", "quad", True), "mov", 2),          # default가 두 번째
    "c3": (("pcm_s16le", "stereo", True), ("aac", "stereo", False), "mov", 1),  # default가 AAC 아님
    "c5": (("pcm_s16le", "stereo", False), ("aac", "quad", True), "mov", 2),
    "c6": (("aac", "stereo", False), ("aac", "quad", False), "mkv", 1),         # default 없음(FFmpeg는 4ch를 고름)
}
SEGMENT = (0.5, 2.0)


def make_case(folder, name):
    (c0, l0, d0), (c1, l1, d1), ext, _ = CASES[name]
    path = folder / f"{name}.{ext}"
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:d=3",
            "-f", "lavfi", "-i", "sine=f=440:d=3", "-f", "lavfi", "-i", "sine=f=880:d=3",
            "-filter_complex", f"[1]aformat=channel_layouts={l0}[a0];[2]aformat=channel_layouts={l1}[a1]",
            "-map", "0:v", "-map", "[a0]", "-map", "[a1]", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a:0", c0, "-c:a:1", c1,
            "-disposition:a:0", "default" if d0 else "0", "-disposition:a:1", "default" if d1 else "0"]
    if ext == "mkv":
        args += ["-default_mode", "passthrough"]  # default 표시를 넣지 않은 그대로 둔다
    subprocess.run(args + [str(path)], check=True, capture_output=True)
    return path


def pcm(path, index, window=None):
    """index 트랙의 16kHz 모노 PCM(Gate·SyncNet과 같은 변환). window=(시작, 끝)이면 그 구간만."""
    cut = [] if window is None else ["-ss", str(window[0]), "-t", str(window[1] - window[0])]
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), *cut, "-map", f"0:{index}",
                           "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], check=True, capture_output=True).stdout


def packets(path, spec):
    """오디오 패킷 그대로(재인코딩 없음)의 바이트. 에뮬레이터는 트랙을 복사만 한다."""
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", spec, "-c", "copy",
                           "-f", "data", "-"], check=True, capture_output=True).stdout


def syncnet_runner():
    return importlib.import_module("research.syncnet.infer_segments")


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe가 없다")
    folder = tmp_path_factory.mktemp("tracks")
    return {name: make_case(folder, name) for name in CASES}


def which_track(data, path, window=None):
    found = [i for i in (1, 2) if data == pcm(path, i, window)]
    assert len(found) == 1, "두 트랙 중 정확히 하나와 같아야 한다"
    return found[0]


@needs_ffmpeg
@pytest.mark.parametrize("name", sorted(CASES))
def test_gate_syncnet_emulator_read_the_rule_selected_track(cases, name, tmp_path, monkeypatch):
    from server.gate import vad
    from server.gate.types import GateConfig
    from training.emulator import video

    path, expected = cases[name], CASES[name][3]
    assert pcm(path, 1) != pcm(path, 2)  # 두 트랙이 실제로 다르다(검사가 헛돌지 않는다)

    # Gate: detect_speech가 실제로 넘긴 PCM이 어느 트랙인가(webrtcvad 판정만 대역으로 바꾼다)
    seen = []
    monkeypatch.setattr(vad, "speech_flags", lambda data, config: seen.append(data) or [])
    vad.detect_speech(path, GateConfig())
    gate = which_track(seen[0], path)

    # SyncNet: 실행기가 자른 클립의 오디오가 어느 트랙의 같은 시간 창인가
    clips = []

    class Pipeline:
        def inference(self, clip, *, cache_dir):
            clips.append(pcm(clip, 1))  # 클립의 stream 1 = 유일한 오디오
            return ([], [], [], 0.0, 0.0, "", False)

    work = tmp_path / "syncnet"
    work.mkdir()
    out = syncnet_runner().infer_segments({"video": str(path), "segments": [list(SEGMENT)]}, work, Pipeline())
    assert out["segments"][0]["status"] == "insufficient_input"  # 절단은 성공했다(트랙 없음은 대역의 반환값)
    syncnet = which_track(clips[0], path, SEGMENT)

    # 압축 에뮬레이터: 고른 트랙을 복사하거나, 복사할 수 없으면 만들지 않는다
    r = video.emulate(path, "x264-crf28-source", tmp_path / "emulated")
    emulator = r["audio"]["selected"]["index"]
    if r["audio"]["selected"]["codec_name"] == "aac":
        assert r["status"] == "completed"
        assert packets(tmp_path / "emulated" / r["output"]["name"], "0:a:0") == packets(path, f"0:{emulator}")
    else:
        assert (r["status"], r["reason_code"], r["output"]) == ("error", "audio_not_copyable", None)

    assert gate == syncnet == emulator == expected


# ---------- 원본 A~E: 선택이 예전과 같다(index 1) ----------

SAMPLES = Path(__file__).resolve().parent.parent / "data/research/samples"


@needs_ffmpeg
@pytest.mark.parametrize("name", ["A", "B", "C", "D", "E"])
def test_original_samples_keep_track_one(name):
    from server.gate import vad

    path = SAMPLES / f"{name}.MOV"
    if not path.is_file():
        pytest.skip(f"{name}.MOV 샘플 없음")
    selection = audio_track.select_audio_stream(path)
    assert selection.index == 1
    assert [(s["index"], s["codec_name"], s["default"], s["decodable"]) for s in selection.streams] == [
        (1, "aac", True, True), (2, None, False, False)]  # 두 번째는 Apple APAC(디코더 없음)
    assert vad.select_audio_index(path, 120) == 1 and syncnet_runner().audio_index_of(path) == 1
    # Gate PCM이 예전 명령(-map 없이 FFmpeg 자동 선택)과 바이트 단위로 같다
    old = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], check=True, capture_output=True).stdout
    assert vad.decode_pcm(path, 120, selection.index) == old


def test_gate_vad_raises_decode_error_when_nothing_to_select(monkeypatch, tmp_path):
    from server.gate import vad

    some = tmp_path / "media.mov"
    some.write_bytes(b"x")
    monkeypatch.setattr(audio_track, "select_audio_stream",
                        lambda path, **kw: audio_track.AudioSelection(streams=({"index": 1},), selected=None))
    with pytest.raises(vad.AudioDecodeError):
        vad.select_audio_index(some, 5)

    def broken(path, **kw):
        raise AudioTrackError("ffprobe exit 1")
    monkeypatch.setattr(audio_track, "select_audio_stream", broken)
    with pytest.raises(vad.AudioDecodeError):
        vad.select_audio_index(some, 5)


@needs_ffmpeg
def test_apple_apac_only_is_still_media_unreadable(tmp_path):
    """원본 A에서 영상 2초 + Apple APAC 트랙만 복사한 임시 파일. has_audio·원인 코드는 예전과 같다."""
    pytest.importorskip("cv2")
    pytest.importorskip("mediapipe")
    pytest.importorskip("webrtcvad")
    from server.gate import run_gate
    from server.gate.types import MEDIA_UNREADABLE

    sample = SAMPLES / "A.MOV"
    if not sample.is_file():
        pytest.skip("A.MOV 샘플 없음")
    clip = tmp_path / "apac_only.mov"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-t", "2", "-i", str(sample),
                    "-map", "0:v:0", "-map", "0:2", "-c", "copy", str(clip)], check=True, capture_output=True)
    assert audio_track.select_audio_stream(clip).index is None
    result = run_gate(clip)
    assert result.media is not None and result.media.has_audio is True
    assert result.reason_code == MEDIA_UNREADABLE
