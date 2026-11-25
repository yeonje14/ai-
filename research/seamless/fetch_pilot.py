"""예약된 Seamless 파일럿 쌍 하나를 공식 S3 방법(파일 ID 지정)으로 받는다.

계획: docs/seamless-pilot-plan.md §3. 예약: docs/seamless-reservation.md.
공식 패키지가 설치된 별도 venv에서 실행한다(trinity 환경에 설치하지 않는다):

    data/research/seamless/.venv/bin/python -I research/seamless/fetch_pilot.py --order 0

보호 장치:
- 예약 파일의 SHA-256이 커밋된 값과 같아야 한다. 공식 인덱스 blob도 기준과 같아야 한다.
- 예약 파일에서 role=pilot인 행만 받는다. 두 파일 ID가 공식 인덱스에서 naturalistic·train이어야 한다.
  내부 test·dev와 공식 dev·test는 받을 방법이 없다.
- 공식 함수는 다운로드 오류를 로그로만 남긴다. 그래서 받은 뒤 mp4·wav·VAD가 있는지 직접 확인한다.
  빠졌으면 공식 URL에 HEAD를 보내 DNS 오류·HTTP 거절·기타를 구분해 기록한다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEAMLESS = REPO_ROOT / "data/research/seamless"
RESERVATION = SEAMLESS / "reservation/reservation.csv"
FILELIST = SEAMLESS / "src/seamless_interaction/assets/filelist.csv"
MEDIA = SEAMLESS / "media"
PILOT = SEAMLESS / "pilot"
LOGS = SEAMLESS / "logs"

# docs/seamless-reservation.md에 커밋한 값
EXPECTED_RESERVATION_SHA256 = "2cd2ddc8ff89e85abf03c3ea2a1b84f0b03119d16bc02e01203d180dbf6538c0"
EXPECTED_FILELIST_BLOB = "e759e6d00f152a4833df2b985de842ab642812cd"
ALLOWED_ROLE = "pilot"
ALLOWED_LABEL = "naturalistic"
ALLOWED_SPLIT = "train"


class GuardError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def select_pilot(reservation: Path, filelist: Path, order: int,
                 expected_res_sha=EXPECTED_RESERVATION_SHA256, expected_blob=EXPECTED_FILELIST_BLOB) -> dict:
    """예약 파일에서 파일럿 order번 행을 고르고 공식 인덱스로 label·split을 확인한다."""
    got = sha256_file(reservation)
    if got != expected_res_sha:
        raise GuardError(f"reservation.csv sha256 {got} != 커밋된 값 {expected_res_sha}")
    data = filelist.read_bytes()
    if git_blob_sha1(data) != expected_blob:
        raise GuardError("filelist blob이 기준과 다르다")
    with reservation.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["role"] == ALLOWED_ROLE and int(r["order"]) == order]
    if len(rows) != 1:
        raise GuardError(f"pilot order {order} 행이 {len(rows)}개다")
    row = rows[0]
    ids = [row["file_id_a"], row["file_id_b"]]
    index = {}
    with filelist.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["file_id"] in ids:
                index[r["file_id"]] = r
    for fid in ids:
        r = index.get(fid)
        if r is None or r["label"] != ALLOWED_LABEL or r["split"] != ALLOWED_SPLIT:
            raise GuardError(f"{fid}: 공식 인덱스에서 {ALLOWED_LABEL}/{ALLOWED_SPLIT}가 아니다")
    return {"role": row["role"], "order": order, "interaction_key": row["interaction_key"],
            "vendor": row["vendor"], "file_id_a": ids[0], "file_id_b": ids[1],
            "index": {fid: {k: index[fid][k] for k in ("label", "split", "batch_idx", "archive_idx")}
                      for fid in ids}}


def classify_url(url: str, timeout: float = 20.0) -> dict:
    """HEAD 한 번으로 실패 원인을 나눈다: dns_error / http_<code> / network_error / reachable."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"kind": "reachable", "status": resp.status}
    except urllib.error.HTTPError as e:
        return {"kind": f"http_{e.code}", "status": e.code}
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.gaierror):
            return {"kind": "dns_error", "detail": str(e.reason)}
        return {"kind": "network_error", "detail": str(e.reason)}
    except (socket.timeout, TimeoutError) as e:
        return {"kind": "network_error", "detail": f"timeout: {e}"}


def check_downloaded(target: Path, file_id: str) -> dict:
    """공식 함수가 만든 파일을 확인한다. 필수: mp4, wav, json의 metadata:vad."""
    files = {}
    for ext in ("mp4", "wav", "json", "npz"):
        p = target / f"{file_id}.{ext}"
        files[ext] = {"path": str(p.relative_to(REPO_ROOT)) if p.is_relative_to(REPO_ROOT) else str(p),
                      "bytes": p.stat().st_size if p.exists() else None}
    missing = [ext for ext in ("mp4", "wav") if not files[ext]["bytes"]]
    meta_keys: list[str] = []
    jp = target / f"{file_id}.json"
    if jp.exists():
        meta_keys = sorted(json.loads(jp.read_text(encoding="utf-8")).keys())
    if "metadata:vad" not in meta_keys:
        missing.append("metadata:vad")
    return {"files": files, "json_keys": meta_keys, "missing_required": missing}


def disk(path: Path) -> dict:
    u = shutil.disk_usage(path)
    return {"free_bytes": u.free, "total_bytes": u.total}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--order", type=int, default=0)
    ap.add_argument("--num-workers", type=int, default=4)
    opt = ap.parse_args(argv)

    pick = select_pilot(RESERVATION, FILELIST, opt.order)
    out_dir = PILOT / f"pilot-{opt.order:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    os.chdir(LOGS)  # 공식 패키지는 현재 폴더에 seamless_interaction_fs.log를 만든다

    from seamless_interaction.fs import SeamlessInteractionFS  # 별도 venv에만 있다

    fs = SeamlessInteractionFS(local_dir=str(MEDIA), filelist_path=str(FILELIST), num_workers=opt.num_workers)
    record = {"pilot": pick, "disk_before": disk(MEDIA), "downloads": {}}
    for fid in (pick["file_id_a"], pick["file_id_b"]):
        idx = pick["index"][fid]
        target = MEDIA / idx["label"] / idx["split"] / f"{int(idx['batch_idx']):04d}" / f"{int(idx['archive_idx']):04d}"
        t0 = time.monotonic()
        error = None
        try:
            fs.gather_file_id_data_from_s3(fid)
        except Exception as e:  # 공식 함수가 올리는 예외도 기록하고 다음 파일로 간다
            error = f"{type(e).__name__}: {e}"
        elapsed = round(time.monotonic() - t0, 2)
        check = check_downloaded(target, fid)
        diag = {}
        if check["missing_required"]:
            for url in fs.get_path_list_for_file_id_s3(fid)[:2]:  # wav, mp4
                diag[url.rsplit("/", 1)[-1]] = classify_url(url)
        else:
            for ext in ("mp4", "wav", "json", "npz"):
                p = target / f"{fid}.{ext}"
                if p.exists():
                    check["files"][ext]["sha256"] = sha256_file(p)
        record["downloads"][fid] = {"elapsed_sec": elapsed, "exception": error, **check, "diagnosis": diag,
                                    "status": "ok" if not check["missing_required"] else "incomplete"}
    record["disk_after"] = disk(MEDIA)
    (out_dir / "fetch.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({fid: {k: d[k] for k in ("status", "elapsed_sec", "missing_required", "diagnosis")}
                      for fid, d in record["downloads"].items()}, ensure_ascii=False, indent=2))
    return 0 if all(d["status"] == "ok" for d in record["downloads"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
