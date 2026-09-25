"""Programmatic visual anchors for previously verified click routes."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageStat


STATUS_BAR_FRACTION = 0.06
MIN_ANCHOR_STD = 8.0
MATCH_THRESHOLD = 0.90
EDGE_MATCH_THRESHOLD = 0.80
UNIQUE_MATCH_MARGIN = 0.12


@dataclass(frozen=True)
class CapturedAnchor:
    png: bytes
    click_offset_px: Tuple[int, int]


@dataclass(frozen=True)
class AnchorMatch:
    point_px: Tuple[int, int]
    point_1000: Tuple[float, float]
    score: float
    margin: float
    edge_score: float
    edge_margin: float


@dataclass(frozen=True)
class EffectMatch:
    accepted: bool
    score: float = 0.0
    edge_score: float = 0.0
    area_ratio: float = 0.0


def identical_decoded_pixels(before: bytes, after: bytes) -> bool:
    """Only a valid, full-size exact match establishes no visible frame change."""
    try:
        with Image.open(BytesIO(before)) as left, Image.open(BytesIO(after)) as right:
            return (left.size == right.size and left.convert('RGBA').tobytes()
                    == right.convert('RGBA').tobytes())
    except (OSError, ValueError, TypeError):
        return False


def visible_change_ratio(before: bytes, after: bytes) -> Optional[float]:
    """Return the changed-pixel ratio outside narrow system-bar margins."""
    try:
        import cv2
        import numpy as np

        before_image = cv2.imdecode(
            np.frombuffer(before, np.uint8), cv2.IMREAD_COLOR)
        after_image = cv2.imdecode(
            np.frombuffer(after, np.uint8), cv2.IMREAD_COLOR)
    except (ImportError, TypeError, ValueError):
        return None
    if (before_image is None or after_image is None
            or before_image.shape != after_image.shape):
        return None
    difference = cv2.absdiff(before_image, after_image).max(axis=2)
    height = difference.shape[0]
    top = round(height * 0.04)
    bottom = max(top + 1, round(height * 0.97))
    content = difference[top:bottom]
    if not content.size:
        return None
    return float((content >= 16).mean())


def _pixel_point(
    width: int,
    height: int,
    point_1000: Sequence[float],
) -> Tuple[int, int]:
    return (
        round(float(point_1000[0]) * max(0, width - 1) / 1000.0),
        round(float(point_1000[1]) * max(0, height - 1) / 1000.0),
    )


def capture_click_anchor(
    screenshot: bytes,
    point_1000: Sequence[float],
) -> Optional[CapturedAnchor]:
    """Crop a small local visual anchor around an already grounded click."""
    try:
        with Image.open(BytesIO(screenshot)) as source:
            image = source.convert("RGB")
    except (OSError, TypeError, ValueError):
        return None
    width, height = image.size
    if width < 32 or height < 32 or len(point_1000) != 2:
        return None
    try:
        x, y = _pixel_point(width, height, point_1000)
    except (TypeError, ValueError):
        return None
    if y < height * STATUS_BAR_FRACTION:
        return None
    half = max(16, min(64, round(min(width, height) * 0.045)))
    left, top = max(0, x - half), max(0, y - half)
    right, bottom = min(width, x + half + 1), min(height, y + half + 1)
    crop = image.crop((left, top, right, bottom))
    if crop.width < 24 or crop.height < 24:
        return None
    if ImageStat.Stat(crop.convert("L")).stddev[0] < MIN_ANCHOR_STD:
        return None
    output = BytesIO()
    crop.save(output, format="PNG")
    return CapturedAnchor(
        png=output.getvalue(),
        click_offset_px=(x - left, y - top),
    )


def _peak(response, *, template_width: int, template_height: int):
    import cv2

    _minimum, best, _minimum_at, location = cv2.minMaxLoc(response)
    masked = response.copy()
    x, y = location
    masked[
        max(0, y - template_height):min(
            masked.shape[0], y + template_height + 1),
        max(0, x - template_width):min(
            masked.shape[1], x + template_width + 1),
    ] = -1.0
    second = float(cv2.minMaxLoc(masked)[1]) if masked.size else -1.0
    return location, float(best), float(best) - second


def relocate_click_anchor(
    anchor_png: bytes,
    click_offset_px: Sequence[int],
    screenshot: bytes,
) -> Optional[AnchorMatch]:
    """Locate an anchor only when grayscale and edge peaks are both unique."""
    try:
        import cv2
        import numpy as np

        template = cv2.imdecode(
            np.frombuffer(anchor_png, np.uint8), cv2.IMREAD_GRAYSCALE)
        scene = cv2.imdecode(
            np.frombuffer(screenshot, np.uint8), cv2.IMREAD_GRAYSCALE)
    except (ImportError, TypeError, ValueError):
        return None
    if template is None or scene is None or len(click_offset_px) != 2:
        return None
    height, width = template.shape[:2]
    if (height >= scene.shape[0] or width >= scene.shape[1]
            or height < 24 or width < 24
            or float(template.std()) < MIN_ANCHOR_STD):
        return None
    try:
        gray_response = cv2.matchTemplate(
            scene, template, cv2.TM_CCOEFF_NORMED)
        gray_at, score, margin = _peak(
            gray_response,
            template_width=width,
            template_height=height,
        )
        template_edges = cv2.Canny(template, 60, 160)
        scene_edges = cv2.Canny(scene, 60, 160)
        if float(template_edges.std()) < 4.0:
            return None
        edge_response = cv2.matchTemplate(
            scene_edges, template_edges, cv2.TM_CCOEFF_NORMED)
        edge_at, edge_score, edge_margin = _peak(
            edge_response,
            template_width=width,
            template_height=height,
        )
    except (TypeError, ValueError, cv2.error):
        return None
    if (score < MATCH_THRESHOLD
            or edge_score < EDGE_MATCH_THRESHOLD
            or margin < UNIQUE_MATCH_MARGIN
            or edge_margin < UNIQUE_MATCH_MARGIN
            or abs(gray_at[0] - edge_at[0]) > 3
            or abs(gray_at[1] - edge_at[1]) > 3):
        return None
    point = (
        gray_at[0] + int(click_offset_px[0]),
        gray_at[1] + int(click_offset_px[1]),
    )
    if (not 0 <= point[0] < scene.shape[1]
            or not scene.shape[0] * STATUS_BAR_FRACTION <= point[1] < scene.shape[0]):
        return None
    return AnchorMatch(
        point_px=point,
        point_1000=(
            point[0] * 1000.0 / max(1, scene.shape[1] - 1),
            point[1] * 1000.0 / max(1, scene.shape[0] - 1),
        ),
        score=score,
        margin=margin,
        edge_score=edge_score,
        edge_margin=edge_margin,
    )


def _effect_crop(before: bytes, after: bytes):
    try:
        import cv2
        import numpy as np

        before_image = cv2.imdecode(
            np.frombuffer(before, np.uint8), cv2.IMREAD_COLOR)
        after_image = cv2.imdecode(
            np.frombuffer(after, np.uint8), cv2.IMREAD_COLOR)
    except (ImportError, TypeError, ValueError):
        return None
    if (before_image is None or after_image is None
            or before_image.shape != after_image.shape):
        return None
    difference = cv2.absdiff(before_image, after_image)
    mask = (difference.max(axis=2) >= 16).astype("uint8") * 255
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
    )
    count, _labels, stats, _centers = cv2.connectedComponentsWithStats(mask)
    if count <= 1:
        return None
    minimum_area = max(24, round(mask.size * 0.00005))
    candidates = [
        stats[index]
        for index in range(1, count)
        if int(stats[index, cv2.CC_STAT_AREA]) >= minimum_area
    ]
    if not candidates:
        return None
    x, y, width, height, area = max(
        candidates, key=lambda item: int(item[cv2.CC_STAT_AREA]))
    padding = max(6, round(min(before_image.shape[:2]) * 0.006))
    left, top = max(0, int(x) - padding), max(0, int(y) - padding)
    right = min(after_image.shape[1], int(x + width) + padding)
    bottom = min(after_image.shape[0], int(y + height) + padding)
    if right - left < 24 or bottom - top < 24:
        return None
    return (
        after_image[top:bottom, left:right].copy(),
        float(area) / float(mask.size),
    )


def compare_action_effects(
    first_before: bytes,
    first_after: bytes,
    second_before: bytes,
    second_after: bytes,
) -> EffectMatch:
    """Fail-closed comparison of the largest visible change from two clicks."""
    first = _effect_crop(first_before, first_after)
    second = _effect_crop(second_before, second_after)
    if first is None or second is None:
        return EffectMatch(False)
    first_crop, first_area = first
    second_crop, second_area = second
    first_height, first_width = first_crop.shape[:2]
    second_height, second_width = second_crop.shape[:2]
    width_ratio = min(first_width, second_width) / max(first_width, second_width)
    height_ratio = min(first_height, second_height) / max(
        first_height, second_height)
    area_ratio = min(first_area, second_area) / max(first_area, second_area)
    if min(width_ratio, height_ratio, area_ratio) < 0.88:
        return EffectMatch(False, area_ratio=area_ratio)
    try:
        import cv2
    except ImportError:
        return EffectMatch(False, area_ratio=area_ratio)
    try:
        target_width = min(first_width, second_width, 640)
        target_height = min(first_height, second_height, 640)
        first_crop = cv2.resize(
            first_crop, (target_width, target_height),
            interpolation=cv2.INTER_AREA)
        second_crop = cv2.resize(
            second_crop, (target_width, target_height),
            interpolation=cv2.INTER_AREA)
        first_gray = cv2.cvtColor(first_crop, cv2.COLOR_BGR2GRAY)
        second_gray = cv2.cvtColor(second_crop, cv2.COLOR_BGR2GRAY)
        score = float(cv2.matchTemplate(
            first_gray, second_gray, cv2.TM_CCOEFF_NORMED)[0, 0])
        first_edge = cv2.Canny(first_gray, 60, 160)
        second_edge = cv2.Canny(second_gray, 60, 160)
        if min(float(first_edge.std()), float(second_edge.std())) < 4.0:
            return EffectMatch(False, score=score, area_ratio=area_ratio)
        edge_score = float(cv2.matchTemplate(
            first_edge, second_edge, cv2.TM_CCOEFF_NORMED)[0, 0])
    except (TypeError, ValueError, cv2.error):
        return EffectMatch(False, area_ratio=area_ratio)
    return EffectMatch(
        accepted=bool(score >= 0.94 and edge_score >= 0.80),
        score=score,
        edge_score=edge_score,
        area_ratio=area_ratio,
    )


__all__ = [
    "AnchorMatch",
    "CapturedAnchor",
    "EffectMatch",
    "capture_click_anchor",
    "compare_action_effects",
    "relocate_click_anchor",
]
