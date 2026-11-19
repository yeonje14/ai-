"""오디오 트랙 선택 규칙(server/gate/audio_track.py).

규칙: 디코딩할 수 있는 오디오 중 default 표시가 있는 것(여럿이면 index가 가장 작은 것),
없으면 디코딩할 수 있는 것 중 index가 가장 작은 것. 없으면 None.
"""
import shutil

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
