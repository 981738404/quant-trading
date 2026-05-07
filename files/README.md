# A 股量化交易脚手架

一个干净、可扩展的 A 股量化项目骨架。当前阶段聚焦在**数据层**——把数据获取抽象成统一接口，后续策略和回测在此基础上叠加。

## 项目结构

```
quant_starter/
├── config.py                # 全局配置
├── requirements.txt         # 依赖
├── .env.example             # 环境变量模板
├── data/                    # 数据层
│   ├── data_loader.py       # 统一数据加载器（核心）
│   ├── tushare_source.py    # Tushare 封装
│   └── akshare_source.py    # AKShare 封装
├── utils/                   # 工具
│   ├── symbol.py            # 股票代码格式转换
│   └── date_utils.py        # 日期格式工具
├── strategies/              # 策略（待开发）
├── examples/                # 示例代码
│   └── 01_basic_usage.py
└── cache/                   # 本地数据缓存（自动生成）
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 Tushare Token（可选但强烈推荐）

注册 [Tushare Pro](https://tushare.pro/register)，获取 token：

```bash
cp .env.example .env
# 编辑 .env，填入你的 token
```

如果不配置 Tushare，DataLoader 会自动回退到 AKShare（免费、无需注册）。

### 3. 运行示例

```bash
python examples/01_basic_usage.py
```

## 核心使用方式

```python
from data.data_loader import DataLoader

loader = DataLoader()

# 日线数据（自动复权 + 缓存）
df = loader.get_daily('000001', '20240101', '20241231', adjust='qfq')

# 指数数据
hs300 = loader.get_index_daily('000300.SH', '20240101', '20241231')

# 股票列表
stocks = loader.get_stock_list()

# 财务/估值指标（需 Tushare token）
basics = loader.get_daily_basic('000001', '20240101', '20241231')
```

## 设计要点

### 为什么要做统一接口？

策略代码不应该直接 `import tushare` 或 `import akshare`。一旦后期换数据源（比如升级到付费的米筐 RQData，或扩展到加密货币），所有策略都要改。

通过 `DataLoader` 抽象层，**换数据源只改一处**。

### 关于复权

- `qfq`（前复权）：以最新价格为基准回算历史，**回测必用**
- `hfq`（后复权）：以历史价格为基准向前推，长期持有收益计算用
- 不复权：仅用于看真实成交价（如打新、计算除权日）

绝对不要拿不复权数据回测——除权除息会造成虚假的"价格跳空"，所有趋势/突破信号都会失真。

### 关于缓存

`DataLoader` 默认开启 parquet 本地缓存。同样的请求第二次会从磁盘读，避免反复打 API。

⚠️ **注意**：缓存基于 (code, start, end, adjust, source) 作为 key。如果你重新运行了带未来日期的请求（比如 end='20251231' 但今天是 11 月），缓存里只有当前已有的数据，需要清缓存重新拉：

```python
loader.clear_cache()
```

## 下一步

- [ ] 添加因子计算模块（动量、价值、质量等）
- [ ] 接入回测框架（vectorbt 或 backtrader）
- [ ] 实现一个完整的多因子策略示例
- [ ] 增量更新机制（只拉最新数据，避免每次全量）

## 常见坑

1. **未来函数**：用了未来才能知道的数据。比如用财报数据时要注意"披露日期"而不是"报告期"。
2. **幸存者偏差**：拿当前的成分股回测过去的业绩。要用每个时点的真实成分股。
3. **停牌处理**：直接用复权价计算收益时，停牌期间会出现 NaN，要单独处理。
4. **涨跌停**：策略发出买入信号时如果当天涨停，实际无法成交。回测要模拟这点。
