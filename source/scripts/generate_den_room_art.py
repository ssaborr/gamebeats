"""Generate GameBeats' 16-bit den background.

The artwork is authored on a strict 400x250 logical pixel canvas and scaled x4
with nearest-neighbour sampling to 1600x1000. Every visible edge therefore sits
on the same 4-pixel grid in the final plate.

The composition keeps the live-UI safe zones:

    upper-left wall .... greeting
    top centre ......... city window
    left middle ........ CRT station
    right upper ........ game shelf / hotspot at ~79%w, 36%h
    right middle ....... control panel / hotspot at ~79%w, 60%h
    right lower ........ record crate / hotspot at ~78%w, 84.5%h
    centre bottom ...... big puppy, kept visually quiet

Run from the project root:
    py source/scripts/generate_den_room_art.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont


# ── Final size / logical pixel grid ─────────────────────────────────────────
SCALE = 4
GW, GH = 400, 250
W, H = GW * SCALE, GH * SCALE

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "assets" / "room" / "den_room.png"
DIM_PATH = ROOT / "assets" / "room" / "den_room_dim.png"
PREVIEW_PATH = ROOT / "assets" / "room" / "den_room_safe_zones.png"
BEFORE_AFTER_PATH = ROOT / "assets" / "room" / "den_room_before_after.png"


# ── Palette: four-tone material ramps, all derived from the app palette ──────
PLUM = "#1B1030"
NIGHT = "#1A1111"
WALL = "#28182F"
WOOD = "#7A3E0E"
WOOD_DARK = "#381F30"
DECK = "#54303A"
DECK_TOP = "#75403F"
MAGENTA = "#7A2E5B"
CREAM = "#FFF3D0"
GOLD = "#FDB75C"
ORANGE = "#FF8A3D"
MINT = "#7CFFC4"
ROSE = "#D8B7B4"
DUST = "#C79AA5"

RAMPS = {
    "ink":      ("#0E0712", "#160C1E", "#241329", "#35203C"),
    "wall":     ("#170C21", "#24142D", "#32203A", "#452847"),
    "wall_hi":  ("#24142D", "#35203C", "#452847", "#5A3552"),
    "wood":     ("#32170F", "#532711", "#7A3E0E", "#A85B1E"),
    "wood_hi":  ("#532711", "#7A3E0E", "#A85B1E", "#D27B2F"),
    "deck":     ("#2A121C", "#54303A", "#75403F", "#9A5A5B"),
    "fabric":   ("#2A1233", "#45204A", "#632D5D", "#7A2E5B"),
    "fabric_hi":("#45204A", "#632D5D", "#7A2E5B", "#A04A78"),
    "mint":     ("#173B35", "#2C6B5A", "#7CFFC4", "#B6FFE0"),
    "mint_dim": ("#102A28", "#1A463C", "#2C6B5A", "#7CFFC4"),
    "gold":     ("#5E2D14", "#8A4A17", "#FDB75C", "#FFE3A6"),
    "orange":   ("#5A2412", "#8A3A17", "#FF8A3D", "#FFC07A"),
    "rose":     ("#3A202B", "#573B45", "#865C64", "#D8B7B4"),
    "purple":   ("#1D1128", "#2A173A", "#3C2350", "#58306A"),
    "blue":     ("#1B1133", "#2F1B42", "#4B2A5A", "#6B3E6B"),
    "metal":    ("#120A18", "#241321", "#3B273B", "#5A3E54"),
    "cream":    ("#8C7A58", "#C9B58B", "#FFF3D0", "#FFFBE9"),
}

INK = RAMPS["ink"][0]
WALL_DARK = RAMPS["wall"][0]
WALL_BASE = RAMPS["wall"][1]
WALL_LIGHT = RAMPS["wall"][2]
WALL_HI = RAMPS["wall"][3]
WOOD_DEEP = RAMPS["wood"][0]
WOOD_SHADE = RAMPS["wood"][1]
WOOD_MID = RAMPS["wood"][2]
WOOD_LIGHT = RAMPS["wood"][3]
DECK_DEEP = RAMPS["deck"][0]
DECK_MID = RAMPS["deck"][1]
DECK_LIGHT = RAMPS["deck"][2]
DECK_HI = RAMPS["deck"][3]
FAB_DARK = RAMPS["fabric"][0]
FAB_MID = RAMPS["fabric"][1]
FAB_LIGHT = RAMPS["fabric"][2]
MINT_DARK = RAMPS["mint"][0]
MINT_MID = RAMPS["mint"][1]
MINT_LIGHT = RAMPS["mint"][2]
MINT_GLOW = RAMPS["mint"][3]
GOLD_DARK = RAMPS["gold"][0]
GOLD_MID = RAMPS["gold"][1]
GOLD_LIGHT = RAMPS["gold"][2]
GOLD_GLOW = RAMPS["gold"][3]
ORANGE_DARK = RAMPS["orange"][0]
ORANGE_MID = RAMPS["orange"][1]
ORANGE_LIGHT = RAMPS["orange"][2]
ROSE_DARK = RAMPS["rose"][0]
ROSE_MID = RAMPS["rose"][1]
ROSE_LIGHT = RAMPS["rose"][2]
PURPLE_DARK = RAMPS["purple"][0]
PURPLE_MID = RAMPS["purple"][1]
PURPLE_LIGHT = RAMPS["purple"][2]
BLUE_DARK = RAMPS["blue"][0]
BLUE_MID = RAMPS["blue"][1]
BLUE_LIGHT = RAMPS["blue"][2]
METAL_DARK = RAMPS["metal"][0]
METAL_MID = RAMPS["metal"][1]
METAL_LIGHT = RAMPS["metal"][2]
CREAM_DARK = RAMPS["cream"][0]
CREAM_MID = RAMPS["cream"][1]
CREAM_LIGHT = RAMPS["cream"][2]

BAYER = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


class Canvas:
    """A 400x250 pixel surface with a deliberately tiny primitive set."""

    def __init__(self, width: int = GW, height: int = GH):
        self.w = width
        self.h = height
        self.img = Image.new("RGB", (width, height), WALL_BASE)
        self.d = ImageDraw.Draw(self.img)
        self.rng = random.Random(2404)

    def px(self, x: int, y: int, color: str):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.img.putpixel((int(x), int(y)), ImageColor.getrgb(color))

    def rect(self, box, fill, outline=None, width=1):
        x0, y0, x1, y1 = box
        self.d.rectangle(
            (int(x0), int(y0), int(x1), int(y1)),
            fill=fill,
            outline=outline,
            width=max(1, int(width)),
        )

    def line(self, points, fill, width=1):
        self.d.line(
            [(int(x), int(y)) for x, y in points],
            fill=fill,
            width=max(1, int(width)),
        )

    def poly(self, points, fill, outline=None, width=1):
        self.d.polygon(
            [(int(x), int(y)) for x, y in points],
            fill=fill,
            outline=outline,
            width=max(1, int(width)),
        )

    def bevel(self, box, fill, hi, lo, border=INK, thickness=1, inner=1):
        x0, y0, x1, y1 = map(int, box)
        self.rect(box, fill, outline=border, width=thickness)
        if inner:
            self.line([(x0 + thickness, y0 + thickness), (x1 - thickness, y0 + thickness)], hi)
            self.line([(x0 + thickness, y0 + thickness), (x0 + thickness, y1 - thickness)], hi)
            self.line([(x0 + thickness, y1 - thickness), (x1 - thickness, y1 - thickness)], lo)
            self.line([(x1 - thickness, y0 + thickness), (x1 - thickness, y1 - thickness)], lo)

    def checker(self, box, color, density=0.25, phase=0):
        x0, y0, x1, y1 = box
        for y in range(int(y0), int(y1)):
            for x in range(int(x0), int(x1)):
                if (BAYER[(y + phase) % 4][(x + phase) % 4] / 15.0) < density:
                    self.px(x, y, color)

    def bayer_rect(self, box, color, density=0.5, phase=0):
        x0, y0, x1, y1 = box
        for y in range(int(y0), int(y1)):
            row = BAYER[(y + phase) % 4]
            for x in range(int(x0), int(x1)):
                if row[(x + phase) % 4] / 15.0 < density:
                    self.px(x, y, color)

    def light_pool(self, cx, cy, rx, ry, color, strength=0.85, phase=0):
        cx, cy = float(cx), float(cy)
        rgb = ImageColor.getrgb(color)
        for y in range(max(0, int(cy - ry)), min(self.h, int(cy + ry) + 1)):
            dy = (y - cy) / max(1.0, ry)
            for x in range(max(0, int(cx - rx)), min(self.w, int(cx + rx) + 1)):
                dx = (x - cx) / max(1.0, rx)
                dist = min(1.0, (dx * dx + dy * dy) ** 0.5)
                if (BAYER[(y + phase) % 4][(x + phase) % 4] / 15.0) < (1.0 - dist) * strength:
                    self.img.putpixel((x, y), rgb)

    def speckle(self, x0, y0, x1, y1, colors, count=100, seed=1, step=1):
        rng = random.Random(seed)
        for _ in range(count):
            x = rng.randrange(int(x0), max(int(x0) + 1, int(x1)), step)
            y = rng.randrange(int(y0), max(int(y0) + 1, int(y1)), step)
            self.px(x, y, colors[rng.randrange(len(colors))])

    def wood_grain(self, x0, y0, x1, y1, dark, light, seed=1):
        rng = random.Random(seed)
        for y in range(int(y0) + 2, int(y1) - 1, 3):
            run = rng.randrange(5, 14)
            x = rng.randrange(int(x0) + 2, max(int(x0) + 3, int(x1) - run - 2))
            self.line([(x, y), (x + run, y)], dark)
            if y % 2 == 0:
                self.line([(x + 2, y + 1), (x + run - 2, y + 1)], light)

    def contact_shadow(self, x0, y0, x1, y1, opacity="half"):
        if opacity == "half":
            self.bayer_rect((x0, y0, x1, y1), INK, 0.55)
        else:
            self.bayer_rect((x0, y0, x1, y1), INK, 0.28)


def _leaf(c: Canvas, x: int, y: int, flip: int = 1) -> None:
    """A tiny hard-edged leaf, never anti-aliased or semi-transparent."""
    x0 = min(x, x + 3 * flip)
    x1 = max(x, x + 3 * flip)
    c.rect((x0, y, x1, y + 1), MINT_MID)
    c.px(x0 + (1 if flip > 0 else 2), y, MINT_LIGHT)
    c.px(x1 - (1 if flip > 0 else 0), y + 1, MINT_DARK)


def _vine(c: Canvas, x: int, y: int, length: int, drift: int, seed: int) -> None:
    """A stepped ivy strand with sparse leaves; stays on the pixel grid."""
    for i in range(max(1, length)):
        xx = int(round(x + math.sin(i * 0.30 + seed) * drift))
        yy = y + i
        c.px(xx, yy, MINT_DARK)
        if i % 3 == 0:
            c.px(xx + 1, yy, MINT_MID)
        if i % 6 == 2:
            side = 1 if (i // 6) % 2 == 0 else -1
            _leaf(c, xx + (3 if side > 0 else -4), yy, side)
        if i % 11 == 5:
            c.px(xx + 2, yy + 1, MINT_LIGHT)


def _build_room() -> Canvas:
    c = Canvas()
    d = c.d

    # ── Back wall ────────────────────────────────────────────────────────────
    for y in range(0, 188, 16):
        t = y / 188.0
        if t < 0.35:
            col = WALL_DARK
        elif t < 0.70:
            col = WALL_BASE
        else:
            col = WALL_LIGHT
        c.rect((0, y, GW - 1, y + 15), col)
    # Big quiet upper-left wall for the live greeting.
    c.bayer_rect((0, 20, 126, 86), WALL_DARK, 0.18)
    # Sparse wallpaper texture.
    for y in range(28, 166, 14):
        for x in range(10, 390, 18):
            if x < 130 and y < 94:
                continue
            if (x + y) % 5 != 0:
                c.px(x, y, WALL_HI)
            if (x + y) % 7 == 0:
                c.px(x + 2, y + 1, WALL_LIGHT)
    # Vertical seams.
    for x in (0, 56, 112, 272, 330, 388):
        c.line([(x, 0), (x, 186)], INK)
        c.line([(x + 1, 0), (x + 1, 186)], WALL_DARK)
    # Dark vignette.
    c.checker((0, 20, 18, 188), INK, 0.65)
    c.checker((382, 20, 400, 188), INK, 0.65)

    # ── Wainscoting and floor ────────────────────────────────────────────────
    c.rect((0, 164, 399, 185), WALL_LIGHT)
    c.line([(0, 163), (399, 163)], INK)
    c.line([(0, 164), (399, 164)], WALL_HI)
    c.line([(0, 184), (399, 184)], INK)
    for x in range(4, 400, 52):
        c.bevel((x, 169, x + 44, 181), WALL_BASE, WALL_HI, WALL_DARK, INK, 1, 1)
        c.line([(x + 6, 174), (x + 38, 174)], WALL_LIGHT)
    # floor
    c.rect((0, 185, 399, 249), "#2B172E")
    for row, (y0, y1, base) in enumerate((
        (185, 198, "#2B172E"),
        (198, 214, "#321A31"),
        (214, 232, "#3A1E38"),
        (232, 249, "#43233F"),
    )):
        c.rect((0, y0, 399, y1), base)
        c.line([(0, y0), (399, y0)], "#1C0F22")
        c.line([(0, y0 + 1), (399, y0 + 1)], "#4A2A3F")
        for x in range((row * 53) % 72 - 72, 400, 72):
            c.line([(x, y0 + 2), (x, y1 - 1)], "#1D0F21")
            c.px(x + 1, y0 + 5, "#4B2A40")
        for x in range(12 + row * 17, 400, 61):
            c.line([(x, y0 + 5), (x + 13, y0 + 5)], "#1E1124")
            c.line([(x + 2, y0 + 6), (x + 10, y0 + 6)], "#522D46")
    c.speckle(0, 186, 400, 250, ("#1B0D1F", "#4A2840", "#32182F"), 150, 7)

    # ── Three light sources: window, CRT, lamp ────────────────────────────────
    c.light_pool(200, 96, 98, 70, ORANGE_DARK, 0.22, 0)
    c.light_pool(204, 120, 84, 48, GOLD_DARK, 0.10, 2)
    c.light_pool(68, 118, 52, 50, MINT_MID, 0.32, 1)
    c.light_pool(276, 124, 38, 88, GOLD_MID, 0.34, 2)
    c.light_pool(276, 190, 34, 20, GOLD_MID, 0.22, 3)
    c.light_pool(276, 72, 24, 22, GOLD_MID, 0.16, 1)

    # ── City window ──────────────────────────────────────────────────────────
    c.contact_shadow(122, 130, 277, 136, "half")
    c.bevel((123, 30, 277, 136), WOOD_MID, WOOD_LIGHT, WOOD_DEEP, INK, 1, 1)
    c.bevel((128, 35, 272, 131), WOOD_DEEP, WOOD_LIGHT, "#241015", INK, 1, 1)
    # curtains behind frame
    for x0, dark in ((119, FAB_MID), (269, FAB_MID)):
        c.rect((x0, 33, x0 + 9, 130), dark)
        for fx in range(x0 + 1, x0 + 9, 3):
            c.line([(fx, 34), (fx, 129)], FAB_DARK)
            c.px(fx + 1, 40, FAB_LIGHT)
        c.rect((x0 - 1, 91, x0 + 10, 95), GOLD_MID)
        c.line([(x0 - 1, 91), (x0 + 10, 91)], GOLD_LIGHT)
    # Sunset sky: hard bands plus Bayer transitions, a low sun, and warm
    # cloud ribbons. This is the room's main light source.
    c.rect((132, 39, 265, 126), PURPLE_DARK)
    bands = (
        (39, 54, PURPLE_DARK, PURPLE_MID, 0.16),
        (54, 68, PURPLE_MID, MAGENTA, 0.22),
        (68, 80, MAGENTA, ORANGE_MID, 0.24),
        (80, 92, ORANGE_MID, ORANGE_LIGHT, 0.30),
        (92, 104, ORANGE_LIGHT, GOLD_LIGHT, 0.32),
        (104, 116, GOLD_MID, ORANGE_MID, 0.26),
        (116, 126, ORANGE_DARK, PURPLE_DARK, 0.20),
    )
    for y0, y1, base, warm, density in bands:
        c.rect((132, y0, 265, y1 - 1), base)
        c.bayer_rect((132, y0, 265, y1), warm, density, y0)
    # A low sun just above the skyline, with a stepped halo.
    sun_cx, sun_cy, sun_r = 200, 92, 8
    for y in range(sun_cy - sun_r - 5, sun_cy + sun_r + 6):
        for x in range(sun_cx - sun_r - 7, sun_cx + sun_r + 8):
            dx = (x - sun_cx) / float(sun_r)
            dy = (y - sun_cy) / float(sun_r)
            dist = dx * dx + dy * dy
            if dist <= 1.0:
                c.px(x, y, CREAM_LIGHT if dist < 0.55 else GOLD_GLOW)
            elif dist <= 2.4 and BAYER[(y + 1) % 4][(x + 2) % 4] / 15.0 < 0.38:
                c.px(x, y, GOLD_LIGHT if dist < 1.8 else ORANGE_LIGHT)
    # Cloud ribbons, broken so the sun reads through them.
    for cy, col, hi in ((66, MAGENTA, ROSE_MID), (71, FAB_MID, ORANGE_MID),
                        (77, MAGENTA, ORANGE_LIGHT), (101, ORANGE_MID, GOLD_LIGHT)):
        start = 134 + ((cy * 7) % 12)
        for x in range(start, 264, 3):
            line_len = 2 + (x % 5)
            if (x + cy) % 11 < 7:
                c.line([(x, cy), (x + line_len, cy)], col)
                if (x + cy) % 5 == 0:
                    c.px(x + line_len, cy - 1, hi)
    # A few birds or heat sparks, kept sparse.
    for bx, by in ((158, 67), (166, 65), (236, 70)):
        c.px(bx, by, INK)
        c.px(bx + 1, by - 1, INK)
        c.px(bx + 2, by, INK)
    c.px(141, 48, CREAM_MID)
    c.px(198, 51, GOLD_LIGHT)
    # layered skyline
    far = ((134, 102, 146, 126), (148, 96, 158, 126), (160, 106, 174, 126),
           (176, 92, 188, 126), (190, 100, 200, 126), (202, 108, 216, 126),
           (218, 94, 232, 126), (234, 102, 248, 126), (250, 98, 264, 126))
    mid = ((134, 111, 149, 126), (152, 105, 166, 126), (170, 116, 184, 126),
           (188, 108, 202, 126), (206, 114, 222, 126), (226, 105, 242, 126),
           (246, 111, 264, 126))
    near = ((132, 118, 150, 126), (154, 114, 174, 126), (178, 120, 196, 126),
            (200, 113, 220, 126), (224, 119, 242, 126), (246, 115, 264, 126))
    for x0, y0, x1, y1 in far:
        c.rect((x0, y0, x1, y1), PURPLE_MID)
        c.line([(x0, y0), (x1, y0)], MAGENTA)
        c.px(x0, y0 + 2, ROSE_MID)
    for x0, y0, x1, y1 in mid:
        c.rect((x0, y0, x1, y1), FAB_DARK)
        c.line([(x0, y0), (x1, y0)], ORANGE_MID)
        c.px(x0, y0 + 2, MAGENTA)
    for x0, y0, x1, y1 in near:
        c.rect((x0, y0, x1, y1), INK)
        c.line([(x0, y0), (x1, y0)], PURPLE_DARK)
        c.px(x0, y0 + 2, PURPLE_MID)
    rng = random.Random(915)
    for x0, y0, x1, y1 in far + mid + near:
        for yy in range(y0 + 3, min(y1, 124), 7):
            for xx in range(x0 + 3, x1 - 2, 6):
                if rng.random() < 0.32:
                    c.px(xx, yy, GOLD_LIGHT if rng.random() < 0.6 else MINT_LIGHT)
    # antenna / water tower
    c.line([(186, 92), (186, 84)], INK)
    c.line([(183, 84), (189, 84)], INK)
    c.rect((158, 86, 164, 96), PURPLE_MID)
    c.rect((156, 83, 166, 87), PURPLE_LIGHT)
    # rain streaks
    rain = random.Random(77)
    for _ in range(34):
        x = rain.randrange(135, 264)
        y = rain.randrange(42, 123)
        length = rain.choice((2, 3, 4))
        roll = rain.random()
        col = GOLD_LIGHT if roll < 0.45 else (ROSE_LIGHT if roll < 0.82 else MINT_MID)
        for i in range(length):
            c.px(x - i // 2, y + i, col)
    # window mullions
    for x in (174, 220):
        c.rect((x, 38, x + 2, 130), WOOD_MID)
        c.line([(x, 38), (x, 130)], WOOD_LIGHT)
        c.line([(x + 2, 38), (x + 2, 130)], WOOD_DEEP)
    c.rect((132, 80, 265, 82), WOOD_MID)
    c.line([(132, 80), (265, 80)], WOOD_LIGHT)
    # glass glints
    c.line([(137, 76), (147, 66)], GOLD_GLOW)
    c.line([(142, 76), (149, 69)], CREAM_MID)
    c.line([(246, 118), (258, 106)], ROSE_LIGHT)
    # sill
    c.bevel((119, 127, 280, 137), WOOD_MID, WOOD_LIGHT, WOOD_DEEP, INK, 1, 1)
    c.line([(124, 131), (275, 131)], GOLD_DARK)
    c.line([(124, 134), (275, 134)], WOOD_DEEP)
    # sill props: plant, cassette, candle
    c.contact_shadow(133, 127, 147, 130, "half")
    c.rect((134, 123, 145, 128), ORANGE_MID)
    c.rect((133, 121, 146, 124), ORANGE_LIGHT)
    c.line([(138, 121), (138, 116)], MINT_MID)
    c.line([(138, 118), (134, 114)], MINT_MID)
    c.line([(138, 117), (142, 112)], MINT_MID)
    for bx, by in ((132, 112), (136, 108), (140, 111), (143, 114), (134, 115)):
        c.rect((bx, by, bx + 3, by + 3), MINT_LIGHT)
        c.px(bx + 1, by + 1, MINT_GLOW)
    c.contact_shadow(188, 127, 202, 130, "half")
    c.rect((188, 124, 202, 129), PURPLE_MID)
    c.line([(189, 125), (201, 125)], GOLD_MID)
    c.px(193, 127, CREAM_MID)
    c.px(198, 127, CREAM_MID)
    c.contact_shadow(244, 126, 252, 130, "half")
    c.rect((244, 119, 252, 129), METAL_MID)
    c.rect((246, 121, 250, 127), CREAM_MID)
    c.px(247, 123, GOLD_LIGHT)
    c.line([(248, 118), (248, 115)], INK)

    # ── Left CRT game station ────────────────────────────────────────────────
    c.contact_shadow(28, 178, 122, 186, "half")
    # desk
    c.bevel((24, 144, 122, 153), WOOD_MID, WOOD_LIGHT, WOOD_DEEP, INK, 1, 1)
    c.line([(29, 147), (117, 147)], WOOD_LIGHT)
    c.line([(29, 151), (117, 151)], WOOD_DEEP)
    for lx in (31, 109):
        c.bevel((lx, 154, lx + 6, 183), WOOD_SHADE, WOOD_MID, WOOD_DEEP, INK, 1, 1)
        c.line([(lx + 2, 157), (lx + 2, 180)], WOOD_DEEP)
    # under-desk shelf
    c.bevel((38, 158, 108, 177), METAL_DARK, METAL_LIGHT, INK, INK, 1, 1)
    c.bevel((47, 164, 78, 175), METAL_MID, METAL_LIGHT, METAL_DARK, INK, 1, 1)
    c.rect((53, 167, 65, 172), MINT_DARK)
    c.rect((55, 168, 63, 171), MINT_LIGHT)
    c.px(72, 167, ORANGE_LIGHT)
    c.px(72, 171, ROSE_LIGHT)
    for gx, gc in ((83, MAGENTA), (89, GOLD_MID), (95, MINT_MID)):
        c.rect((gx, 162, gx + 4, 174), INK)
        c.rect((gx + 1, 163, gx + 3, 170), gc)
    # cables
    c.line([(67, 177), (62, 184), (71, 189), (64, 194)], INK, 2)
    c.line([(68, 177), (63, 184), (72, 189), (65, 194)], METAL_LIGHT)
    # CRT
    c.bevel((32, 86, 108, 146), METAL_MID, METAL_LIGHT, METAL_DARK, INK, 1, 1)
    c.bevel((37, 91, 103, 140), INK, METAL_LIGHT, INK, INK, 1, 1)
    c.rect((40, 94, 100, 133), MINT_DARK)
    # screen gradient + scanlines
    for y in range(95, 133, 3):
        c.rect((40, y, 100, y + 2), MINT_MID)
        c.line([(41, y + 2), (99, y + 2)], MINT_DARK)
    c.bayer_rect((40, 94, 100, 110), MINT_LIGHT, 0.10)
    # screen city / hills
    c.rect((44, 114, 97, 124), "#173B35")
    for x0, w in ((46, 8), (56, 6), (66, 10), (78, 7), (88, 6)):
        c.rect((x0, 108 + (x0 % 3) * 2, x0 + w, 124), MINT_DARK)
        c.rect((x0 + 1, 106 + (x0 % 3) * 2, x0 + w - 1, 110), MINT_MID)
        for wy in range(112, 123, 3):
            for wx in range(x0 + 2, x0 + w - 1, 3):
                c.px(wx, wy, GOLD_LIGHT if (wx + wy) % 5 else MINT_GLOW)
    # tiny platformer character / equalizer
    c.rect((70, 120, 74, 124), ROSE_LIGHT)
    c.rect((71, 117, 73, 120), CREAM_LIGHT)
    c.px(72, 118, INK)
    c.rect((45, 96, 56, 98), MINT_LIGHT)
    c.rect((52, 92, 62, 94), MINT_DARK)
    # scanline roll
    c.line([(41, 101), (99, 101)], MINT_GLOW)
    c.line([(41, 126), (99, 126)], MINT_DARK)
    # glass highlight (curved corner implied by stepped pixels)
    c.line([(43, 99), (50, 95), (54, 95)], MINT_GLOW)
    c.line([(44, 101), (49, 98)], MINT_LIGHT)
    # bezel hardware
    c.rect((37, 137, 99, 140), METAL_DARK)
    c.px(41, 138, MINT_LIGHT)
    c.px(45, 138, ROSE_MID)
    c.rect((50, 138, 76, 139), WOOD_DEEP)
    for bx in range(82, 96, 4):
        c.px(bx, 138, METAL_LIGHT)
    # controller on desk
    c.bevel((82, 137, 100, 143), METAL_MID, METAL_LIGHT, METAL_DARK, INK, 1, 1)
    c.rect((85, 139, 90, 141), ORANGE_LIGHT)
    c.rect((94, 139, 98, 141), CREAM_MID)
    c.rect((90, 141, 94, 142), INK)
    # mint glow pool from CRT
    c.bayer_rect((30, 92, 116, 150), MINT_DARK, 0.09, 1)
    c.bayer_rect((90, 100, 124, 142), MINT_DARK, 0.07, 2)

    # ── Tall plant between CRT and window ────────────────────────────────────
    c.contact_shadow(106, 145, 128, 150, "half")
    c.rect((112, 132, 124, 146), ORANGE_MID)
    c.rect((111, 130, 125, 134), ORANGE_LIGHT)
    c.line([(118, 130), (116, 119), (111, 111)], MINT_MID, 2)
    c.line([(118, 124), (123, 114), (126, 109)], MINT_MID, 2)
    c.line([(117, 121), (111, 119), (106, 115)], MINT_MID)
    for bx, by, bw, bh in ((105, 108, 7, 5), (110, 104, 8, 6), (114, 110, 6, 5),
                           (120, 104, 6, 8), (123, 110, 5, 6), (108, 116, 6, 4)):
        c.rect((bx, by, bx + bw, by + bh), MINT_LIGHT)
        c.line([(bx + 1, by + 1), (bx + bw - 1, by + 1)], MINT_GLOW)
        c.line([(bx + 1, by + bh - 1), (bx + bw - 2, by + bh - 1)], MINT_MID)
    # dark lower leaves
    for bx, by in ((107, 112), (118, 111), (121, 115)):
        c.rect((bx, by, bx + 4, by + 3), MINT_MID)
        c.px(bx + 1, by + 1, MINT_LIGHT)

    # ── Right game shelf ─────────────────────────────────────────────────────
    c.contact_shadow(286, 99, 380, 106, "half")
    c.bevel((285, 38, 380, 103), WOOD_MID, WOOD_LIGHT, WOOD_DEEP, INK, 1, 1)
    c.rect((289, 42, 376, 96), WALL_DARK)
    c.line([(289, 66), (376, 66)], WOOD_DARK)
    c.line([(289, 92), (376, 92)], WOOD_DARK)
    # cases upper shelf
    cases = (
        (291, 49, 5, 15, MINT_MID, MINT_LIGHT),
        (297, 46, 7, 18, GOLD_MID, GOLD_LIGHT),
        (305, 52, 5, 12, MAGENTA, ROSE_LIGHT),
        (311, 44, 7, 20, ORANGE_MID, ORANGE_LIGHT),
        (319, 50, 5, 14, CREAM_LIGHT, CREAM_LIGHT),
        (325, 47, 8, 17, PURPLE_LIGHT, FAB_LIGHT),
        (334, 53, 5, 11, MINT_MID, MINT_GLOW),
        (340, 45, 6, 19, GOLD_MID, CREAM_MID),
    )
    for x, y, w, h, col, hi in cases:
        c.rect((x, y, x + w, y + h), col)
        c.line([(x, y), (x + w, y)], hi)
        c.line([(x + 1, y + 3), (x + w - 1, y + 3)], INK)
        c.line([(x + 1, y + 7), (x + w - 2, y + 7)], INK)
        c.px(x + w // 2, y + h - 3, INK)
    # tiny boombox
    c.bevel((348, 52, 372, 65), METAL_MID, METAL_LIGHT, METAL_DARK, INK, 1, 1)
    c.rect((351, 55, 357, 61), INK)
    c.rect((363, 55, 369, 61), INK)
    c.rect((353, 57, 355, 59), WOOD_MID)
    c.rect((365, 57, 367, 59), WOOD_MID)
    c.px(360, 62, MINT_LIGHT)
    # figurines / books lower shelf
    c.rect((292, 72, 298, 90), FAB_MID)
    c.rect((293, 69, 297, 75), ROSE_LIGHT)
    c.px(294, 72, INK)
    c.px(296, 72, INK)
    c.rect((300, 84, 316, 90), GOLD_DARK)
    c.rect((302, 82, 314, 86), MAGENTA)
    c.rect((318, 79, 324, 90), PURPLE_LIGHT)
    c.rect((326, 85, 344, 90), WOOD_DEEP)
    c.rect((328, 82, 342, 86), MINT_MID)
    c.rect((348, 77, 354, 90), CREAM_MID)
    c.rect((356, 80, 372, 90), ROSE_DARK)
    c.rect((358, 82, 370, 86), ROSE_LIGHT)
    c.line([(292, 91), (376, 91)], WOOD_LIGHT)
    # hanging headphones
    c.line([(378, 70), (384, 70), (384, 80)], METAL_LIGHT)
    c.rect((382, 80, 388, 87), METAL_MID)
    c.rect((383, 82, 387, 85), METAL_DARK)
    c.px(385, 80, GOLD_LIGHT)

    # ── Right control panel ──────────────────────────────────────────────────
    c.contact_shadow(291, 159, 374, 166, "half")
    c.bevel((290, 109, 376, 161), WOOD_MID, WOOD_LIGHT, WOOD_DEEP, INK, 1, 1)
    c.bevel((295, 114, 371, 156), METAL_DARK, METAL_LIGHT, INK, INK, 1, 1)
    # VU meters
    for vx in (300, 338):
        c.rect((vx, 118, vx + 28, 126), INK)
        for i in range(9):
            c.rect((vx + 2 + i * 3, 124 - i, vx + 3 + i * 3, 125), MINT_LIGHT if i < 6 else GOLD_LIGHT)
        c.line([(vx + 1, 126), (vx + 27, 126)], ROSE_DARK)
    # knobs
    for kx, ky, col in ((303, 136, GOLD_LIGHT), (315, 136, ORANGE_LIGHT),
                        (341, 136, MINT_LIGHT), (353, 136, GOLD_LIGHT)):
        c.rect((kx - 3, ky - 3, kx + 3, ky + 3), INK)
        c.rect((kx - 2, ky - 2, kx + 2, ky + 2), col)
        c.line([(kx, ky - 2), (kx, ky)], INK)
    # sliders / LEDs
    for sx in (326, 330, 334):
        c.line([(sx, 132), (sx, 148)], INK)
        c.rect((sx - 1, 139, sx + 1, 141), CREAM_LIGHT)
    for row in range(3):
        for col in range(3):
            c.px(299 + col * 5, 144 + row * 4, (MINT_LIGHT, GOLD_LIGHT, ROSE_LIGHT)[(row + col) % 3])
    # sticky note + cable plug
    c.rect((359, 114, 370, 122), CREAM_MID)
    c.line([(361, 116), (367, 116)], ROSE_DARK)
    c.line([(361, 119), (365, 119)], ROSE_DARK)
    c.line([(371, 146), (381, 151), (379, 161), (372, 164)], METAL_LIGHT)
    c.rect((370, 163, 374, 167), METAL_MID)

    # ── Right record crate ───────────────────────────────────────────────────
    c.contact_shadow(306, 203, 384, 211, "half")
    # records
    for i, col in enumerate((MINT_MID, GOLD_MID, MAGENTA, ORANGE_MID,
                             CREAM_MID, PURPLE_LIGHT, ROSE_MID, MINT_MID)):
        x = 312 + i * 8
        top = 164 + (i % 3)
        c.rect((x, top, x + 7, 186), col)
        c.line([(x, top), (x + 7, top)], CREAM_MID)
        c.rect((x + 2, top + 5, x + 5, top + 10), INK)
        c.px(x + 3, top + 7, col)
    c.bevel((308, 182, 384, 210), WOOD_MID, WOOD_LIGHT, WOOD_DEEP, INK, 1, 1)
    c.rect((312, 186, 380, 205), WOOD_DARK)
    for x in (312, 329, 346, 363, 380):
        c.line([(x, 186), (x, 205)], WOOD_LIGHT)
    c.line([(312, 196), (380, 196)], WOOD_MID)
    # scattered sleeve + headphones on floor
    c.rect((290, 203, 307, 213), INK)
    c.rect((292, 204, 305, 211), MAGENTA)
    c.rect((295, 205, 302, 210), PURPLE_DARK)
    c.rect((294, 207, 301, 209), MINT_LIGHT)
    c.rect((282, 205, 291, 211), GOLD_DARK)
    c.rect((283, 206, 290, 208), GOLD_LIGHT)
    c.line([(277, 204), (282, 201), (285, 204), (290, 201)], METAL_MID)
    c.rect((278, 204, 281, 207), METAL_DARK)
    c.rect((287, 204, 290, 207), METAL_DARK)

    # ── Floor lamp ───────────────────────────────────────────────────────────
    c.contact_shadow(266, 187, 286, 194, "half")
    c.line([(275, 84), (275, 187)], METAL_DARK, 2)
    c.line([(276, 84), (276, 187)], GOLD_DARK)
    c.rect((268, 185, 283, 189), METAL_MID)
    c.poly([(265, 77), (286, 77), (282, 65), (269, 65)], WOOD_MID, INK)
    c.poly([(268, 75), (283, 75), (280, 68), (271, 68)], GOLD_LIGHT, INK)
    c.poly([(270, 73), (281, 73), (279, 70), (272, 70)], GOLD_GLOW)
    c.line([(265, 77), (286, 77)], WOOD_LIGHT)
    for sx in range(268, 284, 4):
        c.line([(sx, 78), (sx, 82)], GOLD_DARK)
    c.bayer_rect((262, 78, 292, 190), GOLD_DARK, 0.045, 0)
    c.bayer_rect((266, 180, 288, 198), GOLD_DARK, 0.09, 1)

    # ── Centre: quiet listening nest, mostly under the live mascot ────────────
    c.bayer_rect((158, 156, 246, 212), INK, 0.16, 2)
    # beanbag, deliberately low-contrast behind the puppy
    c.poly([(164, 187), (171, 170), (184, 162), (220, 162), (235, 170),
            (242, 187), (236, 200), (218, 205), (183, 205), (169, 198)],
           FAB_MID, INK)
    c.poly([(171, 184), (177, 173), (188, 166), (216, 166), (230, 173),
            (236, 184), (230, 195), (215, 199), (184, 199), (175, 195)],
           FAB_LIGHT)
    c.poly([(180, 181), (188, 172), (216, 172), (228, 181), (222, 190),
            (188, 190), (176, 186)], FAB_MID, INK)
    c.line([(188, 176), (216, 176)], FAB_LIGHT)
    # cushion
    c.bevel((196, 180, 226, 195), FAB_LIGHT, RAMPS["fabric_hi"][2], FAB_DARK, INK, 1, 1)
    c.line([(200, 183), (222, 183)], RAMPS["fabric_hi"][2])
    # rug
    c.bevel((140, 194, 268, 214), FAB_DARK, RAMPS["fabric_hi"][2], PURPLE_DARK, INK, 1, 1)
    c.rect((144, 197, 264, 211), FAB_MID)
    for x in range(150, 264, 14):
        c.rect((x, 199, x + 5, 201), GOLD_DARK)
        c.rect((x + 3, 207, x + 8, 209), MINT_DARK)
    for x in range(142, 270, 5):
        c.px(x, 214, ROSE_DARK)
    # side table + record player left of the nest
    c.bevel((132, 160, 166, 188), WOOD_MID, WOOD_LIGHT, WOOD_DEEP, INK, 1, 1)
    c.rect((137, 165, 161, 183), WOOD_DARK)
    c.bevel((138, 154, 160, 165), METAL_DARK, METAL_LIGHT, INK, INK, 1, 1)
    c.rect((141, 157, 157, 163), PURPLE_DARK)
    c.rect((146, 156, 153, 164), ROSE_MID)
    c.rect((147, 158, 152, 162), ROSE_LIGHT)
    c.line([(143, 155), (143, 150), (147, 150)], GOLD_DARK)
    c.rect((146, 148, 150, 151), GOLD_LIGHT)
    # speaker + cassettes below
    c.bevel((136, 174, 150, 186), METAL_MID, METAL_LIGHT, INK, INK, 1, 1)
    for sx in range(139, 148, 3):
        c.line([(sx, 177), (sx, 183)], WOOD_DEEP)
    for i, col in enumerate((GOLD_MID, MINT_MID, MAGENTA)):
        c.rect((154 + i * 4, 178, 157 + i * 4, 186), col)
        c.px(155 + i * 4, 181, CREAM_MID)

    # ── Lived-in props (small, strong silhouettes, contact shadows) ──────────
    # Front rug edge. The live room crop ends near y=188, so this band is the
    # part of the nest that actually sits under the mascot on screen.
    c.bevel((154, 176, 256, 188), FAB_DARK, RAMPS["fabric_hi"][2], PURPLE_DARK, INK, 1, 1)
    c.rect((158, 179, 252, 186), FAB_MID)
    for x in range(162, 252, 10):
        c.rect((x, 181, x + 4, 182), GOLD_DARK)
        c.rect((x + 3, 184, x + 7, 185), MINT_DARK)
    for x in range(154, 257, 3):
        c.px(x, 187, ROSE_DARK)
    # A throw over the right arm of the nest catches the lamp light.
    c.rect((230, 168, 243, 186), ROSE_DARK)
    c.line([(231, 171), (242, 171)], GOLD_MID)
    c.line([(232, 178), (241, 178)], ROSE_LIGHT)
    c.line([(233, 184), (242, 184)], GOLD_DARK)
    c.px(238, 174, GOLD_LIGHT)
    # A little controller just right of the mascot's paws.
    c.rect((228, 179, 242, 185), METAL_DARK)
    c.rect((229, 180, 241, 184), METAL_MID)
    c.rect((231, 181, 234, 182), ROSE_MID)
    c.rect((236, 181, 239, 182), MINT_MID)
    c.px(235, 182, INK)
    c.px(240, 180, GOLD_LIGHT)
    # Floor mic stand, angled toward the mascot. Kept clear of the sprite box.
    c.contact_shadow(243, 185, 259, 189, "half")
    c.rect((244, 185, 256, 188), METAL_DARK)
    c.rect((246, 186, 254, 188), METAL_MID)
    c.line([(249, 185), (249, 153)], METAL_LIGHT)
    c.line([(250, 185), (250, 153)], METAL_DARK)
    c.line([(249, 153), (245, 147)], METAL_LIGHT)
    c.rect((241, 144, 249, 152), METAL_DARK)
    c.rect((242, 145, 248, 151), METAL_MID)
    c.rect((243, 146, 247, 150), MINT_DARK)
    c.px(245, 147, MINT_LIGHT)
    c.px(246, 149, CREAM_MID)

    # mug on the floor by the CRT
    c.contact_shadow(112, 183, 122, 186, "half")
    c.rect((112, 176, 120, 183), CREAM_MID)
    c.rect((113, 177, 119, 180), ROSE_LIGHT)
    c.rect((113, 181, 119, 183), CREAM_LIGHT)
    c.line([(121, 178), (123, 178), (123, 182), (121, 182)], INK)
    c.line([(122, 178), (124, 178), (124, 182), (122, 182)], CREAM_MID)
    # polaroids / stickers on the wall (right of greeting, left of window)
    for px, py, col in ((105, 87, ROSE_MID), (111, 85, GOLD_LIGHT), (117, 87, MINT_MID)):
        c.rect((px, py, px + 5, py + 6), CREAM_MID)
        c.rect((px + 1, py + 1, px + 4, py + 4), col)
        c.px(px + 2, py + 5, INK)
    # sticky notes on wall near shelf
    c.rect((386, 86, 392, 92), CREAM_MID)
    c.line([(387, 88), (390, 88)], ROSE_DARK)
    c.rect((388, 94, 394, 100), GOLD_LIGHT)
    c.line([(389, 96), (392, 96)], ORANGE_DARK)
    # cable run across floor
    c.line([(24, 234), (54, 230), (72, 235), (98, 228), (130, 234),
            (160, 231), (196, 238), (232, 232), (262, 236), (292, 231),
            (320, 238), (352, 232), (386, 236)], INK, 2)
    c.line([(24, 235), (54, 231), (72, 236), (98, 229), (130, 235),
            (160, 232), (196, 239), (232, 233), (262, 237), (292, 232),
            (320, 239), (352, 233), (386, 237)], METAL_LIGHT)
    # sneakers by the crate
    c.contact_shadow(286, 220, 312, 226, "half")
    for sx in (288, 300):
        c.rect((sx, 216, sx + 9, 221), CREAM_MID)
        c.rect((sx + 1, 218, sx + 8, 221), ROSE_MID)
        c.line([(sx, 221), (sx + 10, 221)], INK)
        c.px(sx + 2, 217, CREAM_LIGHT)
    # cassette stack near the plant / floor
    c.contact_shadow(104, 195, 118, 198, "half")
    for i, col in enumerate((GOLD_MID, MAGENTA, MINT_MID)):
        c.rect((104 + i, 191 + i * 3, 117 + i, 194 + i * 3), col)
        c.px(108 + i, 192 + i * 3, INK)
        c.px(113 + i, 192 + i * 3, INK)
    # game cartridge on desk
    c.rect((26, 139, 35, 145), METAL_MID)
    c.rect((28, 137, 33, 141), GOLD_LIGHT)
    c.px(30, 139, INK)
    # soda can on floor near record crate
    c.contact_shadow(374, 220, 382, 223, "half")
    c.rect((374, 214, 380, 222), ROSE_DARK)
    c.rect((375, 215, 379, 219), ROSE_LIGHT)
    c.line([(374, 215), (380, 215)], CREAM_MID)
    c.px(377, 218, INK)
    # little cable plug dangling from control panel
    c.line([(389, 162), (395, 166), (393, 173)], METAL_LIGHT)
    c.rect((391, 172, 395, 176), METAL_MID)
    c.px(393, 174, GOLD_LIGHT)
    # books stacked near floor lamp
    c.contact_shadow(252, 208, 268, 212, "half")
    for i, col in enumerate((MAGENTA, GOLD_MID, MINT_MID)):
        c.rect((253, 201 + i * 3, 267, 204 + i * 3), col)
        c.line([(254, 202 + i * 3), (264, 202 + i * 3)], CREAM_MID)

    # ── Final material / light polish ────────────────────────────────────────
    # Ivy softens the hard furniture edges and ties the window to the nest.
    _vine(c, 116, 58, 50, 3, 4)
    _vine(c, 384, 58, 48, 2, 13)
    _vine(c, 374, 66, 20, 2, 15)
    for lx, ly in ((130, 60), (134, 58), (138, 62), (257, 60), (261, 63)):
        _leaf(c, lx, ly, 1 if lx < 200 else -1)
    # Warm window spill on the wall and the top of the nest.
    c.bayer_rect((125, 128, 278, 186), GOLD_DARK, 0.035, 2)
    c.bayer_rect((132, 128, 272, 160), ORANGE_DARK, 0.03, 1)
    c.bayer_rect((306, 162, 384, 188), GOLD_DARK, 0.03, 2)
    # A low LED strip under the shelf and a warm top rim on the panel.
    for x in range(292, 376, 8):
        c.px(x, 94, GOLD_LIGHT)
        c.px(x + 2, 95, MINT_LIGHT)
        c.px(x + 1, 96, GOLD_DARK)
    c.line([(294, 110), (372, 110)], GOLD_DARK)
    c.line([(294, 111), (304, 111)], GOLD_LIGHT)
    c.line([(348, 111), (372, 111)], GOLD_LIGHT)

    # wood grain runs
    c.wood_grain(25, 145, 121, 152, WOOD_DEEP, WOOD_LIGHT, 3)
    c.wood_grain(286, 39, 379, 102, WOOD_DEEP, WOOD_LIGHT, 4)
    c.wood_grain(309, 183, 383, 209, WOOD_DEEP, WOOD_LIGHT, 5)
    c.wood_grain(124, 31, 276, 135, WOOD_SHADE, WOOD_LIGHT, 6)
    # fabric folds
    c.line([(174, 189), (182, 199)], FAB_LIGHT)
    c.line([(230, 188), (224, 201)], FAB_DARK)
    c.line([(150, 199), (164, 210)], RAMPS["fabric_hi"][2])
    c.line([(247, 199), (238, 210)], RAMPS["fabric_hi"][2])
    # Contact shadows under the big furniture.
    c.contact_shadow(34, 144, 108, 148, "half")
    c.contact_shadow(289, 103, 376, 106, "half")
    c.contact_shadow(293, 158, 372, 162, "half")
    c.contact_shadow(310, 183, 382, 186, "half")
    c.contact_shadow(132, 186, 164, 189, "half")
    # Tiny highlights on metal / glass / lamp.
    c.px(34, 88, METAL_LIGHT)
    c.px(104, 143, METAL_LIGHT)
    c.line([(269, 66), (282, 66)], GOLD_GLOW)
    c.line([(130, 37), (132, 39)], CREAM_MID)
    c.line([(263, 128), (267, 130)], BLUE_LIGHT)
    # Quiet the centre behind the mascot one last time.
    c.bayer_rect((168, 148, 236, 198), INK, 0.08, 0)
    return c


def build_room() -> Image.Image:
    logical = _build_room().img
    return logical.resize((W, H), Image.Resampling.NEAREST)


def build_dim(room: Image.Image) -> Image.Image:
    overlay = Image.new("RGB", room.size, "#120A18")
    dimmed = Image.blend(room, overlay, 0.72)
    warm = Image.new("RGB", room.size, "#3A1E26")
    mask = Image.new("L", room.size, 0)
    md = ImageDraw.Draw(mask)
    md.rectangle((480, 120, 1100, 560), fill=38)
    md.rectangle((1020, 240, 1220, 800), fill=36)
    md.rectangle((80, 320, 480, 660), fill=26)
    return Image.composite(Image.blend(dimmed, warm, 0.16), dimmed, mask)


def _safe_zone_preview(room: Image.Image, before: Image.Image) -> None:
    preview = room.copy()
    d = ImageDraw.Draw(preview, "RGBA")
    try:
        font = ImageFont.truetype(str(ROOT / "assets" / "fonts" / "Silkscreen-Bold.ttf"), 26)
    except OSError:
        font = ImageFont.load_default()
    # Logical room coordinates x4. These are the zones the live UI reserves.
    zones = (
        ((0, 30, 180, 92), (124, 255, 196, 205), "GREETING"),
        ((120, 28, 280, 140), (124, 196, 255, 205), "WINDOW"),
        ((22, 84, 124, 188), (124, 255, 196, 205), "CRT"),
        ((282, 36, 382, 106), (255, 205, 124, 205), "SHELF"),
        ((288, 107, 378, 165), (255, 205, 124, 205), "PANEL"),
        ((304, 162, 388, 216), (255, 205, 124, 205), "CRATE"),
        ((166, 128, 242, 204), (255, 124, 196, 205), "PUPPY"),
    )
    for box, color, label in zones:
        x0, y0, x1, y1 = (int(v * SCALE) for v in box)
        d.rectangle((x0, y0, x1, y1), outline=color, width=6)
        tag_w = max(94, 12 + int(d.textlength(label, font=font)))
        d.rectangle((x0 + 6, y0 + 6, x0 + 6 + tag_w, y0 + 40),
                    fill=(8, 4, 12, 220))
        d.text((x0 + 12, y0 + 12), label, font=font, fill=color)
    # The three live hotspot label anchors, shown as pixel crosshairs.
    for lx, ly in ((316, 90), (316, 150), (312, 211)):
        x, y = int(lx * SCALE), int(ly * SCALE)
        d.rectangle((x - 12, y - 2, x + 12, y + 2), fill=(255, 243, 208, 230))
        d.rectangle((x - 2, y - 12, x + 2, y + 12), fill=(255, 243, 208, 230))
    preview.save(PREVIEW_PATH, optimize=True)

    # Report strip: before, after, and after with the reserved zones.
    label_h = 44
    gap = 20
    canvas = Image.new("RGB", (room.width, room.height * 2 + gap + label_h * 2), "#120A18")
    canvas.paste(before, (0, label_h))
    canvas.paste(preview, (0, label_h * 2 + gap + room.height))
    cd = ImageDraw.Draw(canvas)
    cd.text((16, 8), "BEFORE", font=font, fill=(199, 154, 165))
    cd.text((16, label_h + room.height + gap + 8), "AFTER + SAFE ZONES",
            font=font, fill=(124, 255, 196))
    canvas.save(BEFORE_AFTER_PATH, optimize=True)


def main() -> None:
    previous = None
    backup = ROOT / "assets" / "_backup" / "room" / "den_room.png"
    for candidate in (backup, OUT_PATH):
        if candidate.exists():
            previous = Image.open(candidate).convert("RGB")
            if previous.size == (W, H):
                break
    room = build_room()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    room.save(OUT_PATH, optimize=True)
    build_dim(room).save(DIM_PATH, optimize=True)
    if previous is not None and previous.size == room.size:
        _safe_zone_preview(room, previous)
    print(f"wrote {OUT_PATH} ({room.size[0]}x{room.size[1]})")
    print(f"wrote {DIM_PATH}")
    print(f"wrote {PREVIEW_PATH}")
    print(f"wrote {BEFORE_AFTER_PATH}")


if __name__ == "__main__":
    main()
