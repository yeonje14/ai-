# training

학습·평가 코드 자리(README §15.1). 데이터는 Git 밖 `data/research`에 둔다.

- `datasets/manifest.py`, `datasets/groups.py`: 공통 manifest와 인물·원본 계보 그룹 분할
- `hygiene.py`: 분할 누수 검사
- `evaluation/`: 지표, dev 임계값 고정, 외부 평가 잠금, 실행 명령
- `datasets/mavos.py`: MAVOS-DD 표본의 메타데이터 검사(추론 없음)

사용법과 한계는 `docs/evaluation-pipeline.md`.
