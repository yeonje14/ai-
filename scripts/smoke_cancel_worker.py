"""기존 허가 샘플의 실제 Gate 실행 중 API로 취소한다. 다운로드/새 미디어 생성 없음.

실행: conda activate trinity && python scripts/smoke_cancel_worker.py
독립 uvicorn·Worker·DB를 사용하며 끝나면 이 스모크의 임시 자료를 모두 정리한다.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / 'data/research/samples/KakaoTalk_Video_2026-11-12-14-34-16.mp4'


def process_alive(pid: int) -> bool:
    state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                           capture_output=True, text=True, check=False).stdout.strip()
    return bool(state) and not state.startswith('Z')


def main() -> int:
    if not SAMPLE.is_file():
        raise SystemExit('기존 허가 샘플이 없어 실제 미디어 취소는 미검증입니다.')
    runtime = ROOT / 'data/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cancel-smoke-', dir=runtime) as directory:
        work = Path(directory)
        registry = work / 'registry.json'
        registry.write_text(json.dumps({'authorized_media': [{
            'youtube_video_id': 'TRINITYtest', 'local_path': SAMPLE.name,
        }]}))
        env = {k: v for k, v in os.environ.items() if not k.startswith('TRINITY_')}
        env.update(
            TRINITY_DB_PATH=str(work / 'queue.sqlite3'), TRINITY_RUNTIME_DIR=str(work / 'jobs'),
            TRINITY_AUTHORIZED_MEDIA=str(registry), TRINITY_AUTHORIZED_MEDIA_ROOT=str(SAMPLE.parent),
            TRINITY_HEARTBEAT_INTERVAL_SECONDS='1', TRINITY_LEASE_SECONDS='4',
            TRINITY_GATE_TIMEOUT_SECONDS='30', TRINITY_JOB_TIMEOUT_SECONDS='60',
        )
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}/api/v1'
        token = uuid.uuid4().hex

        def call(path, method='GET', body=None, etag=None):
            headers = {'Content-Type': 'application/json', 'X-Client-Token': token}
            if etag is not None:
                headers['If-Match'] = etag
            req = urllib.request.Request(base + path, method=method, headers=headers,
                                         data=None if body is None else json.dumps(body).encode())
            try:
                response = urllib.request.urlopen(req, timeout=3)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None, response.headers

        with (work / 'server.log').open('w') as server_log, (work / 'worker.log').open('w') as worker_log:
            server = subprocess.Popen(
                [sys.executable, '-m', 'uvicorn', 'server.main:app', '--host', '127.0.0.1',
                 '--port', str(port), '--no-access-log'],
                cwd=ROOT, env=env, stdout=server_log, stderr=subprocess.STDOUT,
            )
            worker = None
            try:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        assert call('/health')[0] == 200
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline or server.poll() is not None:
                            raise RuntimeError('API 서버 시작 실패') from None
                        time.sleep(.05)
                code, created, _ = call('/analyses', 'POST', {'url': 'https://youtu.be/TRINITYtest'})
                assert code == 202
                aid = created['analysis_id']
                path = f'/analyses/{aid}'
                active_etag = call(path)[2]['ETag']
                worker = subprocess.Popen([sys.executable, '-m', 'server.jobs.worker', '--drain'],
                                          cwd=ROOT, env=env, stdout=worker_log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 15
                gate_pid = None
                while gate_pid is None:
                    _, job, headers = call(path)
                    assert job['job_status'] in ('queued', 'processing'), '취소 전에 작업이 종료됨: 미검증'
                    assert headers['ETag'] == active_etag
                    processes = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='],
                                               capture_output=True, text=True, check=True).stdout
                    for line in processes.splitlines():
                        fields = line.strip().split(None, 2)
                        if (len(fields) == 3 and 'server.gate.process' in fields[2]
                                and 'server.jobs.supervisor' not in fields[2] and aid in fields[2]):
                            gate_pid = int(fields[0])
                            break
                    assert time.monotonic() < deadline, '실제 Gate 자식 실행 확인 실패'
                    if gate_pid is None:
                        time.sleep(.01)
                started = time.monotonic()
                code, pending, _ = call(path, 'DELETE', etag=active_etag)
                assert code == 202 and pending['job_status'] == 'processing'
                repeat, _, _ = call(path, 'DELETE', etag=active_etag)
                assert repeat == 202
                deadline = time.monotonic() + 15
                while True:
                    _, job, headers = call(path)
                    if job['job_status'] == 'cancelled':
                        break
                    assert time.monotonic() < deadline and job['job_status'] == 'processing'
                    time.sleep(.03)
                assert headers['ETag'] != active_etag
                assert not process_alive(gate_pid)
                assert not (work / 'jobs' / aid).exists()
                _, result, _ = call(path + '/result')
                assert result['job_status'] == 'cancelled' and result['overall_score'] is None
                assert call(path, 'DELETE', etag=active_etag)[0] == 412
                assert call(path)[0] == 200
                assert call(path, 'DELETE')[0] == 204
                assert call(path)[0] == 404
                assert call(path, 'DELETE')[0] == 404
                worker.wait(timeout=5)
                assert worker.returncode == 0
                print(json.dumps({
                    'actual_server_and_worker': True, 'actual_gate_child_observed': True,
                    'delete_status': code, 'repeated_delete_status': repeat,
                    'job_status': job['job_status'], 'gate_child_stopped': True,
                    'temporary_job_removed': True, 'stale_if_match': 412,
                    'terminal_delete': 204, 'get_after_delete': 404,
                    'cancel_elapsed_sec': round(time.monotonic() - started, 2),
                    'actual_model_cancel': '미검증 (가짜 모델 자식·후손은 통합 테스트로 검증)',
                }, ensure_ascii=False, indent=2))
            finally:
                for proc in (worker, server):
                    if proc is not None and proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=5)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
