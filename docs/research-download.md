# 연구용 다운로드 확인

Worker 전용이며 기본값은 꺼짐이다. 본인 촬영 시연 영상으로만 확인한다. 등록부에 연결된 로컬 파일을 먼저 사용한다. 실제 플랫폼 다운로드와 Shorts 품질은 확인 필요다.

## 설치

저장소 루트에서 아래 명령을 한 줄씩 실행한다. ffmpeg와 ffprobe는 기존 Gate 실행 환경을 사용한다.

```sh
conda activate trinity
python -m venv research/download/.venv
research/download/.venv/bin/python -m pip install --require-hashes -r research/download/requirements.lock.txt
brew install deno
deno --version
research/download/.venv/bin/yt-dlp --version
ffmpeg -version
ffprobe -version
```

Deno는 2.3.0 이상, yt-dlp는 2026.11.23이어야 한다. EJS는 고정된 default 의존성에서 읽는다. [공식 릴리스](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.11.23) · [EJS 런타임 설명](https://github.com/yt-dlp/yt-dlp/wiki/EJS)

## 시연 전 확인

1. README §10의 전용 계정 DB와 작업 폴더를 준비한다. API 터미널에서 `uvicorn server.main:app --no-access-log`를 실행한다. Worker 터미널에도 같은 DB와 작업 폴더 경로를 설정한다.
2. Worker 터미널에서 아래 세 줄을 실행한다.

   ```sh
   export TRINITY_RESEARCH_DOWNLOAD=1
   export TRINITY_DENO_EXECUTABLE="$(command -v deno)"
   python -m server.jobs.worker
   ```

3. app/README.md의 서버 모드로 앱을 띄운다. 키는 앱의 세션 입력란에 입력한다. 등록부에 없는 본인 공개 영상(60초 이하)과 본인 Shorts를 한 건씩 접수한다. 결과에서 원본 길이, 분석 창, Gate 입력 해상도·발화 구간을 확인한다. 60초를 넘는 본인 영상에서는 창의 길이와 원본 기준 위치를 확인한다. 작업 완료와 판정 보류는 함께 나타날 수 있다.
4. Worker 로그의 작업 ID와 단계 시각으로 대기·실행 시간을 확인한다. 작업이 끝난 뒤 해당 ID의 폴더가 사라져야 한다. 입력 URL과 추적 인자, 제목, yt-dlp 원문, 인증값은 기록하지 않는다. 점검 메모에는 상태·원인·길이·해상도·단계 시간만 남긴다.
5. 등록부에 없는 삭제·비공개 영상, 30분 초과 영상, 네트워크를 끊은 경우를 각각 확인한다. 해당 원인 문구가 보이는지, 실패·취소 직후 작업 폴더가 사라지는지 검사한다. 다운로드가 막히면 쿠키나 로그인으로 우회하지 않는다.
6. 등록부 예비 시연은 Worker에서 `TRINITY_RESEARCH_DOWNLOAD=0`으로 다시 시작한 뒤 등록된 본인 촬영 링크로 진행한다. 실제 실행 결과만 녹화하며 미디어는 공개하지 않는다.
