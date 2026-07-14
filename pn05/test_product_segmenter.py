from pn05.product_segmenter import segment_text


def test_segment_text_single_core_product() -> None:
    text = """# 铜日报

## 文档信息

来源文件: sample.html

## 核心正文

铜：关税不确定性铜承压震荡。
库存下降但需求受抑，短线谨慎参与。"""

    segments = segment_text(text)
    displayable = [segment for segment in segments if segment.product != "未知"]

    assert len(displayable) == 1
    assert displayable[0].product == "沪铜"
    assert displayable[0].section_type == "core"
    assert "库存下降" in displayable[0].cleaned_text


def test_segment_text_splits_multiple_product_prefix_blocks() -> None:
    text = """## 核心正文

乙二醇：供应压力仍高，价格承压，短期偏弱。
股指：海外扰动增加，风险偏好回落，维持震荡。"""

    segments = [segment for segment in segment_text(text) if segment.product != "未知"]

    assert [segment.product for segment in segments] == ["乙二醇", "股指"]
    assert "股指" not in segments[0].cleaned_text
    assert "乙二醇" not in segments[1].cleaned_text


def test_segment_text_splits_product_contract_code_boundaries() -> None:
    text = """## 核心正文

PVC05合约下跌39元，库存加速去化，成本支撑预期走强，短期偏弱震荡。
EG05合约下跌4元，乙二醇港口库存累库，预期震荡偏弱。"""

    segments = [segment for segment in segment_text(text) if segment.product != "未知"]

    assert [segment.product for segment in segments] == ["PVC", "乙二醇"]
    assert segments[0].contract == "05"
    assert segments[1].contract == "EG05"
    assert "EG05" not in segments[0].cleaned_text
    assert "PVC05" not in segments[1].cleaned_text


def test_segment_text_splits_pta_contract_code_with_space() -> None:
    text = """## 核心正文

PTA05 合约下跌52元，供给端仍处于检修季，加工费承压。"""

    segments = [segment for segment in segment_text(text) if segment.product != "未知"]

    assert len(segments) == 1
    assert segments[0].product == "PTA"
    assert segments[0].contract == "05"


def test_segment_text_splits_bracket_sections_in_ocr() -> None:
    text = """## 图文识别正文

【乙二醇】港口库存回升，供应压力偏高。【股指】市场波动加剧，观望为主。"""

    segments = [segment for segment in segment_text(text) if segment.product != "未知"]

    assert [segment.product for segment in segments] == ["乙二醇", "股指"]
    assert all(segment.section_type == "ocr" for segment in segments)


def test_segment_text_splits_donghai_aluminum_and_tin_blocks() -> None:
    text = """## 核心正文

【铝】铝锭小幅去库，铝棒库存依然高于去年同期，短期偏空。
【锡】传原定于4月1日召开的矿山复工复产交流会被取消，夜盘锡价上涨。
缅甸强震带来扰动，锡矿供应偏紧，锡价相对坚挺。"""

    segments = [segment for segment in segment_text(text) if segment.product != "未知"]

    assert [segment.product for segment in segments] == ["沪铝", "沪锡"]
    assert "【锡】" not in segments[0].cleaned_text
    assert "矿山复工复产交流会被取消" in segments[1].cleaned_text
    assert "锡矿供应偏紧" in segments[1].cleaned_text


def test_segment_text_keeps_steel_heading_as_group_product() -> None:
    text = """## 核心正文

【钢材】国内钢材期现货市场延续弱势。
有色铜价也承压，但本段观点仍是钢材。"""

    segments = [segment for segment in segment_text(text) if segment.product != "未知"]

    assert len(segments) == 1
    assert segments[0].product == "钢材"
    assert segments[0].product_key == "GROUP.SHFE.STEEL"
    assert segments[0].raw_product_name == "钢材"


def test_segment_text_uses_sentence_windows_for_multi_product_paragraph() -> None:
    text = """## 核心正文

乙二醇供应压力仍高。价格短期偏弱。股指受风险偏好影响。整体维持震荡。"""

    segments = [segment for segment in segment_text(text) if segment.product != "未知"]

    assert {segment.product for segment in segments} == {"乙二醇", "股指"}
    assert all(segment.section_type == "core" for segment in segments)
    assert any("价格短期偏弱" in segment.cleaned_text for segment in segments if segment.product == "乙二醇")


def test_segment_text_does_not_promote_low_frequency_cost_driver() -> None:
    text = """## 图文识别正文

观点: 聚乙烯震荡下行阶段，后期价格中枢有望下降。
逻辑: 聚乙烯产能压力巨大，基差回落，成本端原油预期也偏弱。"""

    segments = [segment for segment in segment_text(text) if segment.product != "未知"]

    assert [segment.product for segment in segments] == ["LLDPE"]
    assert "原油" in segments[0].cleaned_text


def test_segment_text_marks_unclear_multi_product_paragraph_as_mixed() -> None:
    text = """## 核心正文

乙二醇和股指均受宏观扰动影响，方向仍需等待进一步确认。"""

    segments = [segment for segment in segment_text(text) if segment.product != "未知"]

    assert {segment.product for segment in segments} == {"乙二醇", "股指"}
    assert all(segment.section_type == "mixed" for segment in segments)


def test_segment_text_preserves_unknown_text() -> None:
    text = """## 核心正文

研究报告仅包含宏观摘要，暂无明确品种。"""

    segments = segment_text(text)

    assert len(segments) == 1
    assert segments[0].product == "未知"
    assert segments[0].section_type == "core"


def test_segment_text_preserves_unknown_bracket_heading_as_boundary() -> None:
    text = """## 核心正文

【欧集线】运价预期偏强，供给扰动增加。
【沪铜】库存上升，需求承压。"""

    segments = segment_text(text)

    assert [segment.product for segment in segments] == ["未知", "沪铜"]
    assert segments[0].heading == "欧集线"
    assert "沪铜" not in segments[0].cleaned_text
    assert segments[0].section_type == "core"


def test_segment_text_keeps_pdf_wrapped_sentence_for_donghai_soybean_oil() -> None:
    text = """## 核心正文

【豆油】据Mysteel 调研显示，截至2025 年03 月28 日，全国重点地区豆油、棕
榈油、菜油三大油脂商业库存总量为198.55 万吨，较上周减少5.97 万吨，跌幅
2.92%；同比去年同期上涨20.25 万吨，涨幅11.36%。未来进口大豆到港紧缩状
况将逐步改善，阶段性供需转宽预期叠加消费疲软，市场情绪悲观、基差偏弱或
将持续。"""

    segments = [segment for segment in segment_text(text) if segment.product == "豆油"]

    assert len(segments) == 1
    assert "跌幅" in segments[0].cleaned_text
    assert "2.92%" in segments[0].cleaned_text
    assert segments[0].cleaned_text.index("跌幅") < segments[0].cleaned_text.index("2.92%")


def test_segment_text_does_not_create_soybean_oil_segment_from_us_soybean_oil() -> None:
    text = """## 核心正文

【棕榈油】近月马来西亚棕榈油增产季在即，出口环比持续疲软。
4 月份美豆油受政策不确定影响波动增加，马棕短期超跌叠加相关市场提振反弹较多，
但自身基本面趋弱且豆棕依然存在倒挂状态。"""

    products = [segment.product for segment in segment_text(text) if segment.product != "未知"]

    assert "棕榈油" in products
    assert "豆油" not in products
