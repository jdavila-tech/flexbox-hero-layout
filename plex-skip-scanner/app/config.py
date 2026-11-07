"""Settings: config.yaml for behaviour, environment variables for secrets and paths."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ALL_CATEGORIES = [
    "explicit_nudity",
    "partial_nudity",
    "sexual_activity_no_nudity",
    "swimwear_or_underwear",
    "shirtless_male",
    "artwork_or_statue",
    "medical_or_breastfeeding",
    "infant_or_child_nonsexual",
    "skin_tone_clothing_or_false_positive",
    "unclear",
]


@dataclass
class Settings:
    movies_dir: Path
    tv_dir: Path
    data_dir: Path
    config_path: Path
    # sampling / detection
    sample_fps: float = 2.0
    scene_threshold: float = 0.30
    detector_threshold: float = 0.30
    detector_classes: list[str] = field(default_factory=list)
    group_gap_sec: float = 4.0
    min_segment_sec: float = 0.5
    brighten_dark_frames: bool = True
    # review
    review_enabled: bool = True
    review_model: str = "claude-opus-5-5"
    review_effort: str = "low"
    use_fallbacks: bool = True
    frames_per_segment: int = 6
    frame_max_px: int = 512
    subtitle_window_sec: float = 30.0
    # decisions
    skip_categories: list[str] = field(default_factory=list)
    confidence_threshold: float = 0.75
    unreviewed_default: str = "skip"  # skip | keep
    # skip shaping
    refine_fps: float = 5.0
    snap_to_cut_sec: float = 3.0
    padding_sec: float = 0.5
    merge_gap_sec: float = 5.0
    # family edit export
    family_suffix: str = "Family Edit"
    video_extensions: list[str] = field(default_factory=list)


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).resolve()


def load_settings() -> Settings:
    config_path = _env_path("CONFIG_PATH", "/config/config.yaml")
    raw: dict = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text()) or {}

    det = raw.get("detection", {})
    rev = raw.get("review", {})
    dec = raw.get("decisions", {})
    shp = raw.get("skips", {})
    exp = raw.get("export", {})

    s = Settings(
        movies_dir=_env_path("MOVIES_DIR", "/media/movies"),
        tv_dir=_env_path("TV_DIR", "/media/tv"),
        data_dir=_env_path("DATA_DIR", "/data"),
        config_path=config_path,
        sample_fps=float(det.get("sample_fps", 2.0)),
        scene_threshold=float(det.get("scene_threshold", 0.30)),
        detector_threshold=float(det.get("threshold", 0.30)),
        detector_classes=list(det.get("classes", [
            "FEMALE_BREAST_EXPOSED",
            "FEMALE_GENITALIA_EXPOSED",
            "MALE_GENITALIA_EXPOSED",
            "BUTTOCKS_EXPOSED",
            "ANUS_EXPOSED",
        ])),
        group_gap_sec=float(det.get("group_gap_sec", 4.0)),
        min_segment_sec=float(det.get("min_segment_sec", 0.5)),
        brighten_dark_frames=bool(det.get("brighten_dark_frames", True)),
        review_enabled=bool(rev.get("enabled", True)),
        review_model=str(rev.get("model", "claude-opus-5-5")),
        review_effort=str(rev.get("effort", "low")),
        use_fallbacks=bool(rev.get("use_fallbacks", True)),
        frames_per_segment=int(rev.get("frames_per_segment", 6)),
        frame_max_px=int(rev.get("frame_max_px", 512)),
        subtitle_window_sec=float(rev.get("subtitle_window_sec", 30.0)),
        skip_categories=list(dec.get("skip", ["explicit_nudity", "partial_nudity"])),
        confidence_threshold=float(dec.get("confidence_threshold", 0.75)),
        unreviewed_default=str(dec.get("unreviewed_default", "skip")),
        refine_fps=float(shp.get("refine_fps", 5.0)),
        snap_to_cut_sec=float(shp.get("snap_to_cut_sec", 3.0)),
        padding_sec=float(shp.get("padding_sec", 0.5)),
        merge_gap_sec=float(shp.get("merge_gap_sec", 5.0)),
        family_suffix=str(exp.get("family_suffix", "Family Edit")),
        video_extensions=[e.lower() for e in raw.get("video_extensions", [
            ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".ts", ".mpg", ".mpeg", ".webm",
        ])],
    )
    if s.unreviewed_default not in ("skip", "keep"):
        s.unreviewed_default = "skip"
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s


SETTINGS = load_settings()
