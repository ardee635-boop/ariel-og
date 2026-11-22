"""Communications-outage display helpers (Session 7B-2a-ii).

Pure functions, no game state. While Communications is sabotaged the game
shows crew a corrupted `.progress` reading: the number may be wrong, and it is
often shown in another writing system or spelled out in another language.
"""

import random

from . import amongus_config as C

# ── Digit systems (zero-based, index = digit) ──────────────
_DIGIT_SETS = {
    "arabic_indic": "٠١٢٣٤٥٦٧٨٩",
    "persian": "۰۱۲۳۴۵۶۷۸۹",
    "devanagari": "०१२३४५६७८९",
    "bengali": "০১২৩৪৫৬৭৮৯",
    "thai": "๐๑๒๓๔๕๖๗๘๙",
    "fullwidth": "０１２３４５６７８９",
}
_PERCENT_SIGN = {"arabic_indic": "٪", "persian": "٪"}


def _digits(value, style):
    table = _DIGIT_SETS[style]
    return "".join(table[int(ch)] for ch in str(value))


def to_roman(value):
    """Roman numerals for 1-100; 0 is written N (nulla)."""
    if value == 0:
        return "N"
    out = ""
    for amount, symbol in (
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ):
        while value >= amount:
            out += symbol
            value -= amount
    return out


# ── Number words, 0-100 ────────────────────────────────────
def spanish(n):
    ones = ("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce "
            "trece catorce quince dieciséis diecisiete dieciocho diecinueve veinte "
            "veintiuno veintidós veintitrés veinticuatro veinticinco veintiséis "
            "veintisiete veintiocho veintinueve").split()
    tens = {30: "treinta", 40: "cuarenta", 50: "cincuenta", 60: "sesenta",
            70: "setenta", 80: "ochenta", 90: "noventa"}
    if n == 100:
        return "cien"
    if n < 30:
        return ones[n]
    t, u = n - n % 10, n % 10
    return tens[t] if u == 0 else f"{tens[t]} y {ones[u]}"


def french(n):
    ones = ("zéro un deux trois quatre cinq six sept huit neuf dix onze douze "
            "treize quatorze quinze seize").split()
    if n == 100:
        return "cent"
    if n <= 16:
        return ones[n]
    if n < 20:
        return "dix-" + ones[n - 10]
    tens = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante"}
    if n < 60:
        t, u = n - n % 10, n % 10
        if u == 0:
            return tens[t]
        return f"{tens[t]} et un" if u == 1 else f"{tens[t]}-{ones[u]}"
    if n < 80:
        r = n - 60
        if r == 0:
            return "soixante"
        if r == 1:
            return "soixante et un"
        if r == 11:
            return "soixante et onze"
        return "soixante-" + (ones[r] if r <= 16 else "dix-" + ones[r - 10])
    r = n - 80
    if r == 0:
        return "quatre-vingts"
    return "quatre-vingt-" + (ones[r] if r <= 16 else "dix-" + ones[r - 10])


def german(n):
    ones = ("null ein zwei drei vier fünf sechs sieben acht neun zehn elf zwölf "
            "dreizehn vierzehn fünfzehn sechzehn siebzehn achtzehn neunzehn").split()
    tens = {20: "zwanzig", 30: "dreißig", 40: "vierzig", 50: "fünfzig",
            60: "sechzig", 70: "siebzig", 80: "achtzig", 90: "neunzig"}
    if n == 100:
        return "hundert"
    if n == 1:
        return "eins"
    if n < 20:
        return ones[n]
    t, u = n - n % 10, n % 10
    return tens[t] if u == 0 else f"{ones[u]}und{tens[t]}"


def italian(n):
    ones = ("zero uno due tre quattro cinque sei sette otto nove dieci undici "
            "dodici tredici quattordici quindici sedici diciassette diciotto "
            "diciannove").split()
    tens = {20: "venti", 30: "trenta", 40: "quaranta", 50: "cinquanta",
            60: "sessanta", 70: "settanta", 80: "ottanta", 90: "novanta"}
    if n == 100:
        return "cento"
    if n < 20:
        return ones[n]
    t, u = n - n % 10, n % 10
    if u == 0:
        return tens[t]
    stem = tens[t][:-1] if u in (1, 8) else tens[t]
    return stem + ("tré" if u == 3 else ones[u])


def chinese(n):
    d = "零一二三四五六七八九"
    if n == 100:
        return "一百"
    if n < 10:
        return d[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + d[n - 10]
    t, u = divmod(n, 10)
    return d[t] + "十" + (d[u] if u else "")


# language → (spell-out function, percent wording template)
_LANGUAGES = {
    "spanish": (spanish, "{} por ciento"),
    "french": (french, "{} pour cent"),
    "german": (german, "{} Prozent"),
    "italian": (italian, "{} per cento"),
    "chinese": (chinese, "百分之{}"),
}

SCRIPT_STYLES = tuple(_DIGIT_SETS) + ("roman",)
LANGUAGE_STYLES = tuple(_LANGUAGES)


def render_percent(value, style):
    """Render an integer 0-100 as a percentage in the given style."""
    value = max(0, min(100, int(value)))
    if style == "plain":
        return f"{value}%"
    if style == "roman":
        return f"{to_roman(value)}%"
    if style in _DIGIT_SETS:
        return _digits(value, style) + _PERCENT_SIGN.get(style, "%")
    speller, template = _LANGUAGES[style]
    return template.format(speller(value))


def garble_progress(true_percent, rng=None):
    """Return the corrupted `.progress` reading shown during Communications.

    The shown number is wrong with probability COMMS_PROGRESS_WRONG_CHANCE
    (shifted by a random amount, never silently equal to the truth), and the
    rendering is plain only with probability COMMS_PROGRESS_PLAIN_CHANCE;
    otherwise it uses a random other writing system or spoken language.
    Returns {"text", "shown", "style", "accurate"}.
    """
    rng = rng or random
    true_percent = max(0, min(100, int(true_percent)))
    shown = true_percent
    if rng.random() < C.COMMS_PROGRESS_WRONG_CHANCE:
        lo, hi = C.COMMS_PROGRESS_OFFSET_RANGE
        sign = rng.choice((-1, 1))
        shown = true_percent + sign * rng.randint(lo, hi)
        if not 0 <= shown <= 100:
            shown = true_percent - sign * rng.randint(lo, hi)
        shown = max(0, min(100, shown))
        if shown == true_percent:  # clamped back onto the truth
            shown = true_percent + (lo if true_percent + lo <= 100 else -lo)
    if rng.random() < C.COMMS_PROGRESS_PLAIN_CHANCE:
        style = "plain"
    else:
        style = rng.choice(SCRIPT_STYLES + LANGUAGE_STYLES)
    return {
        "text": f"*<[{render_percent(shown, style)}]>*",
        "shown": shown,
        "style": style,
        "accurate": shown == true_percent,
    }
