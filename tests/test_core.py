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
