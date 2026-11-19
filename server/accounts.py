"""격리된 새 DB의 계정 운영 도구. python -m server.accounts --help"""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sqlite3
import stat
import sys
import tempfile
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from server.jobs.schema import jobs_schema

APP_ID = 0x54524941
KEY_LIFETIME = 24 * 3600

ACCOUNT_SCHEMA = """
CREATE TABLE users (
    user_id TEXT PRIMARY KEY NOT NULL,
    disabled_at REAL
);
CREATE TABLE credentials (
    digest BLOB PRIMARY KEY NOT NULL CHECK(length(digest) = 32),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    expires_at REAL NOT NULL,
    revoked_at REAL
);
CREATE UNIQUE INDEX current_key ON credentials(user_id) WHERE revoked_at IS NULL;
"""


def _check_directory(path: Path) -> None:
    directory = path.parent
    if directory.resolve(strict=True) != directory.absolute():
        raise ValueError("심볼릭 링크를 거치지 않는 실제 디렉터리를 지정하세요.")
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("운영자 전용 디렉터리(0700)가 필요합니다.")


def _sidecars(path: Path):
    return [path.with_name(path.name + suffix) for suffix in ("-journal", "-wal", "-shm")]


def _check_private_file(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError("운영자 소유의 비공개 일반 파일만 허용합니다.")


def initialize(path: Path) -> None:
    _check_directory(path)
    for file in (path, *_sidecars(path)):
        if os.path.lexists(file):
            raise FileExistsError(file)
    # 같은 파일시스템에서 완성된 DB만 게시한다. 경합한 init의 결과를 덮지 않는다.
    with tempfile.TemporaryDirectory(dir=path.parent, prefix=".account-init-") as work:
        staged = Path(work) / "db"
        staged.touch(mode=0o600, exist_ok=False)
        with closing(sqlite3.connect(staged)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("BEGIN IMMEDIATE;\n" + ACCOUNT_SCHEMA + jobs_schema(registered_users=True)
                               + f"PRAGMA application_id={APP_ID};\nCOMMIT;")
        os.link(staged, path)


@contextmanager
def connection(path: Path, *, write: bool):
    _check_directory(path)
    _check_private_file(path)
    # 다른 WAL DB에 연결하기만 해도 SQLite가 sidecar를 생성할 수 있다.
    with path.open("rb") as db_file:
        db_file.seek(68)  # SQLite 파일 헤더의 application_id
        if db_file.read(4) != APP_ID.to_bytes(4, "big"):
            raise ValueError("새 계정 DB만 사용할 수 있습니다.")
    for file in _sidecars(path):
        try:
            _check_private_file(file)
        except FileNotFoundError:
            pass  # 다른 정상 연결이 닫히며 WAL/SHM을 정리할 수 있다.
    uri = path.absolute().as_uri() + ("?mode=rw" if write else "?mode=ro")
    with closing(sqlite3.connect(uri, uri=True)) as conn, conn:
        if conn.execute("PRAGMA application_id").fetchone()[0] != APP_ID:
            raise ValueError("새 계정 DB만 사용할 수 있습니다.")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn


def _digest(key: str) -> bytes:
    return hashlib.sha256(key.encode()).digest()


def issue(path: Path, user_id: str | None = None) -> tuple[str, str]:
    with connection(path, write=True) as conn:
        now = time.time()
        if user_id is None:
            user_id = str(uuid.uuid4())
            conn.execute("INSERT INTO users(user_id) VALUES (?)", (user_id,))
        elif not conn.execute("SELECT 1 FROM users WHERE user_id=? AND disabled_at IS NULL",
                              (user_id,)).fetchone():
            raise ValueError("발급 가능한 사용자가 없습니다.")
        conn.execute("UPDATE credentials SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                     (now, user_id))
        key = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO credentials(digest,user_id,expires_at) VALUES (?,?,?)",
                     (_digest(key), user_id, now + KEY_LIFETIME))
    return user_id, key


def revoke(path: Path, user_id: str, *, suspend: bool = False) -> None:
    with connection(path, write=True) as conn:
        now = time.time()
        if not conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
            raise ValueError("등록된 사용자가 없습니다.")
        if suspend:
            conn.execute("UPDATE users SET disabled_at=COALESCE(disabled_at,?) WHERE user_id=?", (now, user_id))
        conn.execute("UPDATE credentials SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, user_id))


def identify(path: Path, key: str) -> str | None:
    with connection(path, write=False) as conn:
        return identify_in(conn, key)


def identify_in(conn: sqlite3.Connection, key: str) -> str | None:
    """호출자의 읽기 스냅샷 또는 쓰기 잠금 안에서 현재 자격을 확인한다."""
    row = conn.execute(
        "SELECT c.user_id FROM credentials c JOIN users u ON u.user_id=c.user_id "
        "WHERE c.digest=? AND c.revoked_at IS NULL AND u.disabled_at IS NULL AND c.expires_at>?",
        (_digest(key), time.time()),
    ).fetchone()
    return row[0] if row else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("init", help="존재하지 않는 새 파일에만 스키마 생성")
    commands.add_parser("issue", help="사용자와 첫 키 발급")
    for action in ("reissue", "revoke", "suspend"):
        commands.add_parser(action).add_argument("user_id")
    parser.epilog = "isatty는 표준 출력이 터미널인지 여부만 확인합니다. 터미널 녹화·스크롤백은 운영자가 관리하세요."
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            initialize(args.db)
        elif args.action in ("issue", "reissue"):
            if not sys.stdout.isatty():
                parser.error("키 발급은 기록되지 않는 대화형 터미널에서 실행하세요.")
            uid, key = issue(args.db, getattr(args, "user_id", None))
            print(f"user_id={uid}\nkey={key}")
        else:
            revoke(args.db, args.user_id, suspend=args.action == "suspend")
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"계정 작업 실패 ({type(exc).__name__})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
