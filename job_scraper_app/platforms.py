"""Static list of platforms that actually distribute AI-training,
data-annotation, data-entry, transcription, and content-moderation work.

This kind of work is usually NOT posted as discrete job ads on boards like
RemoteOK -- it's handed out as tasks after signing up on one of these
platforms directly. Rather than guessing/hardcoding each company's exact
URL (which can go stale), each entry links to a search for the platform's
name so you always land on their current official page.
"""
import urllib.parse

PLATFORMS = [
    {"name": "Appen", "description": "Data annotation, AI training, search evaluation"},
    {"name": "Clickworker", "description": "Data entry, AI training microtasks, transcription"},
    {"name": "TELUS International AI Community", "description": "AI training and data annotation (formerly Lionbridge AI)"},
    {"name": "Remotasks", "description": "Data labeling and annotation for AI models"},
    {"name": "Rev", "description": "Transcription and captioning"},
    {"name": "TranscribeMe", "description": "Transcription"},
    {"name": "Prolific", "description": "Research studies and data tasks"},
    {"name": "Toloka", "description": "Data labeling and AI training microtasks"},
    {"name": "Sama", "description": "Data annotation and content moderation"},
    {"name": "OneForma", "description": "Data collection, annotation, and translation tasks"},
]


def search_url(platform_name):
    query = urllib.parse.quote(f"{platform_name} sign up")
    return f"https://www.google.com/search?q={query}"


def get_platforms():
    return [
        {**p, "search_url": search_url(p["name"])}
        for p in PLATFORMS
    ]
