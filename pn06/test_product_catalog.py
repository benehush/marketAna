from pn06.product_catalog import PRODUCT_CATALOG, get_product
from pn06.product_dict import ProductMatcher, detect_products


def test_catalog_has_unique_identity_and_required_financial_products() -> None:
    keys = [item.product_key for item in PRODUCT_CATALOG]
    assert len(keys) == len(set(keys))
    for key in (
        "CFFEX.IF", "CFFEX.IH", "CFFEX.IC", "CFFEX.IM",
        "CFFEX.TS", "CFFEX.TF", "CFFEX.T", "CFFEX.TL",
    ):
        assert get_product(key) is not None


def test_catalog_includes_dce_timber_futures() -> None:
    item = get_product("DCE.LG")
    assert item is not None
    assert item.display_name == "原木"
    assert item.official_name == "原木"
    assert item.symbol == "LG"


def test_catalog_covers_wenhua_commodity_index_names() -> None:
    wenhua_name_to_display = {
        "铜": "沪铜",
        "铝": "沪铝",
        "锌": "沪锌",
        "铅": "沪铅",
        "镍": "沪镍",
        "锡": "沪锡",
        "氧化铝": "氧化铝",
        "多晶硅": "多晶硅",
        "碳酸锂": "碳酸锂",
        "工业硅": "工业硅",
        "不锈钢": "不锈钢",
        "螺纹钢": "螺纹钢",
        "原油": "原油",
        "燃料油": "燃料油",
        "液化气": "液化气",
        "LU燃油": "低硫燃料油",
        "玻璃": "玻璃",
        "橡胶": "天然橡胶",
        "BR橡胶": "合成橡胶",
        "20号胶": "20号胶",
        "塑料": "LLDPE",
        "PVC": "PVC",
        "PTA": "PTA",
        "短纤": "短纤",
        "瓶片": "瓶片",
        "甲醇": "甲醇",
        "丙烯": "丙烯",
        "聚丙烯": "PP",
        "苯乙烯": "苯乙烯",
        "沥青": "沥青",
        "乙二醇": "乙二醇",
        "尿素": "尿素",
        "纯碱": "纯碱",
        "烧碱": "烧碱",
        "对二甲苯": "PX",
        "焦煤": "焦煤",
        "焦炭": "焦炭",
        "铁矿石": "铁矿石",
        "热卷": "热轧卷板",
        "锰硅": "锰硅",
        "硅铁": "硅铁",
        "纸浆": "纸浆",
        "豆一": "豆一",
        "玉米": "玉米",
        "豆粕": "豆粕",
        "菜籽粕": "菜粕",
        "花生": "花生",
        "豆油": "豆油",
        "棕榈油": "棕榈油",
        "菜籽油": "菜油",
        "棉花": "棉花",
        "白糖": "白糖",
        "鸡蛋": "鸡蛋",
        "玉米淀粉": "玉米淀粉",
        "苹果": "苹果",
        "红枣": "红枣",
        "生猪": "生猪",
    }

    matcher = ProductMatcher()
    for wenhua_name, display_name in wenhua_name_to_display.items():
        assert matcher.resolve_name(wenhua_name).display_name == display_name


def test_matcher_uses_longest_non_overlapping_alias() -> None:
    assert detect_products("玉米淀粉库存回升") == {"玉米淀粉": 1}
    assert detect_products("玉米走弱，玉米淀粉偏强") == {"玉米": 1, "玉米淀粉": 1}
    assert detect_products("低硫燃料油库存下降") == {"低硫燃料油": 1}
    assert detect_products("针叶原木供应偏紧，LG2609合约走强") == {"原木": 2}


def test_matcher_separates_financial_children_and_aggregate_fallbacks() -> None:
    products = detect_products("IF2609偏强，十债走弱，股指整体震荡，国债整体偏多")
    assert set(products) == {"沪深300股指", "10年期国债", "股指", "国债"}
    assert detect_products("T2609上涨") == {"10年期国债": 1}


def test_external_markets_are_not_domestic_product_aliases() -> None:
    assert detect_products("WTI与Brent上涨，LME铜走强，COMEX黄金回落") == {}


def test_dynamic_alias_only_matches_when_supplied() -> None:
    assert ProductMatcher().detect_products("欧集线偏强") == {}
    matcher = ProductMatcher(dynamic_aliases={"欧集线": "INE.EC"})
    assert matcher.detect_products("欧集线偏强") == {"集运指数（欧线）": 1}
