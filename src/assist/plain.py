"""Plain words for the model's terms (PLAN S73): one table of raw term → (plain label, one-line
meaning), used as the visible wording of the guided pages and as hover text on the detail
pages. No rule lives here and nothing here is hashed: changing a word changes no decision."""

from __future__ import annotations

__all__ = ["ASSET", "DOLLAR", "MARKET", "REGIME", "STANCE", "STRENGTH", "STYLE", "label",
           "meaning", "leg"]

REGIME = {
    "risk_on": ("Markets are calm", "Investors are buying risky assets; orders go in one go."),
    "neutral": ("Markets are normal", "No strong mood either way; orders go in one go."),
    "risk_off": ("Markets are nervous", "Investors are moving to safety, which usually hurts "
                 "Indonesian stocks, bonds and the rupiah; every order is split into parts."),
}
DOLLAR = {
    "up": ("Dollar rising", "The US dollar gained more than 2% in 13 weeks: pressure on the "
           "rupiah, and unhedged US holdings gain in rupiah."),
    "flat": ("Dollar steady", "The US dollar moved less than 2% in 13 weeks."),
    "down": ("Dollar falling", "The US dollar lost more than 2% in 13 weeks: usually helps "
             "Indonesian assets and the rupiah."),
}
STANCE = {
    "overweight": ("Hold more than usual", "Conditions look favourable: target 5 points above "
                   "the usual share."),
    "neutral": ("Hold the usual amount", "No clear edge: target the usual share."),
    "underweight": ("Hold less than usual", "Conditions look unfavourable: target 5 points "
                    "below the usual share."),
    "avoid": ("Hold none", "Clearly unfavourable: target 0%."),
}
STYLE = {
    "dividend_value": ("dividend screen", "Dividend yield plus sustainable growth must beat the "
                       "required return, and the dividend must be safe."),
    "garp": ("growth screen", "Growth at a reasonable price: the growth the company delivered "
             "must be higher than the growth today's price already assumes."),
}
STRENGTH = {
    "strong": ("Strong", "A hard limit is broken, or two independent reasons agree."),
    "medium": ("Medium", "One tested screen says so, or it brings the portfolio back to its "
               "usual shares."),
    "weak": ("Weak", "Background only: not tested, shown for context."),
}
MARKET = {"IDN": "Indonesian", "USA": "US", "JPN": "Japanese", "AUS": "Australian",
          "SGP": "Singapore", "KOR": "Korean", "TWN": "Taiwanese", "EMU": "euro-area"}
ASSET = {"stocks": "stocks", "bonds": "bonds", "currency": "cash", "commodities": "commodities"}
_TABLES = {"regime": REGIME, "dollar": DOLLAR, "stance": STANCE, "style": STYLE,
           "strength": STRENGTH}


def label(kind: str, term: str | None) -> str:
    """The plain label of a raw term of `kind` (regime, dollar, stance, style, strength; "neutral"
    is both a regime and a stance); the term itself, underscores as spaces, when unknown."""
    t = _TABLES[kind]
    return t[term][0] if term in t else str(term or "").replace("_", " ")


def meaning(kind: str, term: str | None) -> str | None:
    t = _TABLES[kind]
    return t[term][1] if term in t else None


def leg(market: str, asset: str) -> str:
    """"Indonesian stocks", "US stocks", "Indonesian bonds"."""
    return f"{MARKET.get(market, market)} {ASSET.get(asset, asset)}"
