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
PUPPY_CHANGE_GIF = "changing playlist or song.gif"
PUPPY_PAUSE_GIF = "pause and resume overlay anime.gif"
PUPPY_THINKING_GIF = "puppy-thinking.gif"
# The thinking GIF has nine authored frames.  Play the first six once, then
# ping-pong through frames 7-8-9-8 until the new track/playlist is ready.  The
# short tail loop reads better at 50% slower than the intro's authored cadence.
THINKING_INTRO_FRAMES = 6
THINKING_TAIL_FRAMES = (6, 7, 8, 7)
THINKING_TAIL_DURATION_SCALE = 1.5
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


def normalize_animation_states(
    states,
    *,
    reference="idle",
    target_size=(64, 72),
    bottom_pad=2,
    margin=1,
):
    """Scale several GIF states onto one shared canvas and baseline.

    ``states`` maps a state name to ``(frames, durations)`` (or just frames).
    The reference state is fitted into *target_size* exactly like the old
    single-state mascot, so its on-screen body size does not change.  Every
    other state uses the same scale and is bottom-centred on a canvas large
    enough for its widest/tallest frame.  That keeps the puppy from visibly
    growing or shrinking when it switches between bobbing, changing the
    playlist, and pausing.

    Returns ``(normalized_states, canvas_size)``; every frame in every state
    has the same ``canvas_size``.
    """
    if not states:
        return {}, (0, 0)

    def _unpack(value):
        if (
            isinstance(value, tuple)
            and len(value) == 2
            and not isinstance(value[0], Image.Image)
        ):
            frames, durations = value
        else:
            frames, durations = value, ()
        frames = tuple(frame for frame in (frames or ()) if frame is not None)
        durations = tuple(
            max(20, int(duration or 120)) for duration in (durations or ())
        )
        if not durations:
            durations = tuple(120 for _ in frames)
        elif len(durations) < len(frames):
            durations = durations + (durations[-1],) * (len(frames) - len(durations))
        return frames, durations[: len(frames)]

    cleaned = {str(name): _unpack(value) for name, value in states.items()}
    cleaned = {name: value for name, value in cleaned.items() if value[0]}
    if not cleaned:
        return {}, (0, 0)

    reference_name = reference if reference in cleaned else next(iter(cleaned))
    reference_frames, _ = cleaned[reference_name]
    reference_w = max(frame.width for frame in reference_frames)
    reference_h = max(frame.height for frame in reference_frames)
    scale = 1.0
    if target_size:
        target_w, target_h = int(target_size[0]), int(target_size[1])
        if target_w > 0 and target_h > 0 and reference_w > 0 and reference_h > 0:
            scale = min(target_w / float(reference_w), target_h / float(reference_h))

    scaled_sizes = {}
    max_w = 0
    max_h = 0
    for name, (frames, _durations) in cleaned.items():
        sizes = []
        for frame in frames:
            width = max(1, int(round(frame.width * scale)))
            height = max(1, int(round(frame.height * scale)))
            sizes.append((width, height))
            max_w = max(max_w, width)
            max_h = max(max_h, height)
        scaled_sizes[name] = sizes

    pad = max(0, int(bottom_pad))
    edge = max(0, int(margin))
    canvas_w = max_w + edge * 2
    canvas_h = max_h + pad + edge

    normalized = {}
    for name, (frames, durations) in cleaned.items():
        output = []
        for frame, size in zip(frames, scaled_sizes[name]):
            resized = frame if size == frame.size else frame.resize(size, _RESAMPLE)
            canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            bbox = resized.getchannel("A").getbbox()
            content_bottom = bbox[3] if bbox else resized.height
            x = (canvas_w - resized.width) // 2
            y = canvas_h - pad - content_bottom
            canvas.alpha_composite(resized, (max(0, x), max(0, y)))
            output.append(canvas)
        normalized[name] = (tuple(output), durations)
    return normalized, (canvas_w, canvas_h)


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


def thinking_frame_index(elapsed_ms: float, durations_ms) -> int:
    """Return the looping thinking frame for *elapsed_ms*.

    The thinking clip has a short intro (frames 1-6) followed by a ping-pong
    tail over frames 7-8-9-8.  The tail repeats forever, so this never reaches
    a natural end; the caller stops it when the replacement audio starts.
    """
    durations = tuple(max(1, int(value)) for value in durations_ms or ())
    if not durations:
        return 0

    intro_frames = min(THINKING_INTRO_FRAMES, len(durations))
    intro_total = sum(durations[:intro_frames])
    # Tk timestamps and float subtraction often land a hair below an exact
    # frame boundary.  A sub-millisecond nudge keeps the authored 120 ms cadence
    # without visibly changing the clip.
    elapsed = max(0.0, float(elapsed_ms)) + 0.001
    if elapsed < intro_total:
        return frame_index_at(elapsed, durations[:intro_frames])

    tail = tuple(index for index in THINKING_TAIL_FRAMES if index < len(durations))
    if not tail:
        return len(durations) - 1
    tail_durations = tuple(
        max(1, int(round(durations[index] * THINKING_TAIL_DURATION_SCALE)))
        for index in tail
    )
    offset = elapsed - intro_total
    return tail[frame_index_at(offset, tail_durations)]
