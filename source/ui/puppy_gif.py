"""Load the hand-authored GIF mascots as transparent animation frames.

Tk only shows the first frame of a GIF, so both the in-room puppy and the
desktop overlay need the GIF decoded into RGBA frames first.  The source GIFs
were exported on a near-black backdrop; we remove only the backdrop that is
connected to the image border, which keeps the dark eyes, microphone and
outline intact.

Frames are cropped to a shared box so every beat keeps identical dimensions.
The room frames are then padded onto the old 64x72 sprite aspect ratio with the
same two-pixel paw margin, letting the existing fixed-baseline layout code
continue to work unchanged.
"""

from __future__ import annotations

import math
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

try:
    import numpy as np
except Exception:  # pragma: no cover - Pillow-only fallback
    np = None


# The GIF backdrop is (1, 1, 1) with a little compression noise.  The artwork
# outline begins around channel value 20, so 12 clears the backdrop without
# eating the outline.
GIF_BG_THRESHOLD = 12
GIF_BG_FILL = 128
PUPPY_BOB_GIF = "puppy bobbing head for overlay.gif"
_RESAMPLE = getattr(Image, "Resampling", Image).NEAREST
_CACHE = {}


def _row_runs(candidates):
    """Return the contiguous True runs on every row, as (start, end) pairs."""
    height, width = candidates.shape
    rows = []
    for y in range(height):
        padded = np.empty(width + 2, dtype=bool)
        padded[0] = False
        padded[-1] = False
        padded[1:-1] = candidates[y]
        diff = np.diff(padded.astype(np.int8))
        starts = np.nonzero(diff == 1)[0]
        ends = np.nonzero(diff == -1)[0]
        rows.append(list(zip(starts.tolist(), ends.tolist())))
    return rows


def _fill_border_runs(candidates) -> "np.ndarray":
    """Flood the candidate mask from its border using connected row runs.

    Treating each horizontal run as one node keeps this fast even for a 640x640
    frame: the blank backdrop is a handful of runs per row rather than a pixel
    queue.
    """
    height, width = candidates.shape
    rows = _row_runs(candidates)
    run_count = sum(len(row) for row in rows)
    if not run_count:
        return np.zeros((height, width), dtype=bool)

    # Give every run an id and remember its geometry.
    row_ids = []
    run_y = []
    run_x0 = []
    run_x1 = []
    for y, row in enumerate(rows):
        ids = []
        for start, end in row:
            ids.append(len(run_y))
            run_y.append(y)
            run_x0.append(start)
            run_x1.append(end)
        row_ids.append(ids)

    # Connect runs that touch (overlap or abut) on adjacent rows.
    neighbors = [[] for _ in range(run_count)]
    for y in range(height - 1):
        above = rows[y]
        below = rows[y + 1]
        above_ids = row_ids[y]
        below_ids = row_ids[y + 1]
        i = j = 0
        while i < len(above) and j < len(below):
            a0, a1 = above[i]
            b0, b1 = below[j]
            if a0 <= b1 and b0 <= a1:
                aid = above_ids[i]
                bid = below_ids[j]
                neighbors[aid].append(bid)
                neighbors[bid].append(aid)
            if a1 < b1:
                i += 1
            elif b1 < a1:
                j += 1
            else:
                i += 1
                j += 1

    # Seed from every run that touches the image border.
    seeds = list(row_ids[0]) + list(row_ids[-1])
    for y, row in enumerate(rows):
        for index, (start, end) in enumerate(row):
            if start == 0 or end == width:
                seeds.append(row_ids[y][index])

    seen = bytearray(run_count)
    queue = deque()
    for run_id in seeds:
        if not seen[run_id]:
            seen[run_id] = 1
            queue.append(run_id)
    while queue:
        run_id = queue.popleft()
        for neighbor in neighbors[run_id]:
            if not seen[neighbor]:
                seen[neighbor] = 1
                queue.append(neighbor)

    filled = np.zeros((height, width), dtype=bool)
    for run_id, is_filled in enumerate(seen):
        if is_filled:
            filled[run_y[run_id], run_x0[run_id]:run_x1[run_id]] = True
    return filled


def _border_connected_background(rgb: Image.Image, threshold: int) -> Image.Image:
    """Return an 8-bit mask with 255 where the border backdrop was found."""
    if np is None:  # pragma: no cover - numpy ships with the app
        # Safe, slow fallback: floodfill the RGBA frame from its border, then
        # invert the alpha channel into the same background mask.
        rgba = rgb.convert("RGBA")
        for seed in (
            (0, 0), (rgba.width - 1, 0),
            (0, rgba.height - 1), (rgba.width - 1, rgba.height - 1),
        ):
            ImageDraw.floodfill(rgba, seed, (0, 0, 0, 0), thresh=threshold)
        return ImageOps.invert(rgba.getchannel("A"))

    arr = np.asarray(rgb, dtype=np.uint8)
    candidates = (
        (arr[:, :, 0] <= threshold)
        & (arr[:, :, 1] <= threshold)
        & (arr[:, :, 2] <= threshold)
    )
    filled = _fill_border_runs(candidates)
    mask = Image.fromarray(filled.astype("uint8") * GIF_BG_FILL, "L")
    return mask


def _cutout(frame: Image.Image, threshold: int = GIF_BG_THRESHOLD) -> Image.Image:
    rgba = frame.convert("RGBA")
    mask = _border_connected_background(rgba.convert("RGB"), threshold)
    lut = [0 if value == GIF_BG_FILL else 255 for value in range(256)]
    rgba.putalpha(mask.point(lut))
    return rgba


def load_gif_frames(path, *, threshold: int = GIF_BG_THRESHOLD):
    """Decode *path* into ``(frames, durations_ms)`` with a clean alpha.

    The returned frames are cropped to the union of their content boxes, so all
    frames share one size and the paws never shift between beats.
    """
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return (), ()

    cache_key = (str(path.resolve()), stat.st_mtime_ns, int(threshold))
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    frames = []
    durations = []
    with Image.open(path) as image:
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            frames.append(_cutout(image, threshold))
            durations.append(max(20, int(image.info.get("duration", 120) or 120)))

    boxes = [frame.getchannel("A").getbbox() for frame in frames]
    boxes = [box for box in boxes if box]
    if not boxes:
        result = ((), ())
        _CACHE[cache_key] = result
        return result

    union = (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
    # A one-pixel margin keeps the softened GIF edge from being clipped when
    # the frame is scaled down.
    union = (
        max(0, union[0] - 1), max(0, union[1] - 1),
        min(frames[0].width, union[2] + 1), min(frames[0].height, union[3] + 1),
    )
    frames = tuple(frame.crop(union) for frame in frames)
    result = (frames, tuple(durations))
    _CACHE[cache_key] = result
    return result


def normalize_sprite_frames(frames, *, aspect=(64, 72), bottom_pad=2):
    """Pad cropped frames onto the room sprite canvas without rescaling them."""
    if not frames:
        return ()
    width, height = frames[0].size
    aspect_w, aspect_h = aspect
    ratio = float(aspect_w) / float(aspect_h)
    pad_ratio = max(0.0, float(bottom_pad) / float(aspect_h))

    # Width needed so the content still leaves the paw margin at the bottom.
    canvas_w = max(
        width,
        int(math.ceil(height * ratio / max(0.001, 1.0 - pad_ratio))),
    )
    canvas_h = int(math.ceil(canvas_w / ratio))
    pad_px = max(1, int(round(canvas_h * pad_ratio)))
    while canvas_h - pad_px < height:
        canvas_h += 1
        canvas_w = int(math.ceil(canvas_h * ratio))
        pad_px = max(1, int(round(canvas_h * pad_ratio)))
    target_bottom = canvas_h - pad_px
    normalized = []
    for frame in frames:
        canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        alpha_bbox = frame.getchannel("A").getbbox()
        content_bottom = alpha_bbox[3] if alpha_bbox else frame.height
        x = (canvas_w - frame.width) // 2
        y = target_bottom - content_bottom
        canvas.alpha_composite(frame, (max(0, x), max(0, y)))
        normalized.append(canvas)
    return tuple(normalized)


def fit_frame(frame: Image.Image, max_size, *, resample=_RESAMPLE):
    """Scale a frame to fit *max_size* while preserving its aspect ratio."""
    if frame is None:
        return None
    max_w, max_h = int(max_size[0]), int(max_size[1])
    if frame.width <= 0 or frame.height <= 0 or max_w <= 0 or max_h <= 0:
        return None
    scale = min(max_w / float(frame.width), max_h / float(frame.height))
    size = (
        max(1, int(round(frame.width * scale))),
        max(1, int(round(frame.height * scale))),
    )
    if size == frame.size:
        return frame.copy()
    return frame.resize(size, resample)


def frame_index_at(elapsed_ms: float, durations_ms) -> int:
    """Return the GIF frame that should be visible at *elapsed_ms*."""
    durations = tuple(int(value) for value in durations_ms or ())
    if not durations:
        return 0
    total = sum(max(1, value) for value in durations)
    if total <= 0:
        return 0
    offset = int(max(0.0, elapsed_ms) % total)
    for index, duration in enumerate(durations):
        duration = max(1, duration)
        if offset < duration:
            return index
        offset -= duration
    return len(durations) - 1
