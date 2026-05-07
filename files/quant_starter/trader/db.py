"""
SQLite 持久化层：统一存储交易、持仓快照、每日总结、AI决策依据

表结构：
  trades          —— 每笔买卖（含AI决策依据）
  daily_snapshots —— 每日账户快照（净值曲线）
  decisions       —— 每次扫描对每只股票的完整AI思考过程
"""
import sqlite3
import datetime
from pathlib import Path

DB_FILE = Path(__file__).parent.parent / "trading.db"


def _conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表（幂等）"""
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            time        TEXT    NOT NULL,
            action      TEXT    NOT NULL,   -- BUY / SELL
            code        TEXT    NOT NULL,
            name        TEXT    NOT NULL,
            price       REAL    NOT NULL,
            shares      INTEGER NOT NULL,
            amount      REAL    NOT NULL,   -- 含费用
            cash_after  REAL    NOT NULL,
            pnl         REAL    DEFAULT 0,  -- 卖出时的本次盈亏
            -- AI 决策依据
            composite_score  REAL,          -- 综合评分 0-100
            signal_score     REAL,          -- 信号强度分
            fit_score        REAL,          -- 策略契合分
            winrate_score    REAL,          -- 历史胜率分
            agree_count      INTEGER,        -- 共识同向指标数
            double_confirmed INTEGER,        -- 是否双重确认
            adx              REAL,           -- ADX值
            triggered_signals TEXT,          -- 触发的指标列表（逗号分隔）
            consensus_reason  TEXT,          -- 共识过滤原因
            stop_loss         REAL,          -- 止损价
            risk_pct          REAL           -- 风险%
        );

        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT    NOT NULL UNIQUE,
            total_value  REAL    NOT NULL,
            cash         REAL    NOT NULL,
            market_value REAL    NOT NULL,
            unrealized   REAL    DEFAULT 0,
            realized     REAL    DEFAULT 0,
            day_pnl      REAL    DEFAULT 0,
            total_pnl    REAL    DEFAULT 0,
            total_pnl_pct REAL   DEFAULT 0,
            position_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            time             TEXT    NOT NULL,
            date             TEXT    NOT NULL,
            code             TEXT    NOT NULL,
            name             TEXT    NOT NULL,
            signal           TEXT    NOT NULL,   -- 买入/卖出/观望
            price            REAL,
            pct_change       REAL,               -- 当日涨跌幅
            composite_score  REAL,
            signal_score     REAL,
            fit_score        REAL,
            winrate_score    REAL,
            weighted_score   REAL,
            agree_count      INTEGER,
            double_confirmed INTEGER,
            adx              REAL,
            triggered_signals TEXT,
            consensus_reason  TEXT,
            stop_loss         REAL,
            risk_pct          REAL,
            -- 量化指标快照
            kdj_signal   TEXT,
            macd_signal  TEXT,
            boll_signal  TEXT,
            ma_signal    TEXT,
            vol_signal   TEXT,
            -- 执行结果
            executed     INTEGER DEFAULT 0,      -- 1=已执行模拟交易
            exec_note    TEXT                    -- 执行备注（买入成功/资金不足等）
        );

        CREATE INDEX IF NOT EXISTS idx_trades_code ON trades(code);
        CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(time);
        CREATE INDEX IF NOT EXISTS idx_decisions_date ON decisions(date);
        CREATE INDEX IF NOT EXISTS idx_decisions_code ON decisions(code);
        """)


def insert_trade(*, time: str, action: str, code: str, name: str,
                 price: float, shares: int, amount: float, cash_after: float,
                 pnl: float = 0.0, decision: dict = None):
    """记录一笔交易，decision 是来自 daily_report 的分析结果"""
    d = decision or {}
    sigs = d.get("triggered_signals", "")
    if isinstance(sigs, list):
        sigs = ",".join(sigs)
    with _conn() as c:
        c.execute("""
        INSERT INTO trades
          (time, action, code, name, price, shares, amount, cash_after, pnl,
           composite_score, signal_score, fit_score, winrate_score,
           agree_count, double_confirmed, adx,
           triggered_signals, consensus_reason, stop_loss, risk_pct)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            time, action, code, name, price, shares, amount, cash_after, pnl,
            d.get("composite_score"),
            d.get("signal_score"),
            d.get("fit_score"),
            d.get("winrate_score"),
            d.get("agree_count"),
            int(d.get("double_confirmed", False)),
            d.get("adx"),
            sigs,
            d.get("consensus_reason"),
            d.get("stop_loss"),
            d.get("risk_pct"),
        ))


def upsert_snapshot(*, date: str, total_value: float, cash: float,
                    market_value: float, unrealized: float = 0,
                    realized: float = 0, day_pnl: float = 0,
                    position_count: int = 0):
    total_pnl     = total_value - 100_000.0
    total_pnl_pct = total_pnl / 100_000.0 * 100
    with _conn() as c:
        c.execute("""
        INSERT INTO daily_snapshots
          (date, total_value, cash, market_value, unrealized, realized,
           day_pnl, total_pnl, total_pnl_pct, position_count)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
          total_value   = excluded.total_value,
          cash          = excluded.cash,
          market_value  = excluded.market_value,
          unrealized    = excluded.unrealized,
          realized      = excluded.realized,
          day_pnl       = excluded.day_pnl,
          total_pnl     = excluded.total_pnl,
          total_pnl_pct = excluded.total_pnl_pct,
          position_count= excluded.position_count
        """, (date, total_value, cash, market_value, unrealized, realized,
              day_pnl, total_pnl, total_pnl_pct, position_count))


def insert_decision(r: dict, executed: bool = False, exec_note: str = ""):
    """记录每只股票的完整AI决策，r 是 daily_report.analyze() 的返回值"""
    from strategies.base import SignalType

    now  = datetime.datetime.now().isoformat()
    date = datetime.date.today().isoformat()

    # 提取各指标信号
    def _sig(name):
        for s in r.get("signals", []):
            if s.strategy == name:
                return s.type.value
        return "观望"

    sigs = r.get("signals", [])
    direction = r.get("consensus_signal", "观望")
    triggered = [s.strategy for s in sigs
                 if s.type.value == direction and s.strength >= 40]

    price = r.get("price", 0)
    sl    = r.get("stop_loss", 0)
    risk  = abs(price - sl) / price * 100 if price else 0

    with _conn() as c:
        c.execute("""
        INSERT INTO decisions
          (time, date, code, name, signal, price, pct_change,
           composite_score, signal_score, fit_score, winrate_score,
           weighted_score, agree_count, double_confirmed, adx,
           triggered_signals, consensus_reason, stop_loss, risk_pct,
           kdj_signal, macd_signal, boll_signal, ma_signal, vol_signal,
           executed, exec_note)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            now, date,
            r.get("code"), r.get("name"),
            direction,
            price,
            r.get("pct"),
            r.get("composite_score"),
            r.get("_sig_score"),
            r.get("_fit_score"),
            r.get("_wr_score"),
            r.get("weighted_score"),
            r.get("agree_count"),
            int(r.get("double_confirmed", False)),
            r.get("adx"),
            ",".join(triggered),
            r.get("consensus_reason"),
            sl,
            round(risk, 2),
            _sig("KDJ"),
            _sig("MACD"),
            _sig("BOLL"),
            _sig("长均线"),
            _sig("量价"),
            int(executed),
            exec_note,
        ))


def query_trades(code: str = None, limit: int = 50) -> list:
    with _conn() as c:
        if code:
            return c.execute(
                "SELECT * FROM trades WHERE code=? ORDER BY time DESC LIMIT ?",
                (code, limit)
            ).fetchall()
        return c.execute(
            "SELECT * FROM trades ORDER BY time DESC LIMIT ?", (limit,)
        ).fetchall()


def query_snapshots(days: int = 90) -> list:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM daily_snapshots ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()


def query_decisions(date: str = None, code: str = None, signal: str = None) -> list:
    sql  = "SELECT * FROM decisions WHERE 1=1"
    args = []
    if date:   sql += " AND date=?";    args.append(date)
    if code:   sql += " AND code=?";    args.append(code)
    if signal: sql += " AND signal=?";  args.append(signal)
    sql += " ORDER BY time DESC LIMIT 200"
    with _conn() as c:
        return c.execute(sql, args).fetchall()


def summary_stats(code: str) -> dict:
    """某标的的历史统计：胜率、平均盈亏、交易次数"""
    with _conn() as c:
        sells = c.execute(
            "SELECT pnl FROM trades WHERE code=? AND action='SELL'", (code,)
        ).fetchall()
    if not sells:
        return {"trades": 0, "win_rate": None, "avg_pnl": None}
    pnls     = [r["pnl"] for r in sells]
    win_rate = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    return {
        "trades":   len(pnls),
        "win_rate": round(win_rate, 1),
        "avg_pnl":  round(sum(pnls) / len(pnls), 2),
        "total_pnl": round(sum(pnls), 2),
    }
