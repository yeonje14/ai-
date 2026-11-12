"""WaveRep 프레임 추론 프로세스 (README §14.1 백로그 7번, 어댑터의 모델 쪽 절반).

research/waverep/.venv의 Python으로 실행한다. server/axes/signal/waverep.py가
인자 리스트로 띄우고, 요청·결과를 JSON 파일로 주고받는다.

    research/waverep/.venv/bin/python research/waverep/infer_frames.py \
        --request <작업 폴더>/waverep_request.json --output <작업 폴더>/waverep_result.json

원본 저장소(upstream/)는 수정하지 않는다. 전처리(create_transform)는 원본 함수를 그대로
쓰고, 모델 생성만 여기서 한다. 원본 create_model은 pretrained=True가 고정이라
pretrained=False를 고를 수 없기 때문이다. 아키텍처, crop 크기, 키 걸러내기,
strict 로드는 원본과 같다.

점수는 프레임별 원시 logit이다. 확률로 바꾸지 않고, 임계값을 적용하지 않고, 판정하지 않는다.
프레임 이미지는 디스크에 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import resource
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO_DIR = HERE / "upstream" / "demo"
sys.path.insert(0, str(HERE))

from frame_sampling import select_frame_indices  # noqa: E402

# demo/main_avideo.py와 같은 값
ARC = "vit_base_patch14_reg4_dinov2.lvd142m"
CROPPING = 504
ALLOWED_DEVICES = ("cpu", "mps")
SCHEMA_VERSION = 1


class InferenceStop(Exception):
    """추론하지 않고 끝내는 경우. status와 reason_code를 결과에 그대로 쓴다."""

    def __init__(self, status: str, reason_code: str, detail: str = ""):
        super().__init__(detail or reason_code)
        self.status = status
        self.reason_code = reason_code
        self.detail = detail


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def upstream_commit() -> str | None:
    """upstream/.git에서 커밋 해시를 읽는다. git을 실행하지 않는다. 못 읽으면 None."""
    git_dir = HERE / "upstream" / ".git"
    try:
        head = (git_dir / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            return (git_dir / head[5:]).read_text().strip()
        return head
    except OSError:
        return None


def build_model(weights: Path, device, pretrained: bool):
    """원본 demo/utils.py create_model과 같되 pretrained만 인자로 받는다."""
    import timm
    import torch

    model = timm.create_model(ARC, num_classes=1, pretrained=pretrained, img_size=CROPPING)
    model = model.to(device)
    dat = torch.load(weights, map_location=device)
    if "state_dict" in dat:
        dat = {k[6:]: dat["state_dict"][k] for k in dat["state_dict"] if k.startswith("model")}
    model.load_state_dict(dat)  # strict=True: 키가 하나라도 어긋나면 예외
    del dat
    return model.eval()


class MemoryTracker:
    """프로세스 안에서 읽은 메모리의 최댓값. 읽지 못한 값은 None으로 둔다(0이 아님)."""

    def __init__(self, torch, use_mps: bool):
        self.torch = torch
        self.use_mps = use_mps
        self.mps_driver_peak: int | None = None
        self.mps_current_peak: int | None = None
        self.samples = 0

    def sample(self) -> None:
        if not self.use_mps:
            return
        driver = int(self.torch.mps.driver_allocated_memory())
        current = int(self.torch.mps.current_allocated_memory())
        self.mps_driver_peak = driver if self.mps_driver_peak is None else max(self.mps_driver_peak, driver)
        self.mps_current_peak = current if self.mps_current_peak is None else max(self.mps_current_peak, current)
        self.samples += 1

    def report(self) -> dict:
        return {
            # macOS의 ru_maxrss는 바이트 단위다
            "max_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "mps_driver_allocated_peak_bytes": self.mps_driver_peak,
            "mps_current_allocated_peak_bytes": self.mps_current_peak,
            "mps_samples": self.samples,
        }


def run(request: dict) -> dict:
    t_start = time.perf_counter()
    video = Path(request["video"])
    weights = Path(request["weights"])
    device_requested = request["device"]
    batch_size = int(request["batch_size"])
    pretrained = bool(request["pretrained"])
    sample_fps = request.get("sample_fps")

    if device_requested not in ALLOWED_DEVICES:
        raise InferenceStop("error", "invalid_request", f"device는 {ALLOWED_DEVICES} 중 하나여야 한다")
    if batch_size < 1:
        raise InferenceStop("error", "invalid_request", "batch_size는 1 이상이어야 한다")
    if not video.is_file():
        raise InferenceStop("error", "media_unreadable", "영상 파일 없음")
    if not weights.is_file():
        raise InferenceStop("error", "weights_missing", "가중치 파일 없음")

    if device_requested == "mps":
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    import cv2
    import torch
    from PIL import Image

    sys.path.insert(0, str(DEMO_DIR))
    from utils import create_transform  # 원본 전처리 (수정하지 않음)

    # 장치: mps → cpu 순으로 대체한다. CUDA는 쓰지 않는다.
    device_used = device_requested
    if device_requested == "mps" and not torch.backends.mps.is_available():
        device_used = "cpu"
    device = torch.device(device_used)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise InferenceStop("error", "media_unreadable", "영상을 열 수 없음")
    try:
        video_fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        video_info = {"fps": video_fps, "frame_count": frame_count, "width": width, "height": height}
        if video_fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
            raise InferenceStop("error", "media_unreadable", "영상 정보(fps·프레임 수·크기)를 읽을 수 없음")
        if min(width, height) < CROPPING:
            # 원본 전처리는 리사이즈 없이 가운데 504×504만 자른다. 더 작은 입력은 확인하지 않았다.
            stop = InferenceStop("unsupported_input", "frame_smaller_than_crop")
            stop.video_info = video_info
            raise stop

        try:
            indices = select_frame_indices(request["segments"], video_fps, frame_count, sample_fps)
        except ValueError as e:
            raise InferenceStop("error", "invalid_request", str(e)) from e
        if not indices:
            stop = InferenceStop("insufficient_input", "no_frames_selected")
            stop.video_info = video_info
            raise stop

        t0 = time.perf_counter()
        transform = create_transform(CROPPING)
        model = build_model(weights, device, pretrained)
        model_load_sec = time.perf_counter() - t0

        mem = MemoryTracker(torch, device_used == "mps")
        mem.sample()

        wanted = set(indices)
        last = indices[-1]
        frames: list[dict] = []
        decode_sec = 0.0
        inference_sec = 0.0
        batch_idx: list[int] = []
        batch_dat: list = []
        batches = 0

        def flush() -> None:
            nonlocal inference_sec, batches
            if not batch_dat:
                return
            t = time.perf_counter()
            with torch.no_grad():
                # .cpu()가 MPS 연산이 끝나기를 기다리므로 시간에 실제 계산이 포함된다
                preds = model(torch.stack(batch_dat, 0).to(device))[:, -1].float().cpu().tolist()
            inference_sec += time.perf_counter() - t
            mem.sample()
            batches += 1
            for i, p in zip(batch_idx, preds):
                if not math.isfinite(p):
                    raise InferenceStop("error", "non_finite_logit", f"프레임 {i}")
                frames.append({"index": i, "time_sec": round(i / video_fps, 6), "logit": p})
            batch_idx.clear()
            batch_dat.clear()

        idx = 0
        t = time.perf_counter()
        while idx <= last:
            if not cap.grab():  # 고르지 않은 프레임은 디코딩만 하고 넘긴다
                break
            if idx in wanted:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                batch_dat.append(transform(image))
                batch_idx.append(idx)
                if len(batch_dat) >= batch_size:
                    decode_sec += time.perf_counter() - t
                    flush()
                    t = time.perf_counter()
            idx += 1
        decode_sec += time.perf_counter() - t
        flush()
    finally:
        cap.release()

    if len(frames) != len(indices):
        # 프레임 수 정보와 달리 중간에 디코딩이 끊겼다. 받은 만큼만 있는 결과를 완료로 내지 않는다.
        raise InferenceStop(
            "error", "decode_incomplete", f"고른 프레임 {len(indices)}개 중 {len(frames)}개만 읽음"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "reason_code": None,
        "frames": frames,
        "video": video_info,
        "sampling": {
            "sample_fps": sample_fps,
            "batch_size": batch_size,
            "selected_frames": len(indices),
            "batches": batches,
        },
        "timing": {
            "model_load_sec": round(model_load_sec, 4),
            "decode_sec": round(decode_sec, 4),
            "inference_sec": round(inference_sec, 4),
            "total_sec": round(time.perf_counter() - t_start, 4),
        },
        "memory": mem.report(),
        "model": {
            "name": "waverep",
            "arch": ARC,
            "cropping": CROPPING,
            "weights_file": weights.name,
            "weights_md5": md5_of(weights),
            "upstream_commit": upstream_commit(),
            "pretrained_init": pretrained,
            "device_requested": device_requested,
            "device_used": device_used,
            "torch_version": torch.__version__,
        },
    }


def failure(status: str, reason_code: str, detail: str = "", video_info: dict | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason_code": reason_code,
        "detail": detail,
        "frames": None,  # 실패한 점수는 null이다. 0이나 빈 값으로 채우지 않는다.
        "video": video_info,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    opt = p.parse_args(argv)

    try:
        request = json.loads(opt.request.read_text(encoding="utf-8"))
        result = run(request)
    except InferenceStop as e:
        result = failure(e.status, e.reason_code, e.detail, getattr(e, "video_info", None))
    except Exception as e:  # 한 축의 실패가 호출자까지 번지지 않게 결과 파일로 남긴다
        result = failure("error", "inference_error", type(e).__name__)
        print(f"infer_frames 실패: {type(e).__name__}: {e}", file=sys.stderr)

    tmp = opt.output.with_suffix(opt.output.suffix + ".tmp")
    tmp.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    os.replace(tmp, opt.output)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
