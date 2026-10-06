import hashlib
from typing import Any

import numpy as np

from api.config import PRIVACY_EPSILON, PRIVACY_K, PRIVACY_SALT


def generate_deterministic_noise(
    h3_cell: str,
    from_ts: str,
    to_ts: str,
    category: str | None = None,
    epsilon: float = PRIVACY_EPSILON,
    salt: str = PRIVACY_SALT,
) -> float:
    """
    Generates deterministic Laplace noise for a given cell, time window, and category.
    Using a deterministic seed prevents averaging attacks on repeated queries.
    """
    if epsilon <= 0:
        return 0.0

    # Deterministic seed from SHA256 of unique query dimensions + salt
    cat_str = category if category else "ALL"
    seed_str = f"{salt}:{h3_cell}:{from_ts}:{to_ts}:{cat_str}"
    digest = hashlib.sha256(seed_str.encode("utf-8")).digest()
    seed_int = int.from_bytes(digest[:8], byteorder="big", signed=False)

    rng = np.random.default_rng(seed_int)
    scale = 1.0 / epsilon
    return float(rng.laplace(0.0, scale))

def apply_privacy(
    cells: list[dict[str, Any]],
    from_ts: str,
    to_ts: str,
    category: str | None = None,
    k: int = PRIVACY_K,
    epsilon: float = PRIVACY_EPSILON,
    salt: str = PRIVACY_SALT,
) -> list[dict[str, Any]]:
    """
    Applies L3 K-anonymity suppression and L4 deterministic Laplace noise.
    Procedure:
      1. noisy = max(0, round(true_count + Laplace(0, 1/ε)))
      2. Drop cells where noisy < K
      3. Return noisy counts
    """
    result = []
    for item in cells:
        h3_cell = item["h3"]
        true_cnt = item.get("count", 0)

        if epsilon > 0:
            noise = generate_deterministic_noise(h3_cell, from_ts, to_ts, category, epsilon, salt)
            noisy_cnt = max(0, int(round(true_cnt + noise)))
        else:
            noisy_cnt = true_cnt

        # K-suppression on noisy count
        if noisy_cnt >= k:
            out_item = dict(item)
            out_item["count"] = noisy_cnt
            result.append(out_item)

    return result

def apply_zone_privacy(
    zones: list[dict[str, Any]],
    from_ts: str,
    to_ts: str,
    category: str | None = None,
    k: int = PRIVACY_K,
    epsilon: float = PRIVACY_EPSILON,
    salt: str = PRIVACY_SALT,
) -> list[dict[str, Any]]:
    """
    Applies privacy to top-zones ranking:
    Noise added to count and previous count, zones with count < K dropped.
    """
    result = []
    for z in zones:
        h3_cell = z["h3"]
        true_cnt = z.get("count", 0)
        true_prev = z.get("previous", 0)

        if epsilon > 0:
            noise_cur = generate_deterministic_noise(h3_cell, from_ts, to_ts, category, epsilon, salt)
            noisy_cur = max(0, int(round(true_cnt + noise_cur)))
            # Previous window has a different noise seed because from/to differ
            noise_prev = generate_deterministic_noise(h3_cell, f"prev_{from_ts}", f"prev_{to_ts}", category, epsilon, salt)
            noisy_prev = max(0, int(round(true_prev + noise_prev)))
        else:
            noisy_cur = true_cnt
            noisy_prev = true_prev

        if noisy_cur >= k:
            growth = 0.0
            if noisy_prev > 0:
                growth = round(((noisy_cur - noisy_prev) / noisy_prev) * 100.0, 1)
            elif noisy_cur > 0:
                growth = 100.0

            out_z = dict(z)
            out_z["count"] = noisy_cur
            out_z["previous"] = noisy_prev
            out_z["growth_pct"] = growth
            result.append(out_z)

    # Re-sort by noisy count and reassign ranks
    result.sort(key=lambda x: x["count"], reverse=True)
    for idx, r in enumerate(result, start=1):
        r["rank"] = idx

    return result
