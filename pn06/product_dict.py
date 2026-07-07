"""
pn06 品种关键词词典

维护期货品种的正名、同义词和简称映射。
通过关键词匹配识别文章中的期货品种。
"""

from __future__ import annotations

# ---- 品种词典 ----
# 格式: "正名" → [正名变体, 同义词, 简称, 英文代码...]

PRODUCT_DICT: dict[str, list[str]] = {
    "螺纹钢":  ["螺纹钢", "螺纹", "钢筋", "钢材", "HRB400", "RB"],
    "铁矿石":  ["铁矿石", "铁矿", "矿石", "铁精矿"],
    "沪铜":    ["沪铜", "铜", "电解铜", "CU", "伦铜", "LME铜"],
    "原油":    ["原油", "SC原油", "WTI", "布伦特", "Brent", "美原油"],
    "豆粕":    ["豆粕", "豆粕期货", "豆粕合约"],
    "棕榈油":  ["棕榈油", "棕榈", "棕油"],
    "焦煤":    ["焦煤", "焦炭", "JM", "J焦炭", "焦煤期货"],
    "焦炭":    ["焦炭", "冶金焦", "J焦炭"],
    "黄金":    ["黄金", "金", "AU", "COMEX黄金", "沪金"],
    "白银":    ["白银", "银", "AG", "沪银"],
    "沪铝":    ["沪铝", "铝", "电解铝", "AL", "伦铝"],
    "沪锌":    ["沪锌", "锌", "ZN", "伦锌"],
    "沪镍":    ["沪镍", "镍", "NI", "伦镍"],
    "天然橡胶": ["天然橡胶", "橡胶", "RU", "沪胶"],
    "PTA":     ["PTA", "精对苯二甲酸", "TA"],
    "甲醇":    ["甲醇", "MA", "郑醇"],
    "沥青":    ["沥青", "BU"],
    "PX":      ["PX", "对二甲苯"],
    "乙二醇":  ["乙二醇", "MEG", "EG"],
    "短纤":    ["短纤", "PF"],
    "PP":      ["PP", "聚丙烯"],
    "白糖":    ["白糖", "糖", "SR", "郑糖"],
    "棉花":    ["棉花", "棉", "CF", "郑棉"],
    "玉米":    ["玉米", "C玉米", "玉米期货"],
    "豆油":    ["豆油", "豆油期货", "Y豆油"],
    "菜粕":    ["菜粕", "RM", "郑粕"],
    "菜油":    ["菜油", "OI", "郑油"],
    "生猪":    ["生猪", "LH"],
    "LLDPE":   ["LLDPE", "塑料", "L塑料", "聚乙烯"],
    "PVC":     ["PVC", "聚氯乙烯", "V"],
    "热轧卷板": ["热轧卷板", "热卷", "HC"],
    "玻璃":    ["玻璃", "FG", "郑玻"],
    "纯碱":    ["纯碱", "SA", "郑碱"],
}


# ---- 反向映射: 任一关键词 → 正名 ----
_alias_map: dict[str, str] | None = None


def get_alias_map() -> dict[str, str]:
    """获取关键词→正名的反向映射（懒加载）。"""
    global _alias_map
    if _alias_map is None:
        _alias_map = {}
        for canonical, aliases in PRODUCT_DICT.items():
            for alias in aliases:
                _alias_map[alias.lower()] = canonical
    return _alias_map


def detect_products(text: str) -> dict[str, int]:
    """
    从文本中检测所有提及的期货品种。

    Args:
        text: 清洗后的文章文本

    Returns:
        {正名: 提及次数}，按提及次数降序排列的品种
    """
    alias_map = get_alias_map()
    text_lower = text.lower()
    found: dict[str, int] = {}

    for alias_lower, canonical in alias_map.items():
        count = text_lower.count(alias_lower)
        if count > 0:
            found[canonical] = found.get(canonical, 0) + count

    return dict(sorted(found.items(), key=lambda x: x[1], reverse=True))


def get_primary_product(text: str) -> str | None:
    """
    获取文本中最主要的期货品种（出现次数最多）。

    Returns:
        品种正名，若未检测到任何品种则返回 None
    """
    products = detect_products(text)
    if not products:
        return None
    return next(iter(products))
