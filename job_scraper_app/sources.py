"""Config for generic HTML sources scraped via CSS selectors.

Add a new site by appending a dict here — no code changes needed.
Always check the target site's robots.txt / terms of service first;
many major job boards (Indeed, LinkedIn, etc.) prohibit scraping.

Example template:

HTML_SOURCES = [
    {
        "name": "Example Co Careers",
        "url": "https://example.com/careers",
        "base_url": "https://example.com",
        "listing_selector": ".job-card",          # one element per listing
        "field_selectors": {
            "title": ".job-title",
            "company": ".job-company",
            "location": ".job-location",
            "pay": ".job-pay",                     # optional, omit if not shown
            "link": "a.job-link",
        },
        "link_attr": "href",
        "delay": 1,
    },
]
"""

HTML_SOURCES = []
