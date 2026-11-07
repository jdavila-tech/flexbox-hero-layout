"""Web server: browse the Plex library, queue titles, review flagged scenes."""
from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import jobs, library, pipeline, review, skips
from .config import SETTINGS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

APP_USER = os.environ.get("APP_USER", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
if not APP_PASSWORD:
    APP_PASSWORD = secrets.token_urlsafe(12)
    log.warning("APP_PASSWORD is not set. Temporary password for user '%s': %s", APP_USER, APP_PASSWORD)

security = HTTPBasic(realm="Skip Scanner")


def auth(creds: HTTPBasicCredentials = Depends(security)) -> None:
    ok = secrets.compare_digest(creds.username.encode(), APP_USER.encode()) and \
        secrets.compare_digest(creds.password.encode(), APP_PASSWORD.encode())
    if not ok:
        raise HTTPException(401, "Wrong user or password", headers={"WWW-Authenticate": 'Basic realm="Skip Scanner"'})


@asynccontextmanager
async def lifespan(_app):
    jobs.start_worker()
    log.info("Movies: %s | TV: %s | Claude review: %s", SETTINGS.movies_dir, SETTINGS.tv_dir,
             f"on via {review.model_label()}" if review.available() else f"OFF ({review.unavailable_reason()})")
    yield


app = FastAPI(title="Skip Scanner", dependencies=[Depends(auth)], docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)
STATIC = Path(__file__).parent / "static"


def _video(path: str) -> Path:
    try:
        return library.safe_video_path(path)
    except library.PathError as e:
        raise HTTPException(400, str(e))


def _with_jobs(files: list[dict], active: dict[str, str]) -> None:
    for f in files:
        f["job"] = active.get(f["path"])


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    return {
        "movies_dir": str(SETTINGS.movies_dir), "movies_ok": SETTINGS.movies_dir.is_dir(),
        "tv_dir": str(SETTINGS.tv_dir), "tv_ok": SETTINGS.tv_dir.is_dir(),
        "review": review.available(), "model": review.model_label(), "review_off_reason": review.unavailable_reason(),
        "skip_categories": SETTINGS.skip_categories,
        "confidence_threshold": SETTINGS.confidence_threshold,
        "unreviewed_default": SETTINGS.unreviewed_default,
        "family_suffix": SETTINGS.family_suffix,
    }


@app.get("/api/library/movies")
def movies():
    items = library.list_movies()
    active = jobs.active_paths()
    for m in items:
        _with_jobs(m["files"], active)
    return items


@app.get("/api/library/tv")
def tv():
    shows = library.list_tv()
    active = jobs.active_paths()
    for s in shows:
        for season in s["seasons"]:
            _with_jobs(season["episodes"], active)
    return shows


class JobRequest(BaseModel):
    paths: list[str]
    kind: str = "scan"


@app.post("/api/jobs")
def add_jobs(req: JobRequest):
    if req.kind not in ("scan", "export"):
        raise HTTPException(400, "Unknown job type")
    added, skipped = 0, 0
    for p in req.paths:
        v = _video(p)
        if jobs.enqueue(v, req.kind):
            added += 1
        else:
            skipped += 1
    return {"added": added, "already_queued": skipped}


@app.get("/api/jobs")
def get_jobs():
    return jobs.list_jobs()


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    jobs.cancel(jid)
    return {"ok": True}


@app.post("/api/jobs/clear")
def clear_jobs():
    jobs.clear_finished()
    return {"ok": True}


@app.get("/api/title")
def title(path: str):
    v = _video(path)
    rec = skips.load(v)
    return {"path": str(v), "name": v.name, "record": rec, "file": library.file_status(v)}


@app.get("/api/thumb")
def thumb(path: str, seg: str):
    v = _video(path)
    if not seg.isalnum():
        raise HTTPException(400, "Bad segment id")
    f = pipeline.thumbs_dir(v) / f"{seg}.jpg"
    if not f.exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


class Decision(BaseModel):
    path: str
    seg_id: str
    decision: str | None = None  # "skip" | "keep" | None (back to automatic)
    start: float | None = None
    end: float | None = None


@app.post("/api/decision")
def decide(d: Decision):
    if d.decision not in ("skip", "keep", None):
        raise HTTPException(400, "decision must be skip, keep or null")
    try:
        return skips.set_decision(_video(d.path), d.seg_id, d.decision, d.start, d.end)
    except KeyError as e:
        raise HTTPException(404, str(e))


class Manual(BaseModel):
    path: str
    start: float
    end: float
    note: str = ""


@app.post("/api/manual")
def add_manual(m: Manual):
    if m.end <= m.start or m.start < 0:
        raise HTTPException(400, "End must be after start")
    return skips.add_manual(_video(m.path), m.start, m.end, m.note)


class ManualDelete(BaseModel):
    path: str
    seg_id: str


@app.post("/api/manual/delete")
def delete_manual(m: ManualDelete):
    try:
        return skips.delete_manual(_video(m.path), m.seg_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
