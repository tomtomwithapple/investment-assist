"""Plain words (P91, PLAN S73)."""

from assist import plain


def test_neutral_is_a_regime_and_a_stance():
    assert plain.label("regime", "neutral") == "Markets are normal"
    assert plain.label("stance", "neutral") == "Hold the usual amount"
    assert plain.label("regime", "risk_off") == "Markets are nervous"
    assert "split into parts" in plain.meaning("regime", "risk_off")


def test_styles_stances_strengths_and_unknown_terms():
    assert plain.label("style", "dividend_value") == "dividend screen"
    assert plain.label("style", "garp") == "growth screen"
    assert "Growth at a reasonable price" in plain.meaning("style", "garp")
    assert plain.label("stance", "avoid") == "Hold none"
    assert plain.label("strength", "strong") == "Strong"
    assert plain.label("dollar", "up") == "Dollar strengthening"
    assert plain.label("style", "industry_value") == "industry value"
    assert plain.meaning("style", "industry_value") is None


def test_legs():
    assert plain.leg("IDN", "stocks") == "Indonesian stocks"
    assert plain.leg("USA", "stocks") == "US stocks" and plain.leg("XXX", "bonds") == "XXX bonds"
