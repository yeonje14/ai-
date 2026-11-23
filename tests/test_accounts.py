"""운영 DB 대신 pytest 임시 디렉터리에서 계정 발급과 전환 절차를 검증한다."""
import hashlib
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server import accounts


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "accounts.sqlite"
    accounts.initialize(path)
    return path


def test_secret_storage_and_absolute_expiry(db, monkeypatch):
    now = 1000.0
    monkeypatch.setattr(accounts.time, "time", lambda: now)
    uid, key = accounts.issue(db)
    with accounts.connection(db, write=False) as conn:
        digest, expiry = conn.execute("SELECT digest,expires_at FROM credentials").fetchone()
        assert digest == hashlib.sha256(key.encode()).digest()
        assert expiry == 1000 + 24 * 3600
        assert key not in "\n".join(conn.iterdump())
        assert all(key.encode() not in p.read_bytes() for p in db.parent.glob("accounts.sqlite*"))
    now = expiry - 0.01
    assert accounts.identify(db, key) == uid
    now = expiry
    assert accounts.identify(db, key) is None


def test_reissue_rollback_and_concurrent_rotation(db, monkeypatch):
    uid, old = accounts.issue(db)
    with monkeypatch.context() as patch:
        patch.setattr(accounts.secrets, "token_urlsafe", lambda _: old)
        with pytest.raises(sqlite3.IntegrityError):
            accounts.issue(db, uid)
    assert accounts.identify(db, old) == uid
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: accounts.issue(db, uid), range(2)))
    assert all(owner == uid for owner, _ in results)
    assert sum(accounts.identify(db, key) == uid for _, key in results) == 1
    assert accounts.identify(db, old) is None


def test_revoke_and_suspend_survive_operator_restart(db):
    uid, old = accounts.issue(db)
    cmd = [sys.executable, "-m", "server.accounts", "--db", str(db)]
    subprocess.run([*cmd, "revoke", uid], check=True)
    assert accounts.identify(db, old) is None
    _, new = accounts.issue(db, uid)
    subprocess.run([*cmd, "suspend", uid], check=True)
    assert accounts.identify(db, new) is None
    with pytest.raises(ValueError):
        accounts.issue(db, uid)


def test_cli_refuses_redirected_key_before_writing(db):
    result = subprocess.run([sys.executable, "-m", "server.accounts", "--db", str(db), "issue"],
                            capture_output=True)
    assert result.returncode != 0 and result.stdout == b""
    with accounts.connection(db, write=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_transition_rehearsal(tmp_path, queue, settings):
    # 이미 구 Worker의 drain이 끝난 체크포인트를 이번 테스트 디렉터리에 준비한다.
    assert settings.db_path.parent == settings.runtime_dir.parent == tmp_path
    aid = "c3fc48fd-f100-43a5-848d-a86a13cc94bb"
    with closing(sqlite3.connect(queue.db_path)) as conn, conn:
        conn.execute("INSERT INTO jobs(analysis_id,owner_hash,youtube_video_id,job_status,"
                     "created_at,started_at,finished_at,attempts) "
                     "VALUES (?,'legacy-owner','TRINITYnone','finished',1,2,3,1)", (aid,))
    settings.db_path.chmod(0o600)
    settings.runtime_dir.mkdir()
    assert queue.get(aid, "legacy-owner").job_status == "finished"
    archive = tmp_path / "archive"
    archive.mkdir(mode=0o700)
    legacy = archive / settings.db_path.name
    # Worker 종료와 DB 연결 종료 뒤 sidecar까지 같은 보관 위치에 둔다.
    for path in tmp_path.glob(settings.db_path.name + "*"):
        path.rename(archive / path.name)
    settings.runtime_dir.rename(archive / "runtime")
    old_bytes = legacy.read_bytes()
    with pytest.raises(FileExistsError):
        accounts.initialize(legacy)
    with pytest.raises(ValueError):
        accounts.issue(legacy)
    fresh = tmp_path / "new"
    fresh.mkdir(mode=0o700)
    (fresh / "runtime").mkdir()
    db = fresh / "queue.sqlite"
    accounts.initialize(db)
    with accounts.connection(db, write=True) as conn:
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute("INSERT INTO jobs(analysis_id,user_id,youtube_video_id,job_status,created_at) "
                         "VALUES ('job','legacy-owner','TRINITYnone','queued',0)")
    assert legacy.read_bytes() == old_bytes
    with closing(sqlite3.connect(f"{legacy.as_uri()}?mode=ro", uri=True)) as conn:
        assert conn.execute("SELECT job_status FROM jobs WHERE analysis_id=?", (aid,)).fetchone() == ("finished",)
    assert (archive / "runtime").is_dir() and not list((fresh / "runtime").iterdir())


def test_interactive_operator_commands(db, monkeypatch, capsys):
    args = ["--db", str(db)]
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert accounts.main([*args, "issue"]) == 0
    lines = capsys.readouterr().out.splitlines()
    uid = lines[0].removeprefix("user_id=")
    old = lines[1].removeprefix("key=")
    assert accounts.identify(db, old) == uid
    assert accounts.main([*args, "reissue", uid]) == 0
    new = capsys.readouterr().out.splitlines()[1].removeprefix("key=")
    assert accounts.identify(db, old) is None and accounts.identify(db, new) == uid
    assert accounts.main([*args, "revoke", uid]) == 0
    assert accounts.identify(db, new) is None
    assert accounts.main([*args, "suspend", uid]) == 0
    assert accounts.main([*args, "reissue", uid]) == 1
    assert not capsys.readouterr().out


def test_failed_init_can_retry_without_partial_database(tmp_path, monkeypatch):
    path = tmp_path / "accounts.sqlite"
    with monkeypatch.context() as patch:
        patch.setattr(accounts, "ACCOUNT_SCHEMA", "INVALID SQL;")
        with pytest.raises(sqlite3.Error):
            accounts.initialize(path)
    assert not list(tmp_path.iterdir())
    accounts.initialize(path)
    assert accounts.issue(path)[0]


@pytest.mark.parametrize("suffix", ["", "-journal", "-wal", "-shm"])
def test_init_refuses_existing_file_or_link(tmp_path, suffix):
    path = tmp_path / "new.sqlite"
    occupied = tmp_path / ("new.sqlite" + suffix)
    occupied.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        accounts.initialize(path)
    assert occupied.read_bytes() == b"existing"
    occupied.unlink()
    occupied.symlink_to(tmp_path / "absent")
    with pytest.raises(FileExistsError):
        accounts.initialize(path)
    assert occupied.is_symlink() and not (tmp_path / "absent").exists()


def test_operations_refuse_aliases_and_unsafe_permissions(db, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(db)
    with pytest.raises(ValueError):
        accounts.issue(alias)
    alias.unlink()
    alias.hardlink_to(db)
    with pytest.raises(ValueError):
        accounts.issue(alias)
    alias.unlink()
    db.chmod(0o644)
    with pytest.raises(ValueError):
        accounts.issue(db)
    db.chmod(0o600)
    tmp_path.chmod(0o755)
    try:
        with pytest.raises(ValueError):
            accounts.issue(db)
    finally:
        tmp_path.chmod(0o700)


def test_db_wal_shm_are_private_and_contain_no_key(db):
    with accounts.connection(db, write=False) as conn:
        conn.execute("SELECT count(*) FROM users").fetchone()
        _, key = accounts.issue(db)
        for suffix in ("", "-wal", "-shm"):
            file = db.with_name(db.name + suffix)
            assert file.stat().st_mode & 0o077 == 0
            assert key.encode() not in file.read_bytes()


def test_concurrent_reissue_revoke_suspend(db):
    from threading import Barrier

    uid, old = accounts.issue(db)
    barrier = Barrier(3)

    def operate(action):
        barrier.wait(timeout=5)
        if action == "reissue":
            try:
                return accounts.issue(db, uid)[1]
            except ValueError:
                return None  # 정지가 먼저 커밋됐다.
        accounts.revoke(db, uid, suspend=action == "suspend")
        return None

    with ThreadPoolExecutor(3) as pool:
        keys = list(pool.map(operate, ("reissue", "revoke", "suspend")))
    for key in [old, *filter(None, keys)]:
        assert accounts.identify(db, key) is None
    with accounts.connection(db, write=False) as conn:
        assert conn.execute("SELECT count(*) FROM credentials WHERE revoked_at IS NULL").fetchone() == (0,)
    with pytest.raises(ValueError):
        accounts.issue(db, uid)


def test_wrong_database_open_leaves_no_sidecars(tmp_path):
    path = tmp_path / "other.sqlite"
    path.touch(mode=0o600)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE existing (id INTEGER PRIMARY KEY)")
    original = path.read_bytes()
    with pytest.raises(ValueError):
        accounts.issue(path)
    assert path.read_bytes() == original and list(tmp_path.iterdir()) == [path]


def test_connection_rejects_linked_sidecar_and_parent(db):
    sidecar = db.with_name(db.name + "-wal")
    target = db.parent / "untouched"
    target.write_bytes(b"marker")
    sidecar.symlink_to(target)
    with pytest.raises(ValueError):
        accounts.issue(db)
    assert sidecar.is_symlink() and target.read_bytes() == b"marker"
    alias = db.parent / "alias"
    alias.symlink_to(db.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        accounts.initialize(alias / "new.db")
    assert not (db.parent / "new.db").exists()


def test_competing_initializers_publish_once(tmp_path):
    db = tmp_path / "accounts.sqlite"

    def initialize(_):
        try:
            accounts.initialize(db)
        except FileExistsError:
            return False
        return True

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(initialize, range(2))) == [False, True]
    uid, key = accounts.issue(db)
    assert accounts.identify(db, key) == uid
