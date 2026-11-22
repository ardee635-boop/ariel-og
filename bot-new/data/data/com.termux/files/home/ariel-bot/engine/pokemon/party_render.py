"""
party_render.py — Niflheim party card renderer.

Renders player.party as a PNG image styled to match Niflheim-Online's
color system (see ariel-og-main index.html :root vars). Used by the
.party WhatsApp command via the __IMG__<path>__CAP__<caption> marker.

Fonts: Inter (variable font, fonts/inter/Inter-VariableFont.ttf) used
       throughout — title, names, badges, body text. Replaced Cinzel/
       Liberation Sans entirely: Cinzel is a decorative serif that reads
       poorly at the small scaled-down size WhatsApp actually displays
       this image at, so everything now uses Inter (built for screen/
       UI legibility, matches the site's own body font) at varying
       named weights (Bold/SemiBold/Medium/Regular) via the font()
       helper's set_variation_by_name.

Sprites: downloaded from each OwnedPokemon's `.sprite` URL (PokéAPI
official-artwork, already cached elsewhere in the bot) and cached to
disk so repeat .party calls don't re-download every time.
"""
import os
import hashlib
import requests
from PIL import Image, ImageDraw, ImageFont

# ── Palette (from ariel-og-main index.html :root) ──────────────────
BG          = (5, 10, 18)        # #050a12
ICE         = (143, 227, 255)    # #8FE3FF
ICE_DIM     = (62, 122, 148)     # #3E7A94
TEXT        = (234, 246, 255)    # #EAF6FF
TEXT_MUTED  = (127, 160, 184)    # #7FA0B8
CARD_BG     = (14, 20, 30)
HP_GREEN    = (46, 232, 138)
HP_RED      = (255, 95, 95)
PAR_YELLOW  = (217, 178, 60)
EMPTY_DASH  = (58, 70, 86)

TYPE_COLORS = {
    "psychic": (255, 106, 193), "flying":  (179, 157, 255),
    "water":   (79, 195, 255),  "fire":    (255, 154, 79),
    "grass":   (120, 200, 120), "electric":(240, 210, 80),
    "normal":  (170, 170, 160), "bug":     (166, 185, 40),
    "poison":  (163, 89, 199),  "ground":  (216, 181, 106),
    "rock":    (182, 161, 96),  "ghost":   (112, 88, 168),
    "dragon":  (112, 82, 240),  "dark":    (110, 92, 84),
    "steel":   (170, 170, 190), "fairy":   (240, 160, 208),
    "fighting":(200, 80, 60),   "ice":     (140, 220, 224),
}

from paths import ROOT as _ROOT
_THIS_DIR = _ROOT   # fonts/, assets/ and .sprite_cache stay at the repo root

# Inter (variable font — single file, every weight via named instances)
# replaces Cinzel/Liberation Sans everywhere on this card. Cinzel is a
# decorative serif built for headlines, not for legibility at the small,
# scaled-down size WhatsApp actually renders this image at — swapping to
# Inter (built specifically for screen/UI legibility, matches the site's
# own body font) is a deliberate fix, not a fallback.
FONT_INTER = os.path.join(_THIS_DIR, "fonts/inter/Inter-VariableFont.ttf")

W, H     = 1400, 924
CARD_W, CARD_H = 644, 224
GAP      = 22
MARGIN   = 56

SPRITE_CACHE_DIR = os.path.join(_THIS_DIR, ".sprite_cache")
os.makedirs(SPRITE_CACHE_DIR, exist_ok=True)

_font_cache = {}
def font(weight: bytes, size: int):
    """Load Inter at a given size, set to a named weight instance
    (b'Regular', b'Medium', b'SemiBold', b'Bold', etc.) via the
    variable font's wght axis. Cached per (weight, size) pair."""
    key = (weight, size)
    if key not in _font_cache:
        f = ImageFont.truetype(FONT_INTER, size)
        f.set_variation_by_name(weight)
        _font_cache[key] = f
    return _font_cache[key]


def rounded(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

def dashed_rounded(draw, box, radius, color, dash=8, gap=6, width=2):
    import math
    x0, y0, x1, y1 = box
    def dashed_line(p0, p1):
        x0_, y0_ = p0; x1_, y1_ = p1
        length = math.hypot(x1_ - x0_, y1_ - y0_)
        n = int(length // (dash + gap))
        for i in range(n + 1):
            t0 = (i * (dash + gap)) / length if length else 0
            t1 = min(t0 + dash / length, 1) if length else 0
            xa = x0_ + (x1_ - x0_) * t0; ya = y0_ + (y1_ - y0_) * t0
            xb = x0_ + (x1_ - x0_) * t1; yb = y0_ + (y1_ - y0_) * t1
            draw.line([(xa, ya), (xb, yb)], fill=color, width=width)
    dashed_line((x0 + radius, y0), (x1 - radius, y0))
    dashed_line((x0 + radius, y1), (x1 - radius, y1))
    dashed_line((x0, y0 + radius), (x0, y1 - radius))
    dashed_line((x1, y0 + radius), (x1, y1 - radius))
    draw.arc([x0, y0, x0 + radius * 2, y0 + radius * 2], 180, 270, fill=color, width=width)
    draw.arc([x1 - radius * 2, y0, x1, y0 + radius * 2], 270, 360, fill=color, width=width)
    draw.arc([x0, y1 - radius * 2, x0 + radius * 2, y1], 90, 180, fill=color, width=width)
    draw.arc([x1 - radius * 2, y1 - radius * 2, x1, y1], 0, 90, fill=color, width=width)

def _cache_path_for_url(url: str) -> str:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(SPRITE_CACHE_DIR, f"{h}.png")

def load_sprite(url: str, size: int, accent_color):
    """Download (with on-disk cache) and return a sprite Image, or a
    placeholder circle if the URL is missing/unreachable."""
    if url:
        cache_path = _cache_path_for_url(url)
        try:
            if not os.path.exists(cache_path):
                resp = requests.get(url, timeout=6)
                resp.raise_for_status()
                with open(cache_path, "wb") as f:
                    f.write(resp.content)
            img = Image.open(cache_path).convert("RGBA")
            img.thumbnail((size, size), Image.LANCZOS)
            canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            ox = (size - img.width) // 2
            oy = (size - img.height) // 2
            canvas.paste(img, (ox, oy), img)
            return canvas
        except Exception:
            pass
    # fallback placeholder
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([6, 6, size - 6, size - 6], fill=accent_color + (255,))
    d.ellipse([6, 6, size - 6, size - 6], outline=(255, 255, 255, 60), width=2)
    return img

def draw_hp_bar(draw, x, y, w, h, cur, mx, font_body):
    pct = cur / mx if mx else 0
    draw.text((x, y - 2), "HP", font=font_body, fill=TEXT_MUTED)
    bar_x = x + 40
    bar_w = w - 40 - 110
    rounded(draw, [bar_x, y, bar_x + bar_w, y + h], radius=h // 2, fill=(30, 39, 51))
    fill_color = HP_GREEN if pct > 0.25 else HP_RED
    if pct > 0:
        rounded(draw, [bar_x, y, bar_x + max(bar_w * pct, h), y + h], radius=h // 2, fill=fill_color)
    draw.text((bar_x + bar_w + 14, y - 4), f"{cur} / {mx}", font=font_body, fill=TEXT_MUTED)

def draw_type_pill(draw, x, y, label, color, font_body):
    label = label.upper()
    bbox = draw.textbbox((0, 0), label, font=font_body)
    tw = bbox[2] - bbox[0]
    pad_x, pad_y = 14, 6
    w = tw + pad_x * 2
    h = (bbox[3] - bbox[1]) + pad_y * 2
    rounded(draw, [x, y, x + w, y + h], radius=h // 2, outline=color, width=2)
    draw.text((x + pad_x, y + pad_y - 1), label, font=font_body, fill=color)
    return w

def draw_card(base, draw, x, y, mon, fonts):
    f_name, f_badge, f_type, f_body = fonts
    accent_color = TYPE_COLORS.get(mon["types"][0], ICE)
    rounded(draw, [x, y, x + CARD_W, y + CARD_H], radius=14, fill=CARD_BG)
    rounded(draw, [x, y, x + 8, y + CARD_H], radius=4, fill=accent_color)

    # Sprite sized to the card's own height instead of a fixed constant —
    # fills the vertical space properly rather than leaving a small icon
    # floating in a tall, mostly-empty box.
    art_size = CARD_H - 40
    art_x, art_y = x + 26, y + (CARD_H - art_size) // 2
    sprite = load_sprite(mon.get("sprite", ""), art_size, accent_color)
    base.paste(sprite, (art_x, art_y), sprite)

    info_x = art_x + art_size + 24
    right_edge = x + CARD_W - 24
    avail_w = right_edge - info_x
    cursor_y = y + 18

    # Name gets its own full-width line — no more cramming status/level
    # badges onto the same row where they'd overflow the card. Badges
    # move to a dedicated row below, with real room to breathe.
    draw.text((info_x, cursor_y), mon["name"].upper(), font=f_name, fill=TEXT)

    badge_y = cursor_y + 44
    badge_x = info_x
    bh = 34

    if mon.get("status"):
        st = mon["status"]
        bbox = draw.textbbox((0, 0), st, font=f_badge)
        bw = bbox[2] - bbox[0] + 24
        rounded(draw, [badge_x, badge_y, badge_x + bw, badge_y + bh], radius=8, fill=PAR_YELLOW)
        draw.text((badge_x + 12, badge_y + 6), st, font=f_badge, fill=(20, 16, 8))
        badge_x += bw + 10

    lvl_text = f"Lv{mon['level']}"
    bbox = draw.textbbox((0, 0), lvl_text, font=f_badge)
    bw = bbox[2] - bbox[0] + 24
    rounded(draw, [badge_x, badge_y, badge_x + bw, badge_y + bh], radius=8, fill=(30, 39, 51))
    draw.text((badge_x + 12, badge_y + 6), lvl_text, font=f_badge, fill=TEXT_MUTED)

    ty = badge_y + bh + 14
    tx = info_x
    for t in mon["types"]:
        c = TYPE_COLORS.get(t, ICE)
        tx += draw_type_pill(draw, tx, ty, t, c, f_type) + 10

    # HP bar spans the card's remaining width down to its bottom edge,
    # instead of a thin strip near the top with unused space below it.
    hp_y = y + CARD_H - 34
    draw_hp_bar(draw, info_x, hp_y, avail_w, 16, mon["hp"], mon["max_hp"], f_body)

def draw_empty_slot(draw, x, y):
    dashed_rounded(draw, [x, y, x + CARD_W, y + CARD_H], radius=14, color=EMPTY_DASH, dash=8, gap=6, width=2)
    # Circle matches the filled card's sprite size/position exactly
    # (same art_size math as draw_card) so an empty slot reads as the
    # same weight/scale as a filled one, not a small icon lost in a
    # bigger box.
    art_size = CARD_H - 40
    cx, cy = x + 26 + art_size // 2, y + CARD_H // 2
    r = art_size // 2
    dashed_rounded(draw, [cx - r, cy - r, cx + r, cy + r], radius=r, color=EMPTY_DASH, dash=5, gap=4, width=2)
    plus_font = font(b"Regular", 46)
    d_b = draw.textbbox((0, 0), "+", font=plus_font)
    tw, th = d_b[2] - d_b[0], d_b[3] - d_b[1]
    draw.text((cx - tw / 2, cy - th / 2 - d_b[1]), "+", font=plus_font, fill=EMPTY_DASH)
    label = "NO DATA / EMPTY SLOT"
    lf = font(b"Medium", 22)
    label_x = x + 26 + art_size + 24
    lb = draw.textbbox((0, 0), label, font=lf)
    draw.text((label_x, cy - (lb[3] - lb[1]) / 2), label, font=lf, fill=(74, 88, 104))

def render(party: list[dict], trainer_name: str, out_path: str) -> str:
    """
    party: list of up to 6 dicts, each:
        { "name": str, "level": int, "types": [str, ...],
          "hp": int, "max_hp": int, "status": str|None, "sprite": str }
    trainer_name: player's display/trainer name
    out_path: where to save the PNG
    """
    img = Image.new("RGB", (W, H), BG).convert("RGBA")
    grid_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid_overlay)
    for gx in range(0, W, 40):
        gd.line([(gx, 0), (gx, H)], fill=(255, 255, 255, 10))
    for gy in range(0, H, 40):
        gd.line([(0, gy), (W, gy)], fill=(255, 255, 255, 10))
    img = Image.alpha_composite(img, grid_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    f_title = font(b"Bold", 42)
    f_trainer = font(b"Medium", 17)

    bar_x = MARGIN
    draw.rectangle([bar_x, 46, bar_x + 7, 46 + 42], fill=ICE)
    draw.text((bar_x + 26, 42), "PARTY //", font=f_title, fill=TEXT)
    w1 = draw.textbbox((0, 0), "PARTY // ", font=f_title)[2]
    draw.text((bar_x + 26 + w1, 42), "ACTIVE", font=f_title, fill=ICE)

    trainer_text = f"TRAINER: {trainer_name.upper()}"
    tb = draw.textbbox((0, 0), trainer_text, font=f_trainer)
    draw.text((W - MARGIN - (tb[2] - tb[0]), 58), trainer_text, font=f_trainer, fill=TEXT_MUTED)

    f_name = font(b"Bold", 34)
    f_badge = font(b"SemiBold", 20)
    f_type = font(b"SemiBold", 19)
    f_body = font(b"Medium", 21)
    fonts = (f_name, f_badge, f_type, f_body)

    cols = 2
    start_y = 140
    slots = party[:6] + [None] * (6 - len(party))
    for i, mon in enumerate(slots[:6]):
        col = i % cols
        row = i // cols
        x = MARGIN + col * (CARD_W + GAP)
        y = start_y + row * (CARD_H + GAP)
        if mon:
            draw_card(img, draw, x, y, mon, fonts)
        else:
            draw_empty_slot(draw, x, y)

    img.save(out_path)
    return out_path
