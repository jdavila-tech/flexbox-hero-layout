"""Rough, offline hourly-wage guesses by job-title keyword.

Used ONLY as a fallback when an employer didn't publish a pay rate. These
are general US ballpark ranges, not tailored to a specific listing's
location, company, or seniority — always surfaced to the user as a guess,
never presented as employer-provided pay.
"""

# Ordered most-specific first; the first keyword found in the title wins.
TITLE_RATE_TABLE = [
    ("software", (35, 75)),
    ("developer", (35, 75)),
    ("engineer", (32, 70)),
    ("data scientist", (35, 70)),
    ("data analyst", (28, 55)),
    ("designer", (25, 50)),
    ("product manager", (35, 65)),
    ("project manager", (30, 55)),
    ("marketing", (20, 42)),
    ("recruiter", (20, 40)),
    ("human resources", (20, 40)),
    ("sales", (18, 38)),
    ("account", (25, 45)),
    ("nurse", (28, 50)),
    ("teacher", (18, 35)),
    ("tutor", (18, 35)),
    ("writer", (20, 42)),
    ("editor", (20, 40)),
    ("customer service", (15, 22)),
    ("customer support", (15, 22)),
    ("support", (16, 26)),
    ("nanny", (15, 25)),
    ("babysit", (14, 22)),
    ("driver", (15, 22)),
    ("chef", (16, 28)),
    ("cook", (14, 22)),
    ("barista", (14, 18)),
    ("roaster", (14, 19)),
    ("security", (15, 22)),
    ("warehouse", (15, 21)),
    ("operator", (16, 26)),
    ("technician", (18, 32)),
    ("construction", (18, 32)),
    ("laborer", (15, 24)),
    ("tunnel", (22, 38)),
    ("ganger", (20, 34)),
    ("agent", (16, 30)),
    ("cleaner", (13, 18)),
    ("housekeeping", (13, 18)),
]

GENERIC_FALLBACK = (15, 25)


def estimate_hourly_range_from_title(title):
    """Return (low, high, matched) hourly-rate guess for a job title.

    `matched` is False when no keyword hit and the generic fallback was
    used — callers should flag that as an even rougher guess.
    """
    lowered = (title or "").lower()
    for keyword, (low, high) in TITLE_RATE_TABLE:
        if keyword in lowered:
            return low, high, True
    low, high = GENERIC_FALLBACK
    return low, high, False
