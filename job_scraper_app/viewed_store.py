"""Tracks which job IDs the user has clicked into, persisted to a local
JSON file so it survives page reloads and server restarts."""
import json
import os
import threading

VIEWED_FILE = os.path.join(os.path.dirname(__file__), "viewed.json")
_lock = threading.Lock()


def _load():
    if not os.path.exists(VIEWED_FILE):
        return set()
    with open(VIEWED_FILE) as f:
        return set(json.load(f))


def _save(viewed_ids):
    with open(VIEWED_FILE, "w") as f:
        json.dump(sorted(viewed_ids), f)


def get_viewed():
    return _load()


def mark_viewed(job_id):
    with _lock:
        viewed_ids = _load()
        if job_id not in viewed_ids:
            viewed_ids.add(job_id)
            _save(viewed_ids)
