"""Scan one video: sample frames, detect candidates, refine edges, have Claude review, write skip files."""
from __future__ import annotations

import bisect
import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps, ImageStat

from . import media, review, skips
from .config import SETTINGS

log = logging.getLogger("pipeline")

Progress = Callable[[str, float], None]
StopCheck = Callable[[], bool]

_detector = None


def detector():
    global _detector
    if _detector is None:
        from nudenet import NudeDetector  # heavy import; load once, lazily
        _detector = NudeDetector()
    return _detector


def video_key(video: Path) -> str:
    return hashlib.sha1(str(video).encode()).hexdigest()[:16]


def thumbs_dir(video: Path) -> Path:
    return SETTINGS.data_dir / "thumbs" / video_key(video)


def _brighten_if_dark(path: Path) -> None:
    img = Image.open(path)
    lum = ImageStat.Stat(img.convert("L")).mean[0]
    if lum < 55:
        img = ImageOps.autocontrast(img.convert("RGB"), cutoff=1)
        img = img.point(lambda v: int(255 * (v / 255) ** 0.6))
        img.save(path, "JPEG", quality=85)


def _detect(frames: list[tuple[float, Path]], progress: Progress | None, base: float, span: float,
            should_stop: StopCheck | None) -> list[dict]:
    """Run the detector; return hits [{t, score, labels, path}] for frames above threshold."""
    wanted = set(SETTINGS.detector_classes)
    hits = []
    batch = 16
    for i in range(0, len(frames), batch):
        if should_stop and should_stop():
            raise InterruptedError("cancelled")
        chunk = frames[i:i + batch]
        if SETTINGS.brighten_dark_frames:
            for _, p in chunk:
                _brighten_if_dark(p)
        results = detector().detect_batch([str(p) for _, p in chunk], batch_size=batch)
        for (t, p), dets in zip(chunk, results):
            labels: dict[str, float] = {}
            for d in dets:
                if d["class"] in wanted and d["score"] >= SETTINGS.detector_threshold:
                    labels[d["class"]] = max(labels.get(d["class"], 0.0), round(float(d["score"]), 3))
            if labels:
                hits.append({"t": t, "score": max(labels.values()), "labels": labels, "path": p})
        if progress:
            progress("Looking for possible nudity", base + span * min((i + batch) / max(len(frames), 1), 1.0))
    return hits


def _group(hits: list[dict], step: float) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for h in sorted(hits, key=lambda x: x["t"]):
        if groups and h["t"] - groups[-1][-1]["t"] <= SETTINGS.group_gap_sec:
            groups[-1].append(h)
        else:
            groups.append([h])
    return groups


def _refine(video: Path, work: Path, start: float, end: float, idx: int) -> tuple[float, float]:
    """Look at the edges at a higher frame rate to find where the nudity really starts and ends."""
    fps = SETTINGS.refine_fps
    wanted = set(SETTINGS.detector_classes)

    def hit_times(frames):
        if not frames:
            return []
        res = detector().detect_batch([str(p) for _, p in frames], batch_size=16)
        return [t for (t, _), dets in zip(frames, res)
                if any(d["class"] in wanted and d["score"] >= SETTINGS.detector_threshold for d in dets)]

    try:
        a = hit_times(media.sample_window(video, work / f"r{idx}a", start - 2.0, start + 0.6, fps))
        b = hit_times(media.sample_window(video, work / f"r{idx}b", end - 0.6, end + 2.0, fps))
    except Exception as e:  # refinement is best-effort
        log.warning("Edge refinement failed: %s", e)
        return start, end
    new_start = min(a) if a else start
    new_end = max(b) + 1.0 / fps if b else end
    return min(new_start, start), max(new_end, end)


def _snap(start: float, end: float, cuts: list[float], total: float) -> tuple[float, float]:
    start = max(0.0, start - SETTINGS.padding_sec)
    end = min(total, end + SETTINGS.padding_sec) if total else end + SETTINGS.padding_sec
    i = bisect.bisect_right(cuts, start) - 1
    if i >= 0 and start - cuts[i] <= SETTINGS.snap_to_cut_sec:
        start = cuts[i]
    j = bisect.bisect_left(cuts, end)
    if j < len(cuts) and cuts[j] - end <= SETTINGS.snap_to_cut_sec:
        end = cuts[j]
    if end - start < SETTINGS.min_segment_sec:
        end = start + SETTINGS.min_segment_sec
    return start, end


def _pick_review_frames(group: list[dict], all_frames: list[tuple[float, Path]], start: float, end: float) -> list[tuple[float, Path]]:
    n = max(SETTINGS.frames_per_segment, 1)
    chosen: dict[float, Path] = {}
    for h in sorted(group, key=lambda x: -x["score"])[: max(n // 2, 1)]:
        chosen[h["t"]] = h["path"]
    inside = [f for f in all_frames if start <= f[0] <= end]
    if inside:
        for k in (0, len(inside) // 2, len(inside) - 1):
            if len(chosen) >= n:
                break
            chosen.setdefault(inside[k][0], inside[k][1])
    for h in group:
        if len(chosen) >= n:
            break
        chosen.setdefault(h["t"], h["path"])
    return sorted(chosen.items())[:n]


def _cache_path(video: Path) -> Path:
    d = SETTINGS.data_dir / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{video_key(video)}.json"


def _subs_near(subs: list[tuple[float, float, str]], start: float, end: float) -> list[str]:
    w = SETTINGS.subtitle_window_sec
    return [f"[{int(a // 60)}:{int(a % 60):02d}] {txt}" for a, b, txt in subs if b >= start - w and a <= end + w][:40]


def scan(video: Path, progress: Progress | None = None, should_stop: StopCheck | None = None,
         job_id: str = "manual") -> dict:
    work = SETTINGS.data_dir / "work" / job_id
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        return _scan(video, work, progress, should_stop)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _scan(video: Path, work: Path, progress: Progress | None, should_stop: StopCheck | None) -> dict:
    p = progress or (lambda *_: None)
    stat = video.stat()
    total = media.duration(video)

    p("Reading video", 0.0)
    frames, cuts = media.sample_frames(
        video, work / "frames", SETTINGS.sample_fps, SETTINGS.scene_threshold,
        on_progress=lambda f: p("Reading video", 0.35 * f), should_stop=should_stop,
    )

    hits = _detect(frames, p, 0.35, 0.35, should_stop)
    groups = _group(hits, 1.0 / SETTINGS.sample_fps)
    log.info("%s: %d frames, %d hits, %d candidate segments", video.name, len(frames), len(hits), len(groups))

    cache_file = _cache_path(video)
    cache: dict = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    subs_path = media.find_subtitles(video)
    subs = media.parse_srt(subs_path) if subs_path else []
    tdir = thumbs_dir(video)
    shutil.rmtree(tdir, ignore_errors=True)
    tdir.mkdir(parents=True, exist_ok=True)

    use_claude = review.available()
    tokens = {"input_tokens": 0, "output_tokens": 0}
    segments = []
    for idx, group in enumerate(groups):
        if should_stop and should_stop():
            raise InterruptedError("cancelled")
        p(f"Reviewing scene {idx + 1} of {len(groups)}", 0.70 + 0.28 * idx / max(len(groups), 1))
        raw_start, raw_end = group[0]["t"], group[-1]["t"] + 1.0 / SETTINGS.sample_fps
        r_start, r_end = _refine(video, work, raw_start, raw_end, idx)
        start, end = _snap(r_start, r_end, cuts, total)

        labels: dict[str, float] = {}
        for h in group:
            for k, v in h["labels"].items():
                labels[k] = max(labels.get(k, 0.0), v)
        best = max(group, key=lambda x: x["score"])
        seg = skips.new_segment(start, end, raw_start=round(raw_start, 3), raw_end=round(raw_end, 3),
                                peak_score=best["score"], labels=labels, hits=len(group))
        img = Image.open(best["path"]).convert("RGB")
        img.thumbnail((360, 360))
        img.save(tdir / f"{seg['id']}.jpg", "JPEG", quality=75)

        key = f"{stat.st_size}:{int(stat.st_mtime)}:{raw_start:.1f}:{raw_end:.1f}:{review.model_label()}"
        if key in cache:
            seg["review"] = cache[key]
        elif use_claude:
            frames_for_review = _pick_review_frames(group, frames, start, end)
            result = review.classify(frames_for_review, _subs_near(subs, start, end), video.stem)
            seg["review"] = result
            for k in tokens:
                tokens[k] += (result.get("usage") or {}).get(k, 0)
            if not result.get("error"):
                cache[key] = result
                cache_file.write_text(json.dumps(cache))
        else:
            seg["review"] = {"category": "unclear", "confidence": 0.0,
                             "reason_short": f"Not checked by Claude: {review.unavailable_reason()}", "model": None}
        segments.append(seg)

    old = skips.load(video)
    record = {
        "video": video.name,
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "duration": round(total, 3),
        "frames_checked": len(frames),
        "scene_cuts": len(cuts),
        "subtitles": subs_path.name if subs_path else None,
        "review_model": review.model_label() if use_claude else None,
        "tokens": tokens,
        "edl_sha256": (old or {}).get("edl_sha256"),
        "segments": skips.carry_over_user_decisions(segments, old),
    }
    status = skips.save(video, record)
    p("Done" if status != "edl.new" else "Done (your edited .edl kept; new one saved as .edl.new)", 1.0)
    return record
