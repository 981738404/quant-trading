"""
每日14:30盘前总结报告

对 watchlist.json 中所有标的运行策略扫描 + 共识过滤，
输出今日操作建议（买入/卖出/观望），适合在收盘前30分钟执行。

用法：
    python3 daily_report.py                  # 使用默认 watchlist.json
    python3 daily_report.py --watch my.json  # 指定自定义股票池

watchlist.json 格式：
    [
      {"code": "605099", "name": "共创草坪"},
      {"code": "300274", "name": "阳光电源"}
    ]
"""
import sys, warnings, argparse, datetime, json
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

R    = "\033[0m"
RED  = "\033[91m"
GRN  = "\033[92m"
YLW  = "\033[93m"
CYN  = "\033[96m"
BOLD = "\033[1m"
DIM  = "\033[2m"
MAG  = "\033[95m"

WATCHLIST_DEFAULT = Path(__file__).parent / "watchlist.json"


def fetch_df(code: str, days: int = 300):
    import akshare as ak
    import pandas as pd, datetime as dt

    sh_code = f"sh{code}" if code.startswith(("6", "5")) else f"sz{code}"
    end   = dt.datetime.now().strftime("%Y%m%d")
    start = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y%m%d")
    df = ak.stock_zh_a_daily(symbol=sh_code, start_date=start,
                             end_date=end, adjust="qfq")
    df["date"] = df.index
    df = df.reset_index(drop=True)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"vol": "volume"})
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def fetch_rt_price(code: str):
    import akshare as ak
    try:
        mdf = ak.stock_zh_a_hist_min_em(symbol=code, period="1", adjust="qfq")
        if mdf is not None and not mdf.empty:
            return float(mdf["收盘"].iloc[-1])
    except Exception:
        pass
    return None


def _load_hist_winrates() -> dict:
    """从 batch_result.json 读取历史胜率，返回 {code: {KDJ:%, MACD:%, ...}}"""
    p = Path(__file__).parent / "batch_result.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {d["code"]: d.get("backtest", {}) for d in data}
    except Exception:
        return {}


def calc_composite_score(r: dict, hist: dict) -> float:
    """
    综合推荐评分（0-100），越高越值得操作。
    分三个维度：
      A. 信号强度（40分）：加权得分绝对值 + 共识同向数
      B. 策略契合度（35分）：ADX与策略类型的匹配程度
      C. 历史胜率（25分）：触发策略的历史命中率
    """
    from strategies.base import SignalType

    direction = r["consensus_signal"]   # 买入/卖出/观望
    if direction == "观望":
        return 0.0

    # ── A. 信号强度（满40）────────────────────────────────
    raw_score  = abs(r["weighted_score"])               # 0-100+
    agree      = r["agree_count"]                       # 0-5
    double_bon = 10 if r["double_confirmed"] else 0
    a = min(40, raw_score * 0.25 + agree * 4 + double_bon)

    # ── B. 策略契合度（满35）─────────────────────────────
    adx = r["adx"]
    # 趋势型策略（MACD/长均线）触发时 → ADX高更契合
    trend_sigs  = [s for s in r["signals"]
                   if s.strategy in ("MACD", "长均线") and s.type.value == direction]
    oscil_sigs  = [s for s in r["signals"]
                   if s.strategy in ("KDJ", "BOLL") and s.type.value == direction]

    if trend_sigs and adx > 25:
        b = min(35, 20 + (adx - 25) * 0.6)
    elif oscil_sigs and adx < 20:
        b = min(35, 20 + (20 - adx) * 0.8)
    elif trend_sigs or oscil_sigs:
        b = 15   # 有信号但ADX不完全匹配
    else:
        b = 8    # 仅量价/短均线信号

    # ── C. 历史胜率（满25）───────────────────────────────
    code_hist = hist.get(r["code"], {})
    triggered = [s.strategy for s in r["signals"]
                 if s.type.value == direction and s.strength >= 40]
    name_map  = {"KDJ":"KDJ","MACD":"MACD","短均线":"短均线",
                 "BOLL":"BOLL","量价":"量价","长均线":"长均线"}
    rates = []
    for sname in triggered:
        key = name_map.get(sname, sname)
        bt  = code_hist.get(key, {})
        n   = bt.get("signal_count", 0)
        wr  = bt.get("win_rate", 50)
        if n >= 5:
            rates.append(wr)
    avg_wr = sum(rates) / len(rates) if rates else 50
    c = min(25, (avg_wr - 40) * 0.83)   # 40%胜率=0分，70%=25分
    c = max(0, c)

    return round(a + b + c, 1)


def analyze(code: str, name: str, hist: dict) -> dict:
    from strategies.scanner import scan, stop_loss_price
    from strategies.consensus import consensus_filter, consensus_strength
    from strategies.indicators import adx as calc_adx

    df = fetch_df(code)
    price_rt = fetch_rt_price(code)
    price    = price_rt if price_rt else float(df["close"].iloc[-1])
    prev     = float(df["close"].iloc[-2])
    pct      = (price / prev - 1) * 100

    today_high = float(df["high"].iloc[-1])
    today_low  = float(df["low"].iloc[-1])
    amplitude  = (today_high - today_low) / prev * 100

    final_weighted, score, signals = scan(df)
    consensus_type, agree_count, consensus_reason = consensus_filter(signals)
    confidence = consensus_strength(agree_count)
    double_confirmed = (final_weighted == consensus_type
                        and final_weighted.value != "观望")

    _, _, adx_s = calc_adx(df["high"], df["low"], df["close"], 14)
    adx_val = float(adx_s.dropna().iloc[-1]) if not adx_s.dropna().empty else 20

    sl = float(stop_loss_price(df))

    r = {
        "code":              code,
        "name":              name,
        "price":             price,
        "pct":               pct,
        "amplitude":         amplitude,
        "weighted_signal":   final_weighted.value,
        "weighted_score":    score,
        "consensus_signal":  consensus_type.value,
        "agree_count":       agree_count,
        "confidence":        confidence,
        "double_confirmed":  double_confirmed,
        "consensus_reason":  consensus_reason,
        "stop_loss":         sl,
        "adx":               adx_val,
        "signals":           signals,
    }
    r["composite_score"] = calc_composite_score(r, hist)
    return r


def sig_color(val: str) -> str:
    if val == "买入": return f"{GRN}{BOLD}"
    if val == "卖出": return f"{RED}{BOLD}"
    return DIM


def _score_bar(score: float, width: int = 20) -> str:
    """把 0-100 分映射成可视化进度条"""
    filled = int(score / 100 * width)
    if score >= 70:
        color = GRN
    elif score >= 45:
        color = YLW
    else:
        color = RED
    return f"{color}{'█' * filled}{'░' * (width - filled)}{R} {score:.0f}分"


def _score_label(score: float) -> str:
    if score >= 75: return f"{GRN}{BOLD}强烈推荐{R}"
    if score >= 55: return f"{GRN}推荐{R}"
    if score >= 40: return f"{YLW}可考虑{R}"
    return f"{DIM}参考{R}"


def print_report(results: list, executor):
    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date = datetime.datetime.now().strftime("%Y年%m月%d日")

    buy_list  = sorted([r for r in results if r["consensus_signal"] == "买入"],
                       key=lambda x: -x["composite_score"])
    sell_list = sorted([r for r in results if r["consensus_signal"] == "卖出"],
                       key=lambda x: -x["composite_score"])
    hold_list = [r for r in results if r["consensus_signal"] == "观望"]

    print(f"\n{'═'*72}")
    print(f"  {BOLD}{MAG}每日量化盯盘报告{R}  {date}  {DIM}{now}{R}")
    print(f"{'═'*72}")

    # ══ 买入推荐 ══════════════════════════════════════════════════════
    if buy_list:
        print(f"\n  {GRN}{BOLD}━━  买入推荐  ({len(buy_list)}只)  ━━{R}")
        for r in buy_list:
            _print_scored_row(r, executor, "买入")
    else:
        print(f"\n  {DIM}今日无买入推荐{R}")

    # ══ 卖出推荐 ══════════════════════════════════════════════════════
    if sell_list:
        print(f"\n  {RED}{BOLD}━━  卖出推荐  ({len(sell_list)}只)  ━━{R}")
        for r in sell_list:
            _print_scored_row(r, executor, "卖出")
    else:
        print(f"\n  {DIM}今日无卖出推荐{R}")

    # ══ 观望 ══════════════════════════════════════════════════════════
    print(f"\n  {DIM}━━  观望  ({len(hold_list)}只)  ━━{R}")
    # 观望里也按加权分排序，显示得分最高的几只（可能接近信号）
    near_signal = sorted(
        [r for r in hold_list if abs(r["weighted_score"]) >= 30],
        key=lambda x: -abs(x["weighted_score"])
    )[:5]
    if near_signal:
        print(f"  {DIM}接近信号（得分≥30，可盯盘）:{R}")
        for r in near_signal:
            pct_c = RED if r["pct"] > 0 else GRN
            ws    = r["weighted_score"]
            ws_c  = GRN if ws > 0 else RED
            print(f"    {r['name']}({r['code']})  "
                  f"现价{r['price']:.2f} {pct_c}{r['pct']:+.1f}%{R}  "
                  f"加权{ws_c}{ws:+.1f}{R}  ADX={r['adx']:.0f}")
    rest = [r for r in hold_list if abs(r["weighted_score"]) < 30]
    if rest:
        names = "、".join(r["name"] for r in rest)
        print(f"  {DIM}其余观望: {names}{R}")

    # ══ 账户盈亏 ══════════════════════════════════════════════════════
    print(f"\n{'─'*72}")
    _print_pnl_summary(results, executor)
    print(f"{'═'*72}\n")


def _print_scored_row(r: dict, executor, direction: str):
    """打印带评分的单只股票推荐行"""
    from strategies.base import SignalType

    price  = r["price"]
    pct_c  = RED if r["pct"] > 0 else GRN
    sc     = r["composite_score"]
    marker = "★" if r["double_confirmed"] else "◇"
    d_tag  = f" {GRN}双重确认{R}" if r["double_confirmed"] else ""

    # 触发的主要指标
    active = [s for s in r["signals"]
              if s.type.value == direction and s.strength >= 40]
    ind_str = "  ".join(
        f"{GRN if direction=='买入' else RED}{s.strategy}{R}({s.strength:.0f})"
        for s in active
    )

    print(f"\n  {marker} {BOLD}{r['name']}（{r['code']}）{R}{d_tag}")
    print(f"    现价 {BOLD}{price:.2f}{R}  {pct_c}{r['pct']:+.2f}%{R}  "
          f"振幅{r['amplitude']:.1f}%  ADX={r['adx']:.0f}  "
          f"共识{r['agree_count']}项同向")
    print(f"    推荐评分  {_score_bar(sc)}  {_score_label(sc)}")

    # 评分明细（信号/契合/胜率各占比）
    sig_part = min(40, abs(r["weighted_score"]) * 0.25
                   + r["agree_count"] * 4
                   + (10 if r["double_confirmed"] else 0))
    # 从 calc_composite_score 重算各分项
    adx = r["adx"]
    active_s = [s for s in r["signals"]
                if s.type.value == direction and s.strength >= 40]
    trend_s = [s for s in active_s if s.strategy in ("MACD", "长均线")]
    oscil_s = [s for s in active_s if s.strategy in ("KDJ", "BOLL")]
    if trend_s and adx > 25:
        fit_part = min(35, 20 + (adx - 25) * 0.6)
    elif oscil_s and adx < 20:
        fit_part = min(35, 20 + (20 - adx) * 0.8)
    elif trend_s or oscil_s:
        fit_part = 15
    else:
        fit_part = 8
    wr_part = max(0, min(25, sc - sig_part - fit_part))
    print(f"    {DIM}┌ 信号强度 {sig_part:.0f}/40  "
          f"策略契合 {fit_part:.0f}/35  "
          f"历史胜率 {wr_part:.0f}/25{R}")
    if ind_str:
        print(f"    {DIM}└ 触发指标: {R}{ind_str}")
    print(f"    止损价: {YLW}{r['stop_loss']:.2f}{R}  "
          f"({DIM}跌破离场，风险 {abs(price-r['stop_loss'])/price*100:.1f}%{R})")

    # 执行模拟盘
    if direction == "买入":
        result = executor.buy(r["code"], r["name"], price)
        print(f"    {GRN}▶ 模拟买入{R}: {result}")
    elif direction == "卖出":
        result = executor.sell(r["code"], r["name"], price)
        print(f"    {RED}▶ 模拟卖出{R}: {result}")


def _print_pnl_summary(results: list, executor):
    """打印完整盈亏摘要，并写入日志"""
    from trader import paper as _paper
    from trader.logger import log_daily_report

    pf    = _paper.status()
    cash  = pf["cash"]
    positions = pf["positions"]

    # 从本次扫描结果里取现价
    prices = {r["code"]: r["price"] for r in results}

    unrealized    = 0.0
    pos_lines     = []
    holding_value = 0.0
    for code, pos in positions.items():
        cur  = prices.get(code, pos["cost"])
        fp   = (cur - pos["cost"]) * pos["shares"]
        unrealized    += fp
        holding_value += cur * pos["shares"]
        fp_str  = f"{GRN}+{fp:,.2f}{R}" if fp >= 0 else f"{RED}{fp:,.2f}{R}"
        pct_str = f"{(cur/pos['cost']-1)*100:+.1f}%"
        pos_lines.append(
            f"    {pos['name']}({code})  {pos['shares']}股  "
            f"成本{pos['cost']:.2f} → 现价{cur:.2f}({pct_str})  浮盈{fp_str}"
        )

    market_value = cash + holding_value
    total_pnl    = market_value - 100_000.0
    total_ret    = total_pnl / 100_000.0 * 100
    realized     = pf.get("total_pnl", 0.0)

    pnl_c   = GRN if total_pnl >= 0 else RED
    sign    = "+" if total_pnl >= 0 else ""

    print(f"\n  {BOLD}💰 账户盈亏总览{R}")
    print(f"  {'─'*50}")
    print(f"  初始资金      100,000.00")
    print(f"  可用资金      {cash:>12,.2f}")
    print(f"  持仓市值      {holding_value:>12,.2f}")
    print(f"  账户总值      {BOLD}{market_value:>12,.2f}{R}")
    print(f"  {'─'*50}")
    print(f"  已实现盈亏    {GRN if realized>=0 else RED}{realized:>+12,.2f}{R}")
    print(f"  持仓浮盈      {GRN if unrealized>=0 else RED}{unrealized:>+12,.2f}{R}")
    print(f"  总盈亏        {pnl_c}{BOLD}{sign}{total_pnl:>11,.2f}  ({sign}{total_ret:.2f}%){R}")

    if pos_lines:
        print(f"\n  {BOLD}持仓明细:{R}")
        for l in pos_lines:
            print(l)
    else:
        print(f"\n  {DIM}当前空仓{R}")

    # 写入日志
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    log_daily_report(today, cash, positions, prices, realized)
    print(f"\n  {DIM}📝 已写入 trading_log.md{R}")


def ensure_watchlist(path: Path):
    """如果 watchlist.json 不存在，从 batch_result.json 生成"""
    if path.exists():
        return

    batch = Path(__file__).parent / "batch_result.json"
    if batch.exists():
        data = json.loads(batch.read_text(encoding="utf-8"))
        wl   = [{"code": d["code"], "name": d["name"]} for d in data]
        path.write_text(json.dumps(wl, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"  已从 batch_result.json 生成 watchlist.json（{len(wl)} 只标的）")
    else:
        # 默认只放一只演示标的
        default = [{"code": "605099", "name": "共创草坪"}]
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"  已创建默认 watchlist.json，请手动编辑添加标的")


def main():
    parser = argparse.ArgumentParser(description="每日量化盯盘报告（建议14:30运行）")
    parser.add_argument("--watch", default=str(WATCHLIST_DEFAULT),
                        help="股票池 JSON 文件路径")
    parser.add_argument("--mode",  default="paper",
                        choices=["paper", "easytrader"],
                        help="交易模式")
    parser.add_argument("--days",  type=int, default=300,
                        help="拉取历史数据天数")
    args = parser.parse_args()

    watch_path = Path(args.watch)
    ensure_watchlist(watch_path)

    watchlist = json.loads(watch_path.read_text(encoding="utf-8"))
    total = len(watchlist)

    from trader.executor import Executor
    executor = Executor(mode=args.mode)
    hist     = _load_hist_winrates()

    print(f"\n  {BOLD}正在扫描 {total} 只标的...{R}  "
          f"（建议每日14:30运行，收盘前30分钟操作）\n")

    results = []
    import time
    for i, item in enumerate(watchlist):
        code = item["code"]
        name = item.get("name", code)
        print(f"  [{i+1:>2}/{total}] {name}（{code}）...", end="\r", flush=True)
        try:
            r = analyze(code, name, hist)
            results.append(r)
        except Exception as e:
            print(f"  [{i+1:>2}/{total}] {name}（{code}）  {RED}失败: {e}{R}")
        if i < total - 1:
            time.sleep(1.0)

    print(" " * 60, end="\r")  # 清除进度行
    print_report(results, executor)
    _git_sync_log()


def _git_sync_log():
    """报告结束后，询问是否将 trading_log.md 同步到 git"""
    import subprocess

    repo_root = Path(__file__).parent.parent.parent  # am_god_stock_janaiidesu/
    log_rel   = "files/quant_starter/trading_log.md"
    today     = datetime.date.today().isoformat()

    # 检查今天是否已有针对 trading_log.md 的提交
    try:
        out = subprocess.check_output(
            ["git", "log", "--oneline", "--since=midnight",
             "--", log_rel],
            cwd=repo_root, stderr=subprocess.DEVNULL
        ).decode().strip()
        already_committed_today = bool(out)
        last_commit_msg = out.splitlines()[0] if out else ""
    except Exception:
        already_committed_today = False
        last_commit_msg = ""

    print(f"\n{'─'*68}")

    if already_committed_today:
        print(f"  {YLW}⚠️  今天已有一次提交记录：{R}")
        print(f"  {DIM}{last_commit_msg}{R}\n")
        print(f"  本次报告已写入 trading_log.md，请选择：")
        print(f"  {BOLD}[1]{R} 覆盖今天历史（用本次内容替换今天的提交）")
        print(f"  {BOLD}[2]{R} 追加为新提交（保留今天历史，再加一条）")
        print(f"  {BOLD}[3]{R} 不提交，只保留本地")
        choice = input(f"\n  请输入 1 / 2 / 3：").strip()
    else:
        print(f"  📤 准备将 trading_log.md 同步到 GitHub")
        print(f"  {BOLD}[1]{R} 提交并推送")
        print(f"  {BOLD}[2]{R} 不提交，只保留本地")
        choice = input(f"\n  请输入 1 / 2：").strip()
        # 统一映射：此分支下"2"=不提交，对齐已提交分支的"3"
        if choice == "2":
            choice = "3"

    if choice == "3":
        print(f"  {DIM}已跳过提交，trading_log.md 仅保留本地。{R}\n")
        return

    try:
        subprocess.check_call(
            ["git", "add", log_rel], cwd=repo_root
        )

        commit_msg = f"交易日志 {today}"

        if choice == "1" and already_committed_today:
            # 找到今天第一次提交的 hash，软重置到它之前再重新提交
            first_sha = out.splitlines()[-1].split()[0]
            subprocess.check_call(
                ["git", "reset", "--soft", f"{first_sha}~1"],
                cwd=repo_root
            )
            subprocess.check_call(
                ["git", "add", log_rel], cwd=repo_root
            )
            subprocess.check_call(
                ["git", "commit", "-m", f"{commit_msg}（覆盖）"],
                cwd=repo_root
            )
            subprocess.check_call(
                ["git", "push", "--force-with-lease"], cwd=repo_root
            )
            print(f"  {GRN}✅ 已覆盖今天的历史提交并强推。{R}\n")
        else:
            subprocess.check_call(
                ["git", "commit", "-m", commit_msg], cwd=repo_root
            )
            subprocess.check_call(
                ["git", "push"], cwd=repo_root
            )
            print(f"  {GRN}✅ 已提交并推送到 GitHub。{R}\n")

    except subprocess.CalledProcessError as e:
        print(f"  {RED}❌ Git 操作失败: {e}{R}")
        print(f"  {DIM}可手动运行: git add {log_rel} && git commit -m '{today}' && git push{R}\n")


if __name__ == "__main__":
    main()
