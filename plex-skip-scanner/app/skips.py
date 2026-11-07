"""The .skips.json record next to each video, decisions, and writing the Kodi .edl skip file."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from .config import SETTINGS
from .library import sidecar


def load(video: Path) -> dict | None:
    p = sidecar(video, ".skips.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o664)
    os.replace(tmp, path)


def auto_decision(seg: dict) -> tuple[str, bool]:
    """Return (auto_decision, needs_review) from Claude's review."""
    rev = seg.get("review") or {}
    cat = rev.get("category", "unclear")
    conf = float(rev.get("confidence", 0))
    if cat == "unclear" or conf < SETTINGS.confidence_threshold:
        return "review", True
    return ("skip" if cat in SETTINGS.skip_categories else "keep"), False


def finalize(seg: dict) -> dict:
    if seg.get("source") == "manual":
        seg["needs_review"] = False
        seg["auto_decision"] = seg.get("user_decision") or "skip"
    else:
        seg["auto_decision"], seg["needs_review"] = auto_decision(seg)
    if seg.get("user_decision") in ("skip", "keep"):
        seg["final"] = seg["user_decision"]
    elif seg["auto_decision"] == "review":
        seg["final"] = SETTINGS.unreviewed_default
    else:
        seg["final"] = seg["auto_decision"]
    return seg


def new_segment(start: float, end: float, **extra) -> dict:
    seg = {"id": uuid.uuid4().hex[:10], "start": round(start, 3), "end": round(end, 3),
           "user_decision": None, "source": "auto"}
    seg.update(extra)
    return seg


def carry_over_user_decisions(new_segments: list[dict], old: dict | None) -> list[dict]:
    """Keep the user's earlier choices when a title is scanned again."""
    if not old:
        return new_segments
    old_segs = old.get("segments", [])
    for seg in new_segments:
        for o in old_segs:
            if not o.get("user_decision") or o.get("source") == "manual":
                continue
            overlap = min(seg["end"], o["end"]) - max(seg["start"], o["start"])
            shorter = max(min(seg["end"] - seg["start"], o["end"] - o["start"]), 0.001)
            if overlap / shorter >= 0.5:
                seg["user_decision"] = o["user_decision"]
                if o.get("user_adjusted"):
                    seg["start"], seg["end"], seg["user_adjusted"] = o["start"], o["end"], True
                break
    manual = [o for o in old_segs if o.get("source") == "manual"]
    return new_segments + manual


def skip_ranges(segments: list[dict]) -> list[tuple[float, float]]:
    ranges = sorted((s["start"], s["end"]) for s in segments if s.get("final") == "skip" and s["end"] > s["start"])
    merged: list[list[float]] = []
    for a, b in ranges:
        if merged and a - merged[-1][1] <= SETTINGS.merge_gap_sec:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in merged]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_edl(video: Path, record: dict) -> str:
    """Write the .edl. Returns 'written', 'removed', 'unchanged' or 'edl.new' (user edited the .edl by hand)."""
    ranges = skip_ranges(record["segments"])
    text = "".join(f"{a:.3f}\t{b:.3f}\t0\n" for a, b in ranges)
    edl = sidecar(video, ".edl")
    ours = record.get("edl_sha256")
    if edl.exists():
        current = _sha(edl.read_text(errors="replace"))
        if ours is None or current != ours:
            # Not written by us, or edited by hand since: leave it alone.
            _atomic_write(sidecar(video, ".edl.new"), text)
            return "edl.new"
    if not ranges:
        if edl.exists():
            edl.unlink()
        record["edl_sha256"] = None
        return "removed"
    _atomic_write(edl, text)
    record["edl_sha256"] = _sha(text)
    return "written"


def save(video: Path, record: dict) -> str:
    for seg in record["segments"]:
        finalize(seg)
    record["segments"].sort(key=lambda s: s["start"])
    record["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    record["skip_ranges"] = skip_ranges(record["segments"])
    edl_result = write_edl(video, record)
    record["edl_status"] = edl_result
    _atomic_write(sidecar(video, ".skips.json"), json.dumps(record, indent=2))
    return edl_result


def set_decision(video: Path, seg_id: str, decision: str | None,
                 start: float | None = None, end: float | None = None) -> dict:
    record = load(video)
    if record is None:
        raise KeyError("Not scanned yet")
    for seg in record["segments"]:
        if seg["id"] == seg_id:
            if decision in ("skip", "keep", None):
                seg["user_decision"] = decision
            if start is not None and end is not None and end > start:
                seg["start"], seg["end"], seg["user_adjusted"] = round(start, 3), round(end, 3), True
            break
    else:
        raise KeyError("Segment not found")
    save(video, record)
    return record


def add_manual(video: Path, start: float, end: float, note: str = "") -> dict:
    record = load(video) or {"video": video.name, "segments": [], "scanned_at": None}
    seg = new_segment(start, end, source="manual", user_decision="skip",
                      review={"category": "manual", "confidence": 1.0, "reason_short": note[:80] or "added by hand"})
    record["segments"].append(seg)
    save(video, record)
    return record


def delete_manual(video: Path, seg_id: str) -> dict:
    record = load(video)
    if record is None:
        raise KeyError("Not scanned yet")
    record["segments"] = [s for s in record["segments"] if not (s["id"] == seg_id and s.get("source") == "manual")]
    save(video, record)
    return record
