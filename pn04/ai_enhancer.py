"""
pn04 可选 AI 增强。

该模块只做 parser 阶段的补充解读：当图片/图表 OCR 文本较难直接
进入规则识别时，用已配置的 OpenAI 兼容 LLM（如 SiliconFlow）生成可清洗的 Markdown
说明。AI 失败不影响 parser 成功。
"""

from __future__ import annotations

import logging
from pathlib import Path

from pn04.models import ParseConfig

logger = logging.getLogger(__name__)


class ParserAIEnhancer:
    """基于项目现有 LLM 配置的 parser 辅助解读器。"""

    def __init__(self, config: ParseConfig) -> None:
        self.config = config

    def enhance_image(
        self,
        *,
        image_path: str,
        ocr_text: str,
        title: str = "",
        context: str = "",
    ) -> str:
        """返回图片/图表的 Markdown 解读；未启用或失败时返回空字符串。"""
        if not self.config.parser_ai_enabled:
            return ""

        try:
            from pn07.llm_client import LLMAPIClient
            from pn07.models import LLMConfig

            llm_config = LLMConfig.from_settings()
            if self.config.parser_ai_model:
                llm_config.model = self.config.parser_ai_model
            if not llm_config.is_configured:
                logger.info("parser AI 未配置，跳过图片解读: %s", image_path)
                return ""

            client = LLMAPIClient(llm_config)
            prompt = self._build_prompt(
                image_path=image_path,
                ocr_text=ocr_text,
                title=title,
                context=context,
            )
            return client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是期货研究报告解析助手。只基于输入的 OCR 文本和上下文，"
                            "提取图表/图片中对下游趋势识别有用的信息。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                retries=0,
            ).strip()
        except Exception as exc:
            logger.warning("parser AI 图片解读失败 image=%s error=%s", image_path, exc)
            return ""

    @staticmethod
    def _build_prompt(
        *,
        image_path: str,
        ocr_text: str,
        title: str,
        context: str,
    ) -> str:
        clipped_ocr = ocr_text[:6000]
        clipped_context = context[:2000]
        return (
            f"文档标题：{title or Path(image_path).name}\n"
            f"图片路径：{image_path}\n"
            f"上下文：\n{clipped_context}\n\n"
            f"图片 OCR 文本：\n{clipped_ocr}\n\n"
            "请用 Markdown 输出，包含：\n"
            "1. 主要品种\n"
            "2. 方向线索（看涨/看跌/中性/无法确认）\n"
            "3. 表格或图表关键信息\n"
            "4. 无法确认的信息\n"
            "不要编造 OCR 文本中没有的信息。"
        )
