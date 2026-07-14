"""Direction signal patterns and their base weights."""

from __future__ import annotations

import re


PATTERN_WEIGHTS = {
    "direction_word": 1.00,
    "price_change": 0.90,
    "percentage": 0.90,
    "supply_demand": 0.75,
    "technical": 0.70,
    "momentum": 0.65,
    "sentiment": 0.45,
    "position": 0.55,
    "neutral": 0.50,
}


PATTERNS: tuple[tuple[str, str, str, str], ...] = (
    ("direction_word", "看涨", "bullish", r"看涨|看多|做多|利多|偏多|上行|走强|上涨|上升|反弹|回升|冲高|走高|强势"),
    ("direction_word", "看跌", "bearish", r"看跌|看空|做空|利空|偏空|下行|走弱|下跌|下降|回落|下滑|走低|弱势"),
    ("price_change", "看涨", "bullish", r"(?:上涨|涨|上升|增加|提升|扩大)\s*(?:约|幅度)?\s*[+-]?\d+(?:\.\d+)?\s*(?:%|％|元|点|个基点)?"),
    ("price_change", "看跌", "bearish", r"(?:下跌|跌|下降|减少|回落|降低|收窄)\s*(?:约|幅度)?\s*[+-]?\d+(?:\.\d+)?\s*(?:%|％|元|点|个基点)?"),
    ("supply_demand", "看涨", "bullish", r"(?:库存|仓单)(?:下降|减少|回落|去库)|(?:需求|消费)(?:改善|回暖|增加|旺盛)|供应(?:收紧|减少|偏紧)"),
    ("supply_demand", "看跌", "bearish", r"(?:库存|仓单)(?:上升|增加|累积)|(?:需求|消费)(?:走弱|下降|疲软|不佳)|供应(?:增加|宽松|过剩)"),
    ("technical", "看涨", "bullish", r"突破|上破|金叉|创(?:近期|阶段)?新高|底部反弹"),
    ("technical", "看跌", "bearish", r"破位|下破|死叉|创(?:近期|阶段)?新低|高位回落"),
    ("momentum", "看涨", "bullish", r"连续\d*日上涨|涨势延续|反弹延续|上涨动能"),
    ("momentum", "看跌", "bearish", r"连续\d*日下跌|跌势延续|下跌动能"),
    ("sentiment", "看涨", "bullish", r"市场情绪(?:偏多|乐观)|持仓(?:增加|上升)|成交活跃"),
    ("sentiment", "看跌", "bearish", r"市场情绪(?:偏空|悲观)|持仓(?:减少|下降)|成交低迷"),
    ("neutral", "中性", "neutral", r"震荡|区间运行|盘整|横盘|整理|观望|方向不明|窄幅波动|持稳|持平"),
)


COMPILED_PATTERNS = tuple(
    (signal_type, direction, label, re.compile(pattern))
    for signal_type, direction, label, pattern in PATTERNS
)
