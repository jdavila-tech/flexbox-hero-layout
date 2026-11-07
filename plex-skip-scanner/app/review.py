"""Second opinion from Claude: is a flagged segment real nudity, or a swimsuit, statue, etc.?"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
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


def backend() -> str:
    """'claude_code' (the `claude` command, uses your Claude subscription) or 'api' (API key)."""
    return "api" if SETTINGS.review_backend == "api" else "claude_code"


def available() -> bool:
    if not SETTINGS.review_enabled:
        return False
    if backend() == "api":
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    return shutil.which("claude") is not None and _claude_signed_in()


def _claude_signed_in() -> bool:
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return True
    home = Path(os.environ.get("HOME", "~")).expanduser()
    return (home / ".claude" / ".credentials.json").exists()


def model_label() -> str:
    if backend() == "api":
        return SETTINGS.review_model
    return f"Claude Code ({SETTINGS.claude_code_model or 'default model'})"


def unavailable_reason() -> str:
    if not SETTINGS.review_enabled:
        return "Claude review is turned off in config.yaml"
    if backend() == "api":
        return "No ANTHROPIC_API_KEY set"
    if shutil.which("claude") is None:
        return "The `claude` command was not found"
    return "Claude Code is not signed in (run `claude setup-token`, put the token in .env)"


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
    if backend() == "api":
        return _classify_api(frames, subtitles, title)
    return _classify_claude_code(frames, subtitles, title)


def _classify_claude_code(frames: list[tuple[float, Path]], subtitles: list[str], title: str) -> dict:
    """Ask the `claude` command (Claude Code, signed in with your subscription) to label the scene."""
    work = Path(tempfile.mkdtemp(prefix="review-", dir=SETTINGS.data_dir))
    try:
        lines = []
        for i, (t, path) in enumerate(frames, 1):
            name = f"frame{i}.jpg"
            img = Image.open(path).convert("RGB")
            img.thumbnail((SETTINGS.frame_max_px, SETTINGS.frame_max_px))
            img.save(work / name, "JPEG", quality=80)
            lines.append(f"- {name} (at {_fmt(t)})")
        sub_text = "\n".join(subtitles) if subtitles else "(no subtitles available)"
        prompt = (
            f"Use the Read tool to look at each of these frames in the current folder:\n" + "\n".join(lines) +
            f"\n\nTitle: {title}\nNearby subtitles:\n{sub_text}\n\n"
            "Then classify the segment and answer with the structured output only."
        )
        cmd = ["claude", "-p", prompt,
               "--system-prompt", SYSTEM_PROMPT,
               "--tools", "Read", "--allowedTools", "Read",
               "--json-schema", json.dumps(SCHEMA),
               "--output-format", "json",
               "--no-session-persistence", "--strict-mcp-config", "--setting-sources", ""]
        if SETTINGS.claude_code_model:
            cmd += ["--model", SETTINGS.claude_code_model]
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)  # always use the subscription sign-in, never an API key
        home = env.get("CLAUDE_HOME") or env.get("HOME") or str(SETTINGS.data_dir / "claude-home")
        Path(home).mkdir(parents=True, exist_ok=True)
        env["HOME"] = home
        try:
            proc = subprocess.run(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=SETTINGS.claude_code_timeout)
        except subprocess.TimeoutExpired:
            return _unclear("Claude Code timed out")
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            err = (proc.stderr or proc.stdout or "").strip().splitlines()
            log.warning("Claude Code failed (exit %s): %s", proc.returncode, " | ".join(err[-3:]))
            msg = " ".join(err[-1:])[:120] or f"exit code {proc.returncode}"
            if re.search(r"log ?in|auth|token|credential", msg, re.I):
                msg = "Claude Code is not signed in"
            return _unclear(msg)
        if out.get("is_error"):
            reason = str(out.get("result") or out.get("subtype") or "error")[:120]
            if re.search(r"limit|quota|usage", reason, re.I):
                reason = "Claude usage limit reached"
            return _unclear(reason)
        data = out.get("structured_output")
        if not isinstance(data, dict):
            m = re.search(r"\{.*\}", str(out.get("result", "")), re.S)
            try:
                data = json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                data = None
        if not isinstance(data, dict) or data.get("category") not in ALL_CATEGORIES:
            return _unclear("Claude declined or gave no answer")
        data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0))))
        data["reason_short"] = str(data.get("reason_short", ""))[:120]
        data["model"] = model_label()
        usage = out.get("usage") or {}
        data["usage"] = {"input_tokens": int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0))
                         + int(usage.get("cache_creation_input_tokens", 0)),
                         "output_tokens": int(usage.get("output_tokens", 0))}
        return data
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _classify_api(frames: list[tuple[float, Path]], subtitles: list[str], title: str) -> dict:
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
