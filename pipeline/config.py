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


# --- Phase 2: normalization and classification -------------------------

PROCESSED_DIR_NAME = "processed"

# Names, old names, cities and civic bodies that map to each region. Matched
# case-insensitively on word boundaries (spaces also match hyphens), except
# all-caps acronyms of 5 letters or fewer, which must be uppercase (BMC is also a software firm).
STATE_ALIASES = {
    "Andhra Pradesh": ["Andhra Pradesh", "Amaravati", "Visakhapatnam", "Vizag", "Vijayawada"],
    "Arunachal Pradesh": ["Arunachal Pradesh", "Itanagar"],
    "Assam": ["Assam", "Guwahati", "Dispur"],
    "Bihar": ["Bihar", "Patna"],
    "Chhattisgarh": ["Chhattisgarh", "Raipur"],
    "Goa": ["Goa", "Panaji"],
    "Gujarat": ["Gujarat", "Gandhinagar", "Ahmedabad"],
    "Haryana": ["Haryana", "Gurugram", "Gurgaon"],
    "Himachal Pradesh": ["Himachal Pradesh", "Himachal", "Shimla"],
    "Jharkhand": ["Jharkhand", "Ranchi"],
    "Karnataka": ["Karnataka", "Bengaluru", "Bangalore", "Mysuru", "Mysore", "BBMP", "Greater Bengaluru Authority"],
    "Kerala": ["Kerala", "Thiruvananthapuram", "Trivandrum", "Kochi", "Cochin"],
    "Madhya Pradesh": ["Madhya Pradesh", "Bhopal", "Indore"],
    "Maharashtra": ["Maharashtra", "Bombay", "Mumbai", "Navi Mumbai", "Thane", "Pune", "Nagpur", "BMC", "Brihanmumbai"],
    "Manipur": ["Manipur", "Imphal"],
    "Meghalaya": ["Meghalaya", "Shillong"],
    "Mizoram": ["Mizoram", "Aizawl"],
    "Nagaland": ["Nagaland", "Kohima"],
    "Odisha": ["Odisha", "Orissa", "Bhubaneswar"],
    "Punjab": ["Punjab"],
    "Rajasthan": ["Rajasthan", "Jaipur"],
    "Sikkim": ["Sikkim", "Gangtok"],
    "Tamil Nadu": ["Tamil Nadu", "Tamilnadu", "Madras", "Chennai", "Coimbatore", "Greater Chennai Corporation"],
    "Telangana": ["Telangana", "Hyderabad", "Secunderabad", "Cyberabad", "GHMC"],
    "Tripura": ["Tripura", "Agartala"],
    "Uttar Pradesh": ["Uttar Pradesh", "Lucknow", "Noida", "Greater Noida"],
    "Uttarakhand": ["Uttarakhand", "Dehradun"],
    "West Bengal": ["West Bengal", "Kolkata", "Calcutta", "KMC"],
    "Delhi": ["Delhi", "NDMC", "MCD"],  # "New Delhi" is excluded in normalize.py: mostly a national dateline
    "Jammu and Kashmir": ["Jammu and Kashmir", "Jammu & Kashmir", "J&K", "Kashmir", "Jammu", "Srinagar"],
    "Ladakh": ["Ladakh", "Leh", "Kargil"],
    "Chandigarh": ["Chandigarh"],
    "Puducherry": ["Puducherry", "Pondicherry"],
    "Lakshadweep": ["Lakshadweep", "Kavaratti"],
    "Andaman and Nicobar Islands": ["Andaman and Nicobar Islands", "Andaman", "Nicobar", "Port Blair"],
    "Dadra and Nagar Haveli and Daman and Diu": [
        "Dadra and Nagar Haveli and Daman and Diu", "Dadra", "Nagar Haveli", "Daman", "Diu", "Silvassa"],
}

# Two-letter forms only count in uppercase and next to a government word.
STATE_ABBREVIATIONS = {
    "UP": "Uttar Pradesh", "TN": "Tamil Nadu", "MH": "Maharashtra", "KA": "Karnataka",
    "AP": "Andhra Pradesh", "TS": "Telangana", "WB": "West Bengal",
    "MP": "Madhya Pradesh", "HP": "Himachal Pradesh",
}
ABBREV_CONTEXT = ["govt", "government", "police", "cabinet", "minister", "ministry"]  # plus uppercase CM
ABBREV_CONTEXT_WINDOW = 3  # words either side

# Strip before looking for "AI" so these never count.
AI_GUARDS = ["AI-?ADMK", "AIIMS", "AICTE", "AIIB", "AIMIM", "AITC", "AIFF", "Air India"]
AI_PHRASES = ["artificial intelligence", "GenAI", "generative AI", "machine learning"]  # case-insensitive

GOV_ACTOR_TERMS = [
    "government", "govt", "chief minister", "minister", "cabinet", "department",
    "state mission", "police", "collector", "district administration", "assembly",
    "budget", "MoU", "IT secretary",
]  # plus uppercase CM (checked case-sensitively)

# Extra signals for title-only records (Google News gives no description).
TITLE_GOV_TERMS = ["state government", "state govt", "IT department", "district", "municipal"]
SUBJECT_VERBS = [
    "launches", "unveils", "signs", "sets up", "to set up", "announces", "approves",
    "plans", "rolls out", "partners", "inks", "allocates", "introduces", "adopts",
    "forms", "notifies", "mandates",
]
SUBJECT_MAX_GAP_WORDS = 3

EXCLUDE_STOCK = [
    r"\bstocks?\b", r"\bIPO\b", r"\bmarket cap\b", r"\bSensex\b", r"\bNifty\b",
    r"\bshare price\b", r"\bshares? (?:rise|rises|fall|falls|jump|jumps|surge|surges|slump|slumps|drop|drops|gain|gains|climb|climbs)\b",
]
# A place name right after one of these is an institution, not the state acting.
INSTITUTE_PREFIXES = r"\b(?:IIT|IIIT|NIT|IIM|IISc|AIIMS|NIELIT|(?i:University(?: of)?|College(?: of)?))[\s\-]*$"
INSTITUTE_SUFFIXES = r"^\W*(?:University|College|Institute)\b"
INCIDENT_TERMS = [r"\bdeepfakes?\b", r"\bmorphed\b", r"\bfake video\b", r"\bviral video\b",
                  r"\bAI[\s\-]generated\b", r"\bAI videos?\b", r"\bhoax\b", r"\bfake alert\b"]
POLICY_VERBS = [r"\bbans?\b", r"\bregulat\w*", r"\bguidelines?\b", r"\blaws?\b",
                r"\baction against\b", r"\bSOPs?\b"]
EXCLUDE_OPINION = [r"\bopinion\b", r"\bop-?ed\b", r"\bcolumn\b", r"\beditorial\b", r"\bblog\b"]
OPINION_URL_HINTS = ["/opinion/", "/columns/", "/blogs/", "/editorial/"]
CORPORATE_LAUNCH = r"\b(?:launch(?:es|ed)?|unveil(?:s|ed)?|introduc(?:es|ed)|releases?|debuts?)\b"
NATIONAL_ONLY = [r"\bMeitY\b", r"\bIndiaAI\b", r"\bIndia AI\b", r"\bUnion budget\b", r"\bUnion government\b"]

# First match wins, in this order. budget_funding is last and is only tested
# against the headline, so it applies when the story is mainly about money.
CATEGORY_KEYWORDS = {
    "regulation_ethics": [r"\bregulat\w*", r"\bethic\w*", r"\bguidelines?\b", r"\blegislat\w*",
                          r"\bframeworks?\b", r"\brules\b", r"\bSOPs?\b", r"\badvisor(?:y|ies)\b",
                          r"\bbans?\b", r"\bdeepfake laws?\b", r"\bresponsible AI\b",
                          r"\bAI (?:act|bill|law)\b"],
    "policy_mission": [r"\bpolic(?:y|ies)\b", r"\bmission\b", r"\bstrateg(?:y|ies)\b", r"\broadmap\b",
                       r"\bvision\b", r"\bblueprint\b", r"\baction plan\b", r"\bscheme\b",
                       r"\binitiatives?\b", r"\bprogrammes?\b", r"\bprograms?\b",
                       r"\bfirst government-led\b"],
    "institution": [r"\btask force\b", r"\bcent(?:re|er) of excellence\b", r"\bCoE\b", r"\bcouncil\b",
                    r"\binstitute\b", r"\bcommittee\b", r"\bAI cell\b", r"\bAI university\b"],
    # plain "university" only counts when a state or government is the grammatical subject
    # (handled in classify.categorize)
    "partnership_mou": [r"\bMoU\b", r"\bpartner\w*", r"\btie-?ups?\b", r"\bties up\b", r"\bcollaborat\w*",
                        r"\bagreement\b", r"\bpact\b", r"\binks\b"],
    "infrastructure": [r"\bdata cent(?:re|er)s?\b", r"\bcompute\b", r"\bGPUs?\b", r"\bAI city\b",
                       r"\bAI park\b", r"\bsupercomput\w*", r"\bAI factory\b", r"\bfactor(?:y|ies)\b",
                       r"\bhubs?\b", r"\binnovation city\b", r"\bcampus(?:es)?\b", r"\bparks?\b",
                       r"\bhyperscale\b"],
    "deployment": [r"\bdeploy\w*", r"\bpilot\w*", r"\broll(?:s|ed)? out\b", r"\brollout\b", r"\blaunch\w*",
                   r"\bintroduc\w*", r"\badopt\w*", r"\bcourses?\b", r"\btraining\b",
                   r"\bskilling\b", r"\btrain(?:s|ed)?\b", r"\bchatbot\b", r"\bapp\b", r"\bplatform\b",
                   r"\bAI-powered\b", r"\bAI-enabled\b", r"\bAI-based\b", r"\bAI-assisted\b"],
    "budget_funding": [r"\bbudget\b", r"\ballocat\w*", r"\boutlay\b", r"\bcrore\b"],
    # a leader talking, no action; only when nothing above matched
    "statement": [r"\bsays?\b", r"\burges?\b", r"\bbats for\b", r"\bcalls? for\b", r"\basks?\b",
                  r"\bstress(?:es)?\b", r"\bhighlights?\b", r"\bspeaks?\b"],
}
HEADLINE_ONLY_CATEGORIES = {"budget_funding", "statement"}
# Order matters: first sector that matches wins.
SECTOR_KEYWORDS = {
    "education": [r"\bcurriculum\b", r"\bschools?\b", r"\bstudents?\b", r"\bteachers?\b",
                  r"\bclassrooms?\b", r"\buniversit\w*", r"\bskilling\b", r"\bclass(?:es)?\b",
                  r"\bsubject\b", r"\bcourses?\b", r"\btraining\b", r"\btrain(?:s|ed)?\b",
                  r"\bsyllabus\b", r"\blabs?\b"],
    "health": [r"\bhospitals?\b", r"\bhealth\w*", r"\bpatients?\b", r"\bdiagnos\w*", r"\bmedical\b",
               r"\bMBBS\b", r"\bsurgery\b", r"\bGMCH\b", r"\bdoctors?\b"],
    "agriculture": [r"\bfarmers?\b", r"\bcrops?\b", r"\bagri\w*", r"\bfarm\w*", r"\bsoil\b"],
    "policing": [r"\bpolice\b", r"\bcrime\b", r"\bsurveillance\b", r"\btraffic\b", r"\bcyber crime\b"],
    "citizen_services": [r"\bgrievance\w*", r"\be-?governance\b", r"\bcitizens?\b", r"\bservices\b",
                         r"\bchatbot\b", r"\brevenue\b", r"\bland records?\b"],
}
SUMMARY_MAX_WORDS = 25


# --- Phase 3: dedup, coverage, export ----------------------------------

NEAR_DUP_DAYS = 3            # same story is usually syndicated within a few days
SET_THRESHOLD = 80           # token_set_ratio floor: shared wording
SORT_THRESHOLD = 45          # lowered from 60 after calibration; the numbers guard now handles subset over-merges such as Class 6 vs Class 9
SET_THRESHOLD_NO_DATE = 95   # stricter when a date is missing, since time can't back it up

# Preferred as the representative after government sources: (name, domain fragment)
NATIONAL_OUTLETS = [
    ("The Hindu", "thehindu.com"), ("Indian Express", "indianexpress.com"),
    ("Times of India", "timesofindia.indiatimes.com"), ("Hindustan Times", "hindustantimes.com"),
    ("Economic Times", "economictimes.indiatimes.com"), ("Mint", "livemint.com"),
    ("Business Standard", "business-standard.com"), ("NDTV", "ndtv.com"),
    ("Moneycontrol", "moneycontrol.com"), ("Deccan Herald", "deccanherald.com"),
    ("The News Minute", "thenewsminute.com"), ("PTI", "ptinews.com"),
]

# Coverage tiers
FEATURED_MIN_EVENTS = 15        # enough volume that a dashboard view isn't a handful of dots
FEATURED_MIN_CATEGORIES = 4     # activity should span more than one kind of action
FEATURED_MIN_PUBLISHERS = 6     # guards against one outlet dominating a state's picture
FEATURED_MIN_ACTIVE_MONTHS = 4  # shows sustained activity, not one news burst
FEATURED_MAX_QUERY_SHARE = 0.40  # state label must come mainly from article text, not from which search returned it
LOW_COVERAGE_MIN_EVENTS = 3     # below this there is nothing meaningful to show at all
NON_SUBSTANTIVE_CATEGORIES = {"statement", "other"}  # don't count toward category breadth


# Foreign-government stories mentioning an Indian origin (e.g. a UK minister born in Bihar)
FOREIGN_COUNTRIES = [
    r"\bUK(?:[\u2019']?s)?\b", r"\bU\.K\.", r"\bUS\b", r"\bU\.S\.", r"\bUSA\b", r"\bUAE\b",
    r"\bUnited Kingdom\b", r"\bUnited States\b", r"\bBritain\b", r"\bBritish\b", r"\bSingapore\b",
    r"\bChina\b", r"\bChinese\b", r"\bJapan\b", r"\bAustralia\b", r"\bCanada\b", r"\bGermany\b",
    r"\bFrance\b", r"\bSaudi Arabia\b", r"\bRussia\b", r"\bPakistan\b", r"\bBangladesh\b",
    r"\bSri Lanka\b", r"\bNepal\b", r"\bIsrael\b", r"\bSouth Korea\b",
]
FOREIGN_ROLES = [r"minister", r"government", r"govt", r"parliament", r"cabinet", r"president", r"senate"]

# "<State>-born", "native of <State>": origin, not the subject of the story
ORIGIN_AFTER = r"^[\s\-]*(?:born|origin)\b"
ORIGIN_BEFORE = r"(?:native of|hails? from|hailing from)\s+$"

# Union/Central government as the actor; excluded unless a state-government signal is also present
NATIONAL_ACTOR_TERMS = [
    r"\bUnion (?:Minister|Cabinet|Govt|Government|Ministry)\b", r"\bcentral (?:govt|government|ministry)\b",
    r"\bGovt\.? of India\b", r"\bGovernment of India\b", r"\bMeitY\b", r"\bNITI Aayog\b",
]
# case-sensitive: lowercase "centre" and "AI Centre of Excellence" are not the Union government
NATIONAL_ACTOR_CENTRE = r"\bthe Centre\b|\bCentre[\u2019']s\b|^Centre\b"

# Punjab, Hyderabad (Sindh) and Bengal exist on both sides of the border; spot check found
# all 3 sampled Punjab rows were Pakistani Punjab
FOREIGN_OUTLET_TLDS = (".pk", ".bd")
FOREIGN_OUTLET_NAMES = [
    "The Express Tribune", "Express Tribune", "Dawn", "The News International", "Geo News", "Geo",
    "ARY News", "ARY", "Samaa", "Business Recorder", "Pakistan Today", "Daily Times", "The Nation",
    "The Daily Star", "Prothom Alo",
]
FOREIGN_OUTLET_DOMAINS = ["dawn.com", "geo.tv", "brecorder.com", "arynews.tv", "samaa.tv",
                          "thedailystar.net", "prothomalo.com"]
