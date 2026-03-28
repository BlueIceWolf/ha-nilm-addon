"""Shape similarity helpers for NILM profile curves."""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return default
        return num
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return default
        try:
            num = float(text)
        except ValueError:
            return default
        if math.isnan(num) or math.isinf(num):
            return default
        return num
    return default


def normalize_profile_points(points: object) -> List[float]:
    """Extract power values from profile point list into a numeric vector."""
    if not isinstance(points, list):
        return []

    values: List[float] = []
    for item in points:
        if isinstance(item, (int, float, str)):
            values.append(max(0.0, _safe_float(item)))
            continue
        if isinstance(item, dict):
            for key in ("power_w", "power", "value", "w", "watts", "p"):
                if key in item:
                    values.append(max(0.0, _safe_float(item.get(key))))
                    break
    return values


def _resample(values: Sequence[float], target_len: int = 32) -> List[float]:
    if target_len <= 1:
        return [float(values[0])] if values else [0.0]
    if not values:
        return [0.0] * target_len
    if len(values) == target_len:
        return [float(v) for v in values]

    out: List[float] = []
    n = len(values)
    for idx in range(target_len):
        pos = (idx * (n - 1)) / float(target_len - 1)
        lo = int(math.floor(pos))
        hi = min(n - 1, lo + 1)
        alpha = pos - lo
        val = (float(values[lo]) * (1.0 - alpha)) + (float(values[hi]) * alpha)
        out.append(val)
    return out


def _l2_norm(values: Iterable[float]) -> float:
    return math.sqrt(sum((float(v) ** 2) for v in values))


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    aa = _resample(a)
    bb = _resample(b)
    dot = sum((x * y) for x, y in zip(aa, bb))
    denom = _l2_norm(aa) * _l2_norm(bb)
    if denom <= 1e-9:
        return 0.0
    return max(-1.0, min(1.0, dot / denom))


def euclidean_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    aa = _resample(a)
    bb = _resample(b)
    dist = math.sqrt(sum(((x - y) ** 2) for x, y in zip(aa, bb)))
    scale = max(80.0, _l2_norm(aa), _l2_norm(bb))
    return max(0.0, min(1.0, 1.0 - (dist / scale)))


def dtw_similarity(a: Sequence[float], b: Sequence[float], window: int = 6) -> float:
    """Lightweight DTW-based similarity in [0,1]."""
    aa = _resample(a)
    bb = _resample(b)
    n = len(aa)
    m = len(bb)
    if n == 0 or m == 0:
        return 0.0

    w = max(window, abs(n - m))
    inf = float("inf")
    dp = [[inf for _ in range(m + 1)] for _ in range(n + 1)]
    dp[0][0] = 0.0

    for i in range(1, n + 1):
        start_j = max(1, i - w)
        end_j = min(m, i + w)
        for j in range(start_j, end_j + 1):
            cost = abs(aa[i - 1] - bb[j - 1])
            dp[i][j] = cost + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

    dist = dp[n][m]
    scale = max(80.0, sum(abs(v) for v in aa) / n, sum(abs(v) for v in bb) / m)
    norm = dist / max(scale * max(n, m), 1e-9)
    return max(0.0, min(1.0, 1.0 - norm))


def blended_shape_similarity(candidate_points: object, pattern_points: object) -> float:
    """Combine cosine/euclidean/DTW shape similarities into one robust score."""
    a = normalize_profile_points(candidate_points)
    b = normalize_profile_points(pattern_points)
    if not a or not b:
        return 0.0

    cos = (cosine_similarity(a, b) + 1.0) / 2.0
    euc = euclidean_similarity(a, b)
    dtw = dtw_similarity(a, b)

    return max(0.0, min(1.0, (0.42 * cos) + (0.33 * euc) + (0.25 * dtw)))
