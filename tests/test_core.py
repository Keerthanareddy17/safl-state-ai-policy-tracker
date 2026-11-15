from pipeline.classify import is_ai
from pipeline.normalize import normalize_date, normalize_state


def test_state_variants_agree():
    assert normalize_state("UP govt launches AI mission") == "Uttar Pradesh"
    assert normalize_state("Uttar Pradesh plans AI hub") == "Uttar Pradesh"
    assert normalize_state("Uttar-Pradesh plans AI hub") == "Uttar Pradesh"


def test_city_maps_to_state():
    assert normalize_state("Bengaluru startup raises funds") == "Karnataka"


def test_ap_means_associated_press_without_govt_context():
    assert normalize_state("(AP) Tech firms weigh new chips") is None
    assert normalize_state("AP govt signs MoU") == "Andhra Pradesh"


def test_ai_guards():
    assert not is_ai("AIADMK holds meeting")
    assert not is_ai("AIIMS opens new ward")
    assert is_ai("Kerala unveils AI policy")


def test_dates():
    assert normalize_date("not a date") == (None, "unknown")
    assert normalize_date("Fri, 13 Nov 2026 22:30:00 GMT") == ("2026-11-14", "day")  # IST is UTC+5:30


def test_local_bodies_and_new_delhi():
    assert normalize_state("BMC budget plans AI parking") == "Maharashtra"
    assert normalize_state("GHMC rolls out AI tool") == "Telangana"
    assert normalize_state("New Delhi hosts AI summit") is None


def test_institute_prefix_and_incidents():
    from pipeline.classify import excluded_reason, is_gov_actor
    assert not is_gov_actor("IIT Delhi launches AI course", title_only=True)
    assert is_gov_actor("Kerala launches AI mission", title_only=True)
    assert excluded_reason("Viral video of minister is AI-generated") == "incident_not_policy"
    assert excluded_reason("Govt issues SOP on deepfake videos") is None


def _art(title, date, state="Kerala", precision="day", name="A"):
    return {"title": title, "date": date, "date_precision": precision, "state": state,
            "url": "http://x/" + title, "source_name": name, "source_domain": "", "summary": title,
            "state_basis": "title", "category": "deployment", "sector": ""}


def test_dedup_dates_and_thresholds():
    from pipeline.dedup import cluster
    a = _art("Kerala launches AI chatbot for citizens", "2026-05-01", name="A")
    b = _art("Kerala launches AI chatbot to help citizens with services", "2026-05-03", name="B")
    far = _art("Kerala launches AI chatbot to help citizens with services", "2026-08-01", name="C")
    assert len(cluster([a, b])) == 1
    assert len(cluster([a, far])) == 2
    unknown = _art("Kerala launches AI chatbot to help citizens with services", "", precision="unknown", name="D")
    assert len(cluster([a, unknown])) == 2  # below the stricter 95 bar
