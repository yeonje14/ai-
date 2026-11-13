"""scripts/mavos_sample.py: 원본 묶음 추정, 층화 추출, 부분집합 성질, manifest 해시.

합성한 메타데이터 행만 쓴다. 실제 데이터셋이나 영상은 필요 없다.
"""

from __future__ import annotations

import hashlib
import random
import string

import pytest

from scripts import mavos_sample as ms

LANGS = ("arabic", "english")
FAKE_FOLDERS = ("inswapper", "sonic")


def _row(path, label, split="test", osm=False, osl=False, language="english", size=1000):
    return {
        "video_path": path, "label": label, "split": split,
        "open_set_model": osm, "open_set_language": osl, "language": language,
        "generative_method": path.split("/")[1], "audio_generative_method": "real",
        "audio_fake": False, "video_fake": label == "fake", "size_bytes": size,
    }


def _yt_id(rng):
    return "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(11))


@pytest.fixture
def rows():
    """언어 2개, 가짜 폴더 2개. 원본 30개마다 진짜 4클립, 폴더별 가짜 3클립."""
    rng = random.Random(7)
    out = []
    for lang in LANGS:
        for _ in range(30):
            sid = _yt_id(rng)
            for c in range(4):
                out.append(_row(f"{lang}/real/{sid}_{c}_1.mp4", "real", language=lang, size=2000 + c))
            for folder in FAKE_FOLDERS:
                for c in range(3):
                    out.append(_row(
                        f"{lang}/{folder}/{100 + c}-{sid}_{c}_1.mp4", "fake",
                        osm=folder == "sonic", language=lang, size=5000 + c,
                    ))
    return out


def test_source_group_from_real_and_fake_names():
    known = ms.known_source_ids([_row("english/real/K6rSVoAakQ8_38_2.mp4", "real")])
    assert known == {"K6rSVoAakQ8"}
    assert ms.source_group("english/real/K6rSVoAakQ8_38_2.mp4", known) == "yt:K6rSVoAakQ8"
    assert ms.source_group("english/sonic/1028-K6rSVoAakQ8_38_2.mp4", known) == "yt:K6rSVoAakQ8"
    assert ms.source_group("arabic/inswapper/02690.png_K6rSVoAakQ8_340_1.mp4.mp4", known) == "yt:K6rSVoAakQ8"
    assert ms.source_group("english/knnvc/K6rSVoAakQ8_3_1_abcdef.mp4", known) == "yt:K6rSVoAakQ8"


def test_source_group_fallbacks():
    known = {"K6rSVoAakQ8"}
    assert ms.source_group("russian/sonic/common_voice_ru_19627063_35.mp4", known) == "cv:common_voice_ru_19627063"
    path = "english/echomimic/d92f6642-10d2-11f1-b2c7-ac1f6b417054.mp4"
    assert ms.source_group(path, known) == "unknown:" + path
    # real 폴더에서 확인되지 않은 11자 문자열은 원본 ID로 치지 않는다
    assert ms.source_group("english/roop/5-ZZZZZZZZZZZ_1_1.mp4", known).startswith("unknown:")


def test_only_open_set_model_split_is_sampled(rows):
    extra = [
        _row("english/real/AAAAAAAAAAA_1_1.mp4", "real", split="train"),
        _row("english/real/BBBBBBBBBBB_1_1.mp4", "real", split="validation"),
        _row("german/real/CCCCCCCCCCC_1_1.mp4", "real", osl=True, language="german"),
        _row("german/sonic/1-CCCCCCCCCCC_1_1.mp4", "fake", osm=True, osl=True, language="german"),
    ]
    picked, _ = ms.draw(rows + extra, per_stratum=1000, max_per_source=1000)
    paths = {r["video_path"] for r in picked}
    assert not paths & {r["video_path"] for r in extra}
    assert len(picked) == len(rows)


def test_quota_per_stratum_and_real_ratio(rows):
    picked, short = ms.draw(rows, per_stratum=10)
    assert short == {}
    count = {}
    for r in picked:
        count[(r["category"], r["language"])] = count.get((r["category"], r["language"]), 0) + 1
    for lang in LANGS:
        for folder in FAKE_FOLDERS:
            assert count[(folder, lang)] == 10
        assert count[("real", lang)] == 10 * len(FAKE_FOLDERS)  # 층당 개수 × 가짜 폴더 수 × 1.0
    s = ms.summarize(picked)
    assert s["real"] == s["fake"] == 40


def test_at_most_two_clips_per_source_in_a_stratum(rows):
    picked, _ = ms.draw(rows, per_stratum=10)
    per = {}
    for r in picked:
        key = (r["category"], r["language"], r["source_group"])
        per[key] = per.get(key, 0) + 1
    assert max(per.values()) <= ms.MAX_PER_SOURCE == 2


def test_short_stratum_is_reported_and_not_refilled(rows):
    # 원본 30개 × 최대 2클립 = 층당 60개가 한계
    picked, short = ms.draw(rows, per_stratum=70)
    assert short[("sonic", "english")] == (60, 70)
    assert sum(1 for r in picked if r["category"] == "sonic" and r["language"] == "english") == 60


@pytest.mark.parametrize("small,large", [(5, 10), (20, 25), (10, 60)])
def test_smaller_sample_is_subset_of_larger_with_same_seed(rows, small, large):
    a, _ = ms.draw(rows, per_stratum=small)
    b, _ = ms.draw(rows, per_stratum=large)
    assert {r["video_path"] for r in a} < {r["video_path"] for r in b}


def test_same_sources_are_preferred_across_strata(rows):
    """원본의 순서가 모든 층에서 같으므로, 진짜와 가짜에 같은 원본이 함께 뽑힌다."""
    picked, _ = ms.draw(rows, per_stratum=4)
    real = {r["source_group"] for r in picked if r["label"] == "real"}
    fake = {r["source_group"] for r in picked if r["label"] == "fake"}
    assert fake <= real


def test_draw_is_deterministic_and_independent_of_row_order(rows):
    a, _ = ms.draw(rows)
    shuffled = rows[:]
    random.Random(1).shuffle(shuffled)
    b, _ = ms.draw(shuffled)
    assert ms.manifest_bytes(a) == ms.manifest_bytes(b)
    c, _ = ms.draw(rows, seed=ms.SEED + 1)
    assert ms.manifest_bytes(a) != ms.manifest_bytes(c)


def test_manifest_bytes_format(rows):
    picked, _ = ms.draw(rows, per_stratum=2)
    data = ms.manifest_bytes(picked)
    lines = data.decode("utf-8").split("\n")
    assert lines[0] == ",".join(ms.MANIFEST_FIELDS)
    assert b"\r" not in data and lines[-1] == ""
    paths = [line.split(",")[0] for line in lines[1:-1]]
    assert paths == sorted(paths) and len(paths) == len(set(paths))
    assert len(hashlib.sha256(data).hexdigest()) == 64


def test_approved_values_are_fixed():
    assert (ms.SEED, ms.PER_STRATUM, ms.MAX_PER_SOURCE, ms.REAL_RATIO) == (20261113, 20, 2, 1.0)


def test_invalid_parameters_are_rejected(rows):
    with pytest.raises(ValueError):
        ms.draw(rows, per_stratum=0)
    with pytest.raises(ValueError):
        ms.draw(rows, max_per_source=0)


def test_missing_metadata_stops(tmp_path, capsys):
    assert ms.main(["--metadata", str(tmp_path / "none.csv")]) == 2
    assert "파일 없음" in capsys.readouterr().err
