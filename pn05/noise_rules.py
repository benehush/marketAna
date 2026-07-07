"""
pn05 噪声规则库

维护可扩展的噪声过滤规则：行级关键词和正则模式。
"""

from __future__ import annotations

import re

# ---- 行级关键词 ----
# 包含以下任一关键词的整行将被移除

NOISE_LINE_KEYWORDS: list[str] = [
    # 法律/免责
    "版权所有", "免责声明", "风险提示", "投资有风险", "市场有风险",
    "入市需谨慎", "期市有风险",
    # 营销/推广
    "扫码关注", "添加微信", "加我微信", "QQ群", "微信号",
    "点击关注", "转发", "点赞", "在看", "分享",
    "关注我们", "订阅", "公众号", "广告",
    "二维码", "下载APP", "下载 APP", "APP下载",
    # 联系方式
    "客服电话", "咨询电话", "免费热线", "联系电话",
    "客服热线", "客服中心", "客服 :",
    # 声明
    "本报告仅供参考", "未经许可", "不得转载", "不得复制",
    "未经本公司允许", "不得以任何方式", "商标、服务标识",
    "不作任何保证", "不构成投资", "任何担保", "注明出处",
    "Copyright", "All Rights Reserved",
    # 免责声明整段标记
    "本报告中的信息", "本报告不构成", "本报告版权",
    "本观点其于", "本观点基于", "据此投资", "风险自负", "投资者据此操作",
    # 官网页眉页脚/导航
    "无障碍浏览", "收藏本页面", "[打印]", "上一篇：", "下一篇：",
    "返回顶部", "相关信息", "浙公网安备", "ICP备案", "版权所有",
]


# ---- 整段正则模式 ----
# 匹配从标记词开始到段落结束的整段噪声

NOISE_REGEX_PATTERNS: list[str] = [
    # 免责声明段落
    r"免责声明[\s\S]*?(?=\n\n|\n(?=[^\s])|\Z)",
    r"免责申明[\s\S]*?(?=\n\n|\n(?=[^\s])|\Z)",
    # 风险提示段落
    r"风险提示[：:][\s\S]*?(?=\n\n|\n(?=[^\s])|\Z)",
    # 分析师声明
    r"分析师\s*(声明|承诺|简介)[\s\S]*?(?=\n\n|\n(?=[^\s])|\Z)",
    # 重要声明
    r"重要\s*(声明|事项|提示)[\s\S]*?(?=\n\n|\n(?=[^\s])|\Z)",
    # 法律声明
    r"(法律|合规)\s*声明[\s\S]*?(?=\n\n|\n(?=[^\s])|\Z)",
]


# ---- 纯噪声行模式 ----
# 这些行不包含任何有价值的信息

PURE_NOISE_PATTERNS: list[str] = [
    r"^https?://\S+$",                     # 纯 URL 行
    r"^[=\-_]{3,}$",                         # 纯分隔符行
    r"^[•·●○◆◇▪▸►▻]$",                      # 纯符号行
    r"^[\[\]【】大中小\s]+$",                  # 字号/括号控制行
    r"^\d{1,2}\s*/\s*\d{1,2}$",            # 纯页码
    r"^第[一二三四五六七八九十\d]+页$",          # 中文页码
    r"^400[-\s]?\d{3}[-\s]?\d{4}$",          # 客服电话
    r"^\d{3,5}-\d{6,8}$",                   # 固话
    r"^客服\s*[:：]\s*\d+$",                  # 客服 QQ
    r"^\s*$",                                 # 纯空白行（后续处理）
]


def filter_noise_lines(lines: list[str]) -> tuple[list[str], int]:
    """
    过滤噪声行。

    Args:
        lines: 文本行列表

    Returns:
        (过滤后的行列表, 被移除的行数)
    """
    kept: list[str] = []
    removed = 0

    for line in lines:
        stripped = line.strip()

        # 空行保留（用于段落分隔）
        if not stripped:
            kept.append(line)
            continue

        # 检查纯噪声模式
        if _match_any_pattern(stripped, PURE_NOISE_PATTERNS):
            removed += 1
            continue

        # 检查行级关键词
        if _contains_any_keyword(stripped, NOISE_LINE_KEYWORDS):
            removed += 1
            continue

        kept.append(line)

    return kept, removed


def filter_noise_regex(text: str) -> tuple[str, int]:
    """
    使用正则模式移除整段噪声。

    Args:
        text: 完整文本

    Returns:
        (过滤后的文本, 被移除的字符数)
    """
    original_length = len(text)
    for pattern in NOISE_REGEX_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
    removed_chars = original_length - len(text)
    return text, removed_chars


# ---- 内部函数 ----

def _contains_any_keyword(text: str, keywords: list[str]) -> bool:
    """检查文本是否包含任一关键词（不区分大小写）。"""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _match_any_pattern(text: str, patterns: list[str]) -> bool:
    """检查文本是否匹配任一正则模式。"""
    return any(re.match(p, text) for p in patterns)
