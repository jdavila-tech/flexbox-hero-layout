"""A persistent queue (SQLite) and one background worker that processes titles one at a time."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import export, pipeline
from .config import SETTINGS

log = logging.getLogger("jobs")
_lock = threading.Lock()
_wake = threading.Event()
_cancel: set[str] = set()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(SETTINGS.data_dir / "jobs.sqlite3", timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL,
            status TEXT NOT NULL, stage TEXT, progress REAL DEFAULT 0,
            error TEXT, created REAL, updated REAL)""")
        # A job that was running when the app stopped goes back in the queue.
        c.execute("UPDATE jobs SET status='queued', stage='Waiting', progress=0 WHERE status='running'")


def enqueue(path: Path, kind: str) -> dict | None:
    with _lock, _db() as c:
        existing = c.execute("SELECT id FROM jobs WHERE path=? AND kind=? AND status IN ('queued','running')",
                             (str(path), kind)).fetchone()
        if existing:
            return None
        jid = uuid.uuid4().hex[:12]
        now = time.time()
        c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
                  (jid, str(path), kind, "queued", "Waiting", 0.0, None, now, now))
    _wake.set()
    return {"id": jid}


def list_jobs(limit: int = 200) -> list[dict]:
    with _db() as c:
        rows = c.execute("""SELECT * FROM jobs ORDER BY
            CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, created DESC LIMIT ?""",
                         (limit,)).fetchall()
    return [dict(r) | {"name": Path(r["path"]).name} for r in rows]


def active_paths() -> dict[str, str]:
    with _db() as c:
        rows = c.execute("SELECT path, status FROM jobs WHERE status IN ('queued','running')").fetchall()
    return {r["path"]: r["status"] for r in rows}


def cancel(jid: str) -> None:
    with _lock, _db() as c:
        c.execute("UPDATE jobs SET status='cancelled', stage='Cancelled', updated=? WHERE id=? AND status='queued'",
                  (time.time(), jid))
        _cancel.add(jid)


def clear_finished() -> None:
    with _db() as c:
        c.execute("DELETE FROM jobs WHERE status IN ('done','error','cancelled')")


def _update(jid: str, **fields) -> None:
    fields["updated"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    with _db() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), jid))


def _next() -> sqlite3.Row | None:
    with _lock, _db() as c:
        row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        if row:
            c.execute("UPDATE jobs SET status='running', stage='Starting', updated=? WHERE id=?", (time.time(), row["id"]))
        return row


def _run(row: sqlite3.Row) -> None:
    jid, path, kind = row["id"], Path(row["path"]), row["kind"]
    last = [0.0]

    def progress(stage: str, frac: float) -> None:
        now = time.time()
        if now - last[0] > 1.0 or frac >= 1.0:
            last[0] = now
            _update(jid, stage=stage, progress=round(frac, 3))

    def should_stop() -> bool:
        return jid in _cancel

    try:
        if not path.exists():
            raise FileNotFoundError("The file is no longer there")
        if kind == "scan":
            pipeline.scan(path, progress, should_stop, job_id=jid)
        elif kind == "export":
            export.make_family_edit(path, progress)
        _update(jid, status="done", progress=1.0)
    except InterruptedError:
        _update(jid, status="cancelled", stage="Cancelled")
    except Exception as e:
        log.error("Job %s failed: %s", jid, traceback.format_exc())
        _update(jid, status="error", stage="Failed", error=str(e)[:500])
    finally:
        _cancel.discard(jid)


def _loop() -> None:
    try:
        os.nice(10)  # be gentle with the server
    except OSError:
        pass
    while True:
        row = _next()
        if row is None:
            _wake.wait(timeout=10)
            _wake.clear()
            continue
        _run(row)


def start_worker() -> None:
    init()
    threading.Thread(target=_loop, name="worker", daemon=True).start()
