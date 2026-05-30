"""检索结果增强：时间衰减 + 来源质量加权"""
from datetime import datetime, timedelta
from typing import Optional

# 来源质量分数（0-1），可配置化
DEFAULT_SOURCE_QUALITY = {
    "reuters": 0.9,
    "bbc": 0.85,
    "techcrunch": 0.8,
    "theverge": 0.8,
    "ars technica": 0.8,
    "36kr": 0.75,
    "少数派": 0.7,
    "钛媒体": 0.7,
    "ifanr": 0.65,
    "hackernews": 0.6,
}

# 衰减半衰期（天）
DEFAULT_HALF_LIFE_DAYS = 30


def calculate_source_quality(source: str) -> float:
    """获取来源质量分数，默认 0.5"""
    if not source:
        return 0.5
    source_lower = source.lower()
    for known, score in DEFAULT_SOURCE_QUALITY.items():
        if known in source_lower:
            return score
    return 0.5


def calculate_time_decay(published_at, half_life_days: int = DEFAULT_HALF_LIFE_DAYS) -> float:
    """计算时间衰减因子（0-1）。

    发布时间越近，因子越高。
    超过半衰期后持续衰减，但不会为 0。
    """
    if not published_at:
        return 0.5  # 未知时间，默认 0.5

    try:
        if isinstance(published_at, (int, float)):
            # Epoch seconds from Milvus
            dt = datetime.fromtimestamp(published_at)
        elif isinstance(published_at, str):
            # 尝试解析 ISO 格式
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        else:
            dt = published_at

        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        age_days = (now - dt).days

        if age_days < 0:
            # 未来时间，惩罚
            return 0.3

        # 指数衰减：factor = 0.5 ^ (age / half_life)
        factor = 0.5 ** (age_days / half_life_days)
        return max(0.1, min(1.0, factor))  # 最低 0.1，避免完全置零
    except Exception:
        return 0.5


def boost_results(
    results: list[dict],
    use_time_decay: bool = True,
    use_source_quality: bool = True,
    time_weight: float = 0.3,
    source_weight: float = 0.2,
) -> list[dict]:
    """对检索结果加权。

    最终分数 = 原始分数 * (1 + time_weight * time_factor) * (1 + source_weight * quality_factor)

    保持原始排序，只调整分数。
    """
    boosted = []
    for r in results:
        original_score = r.get("score", 0)

        boost_factor = 1.0

        if use_time_decay:
            time_factor = calculate_time_decay(r.get("published_at"))
            boost_factor *= (1 + time_weight * time_factor)

        if use_source_quality:
            quality = calculate_source_quality(r.get("source", ""))
            boost_factor *= (1 + source_weight * quality)

        boosted_r = {**r, "boosted_score": original_score * boost_factor}
        boosted.append(boosted_r)

    # 按 boosted_score 重新排序
    boosted.sort(key=lambda x: x["boosted_score"], reverse=True)

    return boosted


