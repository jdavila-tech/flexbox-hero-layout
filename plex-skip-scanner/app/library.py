"""Reads the Plex Movies and TV folders and reports each video's scan status."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import SETTINGS

SEASON_RE = re.compile(r"(season|series|s)\s*0*(\d+)", re.I)
SAMPLE_RE = re.compile(r"(^|[\s._-])sample$", re.I)


class PathError(ValueError):
    pass


def roots() -> dict[str, Path]:
    return {"movies": SETTINGS.movies_dir, "tv": SETTINGS.tv_dir}


def safe_video_path(path_str: str) -> Path:
    """Resolve a path and make sure it is a video inside one of the library roots."""
    p = Path(path_str).resolve()
    for root in roots().values():
        try:
            p.relative_to(root)
        except ValueError:
            continue
        if not p.is_file():
            raise PathError("File not found")
        if p.suffix.lower() not in SETTINGS.video_extensions:
            raise PathError("Not a video file")
        return p
    raise PathError("Path is outside the library folders")


def sidecar(video: Path, suffix: str) -> Path:
    return video.with_name(video.stem + suffix)


def is_family_edit(p: Path) -> bool:
    return p.stem.endswith(f" - {SETTINGS.family_suffix}")


def _videos_in(folder: Path) -> list[Path]:
    out = []
    for p in folder.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SETTINGS.video_extensions:
            continue
        if SAMPLE_RE.search(p.stem) or p.parent.name.lower() in ("sample", "samples", "extras", "featurettes", "trailers"):
            continue
        if is_family_edit(p):
            continue
        out.append(p)
    return sorted(out, key=lambda x: x.name.lower())


def file_status(video: Path) -> dict:
    info = {
        "path": str(video),
        "name": video.name,
        "size": video.stat().st_size,
        "scanned": False,
        "skips": 0,
        "review": 0,
        "has_family_edit": False,
    }
    sj = sidecar(video, ".skips.json")
    if sj.exists():
        try:
            data = json.loads(sj.read_text())
            segs = data.get("segments", [])
            info["scanned"] = True
            info["skips"] = sum(1 for s in segs if s.get("final") == "skip")
            info["review"] = sum(1 for s in segs if s.get("needs_review") and not s.get("user_decision"))
            info["scanned_at"] = data.get("scanned_at")
        except (OSError, json.JSONDecodeError):
            pass
    fam = video.with_name(f"{video.stem} - {SETTINGS.family_suffix}{video.suffix if video.suffix.lower() == '.mkv' else '.mkv'}")
    info["has_family_edit"] = fam.exists()
    return info


def list_movies() -> list[dict]:
    root = SETTINGS.movies_dir
    if not root.is_dir():
        return []
    items = []
    for entry in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            vids = _videos_in(entry)
            if vids:
                items.append({"title": entry.name, "files": [file_status(v) for v in vids]})
        elif entry.is_file() and entry.suffix.lower() in SETTINGS.video_extensions and not is_family_edit(entry):
            items.append({"title": entry.stem, "files": [file_status(entry)]})
    return items


def _season_label(folder: Path, show: Path) -> str:
    if folder == show:
        return "Episodes"
    return folder.relative_to(show).parts[0]


def _season_sort(label: str) -> tuple:
    m = SEASON_RE.search(label)
    return (0, int(m.group(2))) if m else (1, label.lower())


def list_tv() -> list[dict]:
    root = SETTINGS.tv_dir
    if not root.is_dir():
        return []
    shows = []
    for show in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        if not show.is_dir() or show.name.startswith("."):
            continue
        seasons: dict[str, list[dict]] = {}
        for v in _videos_in(show):
            seasons.setdefault(_season_label(v.parent, show), []).append(file_status(v))
        if seasons:
            shows.append({
                "title": show.name,
                "seasons": [{"title": k, "episodes": seasons[k]} for k in sorted(seasons, key=_season_sort)],
            })
    return shows
