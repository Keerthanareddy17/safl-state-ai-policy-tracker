from datetime import date

from dateutil.relativedelta import relativedelta

_LARGE = {
    "Telangana": ["Telangana", "Hyderabad"],
    "Karnataka": ["Karnataka", "Bengaluru"],
    "Maharashtra": ["Maharashtra", "Mumbai", "Pune"],
    "Tamil Nadu": ["Tamil Nadu", "Chennai"],
    "Uttar Pradesh": ["Uttar Pradesh", "Lucknow", "Noida"],
    "Andhra Pradesh": ["Andhra Pradesh", "Amaravati", "Visakhapatnam"],
    "West Bengal": ["West Bengal", "Kolkata"],
    "Gujarat": ["Gujarat", "Gandhinagar"],
    "Kerala": ["Kerala", "Thiruvananthapuram"],
    "Odisha": ["Odisha", "Bhubaneswar"],
}

_OTHER = [
    # states
    "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Madhya Pradesh", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Punjab", "Rajasthan", "Sikkim", "Tripura",
    "Uttarakhand",
    # union territories
    "Delhi", "Jammu and Kashmir", "Ladakh", "Chandigarh", "Puducherry",
    "Lakshadweep", "Andaman and Nicobar Islands",
    "Dadra and Nagar Haveli and Daman and Diu",
]

REGIONS = {**{name: [name] for name in _OTHER}, **_LARGE}
REGIONS = dict(sorted(REGIONS.items()))

QUERY_GROUPS = {
    "A": '(policy OR mission OR "task force" OR "centre of excellence" OR regulation OR ethics OR budget OR MoU)',
    "B": '(government OR govt OR minister OR "chief minister" OR launch OR deploy OR pilot)',
}

# fixed so cache keys and the data window don't drift with the run date
DATA_END_DATE = "2026-11-15"

LOOKBACK_MONTHS = 12
N_WINDOWS = 4
NEWSAPI_LOOKBACK_DAYS = 29  # free plan only serves the last ~30 days

# Google News stops at ~100 results per query
TRUNCATION_THRESHOLD = 95


def data_end():
    return date.fromisoformat(DATA_END_DATE)


def quarter_windows():
    """Return (start, end) date pairs, oldest first, covering the lookback ending at DATA_END_DATE."""
    today = data_end()
    step = LOOKBACK_MONTHS // N_WINDOWS
    edges = [today - relativedelta(months=step * i) for i in range(N_WINDOWS, -1, -1)]
    return list(zip(edges[:-1], edges[1:]))
