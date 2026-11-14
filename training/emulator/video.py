"""입력 영상과 프로파일 ID를 받아 열화 영상을 만든다.

    result = emulate(Path("in.mp4"), "x264-crf28-720p", Path("out_dir"))

- 같은 입력·같은 프로파일·같은 FFmpeg 빌드면 같은 바이트가 나오도록 스레드 수를 고정하고
  bitexact로 쓰며 컨테이너 메타데이터를 지운다.
- 원본을 덮어쓰지 않는다. 이미 있는 출력도 덮어쓰지 않는다.
- 쓴 설정과 입출력 해시를 출력 옆의 `<출력>.json`에 남긴다. 반환값과 같은 내용이다.
- FFmpeg는 인자 리스트로 실행한다. 셸을 거치지 않는다.
- 업스케일이 되는 조합은 만들지 않는다(status=skipped_upscale, 출력 없음).

실제 YouTube의 재인코딩과 같다고 주장하지 않는다.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Mapping, Optional

from training.datasets.manifest import sha256_file
from training.emulator.profiles import ALLOWED_ENCODERS, Profile, ProfileError, get_profile

METADATA_SCHEMA_VERSION = 1
STATUS_COMPLETED = "completed"
STATUS_SKIPPED_UPSCALE = "skipped_upscale"
STATUS_ERROR = "error"
LINEAGE_FIELDS = ("dataset_id", "video_id", "source_recording_id", "derivation_group_id", "split")
DEFAULT_TIMEOUT_SEC = 1800.0
DISCLAIMER = "범용 압축 강건성 시험용 변형이다. 실제 YouTube 재인코딩과 같다고 주장하지 않는다."


class EmulatorError(RuntimeError):
    """입력·출력 경로가 규칙에 맞지 않거나 FFmpeg를 실행할 수 없다."""


def output_name(input_path: Path, profile_id: str) -> str:
    return f"{Path(input_path).stem}__{profile_id}.mp4"


def scale_filter(profile: Profile) -> str:
    """짧은 변을 목표로 맞추고 긴 변은 비율을 지켜 짝수로. 원본 해상도면 홀수 변만 짝수로 내린다."""
    if profile.short_side is None:
        return f"scale=trunc(iw/2)*2:trunc(ih/2)*2:flags={profile.scale_flags}"
    t = profile.short_side
    return f"scale=w='if(lt(iw,ih),{t},-2)':h='if(lt(iw,ih),-2,{t})':flags={profile.scale_flags}"


def build_args(ffmpeg: str, input_path: Path, output_path: Path, profile: Profile) -> list[str]:
    if profile.encoder not in ALLOWED_ENCODERS:  # Profile이 이미 막지만 실행 직전에 한 번 더 본다
        raise ProfileError(f"허용하지 않는 인코더: {profile.encoder!r}")
    return [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
        "-i", str(input_path),
        "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn",
        "-map_metadata", "-1", "-map_chapters", "-1",
        "-vf", scale_filter(profile), "-filter_threads", "1",
        "-c:v", profile.encoder, "-preset", profile.preset, "-crf", str(profile.crf),
        "-pix_fmt", profile.pix_fmt, "-threads", str(profile.threads),
        "-c:a", profile.audio,
        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-movflags", "+faststart", "-f", "mp4",
        str(output_path),
    ]


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as e:
        raise EmulatorError(f"실행 파일이 없다: {args[0]}") from e


def ffmpeg_version(ffmpeg: str = "ffmpeg") -> str:
    proc = _run([ffmpeg, "-hide_banner", "-version"], 30)
    if proc.returncode != 0 or not proc.stdout:
        raise EmulatorError("ffmpeg 버전을 읽지 못했다")
    return proc.stdout.splitlines()[0].strip()


def probe_video(path: Path, ffprobe: str = "ffprobe") -> dict:
    """첫 영상 스트림의 요약. 화면에 보이는 방향 기준의 너비·높이(회전 반영)를 돌려준다."""
    proc = _run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,nb_frames,bit_rate"
        ":stream_side_data=rotation:format=duration,bit_rate,size",
        "-of", "json", str(path),
    ], 120)
    if proc.returncode != 0:
        raise EmulatorError(f"ffprobe 실패: {proc.stderr.strip()[:300]}")
    data = json.loads(proc.stdout)
    if not data.get("streams"):
        raise EmulatorError("영상 스트림이 없다")
    s, fmt = data["streams"][0], data.get("format", {})
    rotation = next((int(float(d["rotation"])) for d in s.get("side_data_list", []) if "rotation" in d), 0)
    w, h = int(s["width"]), int(s["height"])
    if abs(rotation) % 180 == 90:
        w, h = h, w

    def num(value, cast):
        try:
            return cast(value)
        except (TypeError, ValueError):
            return None  # 모르는 값은 None이다. 0으로 채우지 않는다

    return {
        "codec": s.get("codec_name"), "codec_profile": s.get("profile"),
        "width": w, "height": h, "pix_fmt": s.get("pix_fmt"),
        "frame_rate": s.get("r_frame_rate"), "frames": num(s.get("nb_frames"), int),
        "video_bit_rate": num(s.get("bit_rate"), int),
        "duration_sec": num(fmt.get("duration"), float),
        "total_bit_rate": num(fmt.get("bit_rate"), int),
        "size_bytes": num(fmt.get("size"), int),
    }


def emulate(
    input_path: Path,
    profile_id: str,
    out_dir: Path,
    *,
    lineage: Optional[Mapping[str, str]] = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> dict:
    """열화 영상 하나를 만들고 기록을 돌려준다.

    lineage: dataset_id, video_id, source_recording_id, derivation_group_id, split 중 아는 것.
    분할은 압축 전에 정해 둔 값을 그대로 넘긴다(README §6.4).
    인코딩 실패는 예외가 아니라 status=error로 돌려준다. 경로 규칙 위반은 EmulatorError다.
    """
    profile = get_profile(profile_id)
    input_path, out_dir = Path(input_path), Path(out_dir)
    if not input_path.is_file():
        raise EmulatorError(f"입력 파일이 없다: {input_path.name}")
    unknown = set(lineage or {}) - set(LINEAGE_FIELDS)
    if unknown:
        raise EmulatorError(f"lineage에 모르는 키: {sorted(unknown)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / output_name(input_path, profile_id)
    meta_path = output_path.with_name(output_path.name + ".json")
    if output_path.resolve() == input_path.resolve():
        raise EmulatorError("출력이 입력과 같은 파일이다. 원본을 덮어쓰지 않는다")
    if output_path.exists() or meta_path.exists():
        raise EmulatorError(f"출력이 이미 있다. 덮어쓰지 않는다: {output_path.name}")

    source = probe_video(input_path, ffprobe)
    tmp_path = output_path.with_name(output_path.name + ".partial")
    args = build_args(ffmpeg, input_path, tmp_path, profile)
    result: dict = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "status": STATUS_COMPLETED,
        "reason": None,
        "profile_id": profile.profile_id,
        "profile": profile.to_dict(),
        "ffmpeg_version": ffmpeg_version(ffmpeg),
        # 경로는 기기마다 달라서 자리표시로 바꿔 적는다
        "ffmpeg_args": ["<input>" if a == str(input_path) else "<output>" if a == str(tmp_path) else a
                        for a in args[1:]],
        "input": {"name": input_path.name, "sha256": sha256_file(input_path), **source},
        "output": None,
        "lineage": {k: (lineage or {}).get(k, "") for k in LINEAGE_FIELDS},
        "note": DISCLAIMER,
    }

    short = min(source["width"], source["height"])
    if profile.short_side is not None and profile.short_side > short:
        result["status"] = STATUS_SKIPPED_UPSCALE
        result["reason"] = f"목표 짧은 변 {profile.short_side}px가 원본 {short}px보다 크다"
    else:
        tmp_path.unlink(missing_ok=True)
        try:
            proc = _run(args, timeout_sec)
            failure = None if proc.returncode == 0 else (proc.stderr.strip()[-500:] or f"종료 코드 {proc.returncode}")
        except subprocess.TimeoutExpired:
            failure = f"시간 초과({timeout_sec}초)"
        if failure is None and not tmp_path.is_file():
            failure = "출력 파일이 생기지 않았다"
        if failure is not None:
            tmp_path.unlink(missing_ok=True)
            result["status"] = STATUS_ERROR
            result["reason"] = failure
        else:
            os.replace(tmp_path, output_path)
            result["output"] = {
                "name": output_path.name, "sha256": sha256_file(output_path),
                **probe_video(output_path, ffprobe),
            }

    meta_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
