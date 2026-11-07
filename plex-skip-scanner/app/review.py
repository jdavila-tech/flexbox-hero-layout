"""Second opinion from Claude: is a flagged segment real nudity, or a swimsuit, statue, etc.?"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
from pathlib import Path

import anthropic
from PIL import Image

from .config import ALL_CATEGORIES, SETTINGS

log = logging.getLogger("review")

SYSTEM_PROMPT = """You are a content-classification step in a home media filter. A family uses it to \
skip nudity in movies they own. An automatic detector flagged a short segment of a film or TV episode; \
you see a few frames from it (with timestamps) and, when available, nearby subtitle lines.

Decide which category best describes the segment as a whole:
- explicit_nudity: exposed genitals, or exposed female breasts with nipples visible, or fully nude bodies.
- partial_nudity: bare buttocks, nudity that is partially obscured but clearly present, sideboob/underboob, \
nude silhouettes that are clearly nude.
- sexual_activity_no_nudity: a sex scene or clearly sexual activity where no nudity is shown.
- swimwear_or_underwear: bikinis, swimsuits, lingerie or underwear that covers the body.
- shirtless_male: a man without a shirt, with nothing else of note.
- artwork_or_statue: paintings, sculptures, drawings or photos within the scene.
- medical_or_breastfeeding: clinical, surgical, autopsy or breastfeeding context.
- infant_or_child_nonsexual: a baby or child in an ordinary non-sexual context (bath time, changing).
- skin_tone_clothing_or_false_positive: skin-coloured clothing, close-ups of arms/backs/faces, or the \
detector was simply wrong.
- unclear: you genuinely cannot tell from these frames.

Judge the frames together; the segment counts as nudity if any frame clearly shows it. Give a confidence \
from 0 to 1. Keep reason_short neutral and under ten words, and do not describe bodies in detail."""

SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ALL_CATEGORIES},
        "confidence": {"type": "number"},
        "reason_short": {"type": "string"},
    },
    "required": ["category", "confidence", "reason_short"],
    "additionalProperties": False,
}

# Models that accept the server-side `fallbacks: "default"` parameter.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-fable-5", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


def available() -> bool:
    return SETTINGS.review_enabled and bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=4, timeout=120.0)
    return _client


def _encode(path: Path) -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((SETTINGS.frame_max_px, SETTINGS.frame_max_px))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _fmt(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:04.1f}"


def classify(frames: list[tuple[float, Path]], subtitles: list[str], title: str) -> dict:
    """Return {"category", "confidence", "reason_short", "model", "error"?}."""
    content: list[dict] = []
    for t, path in frames:
        content.append({"type": "text", "text": f"Frame at {_fmt(t)}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _encode(path)}})
    sub_text = "\n".join(subtitles) if subtitles else "(no subtitles available)"
    content.append({"type": "text", "text": f"Title: {title}\nNearby subtitles:\n{sub_text}\n\nClassify this segment."})

    model = SETTINGS.review_model
    kwargs: dict = dict(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": SETTINGS.review_effort, "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        if SETTINGS.use_fallbacks and model in FALLBACK_MODELS:
            resp = client().beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = client().messages.create(**kwargs)
    except anthropic.AuthenticationError:
        return _unclear("API key rejected")
    except anthropic.BadRequestError as e:
        log.warning("Bad request for %s: %s", title, e.message)
        return _unclear("request rejected")
    except anthropic.RateLimitError:
        return _unclear("rate limited")
    except anthropic.APIStatusError as e:
        return _unclear(f"API error {e.status_code}")
    except anthropic.APIConnectionError:
        return _unclear("network error")

    if resp.stop_reason == "refusal":
        return _unclear("model declined", model=resp.model)
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _unclear("unparseable answer", model=resp.model)
    data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0))))
    data["model"] = resp.model
    data["usage"] = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
    return data


def _unclear(reason: str, model: str | None = None) -> dict:
    return {"category": "unclear", "confidence": 0.0, "reason_short": reason, "model": model, "error": reason}
