"""Pay-rate parsing and bi-weekly net pay estimation."""
import re

WORKDAYS_PER_BIWEEK = 10          # 5-day weeks x 2 weeks
FULL_TIME_HOURS_PER_YEAR = 2080   # used to convert an annual salary to an hourly-equivalent rate
DEFAULT_TAX_RATE = 0.22           # rough flat estimate for federal + state + FICA; adjust to taste


def parse_hourly_rate(pay_text):
    """Extract a representative hourly rate from free-form pay text.

    Handles things like "$18/hr", "$18 - $22 per hour", "$45,000/year",
    "$3,500/month". Returns None if no number can be found.
    """
    if not pay_text:
        return None

    text = pay_text.lower().replace(",", "")
    numbers = [float(n) for n in re.findall(r"\d+\.?\d*", text)]
    if not numbers:
        return None

    value = sum(numbers) / len(numbers)  # midpoint of a range, or the single value

    if "/mo" in text or "month" in text:
        value *= 12  # now annual
        return round(value / FULL_TIME_HOURS_PER_YEAR, 2)

    if "/yr" in text or "year" in text or "annual" in text:
        return round(value / FULL_TIME_HOURS_PER_YEAR, 2)

    if "/hr" in text or "hour" in text:
        return round(value, 2)

    # No explicit unit: guess based on magnitude.
    return round(value / FULL_TIME_HOURS_PER_YEAR, 2) if value > 500 else round(value, 2)


def estimate_biweekly_pay(hourly_rate, hours_low=4, hours_high=5,
                           workdays=WORKDAYS_PER_BIWEEK, tax_rate=DEFAULT_TAX_RATE):
    """Estimate gross/net bi-weekly pay assuming `hours_low`-`hours_high` hrs/day worked."""
    gross_low = round(hourly_rate * hours_low * workdays, 2)
    gross_high = round(hourly_rate * hours_high * workdays, 2)
    return {
        "gross_low": gross_low,
        "gross_high": gross_high,
        "net_low": round(gross_low * (1 - tax_rate), 2),
        "net_high": round(gross_high * (1 - tax_rate), 2),
        "tax_rate": tax_rate,
    }
