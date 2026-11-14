"""manifest의 영상에 압축 프로파일을 적용하고 파생 행을 만든다.

    python -m training.emulator.pipeline --manifest <m.csv> --media-root <dir> \
        --profile x264-crf28-720p [--profile ...] --out-dir <dir> --out-manifest <m2.csv>

순서: 분할을 먼저 정한다 → 압축한다(README §6.4). 분할이 빈 영상은 거부한다.
파생 행은 부모의 분할·라벨·원본 계보·인물을 그대로 물려받고 parent_video_id로 부모와 이어지므로
기존 누수 검사(training/hygiene.py)가 그대로 적용된다.
out-manifest에는 원본 행과 파생 행이 함께 들어간다. 이미 있는 파일은 덮어쓰지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Optional

from training.datasets.manifest import ManifestError, Record, read_manifest, write_manifest
from training.emulator.profiles import ProfileError, get_profile
from training.emulator.video import STATUS_COMPLETED, EmulatorError, emulate


def derived_video_id(parent_video_id: str, profile_id: str) -> str:
    return f"{parent_video_id}@{profile_id}"


def derive_record(parent: Record, profile_id: str, video_path: str, file_hash: str) -> Record:
    """부모 영상의 압축 파생 행. 분할과 계보는 부모 것을 그대로 쓴다."""
    get_profile(profile_id)
    if not parent.split:
        raise EmulatorError(f"{parent.uid}: 분할이 비어 있다. 분할을 정한 뒤에 압축한다")
    if parent.compression_profile_id:
        # 반복 인코딩은 별도 실험 축이다 (README §6.2)
        raise EmulatorError(f"{parent.uid}: 이미 압축 파생본이다. 반복 인코딩은 지원하지 않는다")
    return replace(
        parent,
        video_id=derived_video_id(parent.video_id, profile_id),
        video_path=video_path,
        parent_video_id=parent.video_id,
        derivation_group_id=parent.derivation_group_id or parent.video_id,
        compression_profile_id=profile_id,
        file_hash=file_hash,
    )


def apply_profiles(
    records: Iterable[Record],
    profile_ids: Iterable[str],
    out_dir: Path,
    media_root: Optional[Path] = None,
    **emulate_kwargs,
) -> tuple[list[Record], list[dict]]:
    """(파생 행 목록, 영상별 실행 기록). 출력은 out_dir/<profile_id>/<dataset_id>/ 아래에 둔다.

    한 영상이 실패하거나 건너뛰어져도 나머지는 계속한다. 그런 영상은 파생 행을 만들지 않고
    실행 기록에만 남는다.
    """
    records, profile_ids = list(records), list(profile_ids)
    for pid in profile_ids:
        get_profile(pid)
    out_dir = Path(out_dir)
    derived: list[Record] = []
    results: list[dict] = []
    for rec in records:
        if rec.compression_profile_id:
            continue  # 원본 행만 압축한다
        if not rec.split:
            raise EmulatorError(f"{rec.uid}: 분할이 비어 있다. 분할을 정한 뒤에 압축한다")
        src = Path(rec.video_path)
        if not src.is_absolute() and media_root is not None:
            src = Path(media_root) / src
        for pid in profile_ids:
            lineage = {
                "dataset_id": rec.dataset_id, "video_id": rec.video_id,
                "source_recording_id": rec.source_recording_id,
                "derivation_group_id": rec.derivation_group_id or rec.video_id,
                "split": rec.split,
            }
            target_dir = out_dir / pid / rec.dataset_id
            result = emulate(src, pid, target_dir, lineage=lineage, **emulate_kwargs)
            results.append(result)
            if result["status"] == STATUS_COMPLETED:
                out_path = target_dir / result["output"]["name"]
                derived.append(derive_record(rec, pid, str(out_path), result["output"]["sha256"]))
    return derived, results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="manifest의 영상에 압축 프로파일을 적용한다")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--media-root", type=Path, default=None, help="video_path가 상대 경로일 때의 기준")
    p.add_argument("--profile", action="append", required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--out-manifest", type=Path, required=True)
    opt = p.parse_args(argv)
    try:
        if opt.out_manifest.exists():
            raise EmulatorError(f"이미 있는 파일은 덮어쓰지 않는다: {opt.out_manifest}")
        records = read_manifest(opt.manifest)
        derived, results = apply_profiles(records, opt.profile, opt.out_dir, opt.media_root)
        write_manifest(opt.out_manifest, records + derived)
    except (EmulatorError, ProfileError, ManifestError, OSError) as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"원본 {len(records)}행, 파생 {len(derived)}행, 실행 결과 {counts} → {opt.out_manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
