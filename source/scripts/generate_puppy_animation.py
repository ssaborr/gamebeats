"""Build the in-room puppy animation set.

The four legacy poses are smooth, high-colour raster illustrations. For the
16-bit room we need true pixel sprites: a small fixed palette, hard edges, a
transparent background, and a locked foot baseline. This script quantises the
legacy art into the GameBeats puppy ramp and authors the in-place expressions
used by :mod:`ui.puppy_anim`.

Rules baked into the output:
  * every frame is 64x72 with a binary alpha channel;
  * the paws never leave rows 66-69, so the sprite can stay at a fixed canvas
    position forever;
  * no frame contains a drop shadow, halo, glow, or semi-transparent pixel;
  * frames advance on twos from the single 30 Hz clock;
  * the puppy never wears headphones.  The legacy plates are already drawn
    bare-headed, so no headset overlay is applied.

Run from the project root:
    py source/scripts/generate_puppy_animation.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "assets" / "puppy_design"
OUT = SRC / "anim"
SPEC_PATH = SRC / "puppy_anim.json"
SHEET_PATH = OUT / "contact_sheet.png"

# Authoring happens on the legacy 128x144 plates; output is snapped down to the
# room's 400x250 logical grid. At the default window size the app draws the
# 64x72 sprite at exactly 3x, while the room plate is 400x250 at 3x.
MASTER_W, MASTER_H = 128, 144
FRAME_W, FRAME_H = 64, 72
SCALE = 4
BASELINE_Y = 70

# A hard 19-colour puppy ramp. The first colour is the darkest outline.
PALETTE = (
    (26, 17, 17),      # ink
    (58, 30, 18),      # deepest outline
    (91, 45, 21),      # deep shadow
    (138, 58, 23),     # shadow
    (168, 74, 26),     # deep orange
    (210, 106, 42),    # orange shade
    (255, 180, 94),    # base fur
    (255, 208, 138),   # light fur
    (255, 244, 209),   # muzzle
    (255, 255, 238),   # muzzle highlight
    (255, 255, 255),   # eye glint
    (255, 138, 138),   # tongue
    (184, 74, 90),     # tongue shadow / cheeks
    (42, 23, 58),      # mic shadow
    (58, 43, 58),      # mic body
    (107, 90, 107),    # mic metal
    (199, 184, 176),   # mic highlight
    (253, 183, 92),    # gold hardware
    (122, 46, 91),     # collar / magenta
)

INK = PALETTE[0]
FUR = PALETTE[6]
FUR_LIGHT = PALETTE[7]
CREAM = PALETTE[8]
CREAM_HI = PALETTE[9]
WHITE = PALETTE[10]
PINK = PALETTE[11]
PINK_DARK = PALETTE[12]
MAGENTA = PALETTE[18]

EYE_L = (30, 30, 44, 49)   # exclusive box
EYE_R = (62, 33, 79, 52)

# The singing mouth on the final 64x72 grid.  Used by the desktop overlay to
# close the jaw while keeping every other pixel of the pose fixed.
MOUTH_BOX = (18, 22, 28, 38)


def _palette_image() -> Image.Image:
    img = Image.new("P", (1, 1))
    flat = []
    for color in PALETTE:
        flat.extend(color)
    # Fill unused entries with ink, not black, so a stray quantise index can
    # never introduce a 20th colour.
    flat.extend(list(INK) * (256 - len(PALETTE)))
    img.putpalette(flat)
    return img


def _load_base(name: str) -> Image.Image:
    img = Image.open(SRC / f"{name}.png").convert("RGBA")
    if img.size != (MASTER_W, MASTER_H):
        raise ValueError(f"{name}.png is {img.size}, expected {(MASTER_W, MASTER_H)}")
    # Snap alpha to hard pixels: the source already uses binary alpha, but this
    # protects the generator if the source is ever re-exported with a feather.
    alpha = img.getchannel("A").point(lambda p: 255 if p >= 128 else 0)
    img.putalpha(alpha)
    quantised = img.convert("RGB").quantize(
        palette=_palette_image(), dither=Image.Dither.NONE
    ).convert("RGBA")
    quantised.putalpha(alpha)
    return quantised


def _is_dark(pixel) -> bool:
    r, g, b, a = pixel
    return a > 0 and r < 105 and g < 90 and b < 90


def _is_glint(pixel) -> bool:
    r, g, b, a = pixel
    return a > 0 and r > 232 and g > 222 and b > 175


def _clear(img: Image.Image, box) -> None:
    img.paste((0, 0, 0, 0), box)


def _copy_shifted(img: Image.Image, box, dx=0, dy=0, fill=None) -> None:
    """Move a rectangular region by whole pixels, optionally filling the gap."""
    region = img.crop(box)
    _clear(img, box)
    dest = (box[0] + dx, box[1] + dy)
    img.paste(region, dest, region)
    if fill is not None:
        # Fill only the vacated strips, never the moved art.
        d = ImageDraw.Draw(img)
        if dy > 0:
            d.rectangle((box[0], box[1], box[2] - 1, box[1] + dy - 1), fill=fill)
        elif dy < 0:
            d.rectangle((box[0], box[3] + dy, box[2] - 1, box[3] - 1), fill=fill)
        if dx > 0:
            d.rectangle((box[0], box[1], box[0] + dx - 1, box[3] - 1), fill=fill)
        elif dx < 0:
            d.rectangle((box[2] + dx, box[1], box[2] - 1, box[3] - 1), fill=fill)


def _breath(img: Image.Image) -> Image.Image:
    out = img.copy()
    # Chest and head rise one logical pixel; the paws below row 112 never move.
    _copy_shifted(out, (0, 0, MASTER_W, 112), dy=-1)
    return out


def _shift_head(img: Image.Image, dx: int) -> Image.Image:
    out = img.copy()
    _copy_shifted(out, (0, 0, MASTER_W, 84), dx=dx)
    return out


def _close_eyes(img: Image.Image, happy: bool = False, sleepy: bool = False) -> None:
    out = img
    d = ImageDraw.Draw(out)
    for box in (EYE_L, EYE_R):
        x0, y0, x1, y1 = box
        for y in range(y0, y1):
            for x in range(x0, x1):
                if _is_dark(out.getpixel((x, y))):
                    out.putpixel((x, y), FUR)
    if happy:
        d.line([(32, 43), (33, 42), (34, 41), (35, 41), (36, 41),
                (37, 42), (38, 43)], fill=INK, width=2)
        d.line([(65, 46), (66, 45), (67, 44), (68, 44), (74, 44),
                (75, 45), (76, 46)], fill=INK, width=2)
    elif sleepy:
        d.line([(32, 44), (33, 45), (34, 45), (35, 46), (36, 46),
                (37, 45), (38, 45), (39, 44)], fill=INK, width=2)
        d.line([(65, 47), (66, 48), (67, 48), (68, 49), (73, 49),
                (74, 48), (75, 48), (76, 47)], fill=INK, width=2)
        # A single sleepy lash at each outer corner.
        d.point((41, 44), fill=INK)
        d.point((78, 47), fill=INK)
    else:
        d.line([(32, 43), (33, 44), (34, 44), (35, 45), (36, 45),
                (37, 45), (38, 44), (39, 44)], fill=INK, width=2)
        d.line([(65, 46), (66, 47), (67, 47), (68, 48), (74, 48),
                (75, 47), (76, 47)], fill=INK, width=2)


def _look_left(img: Image.Image, distance: int = 2) -> None:
    """Slide the eye glints toward the CRT without moving the head."""
    out = img
    for box in (EYE_L, EYE_R):
        x0, y0, x1, y1 = box
        glints = []
        for y in range(y0, y1):
            for x in range(x0, x1):
                if _is_glint(out.getpixel((x, y))):
                    glints.append((x, y))
        for x, y in glints:
            out.putpixel((x, y), INK)
        for x, y in glints:
            nx = x - distance
            if x0 <= nx < x1:
                out.putpixel((nx, y), WHITE)


def _perk_ears(img: Image.Image, amount: int = 2) -> None:
    """Raise the outer ear flaps while keeping their inner attachment."""
    out = img
    for x0, x1, direction in ((0, 24, -1), (104, MASTER_W, 1)):
        for x in range(x0, x1):
            # The outer tip rises most; the base stays put.
            if direction < 0:
                lift = amount if x < x0 + 10 else (1 if x < x0 + 18 else 0)
            else:
                lift = amount if x >= x1 - 10 else (1 if x >= x1 - 18 else 0)
            if lift <= 0:
                continue
            for y in range(10, 66):
                if out.getpixel((x, y))[3] > 0:
                    break
            else:
                continue
            col = out.crop((x, 10, x + 1, 66))
            _clear(out, (x, 10, x + 1, 66))
            out.paste(col, (x, 10 - lift), col)
            # Keep the ear attached to the head with a fur fill, never a hole.
            d = ImageDraw.Draw(out)
            d.rectangle((x, 66 - lift, x, 65), fill=FUR)


def _open_mouth_from_sing(base: Image.Image, sing: Image.Image) -> Image.Image:
    out = base.copy()
    # The muzzle and open mouth are identical in position; the mic stays out
    # of this crop so the happy pose can remain mic-free if desired.
    region = sing.crop((34, 42, 84, 77))
    out.paste(region, (34, 42), region)
    return out


def _add_tongue(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    d.rectangle((47, 68, 55, 75), fill=PINK_DARK, outline=INK)
    d.rectangle((48, 69, 54, 74), fill=PINK)
    d.line([(51, 70), (51, 74)], fill=PINK_DARK)
    d.point((49, 70), fill=CREAM_HI)
    d.point((53, 71), fill=CREAM_HI)


def _add_blush(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    for x0, y0 in ((25, 54), (85, 56)):
        d.rectangle((x0, y0, x0 + 3, y0 + 1), fill=PINK_DARK)
        d.point((x0 + 1, y0), fill=PINK)
        d.point((x0 + 2, y0 + 1), fill=PINK)


def _frame() -> Image.Image:
    return Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))


def _downsample(master: Image.Image) -> Image.Image:
    """Snap the authored plate onto the room's 64x72 character grid."""
    smooth = master.resize((FRAME_W, FRAME_H), Image.Resampling.LANCZOS)
    alpha = smooth.getchannel("A").point(lambda p: 255 if p >= 112 else 0)
    rgb = smooth.convert("RGB").quantize(
        palette=_palette_image(), dither=Image.Dither.NONE
    ).convert("RGBA")
    rgb.putalpha(alpha)
    return rgb


def _mouth_frame(base: Image.Image, open_rows: int) -> Image.Image:
    """Return *base* with the singing mouth closed to *open_rows* pixels.

    The desktop singer has to animate without swapping between two different
    illustrations: the legacy ``sing`` and ``mic`` plates pose the paw, head
    and microphone differently, so alternating them reads as a twitch.  Instead
    we keep one held pose and squash only the open mouth, which is the one
    region that actually changes while singing.  The vacated rows are filled
    with the chin colour taken just below the mouth, so no new colours and no
    semi-transparent pixels are introduced.
    """
    out = base.copy()
    x0, y0, x1, y1 = MOUTH_BOX
    # Fill with the muzzle's dominant chin colour.  Stretching a single row
    # would carry its left-edge shadow down the chin as an orange stripe.
    chin_row = [base.getpixel((x, y1)) for x in range(x0, x1)]
    chin_row = [p for p in chin_row if p[3] > 0] or [(255, 244, 209, 255)]
    fill = max(set(chin_row), key=chin_row.count)
    ImageDraw.Draw(out).rectangle((x0, y0, x1 - 1, y1 - 1), fill=fill)
    mouth = base.crop(MOUTH_BOX).resize(
        (x1 - x0, max(1, open_rows)), Image.Resampling.NEAREST
    )
    out.paste(mouth, (x0, y0))
    return out


def build_overlay_frames(frames: dict[str, Image.Image]) -> dict[str, Image.Image]:
    """Author the small desktop singer's four-frame jaw cycle.

    All four frames share the exact same body, head and microphone pixels.
    Only the jaw height and (for the blink) the eyes change, which is what
    makes the overlay read as smooth motion instead of a strobing pose swap.
    """
    open_frame = frames["sing_0"]
    return {
        "talk_open": open_frame.copy(),
        "talk_mid": _mouth_frame(open_frame, 12),
        "talk_low": _mouth_frame(open_frame, 9),
        # A blink reuses the existing eyes-closed pose of the same plate.
        "talk_blink": frames["sing_3"].copy(),
    }


def build_frames() -> dict[str, Image.Image]:
    idle = _load_base("idle")
    sing = _load_base("sing")
    mic = _load_base("mic")

    frames: dict[str, Image.Image] = {}

    frames["idle_0"] = idle.copy()
    frames["idle_1"] = _breath(idle)
    blink = idle.copy()
    _close_eyes(blink)
    frames["idle_blink"] = blink
    frames["idle_tilt"] = _shift_head(idle, -1)
    flick = idle.copy()
    _perk_ears(flick, amount=2)
    frames["idle_flick"] = flick

    frames["sing_0"] = sing.copy()
    frames["sing_1"] = mic.copy()
    frames["sing_2"] = _breath(sing)
    closed = sing.copy()
    _close_eyes(closed)
    frames["sing_3"] = closed
    frames["sing_4"] = _breath(mic)

    sleepy = idle.copy()
    _close_eyes(sleepy, sleepy=True)
    frames["paused_0"] = sleepy
    frames["paused_1"] = _breath(sleepy)

    alert = idle.copy()
    _look_left(alert, 2)
    _perk_ears(alert, amount=2)
    frames["alert_0"] = alert
    frames["alert_1"] = _shift_head(alert, -1)

    happy = _open_mouth_from_sing(idle, sing)
    _close_eyes(happy, happy=True)
    _add_tongue(happy)
    frames["happy"] = happy

    encore = sing.copy()
    _close_eyes(encore)
    _add_blush(encore)
    frames["encore"] = encore

    return frames


SPEC = {
    "version": 1,
    "size": [FRAME_W, FRAME_H],
    "baseline_y": BASELINE_Y,
    "fps": 30,
    "on_twos": 2,
    "audio": {
        "open_level": 0.30,
        "close_level": 0.14,
        "min_hold": 15,
        "min_frame_hold": 6,
    },
    "states": {
        "idle": {
            "frames": ["idle_0", "idle_1", "idle_0", "idle_blink",
                       "idle_0", "idle_flick", "idle_1", "idle_tilt"],
            "hold": [12, 12, 14, 2, 14, 8, 12, 16],
            "static": "idle_0",
        },
        "singing_open": {
            "frames": ["sing_0", "sing_2"],
            "hold": [12, 12],
            "static": "sing_0",
        },
        "singing_closed": {
            "frames": ["sing_1"],
            "hold": [8],
            "static": "sing_1",
        },
        "singing_eyes_closed": {
            "frames": ["sing_3"],
            "hold": [12],
            "static": "sing_3",
        },
        "paused": {
            "frames": ["paused_0", "paused_1"],
            "hold": [30, 30],
            "static": "paused_0",
        },
        "alert": {
            "frames": ["alert_0", "alert_1"],
            "hold": [16, 16],
            "static": "alert_0",
        },
        "reaction": {
            "frames": ["alert_1"],
            "hold": [30],
            "static": "alert_1",
        },
        "happy": {
            "frames": ["happy"],
            "hold": [10],
            "static": "happy",
        },
        "encore": {
            "frames": ["encore"],
            "hold": [8],
            "static": "encore",
        },
    },
}


def _checker(size, cell=32):
    img = Image.new("RGB", size, "#1A1820")
    d = ImageDraw.Draw(img)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if ((x // cell) + (y // cell)) % 2:
                d.rectangle((x, y, x + cell - 1, y + cell - 1), fill="#24212C")
    return img


def build_contact_sheet(frames: dict[str, Image.Image]) -> None:
    order = [
        "idle_0", "idle_1", "idle_blink", "idle_tilt",
        "idle_flick", "sing_0", "sing_1", "sing_2",
        "sing_3", "sing_4", "paused_0", "paused_1",
        "alert_0", "alert_1", "happy", "encore",
        "talk_open", "talk_mid", "talk_low", "talk_blink",
    ]
    cell_w, cell_h = FRAME_W * SCALE, FRAME_H * SCALE
    pad, label_h = 24, 34
    cols = 4
    rows = math.ceil(len(order) / cols)
    sheet = Image.new(
        "RGB",
        (pad + cols * (cell_w + pad), pad + rows * (cell_h + label_h + pad)),
        "#120A18",
    )
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(ROOT / "assets" / "fonts" / "Silkscreen-Bold.ttf"), 20)
    except OSError:
        font = ImageFont.load_default()
    for i, name in enumerate(order):
        col, row = i % cols, i // cols
        x = pad + col * (cell_w + pad)
        y = pad + row * (cell_h + label_h + pad)
        cell = _checker((cell_w, cell_h), 32)
        frame = frames[name].resize((cell_w, cell_h), Image.Resampling.NEAREST)
        cell.paste(frame, (0, 0), frame)
        cd = ImageDraw.Draw(cell)
        by = BASELINE_Y * SCALE
        cd.line([(0, by), (cell_w, by)], fill=(124, 255, 196), width=2)
        sheet.paste(cell, (x, y))
        d.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), outline="#5A3552", width=2)
        d.text((x + 8, y + cell_h + 6), name, font=font, fill="#FFF3D0")
    sheet.save(SHEET_PATH, optimize=True)


def main() -> None:
    master_frames = build_frames()
    frames = {
        name: _downsample(img)
        for name, img in master_frames.items()
    }
    # Overlay-only frames are authored on the final grid so the jaw squash
    # never reshuffles the body pixels.
    frames.update(build_overlay_frames(frames))
    OUT.mkdir(parents=True, exist_ok=True)
    bottoms = {}
    for name, img in frames.items():
        img.save(OUT / f"{name}.png", optimize=True)
        bottom = max(
            (y for y in range(img.height) for x in range(img.width)
             if img.getpixel((x, y))[3] > 0),
            default=0,
        )
        bottoms[name] = bottom + 1
    inconsistent = {n: b for n, b in bottoms.items() if b != BASELINE_Y}
    if inconsistent:
        raise SystemExit(f"feet drifted off the baseline: {inconsistent}")
    SPEC_PATH.write_text(json.dumps(SPEC, indent=2) + "\n", encoding="utf-8")
    build_contact_sheet(frames)
    print(f"wrote {len(frames)} frames to {OUT} (baseline y={BASELINE_Y})")
    print(f"wrote {SPEC_PATH}")
    print(f"wrote {SHEET_PATH}")


if __name__ == "__main__":
    main()
