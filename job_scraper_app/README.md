# Job Scraper Web App

Flask app that pulls job listings, estimates a bi-weekly take-home pay
(assuming 4-5 hrs/day, 10 workdays per 2 weeks, minus an estimated tax
rate), and displays each job as a card with a direct application link.

Out of the box it pulls live data from RemoteOK's public JSON API (no
selectors needed). You can add more HTML sites by editing `sources.py`
with CSS selectors — see the template/comment in that file. Always check
a site's robots.txt / terms of service before scraping it; many major job
boards (Indeed, LinkedIn, etc.) prohibit automated scraping.

## Run on a Linux server

```bash
cd job_scraper_app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Pick the port the app listens on (defaults to 8000)
PORT=8000 python app.py
```

Visit `http://<server-ip>:8000` in a browser. Make sure the port is open
in your firewall/security group (e.g. `sudo ufw allow 8000/tcp`).

### Keep it running after you disconnect

```bash
nohup env PORT=8000 python app.py > job_scraper.log 2>&1 &
```

Or set it up as a systemd service for a production deployment.

## Files

- `app.py` — Flask routes, wires scraping + pay estimation into the page
- `scraper.py` — `scrape_remoteok_api()` (JSON API) and `scrape_job_listings()` (generic CSS-selector scraper for HTML sites)
- `sources.py` — config list of HTML sites to scrape; add new sites here
- `salary.py` — parses a pay-rate string into an hourly rate and estimates bi-weekly net pay
- `templates/index.html`, `static/style.css` — the page UI
