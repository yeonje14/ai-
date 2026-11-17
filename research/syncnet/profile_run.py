"""SyncNet 단계별 시간 측정 실행기 (연구용 프로파일링, 동작 변경 없음).

infer_segments.py와 같은 요청·같은 호출 순서로 돌리되, upstream 객체의 메서드를 실행 중에 타이머로 감싼다.
upstream 파일과 infer_segments.py는 수정하지 않는다(고정 SHA ab819ba 그대로). 감싼 함수는 인자와 반환값을 그대로 전달한다.

시간은 time.monotonic이고 배타적이다: 한 단계의 시간에서 그 안에서 불린 다른 단계의 시간을 뺀다.
그래서 단계별 시간의 합 + wrapper_other = 프로세스 안의 전체 시간이다. 프로세스 시작·종료는 부른 쪽(scripts/profile_syncnet_baseline.py)이 잰다.
B·E의 트랙 실패 원인을 보려고 `_track`의 후보 트랙 길이를 진단용으로 따로 계산한다(upstream 반환값에는 영향이 없다).

    research/syncnet/.venv/bin/python research/syncnet/profile_run.py --request <작업 폴더>/request.json --output <작업 폴더>/profile.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

T0 = time.monotonic()  # 이 파일이 실행되기 시작한 시각. 그 전의 인터프리터 시작은 부른 쪽이 잰다

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import infer_segments  # noqa: E402  (같은 폴더의 래퍼. 수정하지 않는다)

SCHEMA_VERSION = 1


class Prof:
    """배타적 시간 집계. wrap으로 감싼 호출이 중첩되면 안쪽 시간을 바깥에서 뺀다."""

    def __init__(self) -> None:
        self.t: dict[str, float] = {}
        self.n: dict[str, int] = {}
        self.stack: list[list] = []

    def top(self) -> str | None:
        return self.stack[-1][0] if self.stack else None

    def wrap(self, fn, label):
        def inner(*args, **kwargs):
            name = label(*args, **kwargs) if callable(label) else label
            frame = [name, time.monotonic(), 0.0]
            self.stack.append(frame)
            try:
                return fn(*args, **kwargs)
            finally:
                end = time.monotonic()
                self.stack.pop()
                inclusive = end - frame[1]
                self.t[name] = self.t.get(name, 0.0) + inclusive - frame[2]
                self.n[name] = self.n.get(name, 0) + 1
                if self.stack:
                    self.stack[-1][2] += inclusive
        return inner


def ffmpeg_label(output: str) -> str:
    """ffmpeg-python 호출을 출력 파일 이름으로 구분한다(upstream inference의 호출 순서와 대응)."""
    name = Path(output).name
    parent = Path(output).parent.name
    if name == "video.avi":
        return "avi_convert"          # 입력을 25fps MJPEG AVI로 변환(원본 해상도)
    if name == "speech.wav":
        return "audio_resample"
    if name == "%06d.jpg":
        return "crop_frames_extract" if parent.startswith("crop_") else "frames_extract"
    if name == "audio.wav":
        return "crop_audio_extract"
    return "ffmpeg_other"


UNLABELED: list[str] = []  # 이름을 정하지 못한 subprocess 호출(경로는 파일 이름만). 결과에 남겨 빠진 단계가 없는지 본다


def subprocess_label(cmd) -> str:
    cmd = [str(c) for c in cmd]
    if "ffv1" in cmd:
        return "cut_ffv1"             # infer_segments의 구간 절단
    if "-ss" in cmd and "-to" in cmd:
        return "crop_audio_slice"     # upstream _crop의 오디오 자르기
    if "copy" in cmd:
        return "crop_mux"             # upstream _crop의 영상·오디오 합치기
    if cmd and Path(cmd[-1]).name == "extracted_audio.wav":
        return "audio_extract"        # upstream inference의 입력에서 오디오 추출(audio_path=None)
    UNLABELED.append(" ".join(Path(c).name if "/" in c else c for c in cmd)[:160])
    return "subprocess_other"


def diagnose_tracks(dets, cfg) -> dict:
    """upstream `_track`과 같은 묶기를 진단용으로 되풀이해 후보 트랙의 길이를 센다. upstream 결과에는 쓰지 않는다."""
    work = [list(faces) for faces in dets]
    lengths, sizes = [], []
    while True:
        t = []
        for faces in work:
            for f in list(faces):
                if not t:
                    t.append(f)
                    faces.remove(f)
                elif (f["frame"] - t[-1]["frame"] <= cfg.num_failed_det and _iou(f["bbox"], t[-1]["bbox"]) > 0.5):
                    t.append(f)
                    faces.remove(f)
                    continue
                else:
                    break
        if not t:
            break
        lengths.append(len(t))
        sizes.append(max(sum(b["bbox"][2] - b["bbox"][0] for b in t) / len(t),
                         sum(b["bbox"][3] - b["bbox"][1] for b in t) / len(t)))
    long_enough = [n for n in lengths if n > cfg.min_track]
    return {"candidate_track_lengths": sorted(lengths, reverse=True)[:8], "candidates": len(lengths),
            "longest": max(lengths) if lengths else 0, "longer_than_min_track": len(long_enough),
            "mean_face_px_of_longest": round(sizes[lengths.index(max(lengths))], 1) if lengths else None}


def _iou(a, b):
    xa, ya, xb, yb = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-8)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    source, dest = args.request.resolve(), args.output.resolve()
    work = source.parent
    request = json.loads(source.read_text())
    video = Path(request["video"]).resolve()
    if dest.parent != work or not video.is_relative_to(work.parent) or not video.is_file():
        return 1
    request["segments"] = infer_segments.validate_segments(request["segments"])
    request["video"] = str(video)

    prof = Prof()
    import subprocess

    t = time.monotonic()
    import cv2
    import ffmpeg
    import syncnet_python  # noqa: F401  (torch, scenedetect, S3FD를 불러온다)
    from syncnet_python import syncnet_pipeline
    import_sec = time.monotonic() - t
    sync_mod = sys.modules["syncnet_python.SyncNetInstance"]

    seg: dict = {}
    segments: list[dict] = []

    def imread_label(*_a, **_k):
        return {"infer_loop_other": "detect_imread", "crop_other": "crop_imread", "eval_other": "eval_imread"}.get(
            prof.top(), "imread_other")

    # --- 전역 호출(모든 단계에서 불린다): 호출한 단계에 따라 이름을 정한다 ---
    cv2.imread = prof.wrap(cv2.imread, imread_label)
    subprocess.run = prof.wrap(subprocess.run, lambda cmd, *a, **k: subprocess_label(cmd))
    out_run = ffmpeg.nodes.OutputStream.run

    def run_labeled(self, *a, **k):
        # compile의 마지막 인자는 overwrite_output의 `-y`일 수 있다. 출력 파일은 그 앞의 마지막 비플래그 인자다
        target = [x for x in ffmpeg.compile(self) if x != "-y"][-1]
        return prof.wrap(out_run, ffmpeg_label(target))(self, *a, **k)

    ffmpeg.nodes.OutputStream.run = run_labeled
    syncnet_pipeline.SceneManager.detect_scenes = prof.wrap(syncnet_pipeline.SceneManager.detect_scenes, "scene_detect")
    original_scene_list = syncnet_pipeline.SceneManager.get_scene_list

    def scene_list(self, *a, **k):
        scenes = original_scene_list(self, *a, **k)
        seg["scenes"] = [[s.frame_num, e.frame_num] for s, e in scenes]
        return scenes

    syncnet_pipeline.SceneManager.get_scene_list = scene_list
    sync_mod.calc_pdist = prof.wrap(sync_mod.calc_pdist, "eval_pdist")
    sync_mod.python_speech_features.mfcc = prof.wrap(sync_mod.python_speech_features.mfcc, "eval_mfcc")

    # --- 프로세스 단계(infer_segments와 같은 순서) ---
    infer_segments.verify_weights = prof.wrap(infer_segments.verify_weights, "weights_verify")
    infer_segments.load_pipeline = prof.wrap(infer_segments.load_pipeline, "model_load")
    device = infer_segments.resolve_device(request.get("device", "cpu"))
    pipeline = infer_segments.load_pipeline(Path(request["weights_dir"]), device)
    cfg = pipeline.cfg

    # --- 파이프라인 인스턴스 ---
    detect = prof.wrap(pipeline.s3fd.detect_faces, "s3fd_detect")

    def detect_counted(image, *a, **k):
        boxes = detect(image, *a, **k)
        seg["frames"] = seg.get("frames", 0) + 1
        seg["frame_wh"] = [int(image.shape[1]), int(image.shape[0])]
        n = int(len(boxes))
        seg["boxes"] = seg.get("boxes", 0) + n
        seg["frames_with_box"] = seg.get("frames_with_box", 0) + (1 if n else 0)
        return boxes

    pipeline.s3fd.detect_faces = detect_counted
    track = prof.wrap(pipeline._track, "track")

    def track_counted(dets):
        diag = diagnose_tracks(dets, cfg)
        out = track(dets)
        seg.setdefault("track_calls", []).append({"scene_frames": len(dets), "tracks": len(out), **diag})
        return out

    pipeline._track = track_counted
    crop = prof.wrap(pipeline._crop, "crop_other")

    def crop_counted(*a, **k):
        seg["crops"] = seg.get("crops", 0) + 1
        return crop(*a, **k)

    pipeline._crop = crop_counted
    net = pipeline.syncnet.__S__
    net.forward_lip = prof.wrap(net.forward_lip, "eval_forward_lip")
    net.forward_aud = prof.wrap(net.forward_aud, "eval_forward_aud")
    evaluate = prof.wrap(pipeline.syncnet.evaluate, "eval_other")

    def evaluate_counted(*a, **k):
        out = evaluate(*a, **k)
        seg.setdefault("evals", []).append({"offset_frames": out[0], "lse_c": out[1], "lse_d": out[2]})
        return out

    pipeline.syncnet.evaluate = evaluate_counted
    inference = prof.wrap(pipeline.inference, "infer_loop_other")

    def inference_recorded(*a, **k):
        # 구간 하나. 예외는 기록하고 그대로 다시 던진다(infer_segments가 구간 실패로 처리한다)
        seg.clear()
        before = dict(prof.t)
        started = time.monotonic()
        record = {"index": len(segments)}
        segments.append(record)
        try:
            return inference(*a, **k)
        except Exception as e:
            seg["error_type"] = type(e).__name__
            raise
        finally:
            record.update(copy.deepcopy(seg))
            record["inference_sec"] = round(time.monotonic() - started, 4)
            record["stage_sec"] = {k2: round(v - before.get(k2, 0.0), 4) for k2, v in prof.t.items()
                                   if v - before.get(k2, 0.0) > 1e-4}

    pipeline.inference = inference_recorded

    class TimedDir(tempfile.TemporaryDirectory):
        def cleanup(self):
            return prof.wrap(super().cleanup, "tmpdir_cleanup")()

    infer_segments.tempfile = types.SimpleNamespace(TemporaryDirectory=TimedDir)
    result = infer_segments.infer_segments(request, work, pipeline)
    internal = time.monotonic() - T0
    for rec, row in zip(segments, result["segments"]):
        rec.update(start_sec=row["start_sec"], end_sec=row["end_sec"], status=row["status"],
                   reason_code=row["reason_code"], tracks=row["tracks"])
    accounted = sum(prof.t.values())
    out = {"schema_version": SCHEMA_VERSION, "internal_sec": round(internal, 4), "import_sec": round(import_sec, 4),
           "stage_sec": {k: round(v, 4) for k, v in sorted(prof.t.items())}, "stage_calls": dict(prof.n),
           "wrapper_other_sec": round(internal - import_sec - accounted, 4),
           "config": {"facedet_scale": cfg.facedet_scale, "min_track": cfg.min_track, "min_face_size": cfg.min_face_size,
                      "num_failed_det": cfg.num_failed_det, "frame_rate": cfg.frame_rate, "batch_size": cfg.batch_size,
                      "vshift": cfg.vshift, "device": pipeline.device},
           "unlabeled_subprocess": UNLABELED[:5], "segments": segments, "result": result}
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(out, allow_nan=False))
    os.replace(tmp, dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
