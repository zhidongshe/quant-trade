# 沪深300多头趋势量化策略

## 策略概述

基于迅投QMT极速策略交易系统的Python量化策略，以沪深300成分股为标的，采用多因子共振方式选股，配合严格止损机制。

## 核心参数

| 参数 | 值 |
|------|-----|
| 股票池 | 沪深300成分股 |
| 最大持仓 | 5只 |
| 单只仓位 | 20% |
| 硬止损 | -3% |
| 趋势止损 | 跌破20日均线 |
| 跟踪止盈 | 盈利>5%后，从最高点回落5% |
| 佣金 | 万分之一 |
| 印花税 | 千分之一（卖出） |

## 入场条件（三因子共振）

1. 收盘价 > 60日均线
2. 5日均线 > 20日均线
3. MACD柱状线 > 0
4. 当日成交量 > 20日平均成交量

## 文件说明

- `strategy/hs300_trend_strategy.py` — QMT策略主文件
- `strategy/indicators.py` — 技术指标计算（均线、MACD、信号判断）
- `strategy/portfolio.py` — 持仓管理与风控逻辑
- `tests/` — 单元测试

## 使用步骤

### 1. 环境准备

在QMT客户端的【数据管理】中补充以下数据：
- 沪深300成分股的日线历史数据（至少覆盖回测区间+60个交易日）
- 前复权数据

### 2. 导入策略

1. 打开QMT客户端，进入【模型研究】
2. 点击【新建模型】→ 选择Python模型
3. 将 `strategy/hs300_trend_strategy.py` 的代码复制到策略编辑器中
4. 将文件编码改为 **GBK**，并添加 `# -*- coding: gbk -*-` 到第一行
5. 修改 `init` 中的资金账号 `ContextInfo.set_account('你的账号')`
6. 修改 `sys.path.insert` 中的路径为QMT客户端所在机器上的实际路径

### 3. 设置回测参数

在策略编辑器右侧【回测参数】中设置：
- 开始时间、结束时间
- 初始资金：默认100万
- 滑点：0.01元或0.1%
- 买入佣金：0.0001（万分之一）
- 卖出佣金：0.0001
- 卖出印花税：0.001
- 最低佣金：5元
- 基准：000300.SH

### 4. 运行回测

点击【回测】按钮，查看历史表现。

### 5. 实盘/模拟交易

回测满意后，将策略加入【模型交易】，以模拟或实盘方式运行。

## 本地测试

```bash
cd /Users/shezhidong/Documents/代码库/quant-trade
pytest tests/ -v
```

当前测试状态：20 tests passing

### hs300_xtquant_v1 supervised live trading configuration

`hs300_xtquant_v1.py` now reads its live runtime settings from environment variables:

- `HS300_ACCOUNT_ID` — broker account id
- `HS300_QMT_PATH` — MiniQMT userdata path
- `HS300_STATE_DIR` — directory for JSON strategy state
- `HS300_LOG_DIR` — directory for strategy logs
- `HS300_SCHEDULE_TIME` — daily execution time in `HH:MM`

Behavioral safety rules:
- local positions are updated only after broker-side confirmation or broker-position reconciliation
- critical query uncertainty blocks new buys
- stale pending orders are moved to manual review on the next trading day

## 风险提示

1. 最大回撤5%是理想目标，极端行情下可能突破
2. 集中持仓（5只）在单票黑天鹅时风险较大
3. 震荡市中趋势策略可能产生连续磨损
4. 策略历史表现不代表未来收益
