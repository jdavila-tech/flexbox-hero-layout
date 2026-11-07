"""Plex "Family Edit": a second copy of the video with the skipped scenes cut out.

Plex apps ignore .edl skip files, so for Plex the way to skip scenes is a separate version of the
video. Plex shows it under "Play Version". Streams are copied, not re-encoded, so it is fast and
lossless; cuts land on keyframes, always on the side that removes MORE, never less.
"""
from __future__ import annotations

import bisect
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from . import media, skips
from .config import SETTINGS


def family_path(video: Path) -> Path:
    return video.with_name(f"{video.stem} - {SETTINGS.family_suffix}.mkv")


def keep_ranges(skip_ranges: list[tuple[float, float]], total: float, kf: list[float]) -> list[tuple[float, float]]:
    """Ranges to keep. Each kept range starts on a keyframe at or after a skip ends,
    and ends at or before the next skip starts."""
    keep = []
    pos = 0.0
    for a, b in skip_ranges:
        if a > pos:
            keep.append((pos, a))
        # next kept part must start on a keyframe at/after b
        i = bisect.bisect_left(kf, b)
        pos = kf[i] if i < len(kf) else total
    if pos < total:
        keep.append((pos, total))
    return [(s, e) for s, e in keep if e - s > 0.3]


def make_family_edit(video: Path, progress: Callable[[str, float], None] | None = None) -> Path:
    p = progress or (lambda *_: None)
    record = skips.load(video)
    if not record:
        raise ValueError("Scan this title first")
    ranges = [tuple(r) for r in skips.skip_ranges(record["segments"])]
    out = family_path(video)
    if not ranges:
        if out.exists():
            out.unlink()
        p("Nothing to skip; no Family Edit needed", 1.0)
        return out
    p("Finding keyframes", 0.05)
    total = media.duration(video)
    kf = media.keyframes(video)
    if not kf:
        raise RuntimeError("Could not read keyframes")
    parts = keep_ranges(ranges, total, kf)
    lines = ["ffconcat version 1.0"]
    esc = str(video).replace("'", "'\\''")
    for s, e in parts:
        lines += [f"file '{esc}'", f"inpoint {s:.3f}", f"outpoint {e:.3f}"]
    p("Writing Family Edit", 0.3)
    with tempfile.NamedTemporaryFile("w", suffix=".ffconcat", delete=False, dir=SETTINGS.data_dir) as f:
        f.write("\n".join(lines) + "\n")
        concat = f.name
    tmp_out = out.with_name("." + out.name + ".part")
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", concat,
             "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero", "-f", "matroska", str(tmp_out)],
            capture_output=True, check=True,
        )
        tmp_out.replace(out)
    except subprocess.CalledProcessError as e:
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg could not write the Family Edit: " + e.stderr.decode(errors="replace")[-400:])
    finally:
        Path(concat).unlink(missing_ok=True)
    p("Family Edit ready", 1.0)
    return out
