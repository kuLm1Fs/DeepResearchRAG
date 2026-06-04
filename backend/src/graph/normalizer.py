"""Post-processing rules for LLM-extracted entities and relations.

These are deterministic, fast, and run on the LLM's raw output before it ever
touches Neo4j. They are the *only* place that decides what an entity's
canonical name is — the LLM is free to use whatever surface form it likes.

The goal: given a list of {name, type} pairs (possibly with duplicates and
synonyms), produce a consistent canonical form so that downstream dedup via
`entity_id` works.
"""
from __future__ import annotations

from .schema import ENTITY_TYPES, Entity, Relation

# Alias dictionary. Keys are *post-strip* lowercase forms; values are the
# canonical (Chinese-preferred) form. Add more as you discover them in your
# corpus — this is the highest-leverage quality knob.
ALIAS_MAP: dict[str, str] = {
    # Tech majors
    "apple": "苹果",
    "aapl": "苹果",
    "苹果公司": "苹果",
    "microsoft": "微软",
    "msft": "微软",
    "google": "谷歌",
    "alphabet": "谷歌",
    "googl": "谷歌",
    "amazon": "亚马逊",
    "amzn": "亚马逊",
    "meta": "meta",
    "facebook": "meta",
    "fb": "meta",
    "nvidia": "英伟达",
    "nvda": "英伟达",
    "tesla": "特斯拉",
    "tsla": "特斯拉",
    "netflix": "奈飞",
    "nflx": "奈飞",
    # Chinese tech
    "tencent": "腾讯",
    "腾讯控股": "腾讯",
    "alibaba": "阿里巴巴",
    "阿里": "阿里巴巴",
    "baba": "阿里巴巴",
    "baidu": "百度",
    "bytedance": "字节跳动",
    "字节": "字节跳动",
    "douyin": "抖音",
    "tiktok": "抖音",
    "jd": "京东",
    "京东集团": "京东",
    "pdd": "拼多多",
    "拼夕夕": "拼多多",
    # Banks / finance
    "jpmorgan": "摩根大通",
    "jp morgan": "摩根大通",
    "goldman sachs": "高盛",
    "morgan stanley": "摩根士丹利",
    "citi": "花旗",
    "citibank": "花旗",
    "hsbc": "汇丰",
    "icbc": "工商银行",
    "工商银行": "工商银行",
    "中国工商银行": "工商银行",
    "ccb": "建设银行",
    "中国建设银行": "建设银行",
    "abc": "农业银行",
    "中国农业银行": "农业银行",
    "boc": "中国银行",
    "中国银行": "中国银行",
}

# Suffixes to strip (case-insensitive). Order matters: longer first.
STRIP_SUFFIXES: tuple[str, ...] = (
    "集团股份有限公司",
    "股份有限公司",
    "有限责任公司",
    "集团",
    "公司",
    "company",
    "co., ltd",
    "co. ltd",
    "co.,ltd",
    "co ltd",
    "inc.",
    "inc",
    "corp.",
    "corp",
    "corporation",
    "ltd.",
    "ltd",
    "limited",
    "plc",
    "llc",
    "gmbh",
    "ag",
    "sa",
    "s.a.",
)


def normalize_entity_name(name: str) -> str:
    """Return the canonical name for an entity.

    Steps:
      1. Strip whitespace, lowercase (preserves CJK characters unchanged).
      2. Strip corporate suffixes.
      3. Look up alias map.
    """
    if not name:
        return ""
    n = name.strip()
    # lowercase only the ASCII portion; CJK is unaffected by .lower()
    n = n.lower()
    # Strip suffixes (longest first, try multiple times to handle e.g.
    # "Apple Inc." -> "Apple" -> "Apple" after second pass).
    for _ in range(2):
        changed = False
        for suffix in STRIP_SUFFIXES:
            sfx = suffix.lower()
            if n.endswith(sfx) and len(n) > len(sfx):
                n = n[: -len(sfx)].strip()
                changed = True
                break
        if not changed:
            break
    n = n.strip()
    if n in ALIAS_MAP:
        return ALIAS_MAP[n]
    return n


def make_entity_id(name: str, type: str) -> str:
    """Build the canonical dedup key for an entity."""
    canonical = normalize_entity_name(name)
    # Use type as suffix to allow same name with different roles
    # e.g. "苹果" as Company vs "苹果" as Product (iOS).
    return f"{canonical}:{type}"


def is_valid_type(type: str) -> bool:
    return type in ENTITY_TYPES


def normalize_entity(
    raw: dict, source_chunk_id: str, *, min_description_length: int = 10
) -> Entity | None:
    """Build an Entity from a raw LLM dict, or None if it fails validation.

    Applies: name normalization, type enum check, description length filter.
    """
    name = (raw.get("name") or "").strip()
    type_ = (raw.get("type") or "").strip()
    desc = (raw.get("description") or "").strip()

    if not name or not type_ or not desc:
        return None
    if not is_valid_type(type_):
        return None
    if len(desc) < min_description_length:
        return None

    canonical = normalize_entity_name(name)
    if not canonical:
        return None

    return Entity(
        entity_id=make_entity_id(name, type_),
        name=canonical,
        type=type_,  # type: ignore[arg-type]
        description=desc,
        mention_count=1,
        source_chunk_ids=[source_chunk_id],
    )


def normalize_relation(
    raw: dict,
    source_chunk_id: str,
    *,
    min_description_length: int = 10,
) -> Relation | None:
    """Build a Relation from a raw LLM dict, or None if it fails validation.

    Weight is clamped to [0.0, 1.0]. Keywords are deduped and lowercased.
    """
    source = (raw.get("source") or "").strip()
    target = (raw.get("target") or "").strip()
    type_ = (raw.get("type") or "").strip()
    desc = (raw.get("description") or "").strip()

    if not source or not target or not type_ or not desc:
        return None
    if source.lower() == target.lower():
        return None  # self-loop is almost always noise
    if len(desc) < min_description_length:
        return None

    keywords_raw = raw.get("keywords") or []
    if not isinstance(keywords_raw, list):
        keywords_raw = []
    keywords = list({k.strip().lower() for k in keywords_raw if k and k.strip()})

    weight_raw = raw.get("weight", 0.5)
    try:
        weight = float(weight_raw)
    except (TypeError, ValueError):
        weight = 0.5
    weight = max(0.0, min(1.0, weight))

    return Relation(
        source=normalize_entity_name(source),
        target=normalize_entity_name(target),
        type=type_,
        description=desc,
        keywords=keywords,
        weight=weight,
        source_chunk_ids=[source_chunk_id],
    )
