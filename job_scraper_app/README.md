# Job Scraper Web App

Flask app that pulls job listings, estimates a bi-weekly take-home pay
(assuming 4-5 hrs/day, 10 workdays per 2 weeks, minus an estimated tax
rate), and displays each job as a card with a direct application link.
Clicking Apply marks the job as "Viewed" (persisted to disk, survives
restarts).

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

# Defaults to port 8420 if PORT isn't set. If that port is taken,
# the app automatically tries the next one up and prints which it used.
PORT=8420 python app.py
```

Visit `http://<server-ip>:8420` in a browser. Make sure the port is open
in your firewall/security group (e.g. `sudo ufw allow 8420/tcp`).

## Run it as a service (auto-restart on crash, auto-start on boot)

A systemd unit is provided in `deploy/job-scraper.service`. It assumes the
repo lives at `/home/pi/flexbox-hero-layout` — edit the `WorkingDirectory`
and `ExecStart` paths in that file first if yours is elsewhere (or the
service user isn't `pi`).

```bash
sudo cp deploy/job-scraper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable job-scraper   # start automatically on boot
sudo systemctl start job-scraper

# Check status / logs
sudo systemctl status job-scraper
journalctl -u job-scraper -f
```

`Restart=always` means systemd relaunches the app automatically if it
ever crashes or the server reboots — no manual `python app.py` needed
again. Once the service is running, stop starting it manually; run
`sudo systemctl restart job-scraper` instead when you pull new code:

```bash
git pull origin claude/job-scraper-web-app-g1w32a
sudo systemctl restart job-scraper
```

## Files

- `app.py` — Flask routes, wires scraping + pay estimation into the page, picks a free port automatically
- `scraper.py` — `scrape_remoteok_api()` (JSON API) and `scrape_job_listings()` (generic CSS-selector scraper for HTML sites); assigns each job a stable `id`
- `sources.py` — config list of HTML sites to scrape; add new sites here
- `salary.py` — parses a pay-rate string into an hourly rate and estimates bi-weekly net pay
- `title_rates.py` — rough hourly-wage guesses by job-title keyword, used only when the employer didn't list pay
- `viewed_store.py` — persists which job IDs you've clicked "Apply" on (`viewed.json`, not committed to git)
- `templates/index.html`, `static/style.css` — the page UI
- `deploy/job-scraper.service` — systemd unit for auto-start/auto-restart
