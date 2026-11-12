"""FastAPI 진입점. 실행: uvicorn server.main:app --reload

파일 업로드 엔드포인트는 없다. 분석은 별도 Worker 프로세스(server.jobs.worker)가 한다.
"""

from server.api import create_app

app = create_app()
