"""Restricts listings to flexible, low/no-interpersonal-interaction remote
work: AI training / data annotation, data entry & transcription, and
content moderation. Anything not matching one of these is dropped.
"""
import re

TARGET_KEYWORDS = [
    "annotat",          # data annotation / annotator / annotating
    "data label",       # data labeling / labeler
    "data tagging",
    "data entry",
    "transcri",         # transcription / transcriptionist / transcribe
    "content moderat",  # content moderation / moderator
    "chat moderat",
    "engine evaluat",   # search engine evaluator (similar solo/remote gig work)
    "search quality",
    "quality rater",
    "ads quality",
    "rlhf",             # reinforcement learning from human feedback labeling gigs
]

# Catches "AI training" in any word order (e.g. "AI Data Trainer", "Model
# Training Specialist", "LLM Trainer") without also matching unrelated
# roles like "Personal Trainer" or "Sales Trainer".
AI_CONTEXT_WORDS = {"ai", "model", "models", "llm", "llms", "chatbot", "language"}


def is_ai_training_role(text):
    tokens = re.findall(r"[a-z]+", (text or "").lower())
    has_training_word = any(tok.startswith("train") for tok in tokens)
    has_ai_context = any(tok in AI_CONTEXT_WORDS for tok in tokens)
    return has_training_word and has_ai_context


def matches_target_categories(job):
    tags = job.get("tags") or []
    haystack = " ".join([job.get("title", ""), " ".join(tags)])

    if any(keyword in haystack.lower() for keyword in TARGET_KEYWORDS):
        return True

    return is_ai_training_role(haystack)
