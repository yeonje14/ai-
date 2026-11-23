"""격리 스모크의 접수 키, 연결 재시도, 리디렉션 처리."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from uuid import UUID

from server import accounts


def test_smoke_submissions_keep_one_nonce_across_lost_response_and_stop_at_redirect(tmp_path):
    from scripts.worker_smoke_api import WorkerSmokeAPI

    db = tmp_path.resolve() / "smoke.sqlite3"
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            authorization = self.headers["Authorization"]
            key = authorization.removeprefix("Bearer ") if authorization else ""
            received.append((
                self.path, bool(accounts.identify(db, key)), self.headers.get("X-Client-Token"),
                self.headers.get("Idempotency-Key"),
                json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
            ))
            if len(received) == 1:
                return  # 접수 다음 응답을 보내기 전에 연결 종료
            self.send_response(202 if len(received) == 2 else 307)
            self.send_header("Location", "http://127.0.0.1:0/another-origin")
            self.end_headers()
            self.wfile.write(b'{"job_status":"queued"}')

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = WorkerSmokeAPI(db, server.server_port)
            url = {"url": "https://youtu.be/TRINITYtest"}
            assert api.call("/analyses", "POST", url)[:2] == (202, {"job_status": "queued"})
            assert api.call("/analyses", "POST", url)[0] == 307
        finally:
            server.shutdown()
            thread.join()

    assert len(received) == 3
    for path, authenticated, legacy, nonce, body in received:
        assert path == "/api/v1/analyses" and authenticated and legacy is None
        assert UUID(nonce).version == 4 and body == url
    assert received[0][3] == received[1][3] != received[2][3]
