"""
battle_render.py — Niflheim battle card renderer.

Renders a single-turn battle snapshot as a PNG: both Pokémon's official-
artwork sprites over a background scene, each with a solid, sharp-cornered
plate showing name, level, HP bar + HP text, and status condition tag.

Used by wild encounters (battle.py), trainer/gym battles (gym.py), and
PvP (pvp_session.py) via the __IMG__<path>__CAP__<caption> marker — same
mechanism party_render.py uses. This module renders ONLY the visual
snapshot (sprites/HP/name/level/status); all move-used text and effect
bullets (damage numbers, flinch, paralysis procs, etc.) stay in the
caption text built by the caller, never drawn into the image itself.

Fonts: Inter (variable font, fonts/inter/Inter-VariableFont.ttf) — same
       font as party_render.py, chosen for on-screen legibility over a
       decorative face like Cinzel, which reads poorly at WhatsApp's
       scaled-down display size.

Composition: the player's own Pokémon sits bottom-left and larger (closer
       to camera); the opponent sits top-right and smaller (farther way),
       matching the requested depth layout. This is a deliberate PokéAPI-
       official-artwork stand-in for a true front/back sprite pair — since
       official artwork only has one front-facing angle, depth is sold via
       size + position instead of a back-view sprite.

Background: single default scene for now (assets/backgrounds/meadow_default
       .png), with room to add per-zone backgrounds later (see
       BACKGROUNDS dict — add a zone_type key pointing at a new file and
       it'll be picked up automatically by render()'s zone_type param).
"""
import os
import hashlib
import requests
from PIL import Image, ImageDraw, ImageFont

from paths import ROOT as _ROOT
_THIS_DIR = _ROOT   # fonts/, assets/ and .sprite_cache stay at the repo root

# ── Palette (matches party_render.py) ───────────────────────────────
TEXT        = (255, 255, 255)
TEXT_MUTED  = (210, 208, 198)
HP_GREEN    = (55, 234, 80)     # sampled from Gen-3 reference
HP_TRACK    = (56, 58, 47)      # sampled empty-bar track color
HP_YELLOW   = (240, 200, 70)
HP_RED      = (255, 95, 95)
HP_LABEL    = (244, 179, 63)    # orange "HP" label, sampled from reference

# Gen-3 GBA plate palette — olive/khaki body, dark brown-green border,
# swapped in from the reference cartridge screenshot (was a translucent
# cyan-glass HUD before). The badge/orb accent color stays cyan so the
# level circle + type orbs still read as "Niflheim" details on top of
# the borrowed chrome, rather than a full re-theme.
CYAN        = (143, 227, 255)      # #8FE3FF — kept for badge/orb accents only
CYAN_DIM    = (74, 125, 144)
PLATE_FILL  = (71, 70, 65, 235)    # sampled olive-khaki, near-opaque (not glass anymore)
PLATE_EDGE  = (40, 46, 42, 255)    # sampled dark brown-green border
STATUS_BG   = (217, 178, 60)
STATUS_TEXT = (20, 16, 8)

STATUS_TAGS = {
    "burn": "BRN", "poison": "PSN", "bleed": "BLD",
    "paralysis": "PAR", "sleep": "SLP", "freeze": "FRZ",
}

# Same map as party_render.py — kept identical so type-color coding
# stays consistent between the party screen and battle cards.
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

FONT_INTER  = os.path.join(_THIS_DIR, "fonts/inter/Inter-VariableFont.ttf")
FONT_CINZEL = os.path.join(_THIS_DIR, "fonts/cinzel/static/Cinzel-Black.ttf")

W, H = 1000, 660

BACKGROUNDS_DIR = os.path.join(_THIS_DIR, "assets/backgrounds")
BACKGROUNDS = {
    "default": os.path.join(BACKGROUNDS_DIR, "meadow_default.png"),
    # Add per-zone entries later, e.g.:
    # "water": os.path.join(BACKGROUNDS_DIR, "water_default.png"),
    # "town":  os.path.join(BACKGROUNDS_DIR, "town_default.png"),
}

SPRITE_CACHE_DIR = os.path.join(_THIS_DIR, ".sprite_cache")
os.makedirs(SPRITE_CACHE_DIR, exist_ok=True)

_font_cache = {}
def font(weight: bytes, size: int):
    key = (weight, size)
    if key not in _font_cache:
        f = ImageFont.truetype(FONT_INTER, size)
        f.set_variation_by_name(weight)
        _font_cache[key] = f
    return _font_cache[key]


_cinzel_cache = {}
def font_cinzel(size: int):
    """Cinzel-Black — used only for the level badge number, a deliberate
    departure from Inter for one decorative accent (see module docstring
    re: Cinzel reading poorly at small sizes — this is used large, in a
    single short number, where that concern doesn't apply)."""
    if size not in _cinzel_cache:
        _cinzel_cache[size] = ImageFont.truetype(FONT_CINZEL, size)
    return _cinzel_cache[size]


def _cache_path_for_url(url: str) -> str:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(SPRITE_CACHE_DIR, f"{h}.png")


def load_sprite(url: str, size: int):
    """Download (with on-disk cache) and return a square RGBA sprite Image,
    centered in a transparent canvas of (size, size), or a placeholder
    silhouette if the URL is missing/unreachable."""
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
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([size * 0.15, size * 0.15, size * 0.85, size * 0.85],
              fill=(90, 100, 115, 255))
    d.ellipse([size * 0.15, size * 0.15, size * 0.85, size * 0.85],
              outline=(255, 255, 255, 60), width=2)
    return img


def _load_background(zone_type: str | None) -> Image.Image:
    path = BACKGROUNDS.get(zone_type or "default", BACKGROUNDS["default"])
    if not os.path.exists(path):
        path = BACKGROUNDS["default"]
    bg = Image.open(path).convert("RGB")
    # Cover-fit to WxH (crop to match aspect, then resize) so any source
    # image size still fills the card without distortion.
    src_w, src_h = bg.size
    target_ratio = W / H
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        x0 = (src_w - new_w) // 2
        bg = bg.crop((x0, 0, x0 + new_w, src_h))
    else:
        new_h = int(src_w / target_ratio)
        y0 = (src_h - new_h) // 2
        bg = bg.crop((0, y0, src_w, y0 + new_h))
    bg = bg.resize((W, H), Image.LANCZOS)
    return bg


def draw_hp_bar(draw, x, y, w, h, cur, mx, font_body, font_label=None):
    pct = max(0, min(1, cur / mx if mx else 0))
    if pct > 0.5:
        fill_color = HP_GREEN
    elif pct > 0.2:
        fill_color = HP_YELLOW
    else:
        fill_color = HP_RED

    # "HP" label to the left of the bar, Gen-3 style — pushes the bar
    # itself right, so callers should reserve ~34px on the left.
    label_w = 0
    if font_label:
        lb = draw.textbbox((0, 0), "HP", font=font_label)
        label_w = lb[2] - lb[0] + 8
        draw.text((x, y - 3), "HP", font=font_label, fill=HP_LABEL)

    bar_x = x + label_w
    bar_w = w - label_w
    draw.rectangle([bar_x, y, bar_x + bar_w, y + h], fill=HP_TRACK)
    if pct > 0:
        draw.rectangle([bar_x, y, bar_x + max(bar_w * pct, 2), y + h], fill=fill_color)
    draw.rectangle([bar_x, y, bar_x + bar_w, y + h], outline=(0, 0, 0, 140), width=1)
    hp_text = f"{cur}/{mx}"
    draw.text((bar_x + bar_w - draw.textlength(hp_text, font=font_body), y + h + 4),
              hp_text, font=font_body, fill=TEXT)


def draw_plate(base, draw, x, y, mon, align, fonts):
    """
    mon: { "name": str, "level": int, "hp": int, "max_hp": int,
           "status": str|None, "sprite": str, "types": list[str],
           "xp": int|None, "xp_to_next": int|None }
    align: "left" or "right" — which edge the plate's main body anchors/
    grows from (name/HP text side). The level-circle badge sits on the
    OPPOSITE edge — for a right-aligned plate (ally) that's the plate's
    left edge; for a left-aligned plate (enemy) that's the plate's right
    edge — i.e. the badge always sits toward the middle/inner side.

    xp/xp_to_next: only drawn for the player's own mon (wild/trainer
    mons don't track XP) — pass xp=None to skip that row entirely.
    """
    f_name, f_badge, f_body = fonts
    plate_w, plate_h = 410, 112
    px = x if align == "left" else x - plate_w
    py = y
    circle_r  = 46   # level badge radius
    orb_r     = 12   # element orb radius
    bracket_l = 24   # bracket corner accent arm length

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    # Sharp-cornered glass panel (matches the battle-v3.html mockup —
    # was rounded_rectangle before; switched to plain rectangle since
    # bracket accents read cleaner against hard edges).
    odraw.rectangle([px, py, px + plate_w, py + plate_h],
                     fill=PLATE_FILL, outline=PLATE_EDGE, width=2)

    # Level badge: circle at the LOWER INNER corner of the plate (inner
    # = toward the middle of the screen; lower = bottom of the plate),
    # containing ONLY the level number in a bold display font — not a
    # sprite. Kept as the one rounded element per your last call.
    badge_cx = px if align == "right" else px + plate_w
    badge_cy = py + plate_h
    odraw.ellipse([badge_cx - circle_r, badge_cy - circle_r,
                   badge_cx + circle_r, badge_cy + circle_r],
                  fill=PLATE_FILL, outline=PLATE_EDGE, width=2)

    base.paste(Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB"), (0, 0))

    # Bracket corner accents on the two OUTER corners (opposite the
    # badge) — the signature glow detail from the mockup.
    outer_top_x    = px + plate_w if align == "right" else px
    outer_bottom_x = outer_top_x
    if align == "right":
        draw.line([(px, py + bracket_l), (px, py), (px + bracket_l, py)], fill=CYAN, width=2)
    else:
        draw.line([(px + plate_w - bracket_l, py), (px + plate_w, py), (px + plate_w, py + bracket_l)], fill=CYAN, width=2)

    lvl_text = str(mon["level"])
    f_lvl = font_cinzel(36)
    lb = draw.textbbox((0, 0), lvl_text, font=f_lvl)
    lw, lh = lb[2] - lb[0], lb[3] - lb[1]
    draw.text((badge_cx - lw / 2 - lb[0], badge_cy - lh / 2 - lb[1]),
              lvl_text, font=f_lvl, fill=CYAN)

    # Body content: name row uses the full plate width (badge is now
    # at the bottom corner, out of the way up top); HP/XP bar row insets
    # away from the badge since they now share the bottom edge with it.
    pad = 13
    top_left   = px + pad
    top_right  = px + plate_w - pad
    bottom_left  = px + pad if align == "left" else px + pad + circle_r * 0.5
    bottom_right = px + plate_w - pad if align == "right" else px + plate_w - pad - circle_r * 0.5

    # Element orbs — top-right of the plate body, one per actual type,
    # colored via TYPE_COLORS. Max 2 (Pokémon never have more).
    types = (mon.get("types") or [])[:2]
    orb_x = top_right - orb_r
    orb_y = py + 16
    for t in reversed(types):
        color = TYPE_COLORS.get(t, (170, 170, 160))
        draw.ellipse([orb_x - orb_r, orb_y - orb_r, orb_x + orb_r, orb_y + orb_r],
                     fill=color, outline=(255, 255, 255, 90), width=1)
        orb_x -= orb_r * 2 + 6

    # Name row
    name_text = mon["name"].upper()
    name_max_w = (top_right - orb_r * 2 * len(types) - 12) - top_left if types else top_right - top_left
    nb = draw.textbbox((0, 0), name_text, font=f_name)
    active_f_name = f_name
    if (nb[2] - nb[0]) > name_max_w:
        active_f_name = font(b"Bold", 16)
        nb = draw.textbbox((0, 0), name_text, font=active_f_name)
    draw.text((top_left, py + 8), name_text, font=active_f_name, fill=TEXT)

    row_y = py + 8 + (nb[3] - nb[1]) + 8

    if mon.get("status"):
        tag = STATUS_TAGS.get(mon["status"], mon["status"][:3].upper())
        tb = draw.textbbox((0, 0), tag, font=f_badge)
        tw = tb[2] - tb[0] + 12
        th = (tb[3] - tb[1]) + 7
        draw.rectangle([top_left, row_y, top_left + tw, row_y + th], fill=STATUS_BG)
        draw.text((top_left + 6, row_y + 4), tag, font=f_badge, fill=STATUS_TEXT)

    bar_w = bottom_right - bottom_left
    bar_h = 12
    has_xp = mon.get("xp") is not None and mon.get("xp_to_next")
    hp_bar_y = py + plate_h - bar_h - 10 - (10 if has_xp else 0)
    draw_hp_bar(draw, bottom_left, hp_bar_y, bar_w, bar_h, mon["hp"], mon["max_hp"], f_body, f_badge)

    if has_xp:
        xp_bar_y = py + plate_h - 6
        xp_h = 4
        xp_pct = max(0, min(1, mon["xp"] / mon["xp_to_next"]))
        draw.rectangle([bottom_left, xp_bar_y, bottom_left + bar_w, xp_bar_y + xp_h], fill=HP_TRACK)
        if xp_pct > 0:
            draw.rectangle([bottom_left, xp_bar_y, bottom_left + max(bar_w * xp_pct, 2), xp_bar_y + xp_h],
                           fill=CYAN)


def render(player_mon: dict, enemy_mon: dict, out_path: str,
           zone_type: str | None = None, label: str | None = None) -> str:
    """
    player_mon / enemy_mon: { "name": str, "level": int, "hp": int,
        "max_hp": int, "status": str|None, "sprite": str }
    out_path: where to save the PNG.
    zone_type: optional key into BACKGROUNDS (falls back to "default").
    label: optional small corner tag, e.g. "WILD" or a trainer name.
    """
    bg = _load_background(zone_type)
    draw = ImageDraw.Draw(bg)

    f_name = font(b"Bold", 30)
    f_badge = font(b"SemiBold", 19)
    f_body = font(b"Medium", 19)
    fonts = (f_name, f_badge, f_body)

    # Opponent: sprite top-right (farther away); plate in the open sky
    # area to the LEFT of the sprite, with real clearance between them.
    enemy_sprite_size = 186
    enemy_x = W - 64 - enemy_sprite_size
    enemy_y = 50
    enemy_sprite = load_sprite(enemy_mon.get("sprite", ""), enemy_sprite_size)
    bg.paste(enemy_sprite, (enemy_x, enemy_y), enemy_sprite)
    draw_plate(bg, draw, enemy_x - 60, 60, enemy_mon,
               align="right", fonts=fonts)

    # Player: sprite bottom-left (closer); plate down/right toward the
    # path, with real clearance between it and the sprite.
    player_sprite_size = 271
    player_x = 43
    player_y = H - 43 - player_sprite_size
    player_sprite = load_sprite(player_mon.get("sprite", ""), player_sprite_size)
    bg.paste(player_sprite, (player_x, player_y), player_sprite)
    draw_plate(bg, draw, player_x + player_sprite_size + 40, H - 200, player_mon,
               align="left", fonts=fonts)

    if label:
        f_label = font(b"Bold", 16)
        lb = draw.textbbox((0, 0), label.upper(), font=f_label)
        lw, lh = lb[2] - lb[0], lb[3] - lb[1]
        lx, ly = 40, 30
        overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle([lx - 12, ly - 8, lx + lw + 12, ly + lh + 16], fill=PLATE_FILL)
        odraw.rectangle([lx - 12, ly - 8, lx + lw + 12, ly + lh + 16], outline=PLATE_EDGE, width=1)
        bg.paste(Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB"), (0, 0))
        draw.text((lx, ly), label.upper(), font=f_label, fill=TEXT)

    # Export as compressed JPEG instead of raw PNG — the previous PNG
    # export was ~1.4MB per card since it's a full photographic
    # background composite, not flat vector art, so PNG's lossless
    # encoding bought nothing. JPEG at q=82 with 4:2:0 chroma
    # subsampling holds up fine for a photo+UI composite at this size
    # and WhatsApp re-compresses on upload anyway.
    if out_path.lower().endswith(".png"):
        out_path = out_path[:-4] + ".jpg"
    # subsampling=0 (4:4:4, full color detail) instead of 4:2:0 — with
    # the background now only ~3KB, JPEG's chroma subsampling was the
    # main thing softening the HUD text/bar edges, not the photo. Full
    # subsampling costs little extra size here and keeps small text
    # legible on a phone screen.
    bg.save(out_path, "JPEG", quality=88, optimize=True, subsampling=0)
    return out_path
	
