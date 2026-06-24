# quant-trade-new — QMT 实盘/回测两用策略系统设计

- 起草日期: 2026-06-24
- 作者: shezhidong + Claude
- 状态: 待实现（spec 完成，等转 writing-plans）
- 上游参考: [2026-06-21 hs300 backtest v1 设计](2026-06-21-hs300-backtest-v1-design.md)

## 1. 目标

新建独立目录 `quant-trade-new/`，其内**一份**沪深 300 多头趋势策略文件可以**同时**用于：

1. 复制粘贴进 QMT 策略编辑器 → 实盘运行
2. 在本地通过 Shim 层注入 → 基于 `300data/data_a/` 日线数据回测

回测必须支持任意起止日期（如 2020-01-01 ~ 2021-12-31），跨年时同时输出**按自然年分析**和**累计区间分析**。

策略业务规则**逐字照搬** `hs300_trend_strategy_single_file_v1.py`（以下简称 v1），**仅整理代码结构**：拆出短小函数、消除重复、修可见 bug、保持单文件形态。

## 2. 非目标

- 不优化策略参数（保留 v1 现状）
- 不接入第三方回测框架
- 不模拟 tick / 集合竞价 / 涨跌停板成交
- 不实现历史沪深 300 成分股快照（接受静态 universe 偏差）
- 不实现自动复权修正（接受 `data_a/` 数据源既有质量）
- 不支持空头 / 融资融券 / 北交所

## 3. 关键决策与已知约束

| 项 | 决策 | 出处/原因 |
|---|---|---|
| 架构 | **Shim 方案**：策略 QMT 形态，回测时由 Shim 模拟 QMT API | 唯一能满足"一份代码、QMT 形态、本地可跑"三条 |
| v1 处理 | 业务规则字面照搬，结构整理；修 `_execute_sell` 的 log/del 顺序 bug | 用户确认 |
| 时间段入参 | `config.yaml` + CLI 两层，CLI 覆盖 config | 用户选 |
| 报告呈现 | **单 `metrics.csv` 多行**：每年一行 + 最后一行累计 | 用户选 |
| 资金/费率 | 初始资金 50 万；佣金/印花税/过户费/滑点沿用 v1 默认 | 用户定 |
| 撮合价 | **当日 close 同步成交**（方案 A） | 与 QMT 实盘 14:50 决策、~15:00 成交语义最接近 |
| 产物路径 | `quant-trade-new/results/<run_id>/`，`run_id` = `<start>-<end>_<timestamp>` | 用户选 |
| 实盘/回测切换机制 | **删除 `SKIP_HISTORY_WARMUP` 全局开关**；策略无条件过滤 `current_date < strategy_start_date`；回测 Shim 在 `init()` 后覆写 `strategy_start_date` 为回测起始日 | 替代 v1 中"磁盘永远 False，拷进 QMT 手翻 True"的手翻 flag 操作，消除手动出错风险 |
| 日志路径 | 策略读 `getattr(ContextInfo, 'log_dir', r'c:')`；回测 Shim 覆写为 `results/<run_id>/logs/`；QMT 实盘下默认 `c:\` 不变 | 同上"环境差异由 Shim 改 ContextInfo 属性"原则 |
| Universe | **静态全集**：`data_a/` 中 ~300 只成分股 + 指数 | 接受 survivorship + 前视双向偏差 |
| 复权 | 用 `data_a/` 既有数据（**不完全前复权**：2024-06-21 茅台等个别事件未做） | 接受瑕疵，DataLoader 出"可疑跳水"质量日志 |
| T+1 | **严格模拟**：当日买入 `m_nCanUseVolume = 0`，次日才可卖 | 用户确认 |
| Warmup | 数据加载范围 = `[start - 120 交易日, end]` | MA60 + MACD signal + buffer |
| 黄金基线 | E2E 跑 2020 全年后**锁定**指标作为 `golden_2020.json`，后续偏离即报警 | 防止重构无意改业务 |

## 4. 顶层架构

### 4.1 目录结构

```
quant-trade-new/
├── strategy_hs300.py          ← 唯一策略文件（QMT 形态，可直接复制粘贴）
├── backtest/
│   ├── __init__.py
│   ├── shim.py                ← ContextInfo + passorder + qmt 全局函数模拟
│   ├── data_loader.py         ← 读 300data/data_a/*_day.txt
│   ├── account.py             ← 现金/持仓/订单/成交记录/快照
│   ├── engine.py              ← 按交易日推进的主循环
│   ├── reporter.py            ← 年度行 + 累计行 metrics，trades/snapshots/equity
│   ├── strategy_loader.py     ← exec 加载策略文件并注入 globals
│   └── cli.py                 ← argparse 入口，CLI 覆盖 config
├── configs/
│   └── default.yaml           ← 默认参数
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   └── golden_2020.json   ← 黄金基线指标
│   ├── test_indicators.py
│   ├── test_positions.py
│   ├── test_market.py
│   ├── test_costs.py
│   ├── test_qmt_adapter.py
│   ├── test_shim.py
│   ├── test_account.py
│   ├── test_reporter.py
│   └── test_e2e.py
├── results/                   ← gitignore；每次回测 1 个子目录
│   └── <start>-<end>_<timestamp>/
│       ├── metrics.csv
│       ├── trades.csv
│       ├── snapshots.csv
│       ├── equity.png
│       ├── run_config.json
│       ├── logs/strategy.log
│       └── data_quality.log
├── README.md
└── pyproject.toml
```

### 4.2 依赖方向

- `backtest/*` → `import` → `strategy_hs300.py`：单向
- `strategy_hs300.py` 不知道 `backtest/` 存在，也不知道 Shim 存在；它认为自己运行在 QMT 里，调用的是 QMT 注入的全局
- 实盘下 QMT 提供这些全局；回测下 Shim 通过 `exec(source, injected_globals)` 注入

### 4.3 策略文件零环境分支

- 没有 `if is_backtest:`、没有 `SKIP_HISTORY_WARMUP` 这类全局开关
- 环境差异**完全靠** Shim 在 `init()` 之后**覆写 `ContextInfo` 属性**（`strategy_start_date`、`log_dir`、`capital`）来表达
- QMT 实盘下 ContextInfo 没有这些覆写，自然走 v1 现有行为

## 5. 策略文件 `strategy_hs300.py` 内部结构

单文件（必须，要复制进 QMT 编辑器），约 600 行，按以下区段组织：

```
§A 配置常量      MAX_POSITIONS / HARD_STOP_PCT / WEIGHTS / COST 等
§B 日志          _log()，路径从 ContextInfo.log_dir 读，默认 c:\
§C 指标计算      sma / macd / check_buy_signal / score_factors    (纯函数)
§D 持仓与风控    Position / check_hard_stop / check_crash /
                check_trend_break / check_trailing_stop / position_size   (纯函数)
§E 大盘择时      check_market_trend                                (纯函数)
§F 交易成本与撮合 trade_cost(side, amount)                          (纯函数, 统一公式)
§G QMT 接口适配  _normalize_code / _sync_positions / _filter_buyable /
                _execute_buy / _execute_sell / _get_account
§H 主控          init / handlebar
                 handlebar 拆 9 个私有辅助函数:
                   _is_actionable_bar
                   _daily_setup
                   _fetch_data
                   _update_market_streak
                   _evaluate_and_execute_sells
                   _is_rebalance_day
                   _do_rebalance
                   _do_refill
                   _log_status
```

### 5.1 相对 v1 的结构改进（业务规则不变）

| 项 | v1 现状 | 新版 |
|---|---|---|
| `handlebar` 长度 | 460 行 | ~30 行（仅流程编排） |
| `get_history_data` 在 `handlebar` 内调用次数 | 3 次 | 1 次（封 `_fetch_data`） |
| 交易成本公式 | 4 处复制粘贴 | 1 处 `trade_cost()` |
| `_execute_sell` 的 log/del 顺序 bug | 现存 | 修：先记录 PnL，再 del positions |
| `_log_status` 长度 | 150 行 | 仍是 public 函数（handlebar 调用），内部再拆 `_log_holdings / _log_sells_today / _log_summary` 三个私有 helper |
| 测试可达性 | `handlebar` 几乎无法单测 | 9 个小函数全部可单测 |

### 5.2 保留不变（v1 业务规则原样）

- 四因子入场：MA60↑ + MA5>MA20 + MACD红柱>0且扩大 + 放量 + 当日涨>1%
- 截面 Z-score 归一 + 权重 0.30/0.25/0.25/0.20 加权打分
- 大盘择时：close>MA20 + MACD>0 + 当日跌≤-3% 拦截；连续 2 天 OK 才允许买；连续 2 天弱清仓非强势股
- 三层止损：硬止损 5% / 单日暴跌 7% / 跌破 MA20 + MACD 衰竭双确认 / 跟踪止盈 10% 后回落 8%
- 换仓：每 10 个交易日；盈利 >10% 的持仓即使排名跌出也保留
- 持仓上限 5 只，每只 20%
- 14:50 时间闸（实盘有效，回测下 `current_time='00:00:00'` 天然通过）

### 5.3 止盈逻辑三处保留

1. **跟踪止盈** (`check_trailing_stop`)：盈利 >10% 后从最高价回落 >8% 卖出
2. **换仓盈利保护** (`_do_rebalance`)：盈利 >10% 不强制换出
3. **大盘弱清仓豁免** (`_evaluate_and_execute_sells`)：连续 2 天大盘弱时只清盈利 ≤10% 的非强势股

## 6. 回测层 Shim 设计

### 6.1 ContextInfo 模拟

| 属性/方法 | v1 期望 | Shim 实现 |
|---|---|---|
| `barpos` | int 当前 bar 索引 | 每日 +1 |
| `last_processed_barpos` | 幂等用 | 策略自管 |
| `capital` | float 初始资金 | 50w；init 后 Shim 覆写 |
| `accountid`, `positions`, `strategy_start_date`, `log_dir` | 策略自设 | init 后 Shim 覆写 `strategy_start_date` 和 `log_dir` |
| `set_account(id)` | no-op in QMT | no-op |
| `set_universe(codes)` | QMT 内部置股票池 | 记录到 `_active_universe`，影响 `get_history_data` 返回范围 |
| `get_sector('000300.SH')` | 当日 HS300 成分股 | **返回 data_a/ 静态全集**（已知偏差） |
| `get_instrumentdetail(code)` | 含 `m_strInstrumentName`、`UpStopPrice` | 从 data_a/ 第 2 列拿 name；UpStopPrice = 前一日 close × 1.10 |
| `get_history_data(N, '1d', field, dividend_type, skip_paused)` | `dict[code -> list[N 个值]]` | 切 `data_a/` DataFrame，**最后一根 = 当日值** |
| `get_bar_timetag(barpos)` | 毫秒时间戳 | 缓存 `_bar_ts[barpos]` |

### 6.2 `get_history_data` 关键契约

- `period` 仅支持 `'1d'`，其他 `raise NotImplementedError`
- 返回 dict，key 是当前 `_active_universe` 范围内的票 + 已持仓票 + 指数
- 每个 list 的**最后一个元素 = 当日（含）的 close**
- 数据不足 N 天时返回短列表（与 QMT 行为一致），不报错

### 6.3 撮合（方案 A：当日 close 同步成交）

```
passorder(opcode, mode, account_id, code, price_mode, price, volume, ContextInfo):
  # opcode: 23=买, 24=卖；price_mode: 5=最新价
  fill_price = 当日 close
  if 买 and is_limit_up: record_reject(LIMIT_UP)
  elif 卖 and is_limit_down: record_reject(LIMIT_DOWN)
  elif 买 and cash < amount: record_reject(CASH_SHORT)
  elif 卖 and can_use_volume < volume: record_reject(VOLUME_SHORT / T1_LOCKED)
  else: 同步成交，改现金改持仓
```

涨停判定：当日 close ≥ UpStopPrice × 0.995
跌停判定：当日 close ≤ DownStopPrice × 1.005

### 6.4 `get_trade_detail_data` 模拟

- `'ACCOUNT'` 返回 `[SimpleNamespace(m_dBalance, m_dAvailable)]`
- `'POSITION'` 返回每只持仓 `SimpleNamespace(m_strInstrumentID, m_nVolume, m_nCanUseVolume, m_dOpenPrice)`
- **T+1**：`pos.buy_date == today` 时 `m_nCanUseVolume = 0`

### 6.5 静态 universe 局限说明

- `data_a/` 是 ~300 只票的静态快照（约等于近期沪深 300 成分股）
- 早年还未纳入 HS300 但 `data_a/` 中有数据的票 → 回测会"错买" → 前视偏差
- 早年退出 HS300 但已删除的票 → 回测看不到 → survivorship bias
- 两个偏差方向相反，幅度估计 < 3%/年
- spec 写入"已知局限"，未来若有 HS300 历史成分股快照可消除此偏差

### 6.6 复权数据局限说明

- `data_a/` 抽样验证：大多数除权事件已前复权，**但 2024-06-21 茅台等个别事件未做**
- 影响最大单日"假跌"约 2%，远低于策略的 5%/7% 止损阈值
- DataLoader 加载时扫描所有 >5% 的跨日跳水，输出到 `results/<run_id>/data_quality.log`
- 整体回测可信度损失估计 < 1%

## 7. 数据流：完整生命周期

```
CLI 启动
  ↓
Step 1. 配置合并
  ├─ 读 configs/default.yaml
  ├─ CLI 参数覆盖
  └─ 构造 RunConfig (frozen)
  ↓
Step 2. 数据加载 (DataLoader)
  ├─ 扫 300data/data_a/*_day.txt
  ├─ 加载范围 = [start - 120 交易日, end]
  ├─ 数据质量检查 → data_quality.log
  └─ 构造交易日历（取自 SH.000300）
  ↓
Step 3. 策略加载 + Shim 装配 (StrategyLoader)
  ├─ 实例化 ContextInfo, Account
  ├─ injected_globals = {passorder, get_trade_detail_data,
  │                      timetag_to_datetime, get_market_data_ex, np, ...}
  ├─ exec(strategy_hs300.py, injected_globals)
  └─ strategy.init(ContextInfo)
  ↓
Step 4. 环境覆写
  ├─ ctx.strategy_start_date = config.start_date
  ├─ ctx.log_dir = config.run_dir / 'logs'
  └─ ctx.capital = config.initial_capital
  ↓
Step 5. 主循环 (Engine)
  for day in trading_calendar[start:end]:
    shim.advance_to(day)
    account.advance_day(day)       # T+1 解锁昨日买入
    strategy.handlebar(ContextInfo)  # 同步成交
    account.snapshot(day)
  ↓
Step 6. 报告生成 (Reporter)
  ├─ 按自然年切分 snapshots
  ├─ 每年算 metrics + 累计区间整算一次
  └─ 输出 results/<run_id>/{metrics.csv, trades.csv, snapshots.csv,
                            equity.png, run_config.json, logs/, data_quality.log}
```

## 8. 错误处理策略

### 8.1 策略层 — 软失败保持 v1 现状

`try/except` 容忍 QMT 数据空洞，**逐字保留** v1 的吞异常行为：
- ST 过滤 `get_instrumentdetail` 失败 → 当作非 ST 保留
- 单只票 `get_history_data` 短于 70 天 → 跳过
- `get_trade_detail_data` 异常 → fallback 估算总资产

### 8.2 基础设施层 — 显式 fail loud（少数自动恢复例外）

| 错误情形 | 行为 |
|---|---|
| `config.start_date - 120d < data_loader.min_date` | `ConfigError` |
| `config.end_date > data_loader.max_date` | `ConfigError` |
| `data_a/SH.000300_day.txt` 缺失 | `DataError` |
| CSV 列数不对 | `DataError(code, line)` |
| Shim 收到 `period != '1d'` | `NotImplementedError` |
| `passorder` 不支持的 opcode | `NotImplementedError` |
| 结果目录已存在且非空（**自动恢复**） | 追加 `_N` 后缀，info 日志告知 |

### 8.3 业务失败 — 必须进 trades.csv

订单失败的业务原因独立行记录：
- `NO_PRICE` / `LIMIT_UP` / `LIMIT_DOWN` / `CASH_SHORT` / `VOLUME_SHORT` / `T1_LOCKED`
- `status='REJECTED'`, `reason=...`，事后从 trades.csv 反推

## 9. 测试策略 (TDD)

### 9.1 测试金字塔

- **单元测试** ~50 例：纯函数级（指标/风控/择时/成本/适配）
- **集成测试** ~10 例：Shim + Engine + Account 联调（成交/T+1/snapshot/年度切分）
- **端到端 E2E** ~3 例：完整跑短/中/长周期

### 9.2 测试覆盖清单

| 文件 | 例数 | 关键场景 |
|---|---|---|
| test_indicators.py | ~15 | sma/macd 边界；四因子单独打开关闭；score_factors 对齐 v1 |
| test_positions.py | ~10 | 硬止损/暴跌/趋势破/跟踪止盈边界 |
| test_market.py | ~5 | 单日 -3% 拦截；MA20/MACD 组合；数据短 |
| test_costs.py | ~5 | 买无印花、卖有印花、佣金最低 5 元 |
| test_qmt_adapter.py | ~10 | 代码标准化；ST 过滤；账户回退；688 过滤 |
| test_shim.py | ~10 | get_history_data 长度/最后一根/非 1d；passorder 4 类拒单 |
| test_account.py | ~6 | 现金持仓变动；T+1 锁定；snapshot 平衡；多笔同日 |
| test_reporter.py | ~4 | 单年/跨年/0 交易/累计算法正确 |
| test_e2e.py | ~3 | 30 日冒烟；2020 全年黄金基线；2020-2021 跨年 |

### 9.3 E2E 黄金基线

- E2E-1：start=2020-02-03 end=2020-03-15，仅验产物存在，<30s
- E2E-2：start=2020-01-01 end=2020-12-31，锁定 5 项指标到 `golden_2020.json`，容差 ±0.1pp（胜率 ±0.5pp，交易次数精确）
- E2E-3：start=2020-01-01 end=2021-12-31，验 metrics.csv 是 3 行（2020/2021/累计）+ 累计算法验算

### 9.4 测试数据

- 不造 fake，从 `300data/data_a/` 真实子集切片做 fixture
- `pytest.fixture(scope='session')` 缓存
- 选取 SH.600000 / SH.600519 / SH.000300 / 几只典型样本

### 9.5 不测的范围

- v1 业务参数本身（0.30/0.25/0.25/0.20 等权重值）
- 真实 QMT 实盘行为（无法在本地复现）
- 数据质量本身（DataLoader 只负责正确读 CSV）

## 10. 报告产物详细规范

### 10.1 metrics.csv

每个自然年一行 + 最后一行累计。**部分年**（start/end 不是 1-1/12-31）的命名规则：
- 起年若 `start_date != 1-1`：`period='2020(03-15起)'`
- 末年若 `end_date != 12-31`：`period='2021(08-30止)'`
- 中间完整年份：`period='2020'`
- 累计行：`period='total'`

| 列 | 含义 |
|---|---|
| period | 见上 |
| start_date | 该 period 起始日 |
| end_date | 该 period 终止日 |
| start_equity | 起始权益 |
| end_equity | 末权益 |
| total_return | `end/start - 1` |
| annual_return | 几何年化 |
| max_drawdown | 区间内最大回撤 |
| sharpe | 区间夏普（年化） |
| n_trades | 成交笔数（不含拒单） |
| n_rejected | 拒单笔数 |
| win_rate | 盈利笔数/总笔数 |
| avg_holding_days | 平均持有天数 |
| total_cost | 累计交易成本（佣金+印花+过户+滑点） |

### 10.2 trades.csv

| 列 | 含义 |
|---|---|
| trade_id | 自增 |
| date | 成交日 |
| code | 股票代码 |
| name | 股票名 |
| side | buy / sell |
| volume | 成交股数 |
| price | 成交价（当日 close） |
| amount | 成交金额 |
| commission/stamp/transfer/slippage | 4 项成本 |
| reason | 成交/拒单原因（buy_signal/rebalance/hard_stop/trend_break/trailing_stop/crash_protection/market_weak/LIMIT_UP/CASH_SHORT/T1_LOCKED/...） |
| status | FILLED / REJECTED |
| realized_pnl | 卖单的已实现 PnL（含成本） |

### 10.3 snapshots.csv

| 列 | 含义 |
|---|---|
| date | 当日 |
| cash | 当日末现金 |
| position_value | 当日末持仓市值（按 close 计） |
| total_equity | cash + position_value |
| n_positions | 持仓票数 |
| daily_return | total_equity 当日变化率 |

### 10.4 equity.png

- 横轴 = 日期，纵轴 = total_equity
- 跨年时绘制纵向虚线分隔年份
- 标注：最大回撤、最高点、最低点

### 10.5 run_config.json

- 本次跑的完整 RunConfig 序列化
- 命令行原始参数
- Git commit hash
- 跑步起止时间戳

## 11. 实盘部署流程（保持 v1 风格）

1. `git pull` 拿到最新 `strategy_hs300.py`
2. 在 QMT 中新建 Python 模型
3. 复制 `strategy_hs300.py` 全部内容到策略编辑器
4. 修改文件首行编码声明为 `# -*- coding: gbk -*-`（若仓库内已是 utf-8，需另存为 gbk）
5. 修改 `init()` 中的 `set_account('实盘账号')`
6. 设置 K 线周期 = **5 分钟**（不能用日线，原因见 spec 第 12 节）
7. 启动策略

策略文件**无需手动改任何 flag**（区别于 v1）。

## 12. QMT 实盘运行时背景

- v1 在 QMT 实盘下注册为 **5 分钟周期**，每根 5min bar 都会触发 `handlebar`
- 策略内 `if current_time != '00:00:00' and current_time < '14:50:00': return` 把 14:50 之前的 bar 全拦回
- 14:50 那根 bar 触发后调 `passorder`，~14:55 实际成交
- 14:50 时调用 `get_history_data(70, '1d', 'close')` 拿到的最后一根 close = 当日 partial daily bar（QMT 内部从 5min 聚合），与真实 EOD close 漂移 <0.3%
- 回测下 Shim 喂日线，`current_time='00:00:00'`，策略走"日线模式分支"自然通过 14:50 闸
- 两种模式下"今日 close"差异被 v1 既有的 0.05% 滑点 + 0.1% 印花税覆盖

## 13. 已知局限（用户已确认接受）

1. **静态 universe**：~300 只全集，含早年 HS300 调整带来的双向偏差（< 3%/年）
2. **复权不完全**：`data_a/` 个别除权事件未前复权，最大单日"假跌" ~2%，整体可信度损失 < 1%
3. **撮合粒度**：方案 A 用当日 close 同步成交，相对实盘 14:50 决策有 < 0.3% 乐观漂移
4. **不模拟集合竞价 / 涨跌停板上的部分成交**：涨停日整单拒
5. **不支持复权除权调整**：策略层面读到的是 DataLoader 提供的已复权数据，跨除权日的指标不再次调整

## 14. 后续可演进项（不在本次范围）

- 接入 baostock / akshare 的 qfq 数据源，消除复权瑕疵
- 引入 HS300 历史成分股快照，消除 universe 偏差
- 参数搜索 / 网格优化
- 接入第三方回测框架对拍
- Web UI 报告查看器
