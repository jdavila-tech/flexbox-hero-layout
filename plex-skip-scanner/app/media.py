"""ffmpeg / ffprobe helpers: frame sampling, scene cuts, duration, subtitles."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable

PTS_RE = re.compile(r"pts_time:([0-9.]+)")
TIME_RE = re.compile(r"time=(\d+):(\d+):([0-9.]+)")
SRT_TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out or 0)


def sample_frames(video: Path, out_dir: Path, fps: float, scene_threshold: float,
                  on_progress: Callable[[float], None] | None = None,
                  should_stop: Callable[[], bool] | None = None) -> tuple[list[tuple[float, Path]], list[float]]:
    """Decode the video once: save frames at `fps`, plus the first frame after every scene cut
    (so very short shots are not missed), and record the scene-cut times.

    Returns ([(timestamp, frame_path)] sorted by time, [cut_times]).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cut_dir = out_dir / "cuts"
    cut_dir.mkdir(exist_ok=True)
    total = duration(video) or 1.0
    graph = (
        f"[0:v]split=2[a][b];"
        f"[a]fps={fps},scale='min(640,iw)':-2[f];"
        f"[b]scale='min(640,iw)':-2,select='gt(scene\\,{scene_threshold})',showinfo[s]"
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(video), "-an", "-sn",
        "-filter_complex", graph,
        "-map", "[f]", "-q:v", "4", str(out_dir / "%07d.jpg"),
        "-map", "[s]", "-fps_mode", "passthrough", "-q:v", "4", str(cut_dir / "%07d.jpg"),
    ]
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, errors="replace")
    cuts: list[float] = []
    assert proc.stderr is not None
    buf = ""
    while True:
        chunk = proc.stderr.read(4096)
        if not chunk:
            break
        buf += chunk
        *lines, buf = re.split(r"[\r\n]", buf)
        for line in lines:
            if "showinfo" in line and "pts_time:" in line:
                m = PTS_RE.search(line)
                if m:
                    cuts.append(float(m.group(1)))
            elif on_progress and "time=" in line:
                m = TIME_RE.search(line)
                if m:
                    t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    on_progress(min(t / total, 1.0))
        if should_stop and should_stop():
            proc.kill()
            proc.wait()
            raise InterruptedError("cancelled")
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed while reading {video.name}")
    frames = [((int(f.stem) - 1) / fps, f) for f in sorted(out_dir.glob("*.jpg"))]
    # The k-th saved cut image belongs to the k-th scene cut ffmpeg reported.
    cut_imgs = sorted(cut_dir.glob("*.jpg"))
    regular = len(frames)
    for t, f in zip(cuts, cut_imgs):
        i = int(t * fps)
        near = frames[max(i - 1, 0):min(i + 2, regular)]
        if not any(abs(t - x) < 0.25 for x, _ in near):
            frames.append((t, f))
    frames.sort(key=lambda x: x[0])
    return frames, sorted(cuts)


def sample_window(video: Path, out_dir: Path, start: float, end: float, fps: float) -> list[tuple[float, Path]]:
    """Frames between start and end at a higher rate, for refining a segment's edges."""
    out_dir.mkdir(parents=True, exist_ok=True)
    start = max(0.0, start)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-ss", f"{start:.3f}", "-i", str(video),
         "-t", f"{max(end - start, 0.1):.3f}", "-an", "-sn",
         "-vf", f"fps={fps},scale='min(640,iw)':-2", "-q:v", "4", str(out_dir / "%07d.jpg")],
        capture_output=True, check=True,
    )
    return [(start + (int(f.stem) - 1) / fps, f) for f in sorted(out_dir.glob("*.jpg"))]


def find_subtitles(video: Path) -> Path | None:
    candidates = sorted(video.parent.glob(f"{glob_escape(video.stem)}*.srt"))
    for pref in (".en.srt", ".eng.srt", ".english.srt", ".srt"):
        for c in candidates:
            if c.name.lower().endswith(pref):
                return c
    return candidates[0] if candidates else None


def glob_escape(s: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", s)


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    text = path.read_text(errors="replace")
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        m = SRT_TIME_RE.search(block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = block[m.end():].strip()
        body = re.sub(r"<[^>]+>|\{[^}]+\}", "", body).replace("\n", " ").strip()
        if body:
            out.append((start, end, body))
    return out


def keyframes(video: Path) -> list[float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    times = []
    for line in out.splitlines():
        line = line.strip().rstrip(",")
        try:
            times.append(float(line))
        except ValueError:
            continue
    return sorted(times)
