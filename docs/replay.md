# 본인 촬영 결과 녹화와 Pages 재생

Pages는 녹화 목록에서 선택한 실제 상태 응답과 결과를 보여 준다. 화면에는 항상 “시연용 녹화 결과”가 표시된다. 처음 목록은 비어 있다.

## 실제 실행 녹화

1. 본인이 직접 촬영한 A·B·E 중 하나를 로컬 등록부에 연결한다. provenance는 `registered_authorized_source`로 두고 수동 Gate 우회 설정을 비운다. 외부 데이터나 합성 결과는 등록하지 않는다.
2. 저장소 루트에서 README §10대로 로컬 API와 Worker를 같은 체크아웃에서 실행한다. 기본 API 주소는 127.0.0.1의 8000번 포트다. 다운로드는 꺼 둬도 된다.
3. A를 녹화할 때 아래 명령을 입력한다. B와 E는 마지막 인자를 각각 b, e로 바꾼다. 터미널의 숨김 입력에서 계정 키와 등록 영상 링크를 입력한다.

   ```sh
   python scripts/record_demo.py --record a
   ```

4. 스크립트가 실제 작업을 접수하고 상태가 바뀐 시각을 상대 초로 기록한다. 작업이 끝나면 원래 ID를 대체하고 공개 허용 항목만 저장한다. 점수·자유 설명·URL·영상·인증값은 저장하지 않는다. 성공하면 `app/assets/replay/a.json`과 같은 폴더의 `index.json`이 갱신된다.
5. 저장소 루트에서 검사한다. 이미 녹화된 이름은 덮어쓰지 않는다. 검사한 파일만 커밋한다.

   ```sh
   python scripts/record_demo.py --check
   ```

로컬 미리보기는 app 디렉터리에서 `flutter run -d chrome --dart-define=TRINITY_API_MODE=replay`로 실행한다. 배포는 main에 병합한 뒤 GitHub Actions가 맡는다. 테스트와 공개 파일 검사를 통과한 웹 빌드만 /ai-/ 아래에 올라간다.
