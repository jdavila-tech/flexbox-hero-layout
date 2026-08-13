"""Job-listing scrapers.

`scrape_remoteok_api` pulls from RemoteOK's public JSON API, which is meant
for programmatic use and needs no CSS selectors.

`scrape_job_listings` is a generic HTML scraper driven entirely by config
(see sources.py). To add another site: inspect its HTML, fill in the CSS
selectors for a job source dict, and append it to HTML_SOURCES — no code
changes needed. Always check the target site's robots.txt / terms of
service before adding it.
"""
import time

import requests
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobScraperApp/1.0; personal use)"
}
REQUEST_TIMEOUT = 15


def fetch(url):
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp


def scrape_remoteok_api(url="https://remoteok.com/api"):
    data = fetch(url).json()
    jobs = []
    for entry in data:
        if not isinstance(entry, dict) or "id" not in entry:
            continue  # first element is a metadata/legal blob, not a job
        link = entry.get("url") or ""
        if link.startswith("/"):
            link = "https://remoteok.com" + link
        salary_text = entry.get("salary") or ""
        if not salary_text and (entry.get("salary_min") or entry.get("salary_max")):
            salary_text = f"${entry.get('salary_min', '')}-${entry.get('salary_max', '')}/year"
        jobs.append({
            "title": entry.get("position", "Untitled role"),
            "company": entry.get("company", "Unknown"),
            "location": entry.get("location") or "Remote",
            "pay": salary_text,
            "link": link,
            "source": "RemoteOK",
        })
    return jobs


def scrape_job_listings(source):
    """Generic CSS-selector-driven scraper for a single configured HTML source.

    `source` keys:
      name, url, base_url, listing_selector,
      field_selectors: {title, company, location, pay (optional), link},
      link_attr (default "href"), delay (default 1s between requests)
    """
    html = fetch(source["url"]).text
    soup = BeautifulSoup(html, "html.parser")

    jobs = []
    for node in soup.select(source["listing_selector"]):
        job = {"source": source["name"]}
        for field, selector in source["field_selectors"].items():
            el = node.select_one(selector) if selector else None
            if field == "link":
                href = el.get(source.get("link_attr", "href")) if el else None
                if href and href.startswith("/"):
                    href = source["base_url"].rstrip("/") + href
                job["link"] = href
            else:
                job[field] = el.get_text(strip=True) if el else ""
        jobs.append(job)

    time.sleep(source.get("delay", 1))
    return jobs
