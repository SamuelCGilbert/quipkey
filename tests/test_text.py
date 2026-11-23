from hotmic.config import DEFAULT_CONFIG
from hotmic.text import clean_text, short_mic_name

CFG = dict(DEFAULT_CONFIG)


def test_fillers_removed_and_capitalized():
    assert clean_text("um so I think, uh, we should go", CFG) == "So I think, we should go "


def test_no_trailing_space_option():
    assert clean_text("hello", {**CFG, "trailing_space": False}) == "Hello"


def test_fillers_kept_when_disabled():
    cfg = {**CFG, "remove_fillers": False, "trailing_space": False}
    assert clean_text("um hello", cfg) == "um hello"


def test_words_containing_fillers_survive():
    assert clean_text("The umbrella and the hummingbird", CFG) == "The umbrella and the hummingbird "


def test_empty_stays_empty():
    assert clean_text("  ", CFG) == ""
    assert clean_text("um", CFG) == ""


def test_short_mic_name():
    assert short_mic_name("Microphone (6- Antlion Wireless Microphone)") == "Antlion Wireless Microphone"
    assert short_mic_name("Built-in mic") == "Built-in mic"
    assert short_mic_name("Microphone (C922 Pro Stream Web") == "C922 Pro Stream Web"
