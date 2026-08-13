import os

from flask import Flask, render_template

from salary import estimate_biweekly_pay, parse_hourly_rate
from scraper import scrape_job_listings, scrape_remoteok_api
from sources import HTML_SOURCES

app = Flask(__name__)


def enrich_with_pay_estimate(job):
    hourly_rate = parse_hourly_rate(job.get("pay", ""))
    job["hourly_rate"] = hourly_rate
    job["estimate"] = estimate_biweekly_pay(hourly_rate) if hourly_rate else None
    return job


@app.route("/")
def index():
    jobs = []
    errors = []

    try:
        jobs.extend(scrape_remoteok_api())
    except Exception as exc:
        errors.append(f"RemoteOK: {exc}")

    for source in HTML_SOURCES:
        try:
            jobs.extend(scrape_job_listings(source))
        except Exception as exc:
            errors.append(f"{source['name']}: {exc}")

    jobs = [enrich_with_pay_estimate(job) for job in jobs]
    return render_template("index.html", jobs=jobs, errors=errors, job_count=len(jobs))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
