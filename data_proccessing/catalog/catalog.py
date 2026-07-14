"""Independent standard catalog used by the data-processing pipeline.

This is intentionally kept inside ``data_proccessing`` so the package does not
depend on the legacy ``pn06`` implementation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductDefinition:
    product_key: str
    display_name: str
    official_name: str
    exchange: str
    symbol: str
    group: str
    aliases: tuple[str, ...] = ()
    active: bool = True


def _p(
    key: str,
    display: str,
    official: str,
    exchange: str,
    symbol: str,
    group: str,
    *aliases: str,
) -> ProductDefinition:
    return ProductDefinition(key, display, official, exchange, symbol, group, tuple(aliases))


PRODUCT_CATALOG: tuple[ProductDefinition, ...] = (
    # SHFE / INE metals
    _p("SHFE.CU", "沪铜", "铜", "SHFE", "CU", "有色金属", "沪铜", "铜", "电解铜"),
    _p("INE.BC", "国际铜", "国际铜", "INE", "BC", "有色金属", "国际铜", "铜BC"),
    _p("SHFE.AL", "沪铝", "铝", "SHFE", "AL", "有色金属", "沪铝", "铝", "电解铝"),
    _p("SHFE.ZN", "沪锌", "锌", "SHFE", "ZN", "有色金属", "沪锌", "锌"),
    _p("SHFE.PB", "沪铅", "铅", "SHFE", "PB", "有色金属", "沪铅", "铅"),
    _p("SHFE.NI", "沪镍", "镍", "SHFE", "NI", "有色金属", "沪镍", "镍"),
    _p("SHFE.SN", "沪锡", "锡", "SHFE", "SN", "有色金属", "沪锡", "锡"),
    _p("SHFE.AO", "氧化铝", "氧化铝", "SHFE", "AO", "有色金属", "氧化铝"),
    _p("SHFE.AD", "铸造铝合金", "铸造铝合金", "SHFE", "AD", "有色金属", "铸造铝合金", "铝合金"),
    _p("SHFE.AU", "黄金", "黄金", "SHFE", "AU", "贵金属", "黄金", "沪金"),
    _p("SHFE.AG", "白银", "白银", "SHFE", "AG", "贵金属", "白银", "沪银"),
    # SHFE ferrous / energy / materials
    _p("SHFE.RB", "螺纹钢", "螺纹钢", "SHFE", "RB", "黑色金属", "螺纹钢", "螺纹", "钢筋", "HRB400"),
    _p("SHFE.WR", "线材", "线材", "SHFE", "WR", "黑色金属", "线材", "盘条"),
    _p("SHFE.HC", "热轧卷板", "热轧卷板", "SHFE", "HC", "黑色金属", "热轧卷板", "热卷"),
    _p("SHFE.SS", "不锈钢", "不锈钢", "SHFE", "SS", "黑色金属", "不锈钢", "不锈钢期货"),
    _p("GROUP.SHFE.STEEL", "钢材", "钢材", "SHFE", "", "黑色金属", "钢材"),
    _p("SHFE.FU", "燃料油", "燃料油", "SHFE", "FU", "能源化工", "燃料油", "燃油"),
    _p("INE.LU", "低硫燃料油", "低硫燃料油", "INE", "LU", "能源化工", "低硫燃料油", "低硫燃油", "LU燃油", "LU燃料油"),
    _p("SHFE.BU", "沥青", "石油沥青", "SHFE", "BU", "能源化工", "沥青", "石油沥青"),
    _p("SHFE.BR", "合成橡胶", "丁二烯橡胶", "SHFE", "BR", "能源化工", "合成橡胶", "丁二烯橡胶", "BR橡胶", "丁二烯胶"),
    _p("SHFE.RU", "天然橡胶", "天然橡胶", "SHFE", "RU", "能源化工", "天然橡胶", "橡胶", "沪胶"),
    _p("INE.NR", "20号胶", "20号胶", "INE", "NR", "能源化工", "20号胶", "二十号胶"),
    _p("SHFE.SP", "纸浆", "纸浆", "SHFE", "SP", "轻工", "纸浆", "漂针浆"),
    _p("SHFE.OP", "胶版印刷纸", "胶版印刷纸", "SHFE", "OP", "轻工", "胶版印刷纸", "胶版纸"),
    _p("INE.SC", "原油", "原油", "INE", "SC", "能源化工", "原油", "SC原油"),
    _p("INE.EC", "集运指数（欧线）", "集运指数（欧线）", "INE", "EC", "航运指数", "集运指数（欧线）", "集运欧线", "欧线集运", "SCFIS欧线"),
    # DCE agriculture
    _p("DCE.A", "豆一", "黄大豆1号", "DCE", "A", "农产品", "豆一", "黄大豆1号", "黄大豆一号", "A豆一"),
    _p("DCE.B", "豆二", "黄大豆2号", "DCE", "B", "农产品", "豆二", "黄大豆2号", "黄大豆二号", "B豆二"),
    _p("DCE.M", "豆粕", "豆粕", "DCE", "M", "农产品", "豆粕", "豆粕期货", "豆粕合约"),
    _p("DCE.Y", "豆油", "豆油", "DCE", "Y", "农产品", "豆油", "豆油期货", "Y豆油"),
    _p("DCE.P", "棕榈油", "棕榈油", "DCE", "P", "农产品", "棕榈油", "棕榈", "棕油"),
    _p("DCE.C", "玉米", "玉米", "DCE", "C", "农产品", "玉米", "C玉米", "玉米期货"),
    _p("DCE.CS", "玉米淀粉", "玉米淀粉", "DCE", "CS", "农产品", "玉米淀粉", "淀粉"),
    _p("DCE.RR", "粳米", "粳米", "DCE", "RR", "农产品", "粳米"),
    _p("DCE.JD", "鸡蛋", "鸡蛋", "DCE", "JD", "农产品", "鸡蛋"),
    _p("DCE.LH", "生猪", "生猪", "DCE", "LH", "农产品", "生猪"),
    # DCE industrial / chemical
    _p("DCE.I", "铁矿石", "铁矿石", "DCE", "I", "黑色金属", "铁矿石", "铁矿", "铁精矿"),
    _p("DCE.J", "焦炭", "焦炭", "DCE", "J", "黑色金属", "焦炭", "冶金焦", "J焦炭"),
    _p("DCE.JM", "焦煤", "焦煤", "DCE", "JM", "黑色金属", "焦煤", "焦煤期货"),
    _p("DCE.L", "LLDPE", "线型低密度聚乙烯", "DCE", "L", "能源化工", "LLDPE", "塑料", "L塑料", "聚乙烯"),
    _p("DCE.V", "PVC", "聚氯乙烯", "DCE", "V", "能源化工", "PVC", "聚氯乙烯"),
    _p("DCE.PP", "PP", "聚丙烯", "DCE", "PP", "能源化工", "PP", "聚丙烯"),
    _p("DCE.EG", "乙二醇", "乙二醇", "DCE", "EG", "能源化工", "乙二醇", "MEG"),
    _p("DCE.EB", "苯乙烯", "苯乙烯", "DCE", "EB", "能源化工", "苯乙烯"),
    _p("DCE.PG", "液化气", "液化石油气", "DCE", "PG", "能源化工", "液化气", "液化石油气", "LPG"),
    _p("DCE.BZ", "纯苯", "纯苯", "DCE", "BZ", "能源化工", "纯苯"),
    _p("DCE.LG", "原木", "原木", "DCE", "LG", "林产品", "原木", "针叶原木", "原木期货", "LG原木"),
    _p("DCE.FB", "纤维板", "纤维板", "DCE", "FB", "轻工", "纤维板"),
    _p("DCE.BB", "胶合板", "胶合板", "DCE", "BB", "轻工", "胶合板"),
    # CZCE agriculture
    _p("CZCE.CF", "棉花", "棉花", "CZCE", "CF", "农产品", "棉花", "郑棉"),
    _p("CZCE.CY", "棉纱", "棉纱", "CZCE", "CY", "农产品", "棉纱"),
    _p("CZCE.SR", "白糖", "白糖", "CZCE", "SR", "农产品", "白糖", "郑糖"),
    _p("CZCE.OI", "菜油", "菜籽油", "CZCE", "OI", "农产品", "菜油", "菜籽油", "郑油"),
    _p("CZCE.RM", "菜粕", "菜籽粕", "CZCE", "RM", "农产品", "菜粕", "菜籽粕", "郑粕"),
    _p("CZCE.RS", "油菜籽", "油菜籽", "CZCE", "RS", "农产品", "油菜籽", "菜籽"),
    _p("CZCE.AP", "苹果", "苹果", "CZCE", "AP", "农产品", "苹果"),
    _p("CZCE.CJ", "红枣", "红枣", "CZCE", "CJ", "农产品", "红枣"),
    _p("CZCE.PK", "花生", "花生", "CZCE", "PK", "农产品", "花生"),
    _p("CZCE.WH", "强麦", "优质强筋小麦", "CZCE", "WH", "农产品", "强麦", "优质强筋小麦", "强筋小麦"),
    _p("CZCE.PM", "普麦", "普通小麦", "CZCE", "PM", "农产品", "普麦", "普通小麦"),
    _p("CZCE.RI", "早籼稻", "早籼稻", "CZCE", "RI", "农产品", "早籼稻"),
    _p("CZCE.JR", "粳稻", "粳稻", "CZCE", "JR", "农产品", "粳稻"),
    _p("CZCE.LR", "晚籼稻", "晚籼稻", "CZCE", "LR", "农产品", "晚籼稻"),
    # CZCE chemicals / materials
    _p("CZCE.TA", "PTA", "精对苯二甲酸", "CZCE", "TA", "能源化工", "PTA", "精对苯二甲酸"),
    _p("CZCE.MA", "甲醇", "甲醇", "CZCE", "MA", "能源化工", "甲醇", "郑醇"),
    _p("CZCE.FG", "玻璃", "玻璃", "CZCE", "FG", "建材", "玻璃", "郑玻"),
    _p("CZCE.UR", "尿素", "尿素", "CZCE", "UR", "能源化工", "尿素"),
    _p("CZCE.SA", "纯碱", "纯碱", "CZCE", "SA", "能源化工", "纯碱", "郑碱"),
    _p("CZCE.PF", "短纤", "短纤", "CZCE", "PF", "能源化工", "短纤", "涤纶短纤"),
    _p("CZCE.PX", "PX", "对二甲苯", "CZCE", "PX", "能源化工", "PX", "对二甲苯"),
    _p("CZCE.SH", "烧碱", "烧碱", "CZCE", "SH", "能源化工", "烧碱"),
    _p("CZCE.PR", "瓶片", "瓶片", "CZCE", "PR", "能源化工", "瓶片", "聚酯瓶片"),
    _p("CZCE.PL", "丙烯", "丙烯", "CZCE", "PL", "能源化工", "丙烯"),
    _p("CZCE.SF", "硅铁", "硅铁", "CZCE", "SF", "黑色金属", "硅铁"),
    _p("CZCE.SM", "锰硅", "锰硅", "CZCE", "SM", "黑色金属", "锰硅", "硅锰"),
    _p("CZCE.ZC", "动力煤", "动力煤", "CZCE", "ZC", "能源", "动力煤", "郑煤"),
    # GFEX
    _p("GFEX.SI", "工业硅", "工业硅", "GFEX", "SI", "新能源材料", "工业硅"),
    _p("GFEX.LC", "碳酸锂", "碳酸锂", "GFEX", "LC", "新能源材料", "碳酸锂"),
    _p("GFEX.PS", "多晶硅", "多晶硅", "GFEX", "PS", "新能源材料", "多晶硅"),
    _p("GFEX.PT", "铂", "铂", "GFEX", "PT", "贵金属", "铂", "铂金"),
    _p("GFEX.PD", "钯", "钯", "GFEX", "PD", "贵金属", "钯", "钯金"),
    # CFFEX concrete products
    _p("CFFEX.IF", "沪深300股指", "沪深300股指期货", "CFFEX", "IF", "股指期货", "沪深300股指", "沪深300", "IF股指"),
    _p("CFFEX.IH", "上证50股指", "上证50股指期货", "CFFEX", "IH", "股指期货", "上证50股指", "上证50", "IH股指"),
    _p("CFFEX.IC", "中证500股指", "中证500股指期货", "CFFEX", "IC", "股指期货", "中证500股指", "中证500", "IC股指"),
    _p("CFFEX.IM", "中证1000股指", "中证1000股指期货", "CFFEX", "IM", "股指期货", "中证1000", "IM股指"),
    _p("CFFEX.TS", "2年期国债", "2年期国债期货", "CFFEX", "TS", "国债期货", "2年期国债", "二年期国债", "二债"),
    _p("CFFEX.TF", "5年期国债", "5年期国债期货", "CFFEX", "TF", "国债期货", "5年期国债", "五年期国债", "五债"),
    _p("CFFEX.T", "10年期国债", "10年期国债期货", "CFFEX", "T", "国债期货", "10年期国债", "十年期国债", "十债"),
    _p("CFFEX.TL", "30年期国债", "30年期国债期货", "CFFEX", "TL", "国债期货", "30年期国债", "三十年期国债", "三十债"),
    _p("GROUP.CFFEX.INDEX", "股指", "股指期货", "CFFEX", "", "股指期货", "股指", "股指期货"),
    _p("GROUP.CFFEX.BOND", "国债", "国债期货", "CFFEX", "", "国债期货", "国债", "国债期货"),
)

PRODUCT_BY_KEY = {item.product_key: item for item in PRODUCT_CATALOG}
PRODUCT_BY_DISPLAY_NAME = {item.display_name: item for item in PRODUCT_CATALOG}
PRODUCT_BY_SYMBOL = {item.symbol.upper(): item for item in PRODUCT_CATALOG if item.symbol}


def get_product(product_key: str | None) -> ProductDefinition | None:
    return PRODUCT_BY_KEY.get((product_key or "").strip().upper())


def product_key_for_name(name: str | None) -> str:
    item = PRODUCT_BY_DISPLAY_NAME.get((name or "").strip())
    return item.product_key if item else ""


def product_group(product_key: str | None) -> str:
    item = get_product(product_key)
    return item.group if item else ""


def product_for_symbol(symbol: str | None) -> ProductDefinition | None:
    return PRODUCT_BY_SYMBOL.get((symbol or "").strip().upper())


def validate_catalog() -> None:
    keys: set[str] = set()
    symbols: set[str] = set()
    aliases: dict[str, str] = {}
    for item in PRODUCT_CATALOG:
        if item.product_key in keys:
            raise ValueError(f"duplicate product_key: {item.product_key}")
        keys.add(item.product_key)
        if item.symbol:
            symbol_key = item.symbol.upper()
            if symbol_key in symbols:
                raise ValueError(f"duplicate futures symbol: {item.symbol}")
            symbols.add(symbol_key)
        for alias in {item.display_name, item.official_name, *item.aliases}:
            normalized = alias.strip().casefold()
            previous = aliases.get(normalized)
            if previous and previous != item.product_key:
                raise ValueError(f"duplicate product alias: {alias} -> {previous}, {item.product_key}")
            aliases[normalized] = item.product_key


validate_catalog()
