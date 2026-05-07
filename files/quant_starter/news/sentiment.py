"""
新闻情感分析模块（T+1 辅助决策）

核心思路：
  大A实行 T+1 交易制度，当日14:30之后的新闻直接影响第二日操作。
  本模块通过关键词匹配对股票新闻进行情感打分，作为技术信号的"否决/增强"过滤器。

使用方式：
    from news.sentiment import get_news_sentiment
    result = get_news_sentiment("600519", "贵州茅台")
    # result = {
    #   "score": 0.3,         # -1(极度利空) ~ +1(极度利好)
    #   "label": "轻度利好",
    #   "veto": False,         # True = 建议否决买入信号
    #   "boost": True,         # True = 可增强买入置信度
    #   "headlines": [...],    # 关键新闻标题列表
    #   "news_count": 5,       # 获取到的新闻总数
    #   "source": "akshare",   # 数据来源
    # }

局限性说明：
  ✗ 关键词匹配无法理解否定句（如"业绩没有下滑"会被误判）
  ✗ 无法判断新闻时效性的市场消化程度
  ✓ 适合作为强利空新闻的否决过滤器
  ✓ 后期可升级接入 Claude API 做语义级情感分析
"""
import datetime
import re
from typing import Optional


# ── 关键词库 ──────────────────────────────────────────────────────────────────

# 权重说明：3=强信号，2=中等信号，1=弱信号/辅助

POSITIVE_KEYWORDS = {
    # 重大利好（权重3）
    "获批": 3, "中标": 3, "大额订单": 3, "大单": 3, "重大合同": 3,
    "业绩大增": 3, "业绩爆发": 3, "扭亏": 3, "特别分红": 3,
    "政策利好": 3, "重大利好": 3, "利好政策": 3,
    # 常规利好（权重2）
    "利好": 2, "超预期": 2, "业绩增长": 2, "收入增长": 2, "净利润增长": 2,
    "订单": 2, "新合同": 2, "战略合作": 2, "回购": 2, "增持": 2,
    "分红": 2, "股息": 2, "新高": 2, "产能扩张": 2, "并购": 2,
    "国产替代": 2, "新质生产力": 2, "AI赋能": 2, "突破": 2,
    "获奖": 2, "入选": 2, "纳入": 2, "重组": 2,
    # 辅助利好（权重1）
    "业绩预增": 1, "向好": 1, "积极": 1, "乐观": 1, "提升": 1,
    "新品": 1, "创新": 1, "研发突破": 1,
}

NEGATIVE_KEYWORDS = {
    # 严重利空（权重3）
    "立案调查": 3, "立案": 3, "债务违约": 3, "违约": 3,
    "退市": 3, "暂停上市": 3, "强制退市": 3, "爆雷": 3, "暴雷": 3,
    "资不抵债": 3, "破产": 3, "破产重整": 3,
    # 中等利空（权重2）
    "违规": 2, "处罚": 2, "监管处罚": 2, "罚款": 2, "诉讼": 2,
    "亏损": 2, "大幅亏损": 2, "业绩大降": 2, "业绩暴跌": 2,
    "减持": 2, "大幅减持": 2, "质押": 2, "高比例质押": 2,
    "利空": 2, "ST": 2, "摘牌": 2, "被动减持": 2,
    "大额解禁": 2, "解禁": 2,
    # 轻度利空（权重1）
    "预亏": 1, "业绩下滑": 1, "收入下降": 1, "下行压力": 1,
    "降级": 1, "评级下调": 1, "产能过剩": 1, "竞争加剧": 1,
    "调查": 1, "关注函": 1, "问询函": 1, "业绩变脸": 1,
}

# 超高权重否决词（直接触发 veto）
VETO_KEYWORDS = {"立案调查", "立案", "债务违约", "退市", "暂停上市", "爆雷", "暴雷", "破产"}


def _score_text(text: str, pos_kw: dict, neg_kw: dict) -> tuple:
    """对单条文本做关键词打分，返回 (pos_score, neg_score, matched_pos, matched_neg)"""
    pos_score, neg_score = 0.0, 0.0
    matched_pos, matched_neg = [], []

    for kw, weight in pos_kw.items():
        if kw in text:
            pos_score += weight
            matched_pos.append(kw)

    for kw, weight in neg_kw.items():
        if kw in text:
            neg_score += weight
            matched_neg.append(kw)

    return pos_score, neg_score, matched_pos, matched_neg


def get_news_sentiment(
    code: str,
    name: str,
    hours: int = 48,
    min_score: float = 0.0,
) -> dict:
    """
    获取并分析股票近期新闻情感。

    参数：
        code  : 股票代码，如 "600519"
        name  : 股票名称，如 "贵州茅台"
        hours : 只看最近 N 小时内的新闻（默认48h，覆盖昨天+今天）
        min_score : 触发 veto 的最低利空分阈值（默认0）

    返回 dict：
        score       : float, -1 ~ +1，负数=利空，正数=利好
        label       : str, "重大利空" / "轻度利空" / "中性" / "轻度利好" / "重大利好"
        veto        : bool, True=建议否决买入信号
        boost       : bool, True=可增强买入置信度
        headlines   : list[str], 关键新闻标题
        neg_matches : list[str], 命中的利空关键词
        pos_matches : list[str], 命中的利好关键词
        news_count  : int, 获取到的新闻总数
        source      : str, 数据来源
        error       : str|None, 出错时的描述
    """
    result = {
        "score":       0.0,
        "label":       "中性",
        "veto":        False,
        "boost":       False,
        "headlines":   [],
        "neg_matches": [],
        "pos_matches": [],
        "news_count":  0,
        "source":      "none",
        "error":       None,
    }

    # ── 尝试 AKShare 获取新闻 ─────────────────────────────────────────────
    try:
        import akshare as ak
        # AKShare stock_news_em 参数为股票代码
        df = ak.stock_news_em(symbol=code)
        result["source"] = "akshare_em"
    except Exception as e1:
        try:
            # 部分版本接受股票名称
            import akshare as ak
            df = ak.stock_news_em(symbol=name)
            result["source"] = "akshare_em_name"
        except Exception as e2:
            result["error"] = f"新闻获取失败: {e2}"
            return result

    if df is None or df.empty:
        result["error"] = "无新闻数据"
        return result

    result["news_count"] = len(df)

    # ── 时间过滤：只看最近 hours 小时 ─────────────────────────────────────
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=hours)
    time_col = None
    for col in ["发布时间", "时间", "datetime", "date", "pub_time"]:
        if col in df.columns:
            time_col = col
            break

    if time_col:
        try:
            df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
            df = df[df[time_col] >= cutoff]
        except Exception:
            pass  # 时间解析失败时忽略过滤

    if df.empty:
        result["error"] = f"最近 {hours}h 内无新闻"
        return result

    # ── 找到标题列 ─────────────────────────────────────────────────────────
    title_col = None
    for col in ["新闻标题", "标题", "title", "新闻内容"]:
        if col in df.columns:
            title_col = col
            break
    if title_col is None:
        title_col = df.columns[0]

    # ── 逐条打分 ──────────────────────────────────────────────────────────
    total_pos, total_neg = 0.0, 0.0
    all_pos_kw, all_neg_kw = [], []
    key_headlines = []
    veto_triggered = False

    for _, row in df.iterrows():
        text = str(row.get(title_col, ""))
        if not text or len(text) < 3:
            continue

        ps, ns, pm, nm = _score_text(text, POSITIVE_KEYWORDS, NEGATIVE_KEYWORDS)
        total_pos += ps
        total_neg += ns
        all_pos_kw.extend(pm)
        all_neg_kw.extend(nm)

        # 命中否决词
        for vkw in VETO_KEYWORDS:
            if vkw in text:
                veto_triggered = True
                key_headlines.append(f"[严重利空] {text[:60]}")
                break
        else:
            if ps > 0 or ns > 0:
                tag = "[利好]" if ps > ns else "[利空]"
                key_headlines.append(f"{tag} {text[:60]}")

    # ── 计算综合分数 ───────────────────────────────────────────────────────
    denom = total_pos + total_neg
    if denom > 0:
        raw_score = (total_pos - total_neg) / denom
    else:
        raw_score = 0.0

    # ── 设置标签和 veto/boost ─────────────────────────────────────────────
    if veto_triggered or total_neg >= 6:
        label = "重大利空"
        veto  = True
        boost = False
    elif total_neg >= 3:
        label = "轻度利空"
        veto  = False
        boost = False
    elif total_pos >= 4:
        label = "重大利好"
        veto  = False
        boost = True
    elif total_pos >= 2:
        label = "轻度利好"
        veto  = False
        boost = True
    else:
        label = "中性"
        veto  = False
        boost = False

    # 去重关键词
    pos_kw_unique = list(dict.fromkeys(all_pos_kw))
    neg_kw_unique = list(dict.fromkeys(all_neg_kw))

    result.update({
        "score":       round(raw_score, 3),
        "label":       label,
        "veto":        veto,
        "boost":       boost,
        "headlines":   key_headlines[:8],   # 最多展示8条
        "pos_matches": pos_kw_unique,
        "neg_matches": neg_kw_unique,
    })
    return result


def news_modifier(sentiment: dict) -> float:
    """
    将情感结果转化为复合评分修正值（叠加到 composite_score 上）。
    范围：-20（重大利空）~ +8（重大利好）。
    不对称设计：利空惩罚 > 利好奖励（风险控制优先）。
    """
    if sentiment.get("error"):
        return 0.0
    label = sentiment.get("label", "中性")
    return {
        "重大利空": -20.0,
        "轻度利空":  -8.0,
        "中性":       0.0,
        "轻度利好":  +4.0,
        "重大利好":  +8.0,
    }.get(label, 0.0)


# 避免在顶层导入（允许无 pandas 环境导入本文件的常量）
try:
    import pandas as pd
except ImportError:
    pass
