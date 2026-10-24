"""Generate the pixel-art den background used by the main GameBeats page.

The room is drawn procedurally so it can evolve with the app and still ship as
plain PNG assets.  Everything is snapped to a small pixel grid; no photographic
or anti-aliased elements are used.

Usage (from the project root):
    py source/scripts/generate_den_room_art.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# ── Palette (mirrors source/ui/theme.py) ─────────────────────────────────────
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

# Shade steps derived from the core palette. Keeping these close to the eight
# UI colours is what makes the room read as one piece of art rather than a
# collage of unrelated sprites.
INK = "#100812"
VOID = "#160C1E"
WALL_TOP = "#1B0E27"
WALL_MID = "#24142D"
WALL_LOW = "#301A35"
WALL_PANEL = "#39203C"
WALL_PANEL_HI = "#452847"
WALL_LINE = "#170B20"

WOOD_DEEP = "#32170F"
WOOD_SHADE = "#532711"
WOOD_MID = "#7A3E0E"
WOOD_LIGHT = "#A85B1E"
WOOD_HI = "#D27B2F"

MINT_DARK = "#2C6B5A"
MINT_SHADOW = "#1A463C"
MINT_GLOW = "#B6FFE0"
GOLD_DARK = "#8A4A17"
ROSE_DARK = "#865C64"
ROSE_SHADOW = "#573B45"
PURPLE_DARK = "#2A1233"
PURPLE_MID = "#45204A"
PURPLE_LIGHT = "#632D5D"

W, H = 1600, 1000
ROOT = Path(__file__).resolve().parents[2]
FONT_PATH = ROOT / "assets" / "fonts" / "Silkscreen-Regular.ttf"
FONT_BOLD_PATH = ROOT / "assets" / "fonts" / "Silkscreen-Bold.ttf"
OUT_PATH = ROOT / "assets" / "room" / "den_room.png"
DIM_PATH = ROOT / "assets" / "room" / "den_room_dim.png"


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = _rgb(a), _rgb(b)
    return "#%02X%02X%02X" % tuple(
        int(round(ca[i] + (cb[i] - ca[i]) * t)) for i in range(3)
    )


class Canvas:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.img = Image.new("RGB", (width, height), WALL_MID)
        self.d = ImageDraw.Draw(self.img)
        self.rng = random.Random(4127)

    # ── primitives ───────────────────────────────────────────────────────────
    def rect(self, box, fill, outline=None, width=1):
        self.d.rectangle(box, fill=fill, outline=outline, width=width)

    def line(self, xy, fill, width=1):
        self.d.line(xy, fill=fill, width=width)

    def poly(self, points, fill, outline=None, width=1):
        self.d.polygon(points, fill=fill, outline=outline, width=width)

    def text(self, xy, value, size=10, fill=CREAM, bold=False):
        font_path = FONT_BOLD_PATH if bold else FONT_PATH
        try:
            font = ImageFont.truetype(str(font_path), size)
        except Exception:
            self.d.text(xy, value, fill=fill)
            return
        # Render the pixel font through a hard alpha mask so it never looks
        # blurry when the UI nearest-neighbour-scales the room.
        probe = Image.new("L", (max(1, self.width), max(1, self.height)), 0)
        ImageDraw.Draw(probe).text((0, 0), value, font=font, fill=255)
        bbox = probe.getbbox()
        if not bbox:
            return
        mask = Image.new("L", (bbox[2], bbox[3]), 0)
        ImageDraw.Draw(mask).text((-bbox[0], -bbox[1]), value, font=font, fill=255)
        mask = mask.point(lambda v: 255 if v >= 96 else 0)
        self.img.paste(fill, (int(xy[0]), int(xy[1])), mask)

    def bevel(self, box, fill, hi, lo, border=INK, thickness=3, inner=2):
        x0, y0, x1, y1 = box
        self.rect(box, fill, outline=border, width=thickness)
        self.line([(x0 + thickness, y0 + thickness), (x1 - thickness, y0 + thickness)], hi, inner)
        self.line([(x0 + thickness, y0 + thickness), (x0 + thickness, y1 - thickness)], hi, inner)
        self.line([(x0 + thickness, y1 - thickness), (x1 - thickness, y1 - thickness)], lo, inner)
        self.line([(x1 - thickness, y0 + thickness), (x1 - thickness, y1 - thickness)], lo, inner)

    def dither(self, box, color, step=8, phase=0, mask=None):
        x0, y0, x1, y1 = box
        for y in range(int(y0), int(y1), step):
            for x in range(int(x0), int(x1), step):
                if mask == "diag" and ((x // step + y // step + phase) % 2):
                    continue
                if mask == "sparse" and ((x // step * 3 + y // step * 5 + phase) % 4):
                    continue
                self.rect((x, y, min(x + 2, x1), min(y + 2, y1)), color)

    def speckle(self, box, colors, count=90, step=4, seed=0):
        x0, y0, x1, y1 = box
        rng = random.Random(seed or self.rng.randrange(1 << 30))
        for _ in range(count):
            x = rng.randrange(int(x0), max(int(x0) + 1, int(x1)), step)
            y = rng.randrange(int(y0), max(int(y0) + 1, int(y1)), step)
            c = colors[rng.randrange(len(colors))]
            self.rect((x, y, x + 2, y + 2), c)

    def wood_plank(self, box, fill, hi, lo, grain=None):
        x0, y0, x1, y1 = box
        self.rect(box, fill, outline=INK, width=2)
        self.line([(x0 + 2, y0 + 2), (x1 - 2, y0 + 2)], hi, 2)
        self.line([(x0 + 2, y1 - 2), (x1 - 2, y1 - 2)], lo, 2)
        if grain:
            for y in range(y0 + 6, y1 - 3, 8):
                x = x0 + 8 + ((y * 17) % max(8, (x1 - x0) // 2))
                self.line([(x, y), (min(x + 24, x1 - 8), y)], grain, 1)


def build_room() -> Image.Image:
    c = Canvas(W, H)
    d = c.d

    # ── Back wall with a soft, banded gradient and panelled texture ─────────
    for y in range(0, 740, 8):
        t = min(1.0, y / 740.0)
        col = _mix(WALL_TOP, WALL_LOW, t)
        d.rectangle((0, y, W, y + 7), fill=col)
    # Broad vertical wall panels.
    for x in (0, 190, 390, 540, 1080, 1260, 1440):
        d.rectangle((x, 0, x + 3, 730), fill=WALL_LINE)
        d.rectangle((x + 3, 0, x + 6, 730), fill=_mix(WALL_MID, WALL_PANEL, 0.35))
    # Subtle wallpaper motif: tiny diamonds / dots, kept out of the reading
    # zone on the upper left so the greeting stays crisp.
    for y in range(198, 690, 30):
        for x in range(24, 1580, 38):
            if x < 560 and y < 330:
                continue
            if (x // 38 + y // 30) % 3 == 0:
                c.rect((x, y, x + 2, y + 2), WALL_PANEL)
                c.rect((x + 4, y + 5, x + 5, y + 6), _mix(WALL_MID, WALL_PANEL, 0.5))
    # Darker vignette toward the edges.
    c.dither((0, 180, 46, 740), VOID, 8, 0)
    c.dither((1554, 180, 1600, 740), VOID, 8, 1)
    c.dither((0, 0, 1600, 40), VOID, 8, 0)

    # Wainscoting / lower wall panelling.
    d.rectangle((0, 606, W, 738), fill=WALL_PANEL)
    for y in (612, 688, 714, 732):
        d.rectangle((0, y, W, y + 3), fill=WALL_LINE)
        d.rectangle((0, y + 3, W, y + 5), fill=WALL_PANEL_HI)
    for x in range(22, 1600, 132):
        c.bevel((x, 622, x + 110, 706), _mix(WALL_PANEL, WALL_MID, 0.25),
                WALL_PANEL_HI, WALL_LINE, INK, 2, 1)
        c.line([(x + 14, 637), (x + 96, 637)], _mix(WALL_PANEL, WALL_PANEL_HI, 0.5), 1)

    # ── Floorboards ─────────────────────────────────────────────────────────
    d.rectangle((0, 738, W, H), fill="#2B172E")
    floor_rows = [(738, 772), (772, 812), (812, 862), (862, 918), (918, 1000)]
    for idx, (y0, y1) in enumerate(floor_rows):
        base = _mix("#2B172E", "#412238", 0.11 * idx)
        d.rectangle((0, y0, W, y1), fill=base)
        d.rectangle((0, y0, W, y0 + 3), fill="#4A2A3F")
        d.rectangle((0, y1 - 3, W, y1), fill="#1E1022")
        # Staggered board seams + little highlight ticks.
        offset = (idx * 211) % 320
        for x in range(-offset, W, 320):
            d.rectangle((x, y0 + 3, x + 4, y1 - 3), fill="#1D0F21")
            d.rectangle((x + 4, y0 + 3, x + 6, y1 - 3), fill="#4B2A40")
        for x in range(40 + idx * 73, W, 150):
            c.line([(x, y0 + 15), (x + 56, y0 + 15)], "#1E1124", 2)
            c.line([(x + 8, y0 + 16), (x + 48, y0 + 16)], "#522D46", 1)
    # Grain and scuffs.
    c.speckle((0, 750, 1600, 1000), ("#1C0E20", "#4B2940", "#3A1D33"), 200, 4, 21)

    # Soft pools of light from the window and floor lamp.
    c.dither((500, 520, 1090, 850), "#3B243D", 10, 0, "sparse")
    c.dither((1010, 470, 1230, 840), "#5A3A30", 12, 0, "sparse")

    # ── City window ─────────────────────────────────────────────────────────
    # Wall glow / shadow around the frame.
    c.dither((470, 136, 1120, 560), "#3A1F43", 12, 0, "sparse")
    c.dither((490, 150, 1098, 532), "#5A3826", 10, 1, "sparse")

    # Curtains sit behind the wooden frame.
    for side, x0 in (("left", 484), ("right", 1050)):
        x1 = x0 + 45
        d.rectangle((x0, 148, x1, 510), fill=MAGENTA, outline=INK, width=3)
        for fx in range(x0 + 4, x1 - 3, 9):
            d.rectangle((fx, 152, fx + 3, 506), fill=_mix(MAGENTA, PURPLE_DARK, 0.44))
            d.rectangle((fx + 3, 152, fx + 5, 506), fill=_mix(MAGENTA, PURPLE_LIGHT, 0.28))
        # gold tie-back
        d.rectangle((x0 - 4, 382, x1 + 4, 396), fill=GOLD_DARK)
        d.rectangle((x0 - 4, 382, x1 + 4, 388), fill=GOLD)
        d.rectangle((x0 + 12, 389, x1 - 8, 394), fill=ORANGE)

    # Frame body.
    c.bevel((500, 150, 1080, 530), WOOD_MID, WOOD_HI, WOOD_DEEP, INK, 4, 3)
    c.bevel((520, 170, 1060, 510), WOOD_DEEP, WOOD_LIGHT, "#241015", INK, 3, 2)
    # Sill.
    c.bevel((458, 505, 1120, 544), WOOD_MID, WOOD_HI, WOOD_DEEP, INK, 3, 3)
    d.rectangle((470, 512, 1108, 518), fill=GOLD_DARK)
    d.rectangle((470, 518, 1108, 526), fill=WOOD_MID)
    d.rectangle((470, 526, 1108, 535), fill=WOOD_DEEP)
    for x in range(492, 1100, 96):
        d.rectangle((x, 534, x + 6, 544), fill=INK)

    # Night sky.
    d.rectangle((540, 190, 1040, 500), fill="#1D1236")
    for y in range(190, 500, 24):
        t = (y - 190) / 310.0
        d.rectangle((540, y, 1040, y + 23), fill=_mix("#1B1133", "#2F1B42", t))
    # Window glow near the horizon.
    c.dither((540, 360, 1040, 500), "#5E2C43", 10, 0, "sparse")

    # Stars (2/3 px crosses) and a big cream moon.
    stars = [
        (580, 225, 4), (640, 268, 3), (705, 212, 4), (760, 250, 3),
        (820, 220, 4), (882, 260, 3), (935, 230, 4), (1008, 274, 3),
        (610, 315, 3), (730, 330, 3), (864, 314, 4), (1000, 320, 3),
        (672, 370, 3), (790, 382, 3), (918, 370, 3),
    ]
    for sx, sy, size in stars:
        col = MINT if (sx + sy) % 3 == 0 else CREAM
        c.rect((sx - size, sy, sx + size + 1, sy + 2), col)
        c.rect((sx - 1, sy - size, sx + 2, sy + size + 1), col)
    # Moon.
    d.rectangle((976, 222, 1008, 254), fill=CREAM)
    d.rectangle((970, 228, 1014, 248), fill=CREAM)
    d.rectangle((982, 216, 1002, 260), fill=CREAM)
    d.rectangle((984, 236, 1002, 250), fill="#E8D9B6")
    d.rectangle((992, 224, 1006, 232), fill="#E8D9B6")
    c.dither((958, 208, 1026, 276), "#FFF3D0", 12, 0, "sparse")

    # Skyline. Solid silhouettes with tiny lit windows.
    skyline = [
        (542, 438, 568, 500, "#2B193C"), (570, 414, 600, 500, "#25152F"),
        (602, 448, 622, 500, "#341D43"), (624, 390, 660, 500, "#2A173A"),
        (662, 430, 690, 500, "#241430"), (692, 404, 720, 500, "#2E193D"),
        (722, 454, 744, 500, "#281636"), (746, 420, 782, 500, "#341B43"),
        (784, 382, 812, 500, "#281537"), (814, 438, 838, 500, "#301A3E"),
        (840, 410, 874, 500, "#241431"), (876, 448, 902, 500, "#341D42"),
        (904, 400, 936, 500, "#281638"), (938, 430, 966, 500, "#2D193B"),
        (968, 452, 996, 500, "#24142F"), (998, 418, 1038, 500, "#301A40"),
    ]
    for x0, y0, x1, y1, col in skyline:
        d.rectangle((x0, y0, x1, y1), fill=col)
        d.rectangle((x0, y0, x1, y0 + 3), fill=_mix(col, "#5A3552", 0.5))
    # Antenna, water tower and bridge silhouette.
    c.line([(800, 382), (800, 344)], INK, 3)
    c.line([(788, 344), (812, 344)], INK, 2)
    d.rectangle((632, 350, 656, 390), fill="#25152F")
    d.rectangle((626, 342, 662, 352), fill="#351D43")
    c.line([(640, 390), (628, 412), (652, 390), (664, 412)], INK, 2)
    c.line([(542, 480), (1038, 480)], "#3B2248", 3)
    c.line([(590, 480), (590, 468), (640, 468)], "#3B2248", 2)
    # Lit windows.
    rng = random.Random(88)
    lit = (GOLD, ORANGE, MINT, "#E8C27C")
    for x0, y0, x1, y1, col in skyline:
        for yy in range(y0 + 12, min(y1 - 4, 488), 14):
            for xx in range(x0 + 8, x1 - 5, 12):
                if rng.random() < 0.34:
                    d.rectangle((xx, yy, xx + 3, yy + 4), fill=lit[rng.randrange(len(lit))])
    # A couple of tiny skyline details.
    d.rectangle((580, 386, 600, 402), fill="#3B2048")
    d.rectangle((936, 365, 952, 388), fill="#3B2048")

    # Window mullions and inner bevel.
    for x in (700, 860):
        d.rectangle((x, 182, x + 9, 505), fill=WOOD_MID, outline=INK, width=2)
        d.rectangle((x + 2, 184, x + 4, 503), fill=WOOD_HI)
        d.rectangle((x + 7, 184, x + 9, 503), fill=WOOD_DEEP)
    d.rectangle((540, 342, 1040, 351), fill=WOOD_MID, outline=INK, width=2)
    d.rectangle((540, 344, 1040, 346), fill=WOOD_HI)
    # Glass corner glints.
    c.line([(548, 386), (576, 358)], "#B6A6C1", 2)
    c.line([(596, 386), (624, 358)], "#8C7898", 2)
    c.line([(1000, 206), (1028, 234)], "#8C7898", 2)

    # Sill clutter.
    c.bevel((536, 462, 584, 506), "#9A4A2C", "#D27A45", "#4A231B", INK, 2, 2)
    d.rectangle((528, 456, 592, 468), fill="#C66A3B", outline=INK, width=2)
    d.rectangle((532, 458, 588, 461), fill="#E18B4E")
    # plant
    c.line([(560, 456), (558, 426), (548, 410)], MINT_DARK, 3)
    c.line([(560, 442), (570, 426), (582, 414)], MINT_DARK, 3)
    for bx, by, bw, bh in ((538, 402, 16, 13), (546, 390, 16, 14), (558, 410, 18, 14),
                           (566, 394, 13, 24), (574, 406, 16, 16), (542, 420, 16, 12)):
        d.rectangle((bx, by, bx + bw, by + bh), fill=MINT, outline=MINT_SHADOW, width=2)
        d.rectangle((bx + 3, by + 3, bx + bw - 4, by + 5), fill=MINT_GLOW)
    # cassette + candle jar
    c.bevel((742, 482, 802, 507), "#2B1832", "#5A3552", "#180C1E", INK, 2, 1)
    d.rectangle((750, 489, 794, 493), fill=GOLD_DARK)
    d.rectangle((752, 495, 758, 501), fill=CREAM)
    d.rectangle((786, 495, 792, 501), fill=CREAM)
    c.bevel((996, 454, 1040, 508), "#3A2730", "#71545C", "#1C1018", INK, 2, 1)
    d.rectangle((1000, 470, 1036, 506), fill="#C68B4A")
    d.rectangle((1002, 474, 1034, 480), fill="#E9B160")
    c.line([(1018, 466), (1018, 458)], INK, 2)
    d.rectangle((1015, 454, 1021, 468), fill=GOLD)
    # little figurine
    d.rectangle((866, 472, 890, 505), fill="#3B2550", outline=INK, width=2)
    d.rectangle((872, 462, 884, 476), fill=ROSE, outline=INK, width=2)
    d.rectangle((875, 467, 878, 470), fill=INK)
    d.rectangle((881, 467, 884, 470), fill=INK)

    # ── Left: CRT game station ──────────────────────────────────────────────
    # Keep the upper-left wall quiet: the live greeting is drawn there by the
    # UI, and a poster behind it made the copy hard to read.

    # Screen glow behind the television.
    c.dither((92, 342, 456, 650), "#234D49", 10, 1, "sparse")
    # Desk.
    c.bevel((80, 588, 456, 632), WOOD_MID, WOOD_HI, WOOD_DEEP, INK, 3, 3)
    d.rectangle((94, 596, 442, 603), fill=WOOD_LIGHT)
    d.rectangle((94, 620, 442, 628), fill=WOOD_DEEP)
    for lx in (110, 404):
        c.bevel((lx, 632, lx + 30, 706), WOOD_SHADE, WOOD_MID, WOOD_DEEP, INK, 3, 2)
        d.rectangle((lx + 5, 638, lx + 9, 698), fill=WOOD_DEEP)
    # Lower shelf / console.
    c.bevel((112, 640, 416, 704), "#251522", "#4D2A40", "#130A18", INK, 3, 2)
    c.bevel((146, 660, 292, 696), "#292033", "#5A3552", "#170D1E", INK, 2, 2)
    d.rectangle((158, 668, 198, 688), fill=MINT_DARK, outline=INK, width=2)
    d.rectangle((164, 674, 192, 682), fill=MINT)
    d.rectangle((260, 670, 270, 676), fill=ORANGE)
    d.rectangle((260, 682, 270, 688), fill=ROSE)
    for gx, gc in ((306, MAGENTA), (328, GOLD), (350, MINT)):
        c.bevel((gx, 654, gx + 18, 694), "#1D1124", "#4A2A40", "#0F0813", INK, 2, 1)
        d.rectangle((gx + 4, 660, gx + 14, 676), fill=gc)
        d.rectangle((gx + 5, 662, gx + 13, 664), fill=CREAM)
    # Cables.
    c.line([(182, 696), (164, 724), (196, 742), (178, 762)], INK, 3)
    c.line([(183, 696), (165, 724), (197, 742), (179, 762)], "#4A2A40", 1)

    # CRT case and screen.
    c.bevel((116, 362, 414, 604), "#2A1726", "#5A3045", "#140A17", INK, 4, 3)
    c.bevel((136, 382, 392, 568), "#1A0E1B", "#44273D", "#0E0710", INK, 3, 2)
    # Mint screen with a tiny platformer scene.
    d.rectangle((152, 398, 376, 548), fill="#255B54")
    d.rectangle((156, 402, 372, 544), fill="#2E7568")
    for yy in range(402, 544, 20):
        d.rectangle((156, yy, 372, yy + 9), fill="#28675E")
    c.dither((156, 402, 372, 460), MINT_DARK, 10, 0, "sparse")
    # clouds / distant hills
    for x0, y0, w, h in ((180, 426, 44, 12), (318, 414, 34, 10), (286, 440, 26, 8)):
        d.rectangle((x0, y0 + 4, x0 + w, y0 + h), fill="#8FE6CF")
        d.rectangle((x0 + 8, y0, x0 + w - 8, y0 + 8), fill="#B9F7E3")
    # city blocks
    d.rectangle((166, 486, 362, 514), fill="#173B3B")
    d.rectangle((178, 468, 214, 514), fill="#1E4A47")
    d.rectangle((234, 478, 272, 514), fill="#1E4A47")
    d.rectangle((292, 460, 338, 514), fill="#173B3B")
    for wx in range(184, 360, 18):
        if wx % 36 == 4:
            d.rectangle((wx, 472, wx + 6, 480), fill=GOLD)
        else:
            d.rectangle((wx, 492, wx + 6, 496), fill=MINT)
    # player pixel sprite
    d.rectangle((252, 488, 268, 512), fill=INK)
    d.rectangle((256, 482, 268, 492), fill=CREAM)
    d.rectangle((258, 486, 262, 489), fill=INK)
    d.rectangle((266, 484, 268, 488), fill=INK)
    d.rectangle((250, 500, 256, 512), fill=ROSE)
    d.rectangle((268, 500, 274, 512), fill=ROSE)
    # scanlines
    for yy in range(404, 544, 6):
        d.rectangle((156, yy, 372, yy + 1), fill="#1F4D49")
    c.text((202, 520), "PLAYER 1", 10, "#D3FFEC", bold=True)
    # glass glare
    c.line([(162, 420), (206, 400)], "#A9FBE5", 2)
    c.line([(168, 430), (190, 419)], "#A9FBE5", 1)
    # TV hardware
    d.rectangle((118, 586, 412, 596), fill="#170C1A")
    for bx in range(142, 390, 28):
        d.rectangle((bx, 586, bx + 12, 596), fill=WOOD_DEEP)
    d.rectangle((136, 572, 146, 580), fill=MINT)
    d.rectangle((154, 572, 176, 580), fill=ROSE_DARK)
    d.rectangle((184, 572, 206, 580), fill=WOOD_DEEP)
    # controller on the desk
    c.bevel((296, 560, 382, 588), "#30243A", "#63415A", "#160C1D", INK, 2, 2)
    d.rectangle((304, 568, 318, 578), fill=ORANGE)
    d.rectangle((358, 568, 372, 578), fill=CREAM)
    d.rectangle((326, 574, 350, 578), fill=INK)
    # mug on floor beside desk
    c.bevel((438, 716, 482, 766), "#2E2230", "#6A4A55", "#170D1C", INK, 2, 2)
    d.rectangle((442, 720, 478, 742), fill=CREAM)
    d.rectangle((446, 724, 474, 730), fill=ROSE)
    d.rectangle((446, 748, 474, 758), fill=CREAM)
    c.line([(482, 728), (496, 728), (496, 744), (482, 744)], INK, 3)

    # ── Tall plant between TV and window ────────────────────────────────────
    c.bevel((430, 528, 502, 612), "#8A4228", "#C86A3B", "#482116", INK, 3, 2)
    d.rectangle((424, 520, 508, 540), fill="#A95231", outline=INK, width=3)
    d.rectangle((430, 524, 502, 529), fill="#D27A45")
    d.rectangle((446, 546, 486, 602), fill="#6E3222")
    c.line([(466, 528), (462, 470), (452, 432)], "#1D5B46", 4)
    c.line([(466, 502), (486, 466), (500, 438)], "#1D5B46", 4)
    c.line([(462, 484), (438, 456), (424, 438)], "#1D5B46", 3)
    leaves = [
        (414, 420, 30, 18), (440, 404, 34, 22), (470, 416, 28, 18),
        (486, 388, 24, 30), (450, 378, 22, 28), (414, 452, 24, 16),
        (488, 448, 20, 22), (456, 446, 26, 16),
    ]
    for bx, by, bw, bh in leaves:
        d.rectangle((bx, by, bx + bw, by + bh), fill=MINT, outline=MINT_SHADOW, width=2)
        d.rectangle((bx + 4, by + 3, bx + bw - 5, by + 6), fill=MINT_GLOW)
        d.rectangle((bx + 2, by + bh - 5, bx + bw - 3, by + bh - 3), fill=MINT_DARK)
    # a couple of dark leaves for depth
    for bx, by, bw, bh in ((426, 436, 20, 14), (474, 438, 22, 13), (440, 394, 16, 14)):
        d.rectangle((bx, by, bx + bw, by + bh), fill=MINT_DARK, outline=INK, width=2)
        d.rectangle((bx + 3, by + 2, bx + bw - 4, by + 4), fill=MINT)

    # ── Right: game shelf ───────────────────────────────────────────────────
    # back shadow
    c.dither((1128, 176, 1510, 430), VOID, 10, 0, "sparse")
    c.bevel((1140, 176, 1498, 410), "#2C182E", "#5A3552", "#160B1D", INK, 4, 3)
    d.rectangle((1160, 196, 1478, 374), fill="#301A34")
    # shelf top and bottom
    c.bevel((1130, 374, 1508, 408), WOOD_MID, WOOD_HI, WOOD_DEEP, INK, 3, 3)
    d.rectangle((1142, 382, 1496, 389), fill=WOOD_LIGHT)
    for bx in (1160, 1464):
        c.bevel((bx, 408, bx + 22, 428), WOOD_DARK, WOOD_MID, WOOD_DEEP, INK, 2, 1)
    # game cases / books
    cases = [
        (1160, 120, MINT, 18), (1184, 138, GOLD, 20), (1210, 128, MAGENTA, 16),
        (1232, 150, ORANGE, 18), (1257, 134, CREAM, 20), (1285, 144, PURPLE_MID, 17),
        (1308, 124, MINT, 18), (1334, 152, GOLD, 16), (1358, 132, MAGENTA, 20),
        (1388, 142, ORANGE, 16), (1411, 118, CREAM, 18), (1436, 148, MINT, 20),
        (1462, 132, GOLD, 16),
    ]
    for gx, height, col, width in cases:
        top = 360 - height
        c.bevel((gx, top, gx + width, 366), col, _mix(col, CREAM, 0.38),
                _mix(col, INK, 0.48), INK, 2, 1)
        d.rectangle((gx + 4, top + 12, gx + width - 4, top + 54), fill=INK)
        d.rectangle((gx + 6, top + 16, gx + width - 6, top + 21), fill=_mix(col, CREAM, 0.5))
        d.rectangle((gx + 7, top + 28, gx + width - 7, top + 32), fill=_mix(col, INK, 0.5))
        d.rectangle((gx + 7, top + 40, gx + width - 9, top + 44), fill=_mix(col, INK, 0.5))
        d.rectangle((gx + width // 2 - 2, top + 58, gx + width // 2 + 2, top + 68), fill=INK)
    # leaning case
    c.poly([(1116, 366), (1134, 366), (1148, 250), (1132, 246)], "#26313A", INK, 2)
    c.poly([(1123, 348), (1135, 348), (1144, 264), (1135, 262)], MINT_DARK)
    # figurines on the shelf top edge
    d.rectangle((1184, 342, 1216, 368), fill="#3B2050", outline=INK, width=2)
    d.rectangle((1190, 328, 1210, 346), fill=ROSE, outline=INK, width=2)
    d.rectangle((1194, 334, 1198, 338), fill=INK)
    d.rectangle((1204, 334, 1208, 338), fill=INK)
    d.rectangle((1192, 346, 1208, 362), fill=CREAM)
    d.rectangle((1262, 346, 1286, 368), fill=MAGENTA, outline=INK, width=2)
    d.rectangle((1268, 336, 1280, 350), fill=GOLD, outline=INK, width=2)
    # tiny boombox on the left end of the shelf
    c.bevel((1450, 330, 1510, 368), "#2F2130", "#654556", "#140C19", INK, 2, 2)
    d.rectangle((1458, 338, 1474, 354), fill=INK)
    d.rectangle((1482, 338, 1498, 354), fill=INK)
    d.rectangle((1462, 342, 1470, 350), fill=WOOD_MID)
    d.rectangle((1486, 342, 1494, 350), fill=WOOD_MID)
    d.rectangle((1474, 356, 1482, 362), fill=MINT)

    # ── Right: control panel ────────────────────────────────────────────────
    c.dither((1160, 420, 1480, 648), VOID, 12, 0, "sparse")
    c.bevel((1168, 430, 1466, 626), WOOD_MID, WOOD_HI, WOOD_DEEP, INK, 4, 3)
    c.bevel((1190, 448, 1444, 608), "#241321", "#51304A", "#100812", INK, 3, 2)
    # VU meters
    for vx in (1208, 1360):
        d.rectangle((vx, 462, vx + 58, 490), fill="#160C18", outline=INK, width=2)
        for i in range(9):
            d.rectangle((vx + 5 + i * 6, 480 - i * 2, vx + 8 + i * 6, 484), fill=MINT if i < 6 else GOLD)
        d.rectangle((vx + 4, 486, vx + 54, 488), fill=ROSE_DARK)
    # knobs
    for kx, ky, col in ((1215, 526, GOLD), (1260, 526, ORANGE), (1368, 526, MINT), (1414, 526, GOLD)):
        d.rectangle((kx - 15, ky - 15, kx + 15, ky + 15), fill="#160C18", outline=INK, width=2)
        d.rectangle((kx - 11, ky - 11, kx + 11, ky + 11), fill=col, outline=INK, width=2)
        d.rectangle((kx - 2, ky - 9, kx + 2, ky + 3), fill=INK)
    # sliders / patch bay
    for sx in (1306, 1322, 1338, 1354):
        d.rectangle((sx, 512, sx + 3, 580), fill=INK)
        d.rectangle((sx - 3, 548, sx + 6, 555), fill=CREAM)
    for row in range(4):
        for col in range(3):
            d.rectangle((1220 + col * 18, 560 + row * 11, 1226 + col * 18, 566 + row * 11),
                        fill=(MINT, GOLD, ROSE)[(row + col) % 3])
    c.text((1200, 590), "GB-01", 8, GOLD, bold=True)
    # cable snaking out of the panel
    c.line([(1446, 590), (1480, 624), (1500, 676), (1472, 708)], INK, 4)
    c.line([(1447, 591), (1481, 625), (1501, 677), (1473, 709)], "#4A2A40", 1)
    # sticky note
    d.rectangle((1390, 440, 1434, 466), fill="#E9C97B")
    d.rectangle((1394, 446, 1424, 448), fill=ROSE_DARK)
    d.rectangle((1394, 452, 1420, 454), fill=ROSE_DARK)
    d.rectangle((1394, 458, 1416, 460), fill=ROSE_DARK)

    # ── Right: record crate ─────────────────────────────────────────────────
    c.dither((1200, 650, 1540, 840), VOID, 12, 0, "sparse")
    # records poking out
    record_cols = (MINT, GOLD, MAGENTA, ORANGE, CREAM, PURPLE_MID, ROSE, MINT)
    for i, col in enumerate(record_cols):
        x = 1244 + i * 28
        top = 626 + (i % 3) * 8
        c.bevel((x, top, x + 28, 728), col, _mix(col, CREAM, 0.3), _mix(col, INK, 0.4), INK, 2, 1)
        d.rectangle((x + 6, top + 14, x + 22, top + 34), fill=INK)
        d.rectangle((x + 10, top + 18, x + 18, top + 30), fill=_mix(col, CREAM, 0.4))
    c.bevel((1228, 700, 1510, 822), WOOD_MID, WOOD_HI, WOOD_DEEP, INK, 4, 3)
    d.rectangle((1242, 714, 1496, 808), fill=WOOD_DARK)
    for x in (1242, 1326, 1410, 1494):
        d.rectangle((x, 714, x + 4, 808), fill=WOOD_LIGHT)
    d.rectangle((1242, 752, 1496, 760), fill=WOOD_MID)
    c.text((1286, 770), "GOOD FINDS", 10, GOLD, bold=True)
    # hardware corners
    for x, y in ((1234, 706), (1502, 706), (1234, 814), (1502, 814)):
        d.rectangle((x, y, x + 8, y + 8), fill=GOLD_DARK, outline=INK, width=1)
    # scattered vinyl sleeves + headphones on the floor
    c.bevel((1136, 780, 1222, 830), "#25142B", "#593453", "#120A18", INK, 2, 2)
    d.rectangle((1146, 788, 1212, 822), fill=MAGENTA)
    d.rectangle((1156, 794, 1202, 816), fill=PURPLE_DARK)
    d.rectangle((1170, 798, 1188, 812), fill=MINT)
    d.rectangle((1110, 800, 1150, 816), fill=INK, outline=INK, width=2)
    d.rectangle((1122, 804, 1148, 813), fill=GOLD)
    d.rectangle((1108, 792, 1132, 800), fill=ROSE_DARK)

    # ── Floor lamp and light pool ───────────────────────────────────────────
    c.dither((1042, 284, 1172, 394), GOLD, 10, 0, "sparse")
    c.line([(1104, 382), (1104, 756)], "#24101A", 6)
    c.line([(1101, 382), (1101, 756)], GOLD_DARK, 2)
    c.bevel((1090, 740, 1122, 760), "#2B1622", "#5C3442", "#120A12", INK, 2, 2)
    # shade
    c.poly([(1058, 336), (1150, 336), (1126, 286), (1082, 286)], WOOD_MID, INK, 3)
    c.poly([(1066, 330), (1142, 330), (1122, 294), (1086, 294)], GOLD, INK, 2)
    c.poly([(1082, 324), (1126, 324), (1114, 302), (1094, 302)], "#FFD98A")
    d.rectangle((1056, 334, 1152, 342), fill=WOOD_HI, outline=INK, width=2)
    for sx in range(1064, 1146, 12):
        d.rectangle((sx, 342, sx + 2, 354), fill=GOLD_DARK)
    # light cone
    c.dither((1070, 344, 1140, 800), "#6A4533", 14, 0, "sparse")
    c.dither((1054, 760, 1160, 830), GOLD_DARK, 14, 0, "sparse")

    # ── Centre: listening rug / low nest ────────────────────────────────────
    # The mascot is drawn live on top of this, so keep the centre dark and
    # uncluttered; the visible edges do the storytelling.
    c.dither((588, 680, 1012, 840), VOID, 12, 0, "sparse")
    # beanbag / floor cushion
    c.poly([(626, 780), (676, 704), (742, 676), (848, 676), (920, 704), (966, 780),
            (942, 824), (884, 840), (812, 846), (718, 838), (650, 820)], PURPLE_MID, INK, 4)
    c.poly([(650, 774), (690, 716), (750, 694), (842, 694), (900, 716), (944, 774),
            (914, 808), (842, 816), (750, 814), (682, 804)], PURPLE_LIGHT)
    c.poly([(690, 748), (742, 716), (846, 718), (900, 750), (880, 778), (738, 780)], "#45204A", INK, 2)
    c.line([(748, 724), (840, 726)], "#7A4170", 2)
    # cushion
    c.bevel((760, 744, 920, 804), "#5F2B52", "#9C527C", "#2C1233", INK, 3, 2)
    d.rectangle((780, 754, 900, 758), fill="#B66A8C")
    # rug in front / under the mascot
    c.bevel((520, 770, 1084, 842), "#4C2342", "#8A4A6A", "#2A102A", INK, 4, 3)
    d.rectangle((536, 780, 1068, 832), fill="#5E2B4E")
    for x in range(550, 1068, 52):
        d.rectangle((x, 786, x + 20, 792), fill=GOLD_DARK)
        d.rectangle((x + 4, 814, x + 24, 820), fill=MINT_DARK)
    d.rectangle((512, 770, 534, 842), fill=ROSE_DARK)
    d.rectangle((1070, 770, 1092, 842), fill=ROSE_DARK)
    for x in range(516, 1090, 18):
        d.rectangle((x, 838, x + 8, 846), fill=ROSE_DARK)

    # ── Side table + record player (left of the nest) ──────────────────────
    c.bevel((548, 642, 702, 742), WOOD_MID, WOOD_HI, WOOD_DEEP, INK, 4, 3)
    d.rectangle((562, 656, 688, 728), fill=WOOD_DARK)
    c.bevel((574, 622, 676, 658), "#2A1A2D", "#5A3552", "#120A18", INK, 2, 2)
    d.rectangle((584, 630, 666, 650), fill="#1A1020")
    d.rectangle((594, 634, 656, 646), fill=INK)
    d.rectangle((606, 632, 646, 650), fill=ROSE_DARK)
    d.rectangle((614, 638, 638, 646), fill=ROSE)
    c.line([(600, 624), (600, 606), (620, 606)], GOLD_DARK, 3)
    d.rectangle((618, 600, 632, 610), fill=GOLD)
    # tiny speaker + cassettes under the table
    c.bevel((566, 688, 620, 724), "#2A1A2D", "#5A3552", "#120A18", INK, 2, 1)
    for sx in range(574, 612, 8):
        d.rectangle((sx, 696, sx + 4, 716), fill=WOOD_MID)
    for i, col in enumerate((GOLD, MINT, MAGENTA)):
        c.bevel((632 + i * 16, 696, 646 + i * 16, 724), col, _mix(col, CREAM, 0.4),
                _mix(col, INK, 0.5), INK, 1, 1)

    # ── Foreground clutter, cables, and little stories ─────────────────────
    # A game controller on the floor to the left of the rug.
    c.bevel((470, 800, 542, 832), "#2A2034", "#604666", "#120A18", INK, 2, 2)
    d.rectangle((478, 808, 496, 818), fill=ORANGE)
    d.rectangle((516, 808, 534, 818), fill=CREAM)
    d.rectangle((498, 814, 512, 818), fill=INK)
    # cassette tapes + a mug near the left edge.
    c.bevel((340, 780, 418, 820), "#25142B", "#593453", "#120A18", INK, 2, 2)
    d.rectangle((348, 788, 410, 814), fill=MAGENTA)
    d.rectangle((360, 794, 398, 808), fill=CREAM)
    d.rectangle((366, 796, 374, 806), fill=INK)
    d.rectangle((384, 796, 392, 806), fill=INK)
    c.bevel((250, 790, 300, 830), "#D8C5A2", "#FFF6D8", "#7D6A58", INK, 2, 2)
    d.rectangle((256, 796, 294, 812), fill=CREAM)
    c.line([(300, 800), (318, 800), (318, 820), (300, 820)], INK, 3)
    c.line([(301, 801), (317, 801), (317, 819), (301, 819)], "#D8C5A2", 1)
    # A little stack of game cases at the lower left.
    for i, col in enumerate((MINT, GOLD, ROSE)):
        c.bevel((54, 780 + i * 11, 178, 792 + i * 11), col, _mix(col, CREAM, 0.35),
                _mix(col, INK, 0.4), INK, 1, 1)
    # Cable across the floor.
    c.line([(96, 928), (216, 908), (286, 930), (384, 900), (462, 928), (550, 912),
            (660, 936), (820, 916), (1010, 936), (1140, 918), (1290, 946), (1500, 920)], INK, 4)
    c.line([(96, 927), (216, 907), (286, 929), (384, 899), (462, 927), (550, 911),
            (660, 935), (820, 915), (1010, 935), (1140, 917), (1290, 945), (1500, 919)],
           "#4A2A40", 1)
    # Subtle floor highlights / scuffs.
    for x, y, w in ((640, 866, 44), (880, 892, 32), (1090, 872, 54), (1320, 892, 38),
                    (240, 866, 48), (440, 900, 60)):
        d.rectangle((x, y, x + w, y + 2), fill="#5F3550")
        d.rectangle((x + 8, y + 4, x + w - 6, y + 5), fill="#2A152D")

    # ── Final light and texture pass ────────────────────────────────────────
    # A faint mint rim from the CRT and a warm rim from the lamp.
    c.dither((80, 350, 470, 660), "#2B5A50", 16, 0, "sparse")
    c.dither((1030, 300, 1180, 760), "#6C4A31", 16, 0, "sparse")
    # Ceiling string lights, tucked above the main composition.
    c.line([(300, 178), (340, 196), (382, 178), (426, 198), (470, 178)], INK, 2)
    for lx, ly, col in ((340, 196, GOLD), (426, 198, MINT), (470, 178, ROSE), (382, 178, ORANGE)):
        d.rectangle((lx - 3, ly, lx + 3, ly + 5), fill=col, outline=INK, width=1)
        c.dither((lx - 8, ly + 2, lx + 8, ly + 14), col, 12, 0, "sparse")
    # Fine grain on the largest flat areas (wall + floor) for a hand-made feel.
    c.speckle((0, 200, 1600, 700), (WALL_PANEL, WALL_LINE, "#3C2144"), 160, 4, 5)
    c.speckle((0, 740, 1600, 1000), ("#1B0D1F", "#4A2840", "#32182F"), 140, 4, 9)
    # Edge vignette, stronger at the bottom corners.
    c.dither((0, 680, 70, 1000), INK, 8, 0)
    c.dither((1530, 680, 1600, 1000), INK, 8, 1)
    c.dither((0, 900, 1600, 1000), VOID, 10, 0, "sparse")

    return c.img


def build_dim(room: Image.Image) -> Image.Image:
    """A darker copy for the content-page backdrops."""
    overlay = Image.new("RGB", room.size, "#120A18")
    dimmed = Image.blend(room, overlay, 0.72)
    # Keep a touch of the warm window/lamp pools alive.
    warm = Image.new("RGB", room.size, "#3A1E26")
    mask = Image.new("L", room.size, 0)
    md = ImageDraw.Draw(mask)
    md.rectangle((490, 150, 1090, 535), fill=38)
    md.rectangle((1020, 270, 1200, 800), fill=38)
    md.rectangle((90, 340, 460, 660), fill=26)
    dimmed = Image.composite(Image.blend(dimmed, warm, 0.16), dimmed, mask)
    return dimmed


def main():
    room = build_room()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    room.save(OUT_PATH, optimize=True)
    build_dim(room).save(DIM_PATH, optimize=True)
    print(f"wrote {OUT_PATH}")
    print(f"wrote {DIM_PATH}")


if __name__ == "__main__":
    main()
