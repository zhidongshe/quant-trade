# 沪深 300 多头趋势策略 v1 — 离线回测系统设计

- 起草日期: 2026-06-21
- 作者: shezhidong + Claude
- 状态: 待实现（spec 完成，等转 writing-plans）

## 1. 目标

为 `hs300_trend_strategy_single_file_v1.py`（以下简称 v1）搭建一套**本地离线回测系统**，使用 `300data/` 中现有的沪深 300 成分股日线与 5 分钟数据，量化评估该策略在 2019-09 ~ 2025-12 区间的历史表现。

**硬约束**：v1 文件**不做任何改动**，回测系统通过提供 QMT 运行时 shim 让 v1 原文运行。

## 2. 非目标

- 不做参数搜索 / 网格优化（先看当前参数表现，调参留待后续）
- 不接入第三方回测框架（backtrader / vectorbt 等）
- 不模拟 tick 级撮合，不模拟集合竞价细节
- 不处理北交所、退市股、停牌恢复等边缘 case（数据里没的就跳过）
- 不考虑融资融券、做空

## 3. 已知约束与权衡（用户确认）

| 项 | 选择 | 含义/取舍 |
|---|---|---|
| Bar 频率 | **5min 驱动**（每根 5min bar 调一次 `v1.handlebar`） | 忠实 QMT 行为；v1 自带 `current_time < '14:55:00'` 闸过滤非决策 bar |
| 回测区间 | **可配置**，默认 2019-09-01 ~ 2025-12-31 | 默认头 60 个交易日做 MA60 热身 |
| 报告口径 | **按自然年拆分**：2019(09-12), 2020, 2021, …, 2025；外加全期合计 | 用户明确要求 |
| 股池 | **以当前 300 成分股为全期固定股池**（300data 里的 ~300 只） | 存在幸存者偏差但工程上可接受 |
| 初始资金 / 成本 | **可配置**，默认 100 万 / 万三佣金 / 千五印花税 / 0.1% 滑点 | |
| 成交价 | **当日 15:00 收盘价**（=当日最后一根 5min bar 的 close） | v1 在 14:55 bar 发单 → 物理上次日开盘前最近可成交价 ≈ EOD close |
| 复权 | **shim 内部前复权** | 蓝筹分红/送股频繁，不复权会污染跨除权日的 MA/MACD |
| ST / 涨停 / 科创板过滤 | **简化 mock**：涨停=当日涨幅≥9.5%、ST=名字含 ST/*ST、科创板=688 开头 | 与 v1 调用的 QMT 接口同型，足够 |
| 代码组织 | **单文件 `backtest_v1.py`** + `from hs300_trend_strategy_single_file_v1 import handlebar, init` | v1 顶部 gbk 声明需用自定义 loader 处理 |
| 对拍 | **跳过**（用户无 QMT 历史成交日志） | 改用集成+冒烟测试兜底 |

## 4. 顶层架构

```
backtest_v1.py
├─ BacktestConfig          dataclass + argparse
├─ DataLoader              一次加载 300data，缓存到内存，含前复权处理
├─ QMTShim                 mock ContextInfo / passorder / get_trade_detail_data / get_sector / get_instrumentdetail / timetag_to_datetime
├─ BacktestAccount         现金、持仓、订单队列、成交流水、每日快照
├─ EventLoop               按 5min bar 推进，调 v1.handlebar(shim)，触发 fill
├─ Reporter                输出 4 类产物
└─ main()                  串联
```

### 数据流

```
csv → DataLoader.load_all()
        │
        ▼
EventLoop.run():
    for D in trading_days[start..end]:
        for bar in D 的 48 根 5min bar:
            shim.advance_to(bar)
            v1.handlebar(shim)               # v1 原文
            if shim.pending_orders:
                account.fill_orders(next_bar_open_price)
            if bar 是当日 15:00 bar:
                account.snapshot(D)
        │
        ▼
Reporter.write(account, equity_curve, hs300_index)
  → metrics.csv / equity_curve.png / trades.csv / daily_snapshot.csv
```

### 关键不变量

1. **v1 0 改动**——shim 撑起 v1 看到的整个世界
2. **绝不泄露未来**——14:55 调 `get_history_data('1d')` 时，"今天"那根日线 close = 截至 14:55 的最新价，high/low/volume 为 09:30~14:55 累计
3. **passorder 异步成交**——shim 截获后入队，下一个 bar 才显式 fill；不立即修改账户

## 5. QMT shim 详细职责

v1 调到的所有 QMT 接口对照表：

| v1 调到的接口 | shim 行为 |
|---|---|
| `ContextInfo.barpos` | 当前 5min bar 全局序号（int，从 0 递增） |
| `ContextInfo.get_bar_timetag(barpos)` | 返回该 bar 的 timestamp（毫秒）；用 **bar 结束时刻** 打标，与 QMT 一致 |
| `ContextInfo.is_last_bar()` | 始终返回 `True`（回测无回放对照；v1 已用 quickTrade=1 绕开依赖） |
| `ContextInfo.set_universe(codes)` | 记录到 `_universe: set`，下次 get_history_data 时校验 |
| `ContextInfo.get_history_data(N, '1d', field, dividend_type='front', skip_paused=True)` | **核心**：返回 `{code: ndarray(N)}`；过去 N-1 个完整日线 + 当日 partial bar（前复权） |
| `ContextInfo.get_market_data_ex(...)` | dict 形态；复用上面实现 |
| `passorder(opType, orderType, account, code, prtype, price, volume, ..., quickTrade=1, ...)` | 校验 → 入 `pending_orders` |
| `get_trade_detail_data(account, 'stock', 'POSITION')` | 返回对象列表；属性名匹配 v1 实际使用（`m_strInstrumentID`, `m_nVolume`, `m_dOpenPrice`, `m_dMarketValue`, …） |
| `get_trade_detail_data(account, 'stock', 'ACCOUNT')` | 总资产、可用资金、市值 |
| `get_sector('沪深300')` | 返回 300data 中所有有日线的 SH./SZ. code 列表（全期固定） |
| `get_instrumentdetail(code)` | 返回 `{'PreClose', 'UpStopPrice', 'DownStopPrice', 'InstrumentName'}` |
| `timetag_to_datetime(timetag, fmt)` | `datetime.fromtimestamp(timetag/1000).strftime(fmt)` |

### 5.1 partial day bar 构造（防止未来泄露）

当 v1 在 D 日某根 5min bar t 时调 `get_history_data(N, '1d', field)`：

```python
def get_history_data(N, period='1d', field='close', ...):
    if period != '1d':
        raise NotImplementedError  # v1 只用 '1d'
    result = {}
    for code in universe:
        past_complete = daily_df[code].loc[:D-1天]          # 取最后 N-1 行
        today_bars = m5_df[code].loc[D, 09:35 : t]          # 含 t 这根
        today_partial = aggregate_5m_to_day(today_bars)     # OHLCV
        full = concat(past_complete[-(N-1):], today_partial)
        result[code] = apply_forward_adjust(full[field], code, t)
    return result
```

`aggregate_5m_to_day`：
- open = D 日第一根 5min 的 open
- high = max(已发生 5min bars 的 high)
- low = min(已发生 5min bars 的 low)
- close = **当前 bar 的 close**
- volume = sum(已发生 5min bars 的 turnover)（v1 里 volume 字段实际是成交额，保持一致）

### 5.2 前复权

启动时：对每只股票从原始日线序列检测除权日（`close / prev_close` 与同期指数比异常跳变、或对照成交价跳变阈值），生成复权因子表 `adj_factor[code][date]`。所有暴露给 v1 的价格序列乘上对应因子。

成交价、止损价、买入均价等**所有 v1 看到的价格**都走前复权。但账户里现金/股数等用真实价格——这点需要在 shim 边界做映射：
- v1 看价：前复权
- shim 内部撮合 / 写 trades.csv：使用**原始价 + 持仓数**（更易复现到实盘逻辑）
- 持仓估值：原始价 × 股数

## 6. 账户 / 订单 / 成交模型

### 数据结构

```python
@dataclass
class Position:
    code: str
    volume: int               # 股数（100 倍数）
    open_price: float         # 多次加仓摊薄均价（原始价）
    open_date: str
    market_value: float       # 每根 bar 末更新

@dataclass
class Trade:
    bar_time: datetime
    code: str
    name: str
    side: str                 # 'BUY' | 'SELL' | 'BUY_REJECTED' | 'SELL_REJECTED'
    price: float              # 原始成交价（REJECTED 行 price=0）
    volume: int               # REJECTED 行记 v1 想下的数量
    amount: float
    commission: float
    stamp_tax: float          # 卖出才有
    transfer_fee: float       # 沪市才有
    cash_after: float
    reason: str               # 复制自 v1 内部 reason；REJECTED 行追加拒因（如 LIMIT_UP / CASH_SHORT / VOLUME_SHORT）

@dataclass
class Snapshot:
    date: str
    cash: float
    total_equity: float
    position_count: int
    positions: list[Position]

class BacktestAccount:
    cash: float
    positions: dict[str, Position]
    pending_orders: list[Order]
    trades: list[Trade]
    snapshots: list[Snapshot]
    t1_locked: dict[str, dict[str, int]]   # {code: {buy_date: volume}}，T+1 锁定
```

### 订单生命周期

```
v1 调 passorder
  ↓
shim 截获 → 入 pending_orders
  ↓
EventLoop 推进到下一根 5min bar
  ↓
account.fill_orders(fill_price_provider):
  - 取下一根 bar 的 close（=15:00 EOD close）作为成交参考价
  - 应用滑点：买 = ref ×(1+slippage)，卖 = ref ×(1−slippage)
  - 涨停检查（仅买）：当日 close 相对昨日 close ≥+9.5% → reject
  - 资金检查（买）：cash < amount+fee → reject
  - 持仓检查（卖）：可用股 < volume → reject（T+1 锁定要扣掉）
  - 成交 → 计算 commission/stamp_tax/transfer_fee → 更新 cash/positions/t1_locked → append trades
  - reject → append 到 trades（side=BUY_REJECTED 等），reason 记原因
```

### 成本配置

```python
@dataclass
class CostConfig:
    commission_rate: float = 0.0003
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.0005       # 仅卖出
    transfer_fee_rate: float = 0.00001   # 仅沪市
    slippage_pct: float = 0.001
```

## 7. 数据加载策略

`DataLoader(data_root='300data')`：

**启动一次性加载**：
- 全部股票 + 沪深 300 指数的**日线**入 `daily_df: dict[code, pd.DataFrame]`（~48 万行，几十 MB）
- 同步计算并缓存前复权因子表

**5min 数据按月延迟加载**：
- 进入新月时把当月所有票的 5min 入内存（~300 只 × 1 月 × 2000 bar = 60 万行/月）
- 始终保留 **当前月 + 前 1 月** 的窗口；进入新月时释放窗口外的（避免跨月初首日还要回看上月末时数据已被释放）
- 5min 文件命名：`SH.600000_2024-12.txt`

**索引**：
- daily: `date(str 'YYYY-MM-DD') → row`
- 5min: `datetime → row`，再按 (date, bar_idx_within_day) 组装快速访问

**缺失处理**：某只票某日无数据 → 当日跳过该票（不当作停牌特殊处理）

## 8. 性能预算

- 6.5 年 ≈ 1600 交易日 × 48 bar = 76,800 次 handlebar 调用
- 95% 被 v1 时间闸过滤，实际跑信号 ~1600 次
- 每次跑信号 = 300 只票各算 MA60/MACD，numpy 向量化下毫秒级
- **总预计耗时：30 秒 ~ 2 分钟**

如果超过 2 分钟需要 profile 看是不是 partial day bar 构造在重复造序列，可加缓存。

## 9. 配置与入口

```python
@dataclass
class BacktestConfig:
    data_root: str = '300data'
    start_date: str = '2019-09-01'
    end_date: str = '2025-12-31'
    initial_cash: float = 1_000_000
    commission_rate: float = 0.0003
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_pct: float = 0.001
    output_dir: str = 'backtest_results'
    verbose: bool = False

    @classmethod
    def from_cli(cls, argv): ...
```

CLI 示例：
```bash
python backtest_v1.py \
    --start 2020-01-01 --end 2024-12-31 \
    --initial-cash 3000000 --slippage 0.0005
```

输出目录：`backtest_results/20260621_153000_2020-01-01_2024-12-31/`

### v1 文件 import

v1 顶部为 `# -*- coding: gbk -*-`。本地 import 用 `importlib.util.spec_from_file_location` 配合自定义 source loader，读 gbk 后转 utf-8 喂给 exec。封装为 `_load_v1_module(path) -> module`。

## 10. 报告输出（4 类）

### 10.1 `metrics.csv` + 控制台

按自然年拆 + 全期合计。列：

| period | start_equity | end_equity | return | ann_return | max_dd | sharpe | trades | win_rate |
|---|---|---|---|---|---|---|---|---|

指标定义：
- `return` = end/start − 1
- `ann_return` = (1+return)^(252/trading_days) − 1
- `max_dd` = 期内权益曲线最大回撤百分比
- `sharpe` = mean(daily_return) / std(daily_return) × √252，rf=0
- `trades` = 期内买入笔数
- `win_rate` = 盈利平仓笔数 / 平仓总笔数（按 FIFO 配对）

### 10.2 `equity_curve.png`

matplotlib 双子图：
- 上：策略权益（基准化 1.0）vs 沪深 300（基准化 1.0），叠红虚线标年起点
- 下：回撤曲线（drawdown %）

### 10.3 `trades.csv`

按 §6 的 `Trade` 字段全列输出，含 reject 行。

### 10.4 `daily_snapshot.csv`

```
date, cash, total_equity, position_count, positions
```

`positions` 字段：`600519.SH:100@1102.5;000858.SZ:300@198.4;...`

## 11. 测试策略

### 11.1 单元测试 `tests/test_backtest_*.py`

| 文件 | 覆盖 |
|---|---|
| `test_data_loader.py` | csv 解析、复权因子计算（构造 10送10 人造数据） |
| `test_qmt_shim.py` | partial day bar 截止 14:55 正确性、is_limit_up 阈值、get_history_data 返回长度与排序 |
| `test_account.py` | passorder→fill 全链路、滑点/手续费/印花税/过户费计算、T+1、涨停 reject、资金不足 reject |
| `test_reporter.py` | max_dd、sharpe、win_rate 用已知小样本对拍 |

### 11.2 集成测试 `tests/test_backtest_integration.py`

用 1 只票（600000）、1 个月数据，跑**极简自制策略**（每月初买、月末卖），断言：trades 数、终值、cash 流转。这层验证 EventLoop+Account+Shim 协同，不依赖 v1。

### 11.3 冒烟测试 `tests/test_backtest_smoke_v1.py`

最近 3 个月真实数据跑 v1，断言：无 exception、metrics.csv 生成、trades 数 ∈ [1, 1000]。这层抓"shim 能不能撑起 v1 这个黑盒"。

### 11.4 不写

- v1 策略本身的逻辑回归测试——既然约定不改 v1，对错靠回测结果体现
- QMT 实盘对拍——用户无历史成交日志

## 12. 实施顺序建议（留给 writing-plans 细化）

1. DataLoader + 前复权（含单测）
2. BacktestAccount + 订单/成交模型（含单测）
3. QMTShim 主体 + partial day bar（含单测）
4. EventLoop + v1 gbk import（含集成测试）
5. Reporter 4 类产物（含单测）
6. 冒烟测试跑通真实 3 个月
7. 全期跑通 + 指标合理性人工审查

## 13. 风险与未决

- **复权检测算法的健壮性**：用阈值检测除权可能漏报或误报，初版用 close 跳变 > 8% 且无大盘对应跳变作为信号；如效果不好需引入官方除权日列表
- **5min 月切边界**：跨月加载/释放需谨慎，集成测试要覆盖月末→月初这种边界
- **`get_trade_detail_data` 返回的对象**：v1 用到的属性名需要把 v1 文件再扫一遍确保覆盖（实现时一并列出）
- **passorder 的参数语义**：v1 用了 quickTrade=1 而且不依赖 is_last_bar，但参数定义需对照 QMT 文档（`docs/国金QMT极速策略交易系统_模型资料_Python_API_说明文档_Python3.pdf`）确认 opType / orderType 取值含义
