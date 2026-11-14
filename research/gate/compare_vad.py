"""VAD 후보 비교 (연구용). research/gate/.venv에서 실행한다. torch를 쓰지 않는다.

    research/gate/.venv/bin/python research/gate/compare_vad.py \
        --noise data/research/samples/<발화 없는 허가 영상>.mp4 --work data/research/gate-vad

하는 일:
- 발화가 없는 실제 녹음(오경보율), macOS `say`로 만든 합성 음성(재현율), 둘을 섞은 것에
  webrtcvad 민감도 0~3과 다른 후보를 돌려 30ms 단위로 비교한다.
- 합성 음성의 기준(어느 30ms가 음성인가)은 깨끗한 합성 음성의 에너지로 정한다.

주의: 합성 음성은 실제 발화가 아니다. 소음 녹음은 하나뿐이다. 이 결과로 VAD의 정확도를 주장하지 않는다.
오디오는 --work 폴더(Git 제외)에만 둔다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 16000
FRAME = 480  # 30ms
TEXTS = {
    "ko": ("Eddy (한국어(한국))", "안녕하세요. 오늘은 날씨가 맑아서 공원에 나왔습니다. 잠시 후에 다시 말씀드리겠습니다. "
           "[[slnc 1500]] 지금부터 간단히 설명을 시작하겠습니다. 첫 번째 주제는 영상 분석입니다."),
    "en": ("Samantha", "Hello. I came out to the park because the weather is clear today. I will talk again shortly. "
           "[[slnc 1500]] Now let me begin a short explanation. The first topic is video analysis."),
}


def run(cmd: list[str]) -> bytes:
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def decode(path: Path) -> np.ndarray:
    pcm = run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
               "-ar", str(SR), "-f", "s16le", "-"])
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12))


def frames_of(x: np.ndarray) -> np.ndarray:
    n = len(x) // FRAME
    return x[: n * FRAME].reshape(n, FRAME)


def reference_flags(clean: np.ndarray) -> np.ndarray:
    """깨끗한 합성 음성에서 에너지가 최대 프레임보다 40dB 이상 낮지 않은 30ms를 음성으로 본다."""
    e = 10 * np.log10(np.mean(frames_of(clean) ** 2, axis=1) + 1e-12)
    return e > e.max() - 40.0


# ---------- 후보 ----------

def webrtc(level: int):
    def f(x: np.ndarray) -> np.ndarray:
        import webrtcvad
        vad = webrtcvad.Vad(level)
        pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
        return np.array([vad.is_speech(fr.tobytes(), SR) for fr in frames_of(pcm)])
    return f


def energy(x: np.ndarray) -> np.ndarray:
    """기준선: 프레임 에너지가 -45 dBFS보다 크면 음성. 소음을 구분하지 못하는 것이 정상이다."""
    return 10 * np.log10(np.mean(frames_of(x) ** 2, axis=1) + 1e-12) > -45.0


def silero(model: Path, threshold: float = 0.5):
    def f(x: np.ndarray) -> np.ndarray:
        import onnxruntime as ort
        sess = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros((1, 64), dtype=np.float32)
        probs = []
        for i in range(0, len(x) - 511, 512):  # 32ms 창
            chunk = x[i:i + 512][None, :].astype(np.float32)
            out, state = sess.run(None, {
                "input": np.concatenate([context, chunk], axis=1),
                "state": state, "sr": np.array(SR, dtype=np.int64),
            })
            context = chunk[:, -64:]
            probs.append(float(out.reshape(-1)[0]))
        return _resample_flags(np.array(probs) >= threshold, 512, len(x))
    return f


def yamnet(model: Path, threshold: float = 0.3):
    def f(x: np.ndarray) -> np.ndarray:
        from mediapipe.tasks.python import BaseOptions, audio
        from mediapipe.tasks.python.components import containers
        opts = audio.AudioClassifierOptions(base_options=BaseOptions(model_asset_path=str(model)), max_results=-1)
        with audio.AudioClassifier.create_from_options(opts) as clf:
            results = clf.classify(containers.AudioData.create_from_array(x.astype(np.float32), SR))
        flags = np.zeros(len(x) // FRAME, dtype=bool)
        stamps = [r.timestamp_ms for r in results]
        for k, r in enumerate(results):
            score = next((c.score for c in r.classifications[0].categories if c.category_name == "Speech"), 0.0)
            end_ms = stamps[k + 1] if k + 1 < len(stamps) else len(x) / SR * 1000
            flags[int(stamps[k] / 30):int(np.ceil(end_ms / 30))] = score >= threshold
        return flags
    return f


def _resample_flags(flags: np.ndarray, hop: int, n_samples: int) -> np.ndarray:
    """다른 창 길이의 판정을 30ms 프레임 중심 시각 기준으로 옮긴다."""
    n = n_samples // FRAME
    centers = (np.arange(n) * FRAME + FRAME // 2) // hop
    return np.array([flags[c] if c < len(flags) else False for c in centers])


# ---------- 실행 ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--noise", type=Path, required=True, help="발화가 없는 허가 녹음(영상 또는 오디오)")
    ap.add_argument("--work", type=Path, required=True, help="합성 음성·모델·결과를 두는 폴더(Git 제외)")
    ap.add_argument("--snr", type=float, nargs="*", default=[20.0, 10.0, 0.0])
    opt = ap.parse_args()
    opt.work.mkdir(parents=True, exist_ok=True)

    noise = decode(opt.noise)
    candidates = {f"webrtcvad-{k}": webrtc(k) for k in range(4)}
    candidates["energy(-45dBFS)"] = energy
    skipped = {}
    for name, pattern, make in (("silero-onnx", "silero_vad*.onnx", silero), ("yamnet-speech", "yamnet*.tflite", yamnet)):
        found = sorted(opt.work.glob(pattern))
        if found:
            candidates[f"{name}"] = make(found[0])
        else:
            skipped[name] = f"모델 파일 없음({pattern})"

    clips: dict[str, tuple[np.ndarray, np.ndarray | None]] = {"noise_only": (noise, None)}
    for lang, (voice, text) in TEXTS.items():
        aiff = opt.work / f"tts_{lang}.aiff"
        run(["say", "-v", voice, "-o", str(aiff), text])
        clean = decode(aiff)
        clean = clean[: len(clean) // FRAME * FRAME]
        ref = reference_flags(clean)
        clips[f"tts_{lang}_clean"] = (clean, ref)
        tiled = np.tile(noise, int(np.ceil(len(clean) / len(noise))))[: len(clean)]
        for snr in opt.snr:
            gain = 10 ** ((rms_db(clean[np.repeat(ref, FRAME)[: len(clean)]]) - snr - rms_db(tiled)) / 20)
            clips[f"tts_{lang}_snr{snr:g}"] = (np.clip(clean + gain * tiled, -1, 1), ref)

    rows = []
    for clip, (x, ref) in clips.items():
        for name, fn in candidates.items():
            try:
                flags = fn(x)[: len(x) // FRAME]
            except Exception as e:  # 후보 하나가 실패해도 나머지는 계속 비교한다
                rows.append({"clip": clip, "vad": name, "error": f"{type(e).__name__}: {e}"[:200]})
                continue
            row = {"clip": clip, "vad": name, "frames": int(len(flags)),
                   "flagged_ratio": round(float(flags.mean()), 4)}
            if ref is not None:
                r = ref[: len(flags)]
                row["recall"] = round(float(flags[r].mean()), 4)                 # 음성 프레임 중 잡은 비율
                row["false_alarm"] = round(float(flags[~r].mean()), 4) if (~r).any() else None  # 비음성 프레임 중 음성이라 한 비율
            rows.append(row)

    out = {"noise_rms_dbfs": round(rms_db(noise), 2), "noise_sec": round(len(noise) / SR, 2),
           "skipped": skipped, "rows": rows}
    (opt.work / "compare_vad.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    json.dump(out, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
