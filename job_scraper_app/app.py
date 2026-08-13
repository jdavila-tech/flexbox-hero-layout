import os
import socket

from flask import Flask, abort, redirect, render_template

from job_filters import matches_target_categories
from platforms import get_platforms
from salary import estimate_biweekly_pay, estimate_biweekly_pay_range, parse_hourly_rate
from scraper import scrape_job_listings, scrape_remoteok_api, scrape_remotive_api
from sources import HTML_SOURCES
from title_rates import estimate_hourly_range_from_title
from viewed_store import get_viewed, mark_viewed

DEFAULT_PORT = 8420  # distinctive default so it's less likely to collide with other local services

app = Flask(__name__)

# Maps job id -> real apply URL for whatever was scraped on the last page
# load, so /go/<job_id> can redirect without trusting a client-supplied URL.
_job_links = {}


def enrich_with_pay_estimate(job):
    hourly_rate = parse_hourly_rate(job.get("pay", ""))
    if hourly_rate:
        job["hourly_rate"] = hourly_rate
        job["estimate"] = estimate_biweekly_pay(hourly_rate)
        job["estimate_source"] = "listed"
    else:
        rate_low, rate_high, matched = estimate_hourly_range_from_title(job.get("title", ""))
        job["hourly_rate"] = None
        job["estimate"] = estimate_biweekly_pay_range(rate_low, rate_high)
        job["estimate_source"] = "guessed" if matched else "guessed_generic"
    return job


@app.route("/")
def index():
    jobs = []
    errors = []

    try:
        jobs.extend(scrape_remoteok_api())
    except Exception as exc:
        errors.append(f"RemoteOK: {exc}")

    try:
        jobs.extend(scrape_remotive_api())
    except Exception as exc:
        errors.append(f"Remotive: {exc}")

    for source in HTML_SOURCES:
        try:
            jobs.extend(scrape_job_listings(source))
        except Exception as exc:
            errors.append(f"{source['name']}: {exc}")

    scraped_count = len(jobs)
    jobs = [job for job in jobs if matches_target_categories(job)]
    jobs = [enrich_with_pay_estimate(job) for job in jobs]
    jobs.sort(key=lambda job: job["estimate_source"] != "listed")  # employer-listed pay first

    viewed_ids = get_viewed()
    for job in jobs:
        job["viewed"] = job["id"] in viewed_ids
        if job.get("link"):
            _job_links[job["id"]] = job["link"]

    return render_template(
        "index.html", jobs=jobs, errors=errors,
        job_count=len(jobs), scraped_count=scraped_count,
        platforms=get_platforms(),
    )


@app.route("/go/<job_id>")
def go(job_id):
    link = _job_links.get(job_id)
    if not link:
        abort(404)
    mark_viewed(job_id)
    return redirect(link)


def find_available_port(preferred, host="0.0.0.0", max_tries=20):
    port = preferred
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                port += 1
    raise RuntimeError(f"No available port found starting at {preferred}")


if __name__ == "__main__":
    preferred_port = int(os.environ.get("PORT", DEFAULT_PORT))
    port = find_available_port(preferred_port)
    if port != preferred_port:
        print(f"Port {preferred_port} was already in use; using {port} instead.")
    app.run(host="0.0.0.0", port=port)
