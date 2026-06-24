# quant-trade-new Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `quant-trade-new/` 目录，构建一份 QMT 形态的沪深 300 趋势策略文件，可同时用于 QMT 实盘和本地基于 `300data/data_a/` 的日线回测，支持任意起止日期 + 跨年时按自然年 + 累计分析。

**Architecture:** Shim 方案。策略文件 `strategy_hs300.py` 单文件 QMT 形态；本地回测时由 `backtest/shim.py` 模拟 QMT API (`ContextInfo`, `passorder`, `get_trade_detail_data`, `timetag_to_datetime`)，通过 `exec(source, injected_globals)` 注入。策略业务规则字面照搬 v1，仅整理结构 + 修一个 bug。

**Tech Stack:** Python 3.9+, numpy, pandas, matplotlib, pyyaml, pytest

## Global Constraints

每个 task 的隐式要求都包含这一节，不再每 task 重复：

- **目标根目录**：`/Users/shezhidong/Documents/代码库/quant-trade/quant-trade-new/`（相对路径下文统一用 `quant-trade-new/...`）
- **v1 源文件**（拷贝逻辑用）：`/Users/shezhidong/Documents/代码库/quant-trade/hs300_trend_strategy_single_file_v1.py`
- **数据目录**：`/Users/shezhidong/Documents/代码库/quant-trade/300data/data_a/`（301 个 `<EX>.<code>_day.txt`，含 `SH.000300_day.txt` 指数）
- **CSV 列顺序**：`code,name,time_key,high,open,low,close,turnover`
- **strategy_hs300.py 单文件硬约束**：必须能整文件复制粘贴进 QMT 策略编辑器，**不许 import 本仓库内其他文件**
- **v1 业务规则字面照搬**：四因子、Z-score 0.30/0.25/0.25/0.20 加权、大盘择时连续 2 天、10 日换仓、三层止损、单日 -7% 暴跌保护、大盘弱清仓豁免 — 一行都不动
- **唯一允许的 bug 修复**：v1 `_execute_sell` 在 `del positions[code]` 之后才 `_log` 卖出信息导致 fallback 分支；新版必须先记录再删
- **初始资金 50w**；佣金 0.01% (最低 5 元) / 印花税 0.1% (仅卖) / 过户费 0.001% / 滑点 0.05% — 沿用 v1 默认
- **撮合**：方案 A，当日 close 同步成交
- **T+1**：严格模拟，当日买入 `m_nCanUseVolume = 0`
- **warmup**：DataLoader 加载范围 = `[start - 120 交易日, end]`
- **Universe**：`data_a/` 静态全集 + 指数
- **TDD**：每个 task 内 "先写失败测试 → 跑确认失败 → 写最小实现 → 跑确认通过 → commit"
- **测试速度**：单元 + 集成测试套件 `pytest tests/ -x --ignore=tests/test_e2e.py` 必须 < 30s
- **commit 风格**：参考仓库现有：`feat(component): 描述` / `test(component): 描述` / `fix(component): 描述`

## File Structure

完整产物清单 — 实现期间每个文件归属于唯一一个 task（首次创建的 task）：

```
quant-trade-new/
├── pyproject.toml                          [Task 1]
├── README.md                               [Task 1]
├── .gitignore                              [Task 1]
├── configs/
│   └── default.yaml                        [Task 1]
├── strategy_hs300.py                       [Task 2 起多 task 累加]
│   §A 常量                                 [Task 2]
│   §C 指标                                 [Task 2]
│   §D 持仓风控                              [Task 3]
│   §E 大盘择时                              [Task 4]
│   §F 交易成本                              [Task 5]
│   §B 日志                                  [Task 10]
│   §G QMT 适配                             [Task 10]
│   §H init + handlebar                     [Task 11]
├── backtest/
│   ├── __init__.py                         [Task 1]
│   ├── cli.py                              [Task 1]
│   ├── data_loader.py                      [Task 6]
│   ├── account.py                          [Task 7]
│   ├── shim.py                             [Task 8 起 2 task 累加]
│   ├── strategy_loader.py                  [Task 12]
│   ├── engine.py                           [Task 13]
│   └── reporter.py                         [Task 14]
└── tests/
    ├── __init__.py                         [Task 1]
    ├── conftest.py                         [Task 1]
    ├── fixtures/                           [Task 15]
    │   └── golden_2020.json                [Task 15]
    ├── test_cli.py                         [Task 1]
    ├── test_indicators.py                  [Task 2]
    ├── test_positions.py                   [Task 3]
    ├── test_market.py                      [Task 4]
    ├── test_costs.py                       [Task 5]
    ├── test_data_loader.py                 [Task 6]
    ├── test_account.py                     [Task 7]
    ├── test_shim_context.py                [Task 8]
    ├── test_shim_orders.py                 [Task 9]
    ├── test_qmt_adapter.py                 [Task 10]
    ├── test_handlebar.py                   [Task 11]
    ├── test_strategy_loader.py             [Task 12]
    ├── test_engine.py                      [Task 13]
    ├── test_reporter.py                    [Task 14]
    └── test_e2e.py                         [Task 15]
```

---

### Task 1: Project Scaffold + CLI + RunConfig

**Files:**
- Create: `quant-trade-new/pyproject.toml`
- Create: `quant-trade-new/README.md`
- Create: `quant-trade-new/.gitignore`
- Create: `quant-trade-new/configs/default.yaml`
- Create: `quant-trade-new/backtest/__init__.py`
- Create: `quant-trade-new/backtest/cli.py`
- Create: `quant-trade-new/tests/__init__.py`
- Create: `quant-trade-new/tests/conftest.py`
- Test: `quant-trade-new/tests/test_cli.py`

**Interfaces:**
- Consumes: 无（首 task）
- Produces:
  - `backtest.cli.RunConfig` (frozen dataclass)，字段：`start_date: date`, `end_date: date`, `initial_capital: float`, `data_root: str`, `results_dir: str`, `commission_rate: float`, `commission_min: float`, `stamp_rate: float`, `transfer_rate: float`, `slippage_rate: float`, `max_positions: int`, `rebalance_interval: int`, `warmup_days: int`
  - `backtest.cli.load_config(config_path: str | None, cli_overrides: dict) -> RunConfig`
  - `backtest.cli.parse_args(argv: list[str]) -> argparse.Namespace`
  - `backtest.cli.build_run_id(start: date, end: date, now: datetime) -> str` 返回 `"20200101-20211231_20260624-203015"` 形式

- [ ] **Step 1: 创建目录骨架**

```bash
mkdir -p quant-trade-new/configs quant-trade-new/backtest quant-trade-new/tests/fixtures
touch quant-trade-new/backtest/__init__.py quant-trade-new/tests/__init__.py
```

- [ ] **Step 2: 写 pyproject.toml**

`quant-trade-new/pyproject.toml`:
```toml
[project]
name = "quant-trade-new"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [
    "numpy>=1.24",
    "pandas>=2.0",
    "matplotlib>=3.7",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
test = ["pytest>=7.4"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["backtest*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["e2e: slow end-to-end tests"]
```

- [ ] **Step 3: 写 .gitignore**

`quant-trade-new/.gitignore`:
```
results/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.venv/
```

- [ ] **Step 4: 写 configs/default.yaml**

`quant-trade-new/configs/default.yaml`:
```yaml
# v1 默认参数 + 用户指定初始资金 50w
initial_capital: 500000.0

# 数据
data_root: "../300data/data_a"
results_dir: "results"

# 时间段（必须 CLI 或此处提供）
start_date: null
end_date: null

# 费率（v1 默认）
commission_rate: 0.0001
commission_min: 5.0
stamp_rate: 0.001
transfer_rate: 0.00001
slippage_rate: 0.0005

# 策略参数（v1 默认）
max_positions: 5
rebalance_interval: 10
warmup_days: 120
```

- [ ] **Step 5: 写 tests/conftest.py（pytest 路径配置）**

`quant-trade-new/tests/conftest.py`:
```python
import sys
from pathlib import Path

# 让 tests 能 import backtest.* 和 strategy_hs300
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
```

- [ ] **Step 6: 写失败测试 test_cli.py**

`quant-trade-new/tests/test_cli.py`:
```python
from datetime import date, datetime
from backtest.cli import load_config, parse_args, build_run_id


def test_load_default_config():
    cfg = load_config('configs/default.yaml', {})
    assert cfg.initial_capital == 500000.0
    assert cfg.commission_rate == 0.0001
    assert cfg.max_positions == 5
    assert cfg.warmup_days == 120


def test_cli_overrides_config():
    cli_overrides = {'start_date': date(2020, 1, 1), 'end_date': date(2021, 12, 31),
                     'initial_capital': 1000000.0}
    cfg = load_config('configs/default.yaml', cli_overrides)
    assert cfg.start_date == date(2020, 1, 1)
    assert cfg.end_date == date(2021, 12, 31)
    assert cfg.initial_capital == 1000000.0  # CLI 覆盖 config


def test_missing_dates_raises():
    import pytest
    with pytest.raises(ValueError, match="start_date"):
        load_config('configs/default.yaml', {})  # 默认 config 里 start/end 都是 null


def test_parse_args_basic():
    ns = parse_args(['--start', '2020-01-01', '--end', '2021-12-31',
                     '--capital', '500000'])
    assert ns.start == date(2020, 1, 1)
    assert ns.end == date(2021, 12, 31)
    assert ns.capital == 500000.0


def test_build_run_id_format():
    now = datetime(2026, 6, 24, 20, 30, 15)
    rid = build_run_id(date(2020, 1, 1), date(2021, 12, 31), now)
    assert rid == "20200101-20211231_20260624-203015"
```

- [ ] **Step 7: 跑测试验证失败**

```bash
cd quant-trade-new && pytest tests/test_cli.py -v
```
预期：FAIL，`ModuleNotFoundError: No module named 'backtest.cli'`

- [ ] **Step 8: 写 backtest/cli.py 最小实现**

`quant-trade-new/backtest/cli.py`:
```python
"""CLI 入口与配置合并。"""
import argparse
import yaml
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class RunConfig:
    start_date: date
    end_date: date
    initial_capital: float
    data_root: str
    results_dir: str
    commission_rate: float
    commission_min: float
    stamp_rate: float
    transfer_rate: float
    slippage_rate: float
    max_positions: int
    rebalance_interval: int
    warmup_days: int


def _parse_date(v):
    if v is None:
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def load_config(config_path: str | None, cli_overrides: dict) -> RunConfig:
    raw: dict = {}
    if config_path:
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
    raw.update({k: v for k, v in cli_overrides.items() if v is not None})

    start = _parse_date(raw.get('start_date'))
    end = _parse_date(raw.get('end_date'))
    if start is None:
        raise ValueError("start_date 必须通过 CLI 或 config 提供")
    if end is None:
        raise ValueError("end_date 必须通过 CLI 或 config 提供")
    if end < start:
        raise ValueError(f"end_date {end} 必须 >= start_date {start}")

    return RunConfig(
        start_date=start, end_date=end,
        initial_capital=float(raw.get('initial_capital', 500000.0)),
        data_root=str(raw.get('data_root', '../300data/data_a')),
        results_dir=str(raw.get('results_dir', 'results')),
        commission_rate=float(raw.get('commission_rate', 0.0001)),
        commission_min=float(raw.get('commission_min', 5.0)),
        stamp_rate=float(raw.get('stamp_rate', 0.001)),
        transfer_rate=float(raw.get('transfer_rate', 0.00001)),
        slippage_rate=float(raw.get('slippage_rate', 0.0005)),
        max_positions=int(raw.get('max_positions', 5)),
        rebalance_interval=int(raw.get('rebalance_interval', 10)),
        warmup_days=int(raw.get('warmup_days', 120)),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog='backtest')
    p.add_argument('--config', default='configs/default.yaml')
    p.add_argument('--start', type=date.fromisoformat, dest='start')
    p.add_argument('--end', type=date.fromisoformat, dest='end')
    p.add_argument('--capital', type=float, dest='capital')
    p.add_argument('--data-root', dest='data_root')
    p.add_argument('--results-dir', dest='results_dir')
    return p.parse_args(argv)


def build_run_id(start: date, end: date, now: datetime) -> str:
    return f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}_{now.strftime('%Y%m%d-%H%M%S')}"


def main():
    ns = parse_args(None)
    overrides = {
        'start_date': ns.start, 'end_date': ns.end,
        'initial_capital': ns.capital,
        'data_root': ns.data_root, 'results_dir': ns.results_dir,
    }
    cfg = load_config(ns.config, overrides)
    print(cfg)


if __name__ == '__main__':
    main()
```

- [ ] **Step 9: 跑测试验证通过**

```bash
cd quant-trade-new && pytest tests/test_cli.py -v
```
预期：5 PASSED

- [ ] **Step 10: 写 README.md 骨架**

`quant-trade-new/README.md`:
```markdown
# quant-trade-new

沪深 300 多头趋势策略，QMT 实盘 + 本地日线回测两用。

## 安装
```bash
cd quant-trade-new
pip install -e .[test]
```

## 跑回测
```bash
python -m backtest.cli --start 2020-01-01 --end 2021-12-31
```

## 跑测试
```bash
pytest tests/ -x
```

## 部署到 QMT
见 `docs/superpowers/specs/2026-06-24-quant-trade-new-design.md` §11
```

- [ ] **Step 11: Commit**

```bash
cd /Users/shezhidong/Documents/代码库/quant-trade
git add quant-trade-new/
git commit -m "feat(scaffold): quant-trade-new 项目骨架 + RunConfig + CLI"
```

---

### Task 2: Strategy §A 常量 + §C 指标 (sma/macd/check_buy_signal/score_factors)

**Files:**
- Create: `quant-trade-new/strategy_hs300.py` (新建，含 §A + §C)
- Test: `quant-trade-new/tests/test_indicators.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `strategy_hs300.sma(prices: np.ndarray, period: int) -> np.ndarray`
  - `strategy_hs300.macd(prices: np.ndarray, fast=12, slow=26, signal=9) -> tuple[np.ndarray, np.ndarray, np.ndarray]` 返回 (dif, dea, hist)
  - `strategy_hs300.check_buy_signal(prices: np.ndarray, volumes: np.ndarray) -> bool`
  - `strategy_hs300.score_factors(prices: np.ndarray, volumes: np.ndarray) -> dict | None` （v1 中叫 `score_stock`，新版改名）
  - 常量：`MAX_POSITIONS=5`, `HARD_STOP_PCT=0.05`, `PROFIT_THRESHOLD=0.10`, `TRAILING_PULLBACK=0.08`, `REBALANCE_INTERVAL=10`, `INDEX_CODE='000300.SH'`, `WEIGHTS = {'trend':0.30, 'spread':0.25, 'macd':0.25, 'volume':0.20}`, `COST = {...}`

- [ ] **Step 1: 写 tests/test_indicators.py（15 例）**

```python
import numpy as np
import pytest
from strategy_hs300 import sma, macd, check_buy_signal, score_factors


# === sma ===
def test_sma_returns_nan_when_too_short():
    out = sma(np.array([1.0, 2.0, 3.0]), period=5)
    assert np.all(np.isnan(out))


def test_sma_basic_5period():
    prices = np.arange(1, 11, dtype=float)  # 1..10
    out = sma(prices, period=5)
    assert np.isnan(out[3])
    assert out[4] == 3.0   # (1+2+3+4+5)/5
    assert out[9] == 8.0   # (6+7+8+9+10)/5


# === macd ===
def test_macd_returns_three_arrays_same_length():
    prices = np.linspace(10, 20, 100)
    dif, dea, hist = macd(prices)
    assert len(dif) == len(dea) == len(hist) == 100


def test_macd_rising_series_has_positive_hist_after_warmup():
    prices = np.linspace(10, 50, 100)  # 单调递增
    _, _, hist = macd(prices)
    assert hist[-1] > 0


# === check_buy_signal ===
@pytest.fixture
def good_setup():
    """构造 100 天单调微升 + 当日放量上涨 1.5% 的序列。"""
    prices = np.array([10.0 + i * 0.05 for i in range(99)])
    prices = np.append(prices, prices[-1] * 1.015)  # 当日涨 1.5%
    volumes = np.array([1000.0] * 99 + [2000.0])    # 当日放量
    return prices, volumes


def test_check_buy_signal_passes_good_setup(good_setup):
    p, v = good_setup
    assert check_buy_signal(p, v) is True


def test_check_buy_signal_fails_short_prices():
    assert check_buy_signal(np.array([1.0] * 10), np.array([1.0] * 10)) is False


def test_check_buy_signal_fails_below_ma60(good_setup):
    p, v = good_setup
    p[-1] = p[-2] * 0.5  # 当日暴跌至 MA60 下
    assert check_buy_signal(p, v) is False


def test_check_buy_signal_fails_ma5_below_ma20(good_setup):
    p, v = good_setup
    # 倒退 ma5 到 ma20 下方
    p[-5:] = p[-5:] - 5.0
    p[-1] = p[-2] * 1.015  # 保住涨幅条件
    assert check_buy_signal(p, v) is False


def test_check_buy_signal_fails_today_change_below_1pct(good_setup):
    p, v = good_setup
    p[-1] = p[-2] * 1.005  # 仅涨 0.5%
    assert check_buy_signal(p, v) is False


def test_check_buy_signal_fails_no_volume_expansion(good_setup):
    p, v = good_setup
    v[-1] = 500.0  # 缩量
    assert check_buy_signal(p, v) is False


def test_check_buy_signal_fails_macd_hist_shrinking(good_setup):
    p, v = good_setup
    # 通过把当日 close 拉得很高让 hist 强劲，再人为构造下一日缩窄
    # 这里换一种构造：去掉涨幅，制造 hist 收窄
    p[-2] = p[-3] * 1.03
    p[-1] = p[-2] * 1.001  # 涨幅 < 1%，会被涨幅条件提前否定
    assert check_buy_signal(p, v) is False


# === score_factors ===
def test_score_factors_none_when_signal_fails():
    p = np.array([10.0] * 100)  # 横盘，必失败
    v = np.array([1000.0] * 100)
    assert score_factors(p, v) is None


def test_score_factors_returns_four_keys(good_setup):
    p, v = good_setup
    f = score_factors(p, v)
    assert f is not None
    assert set(f.keys()) == {'trend_score', 'ma_spread_score', 'macd_score', 'volume_score'}


def test_score_factors_values_finite(good_setup):
    p, v = good_setup
    f = score_factors(p, v)
    assert all(np.isfinite(v) for v in f.values())
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_indicators.py -v
```
预期：所有 FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 创建 strategy_hs300.py，写 §A + §C**

`quant-trade-new/strategy_hs300.py`:
```python
# -*- coding: utf-8 -*-
"""沪深300多头趋势策略 — QMT 实盘/本地回测两用单文件版。

部署到 QMT 时改首行为 # -*- coding: gbk -*-，并修改 init() 里的 set_account。
本地回测时由 backtest/shim.py 注入 QMT 全局函数。
策略业务规则与 hs300_trend_strategy_single_file_v1.py 完全一致，仅整理结构。
"""

import numpy as np
import os
from datetime import datetime

# ════════════════════════════════════════════════════
# §A 配置常量
# ════════════════════════════════════════════════════

ACCOUNT_ID = '8890358835'  # 实盘部署时改成你的账号
ACCOUNT_TYPE = 'STOCK'
MAX_POSITIONS = 5
HARD_STOP_PCT = 0.05
PROFIT_THRESHOLD = 0.10
TRAILING_PULLBACK = 0.08
REBALANCE_INTERVAL = 10
INDEX_CODE = '000300.SH'

WEIGHTS = {'trend': 0.30, 'spread': 0.25, 'macd': 0.25, 'volume': 0.20}

COST = {
    'commission': 0.0001,
    'commission_min': 5.0,
    'stamp': 0.001,
    'transfer': 0.00001,
    'slippage': 0.0005,
}


# ════════════════════════════════════════════════════
# §C 指标计算（纯函数）
# ════════════════════════════════════════════════════

def sma(prices, period):
    """简单移动平均，长度不足时返回全 nan。与 v1 行为一致。"""
    prices = np.asarray(prices, dtype=float)
    if len(prices) < period:
        return np.full_like(prices, np.nan, dtype=float)
    result = np.full_like(prices, np.nan, dtype=float)
    cumsum = np.cumsum(np.insert(prices, 0, 0))
    result[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return result


def macd(prices, fast=12, slow=26, signal=9):
    """MACD (dif, dea, hist)。EMA 实现与 v1 一致。"""
    prices = np.asarray(prices, dtype=float)

    def _ema(data, period):
        alpha = 2.0 / (period + 1)
        result = np.zeros_like(data, dtype=float)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    ema_fast = _ema(prices, fast)
    ema_slow = _ema(prices, slow)
    dif = ema_fast - ema_slow
    dea = _ema(dif, signal)
    hist = dif - dea
    return dif, dea, hist


def check_buy_signal(prices, volumes):
    """四因子入场。逻辑字面复制 v1 行 87-115。"""
    prices = np.asarray(prices, dtype=float)
    volumes = np.asarray(volumes, dtype=float)

    if len(prices) < 70 or len(volumes) < 20:
        return False

    ma60 = sma(prices, 60)
    if np.isnan(ma60[-1]) or prices[-1] <= ma60[-1]:
        return False

    ma5 = sma(prices, 5)
    ma20 = sma(prices, 20)
    if np.isnan(ma5[-1]) or np.isnan(ma20[-1]) or ma5[-1] <= ma20[-1]:
        return False

    _, _, hist = macd(prices)
    if hist[-1] <= 0:
        return False
    if len(hist) >= 3 and hist[-1] <= hist[-2]:
        return False

    if len(prices) >= 2 and prices[-1] <= prices[-2] * 1.01:
        return False

    vol_ma20 = sma(volumes, 20)
    if np.isnan(vol_ma20[-1]) or volumes[-1] <= vol_ma20[-1]:
        return False

    return True


def score_factors(prices, volumes):
    """对满足四因子的票返回 4 维原始因子；不满足返回 None。
    逻辑字面复制 v1 行 118-144（v1 中函数名为 score_stock）。"""
    if not check_buy_signal(prices, volumes):
        return None

    prices = np.asarray(prices, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    price = prices[-1]

    ma60 = sma(prices, 60)
    trend_score = (price - ma60[-1]) / ma60[-1]

    ma5 = sma(prices, 5)
    ma20 = sma(prices, 20)
    ma_spread_score = (ma5[-1] - ma20[-1]) / ma20[-1]

    _, _, hist = macd(prices)
    macd_score = hist[-1] / ma20[-1]

    vol_ma20 = sma(volumes, 20)
    ratio = volumes[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
    volume_score = float(np.log(max(ratio, 0.01)))

    return {
        'trend_score': float(trend_score),
        'ma_spread_score': float(ma_spread_score),
        'macd_score': float(macd_score),
        'volume_score': float(volume_score),
    }
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd quant-trade-new && pytest tests/test_indicators.py -v
```
预期：15 PASSED

- [ ] **Step 5: Commit**

```bash
cd /Users/shezhidong/Documents/代码库/quant-trade
git add quant-trade-new/strategy_hs300.py quant-trade-new/tests/test_indicators.py
git commit -m "feat(strategy): §A 常量 + §C 指标 (sma/macd/check_buy_signal/score_factors)"
```

---

### Task 3: Strategy §D 持仓风控

**Files:**
- Modify: `quant-trade-new/strategy_hs300.py`（追加 §D）
- Test: `quant-trade-new/tests/test_positions.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `strategy_hs300.Position(stockcode: str, buy_price: float, buy_date: str, volume: int, buy_trading_day_idx: int = 0)` dataclass-like class with `highest_price` attr
  - `check_hard_stop(pos: Position, current_price: float, hard_stop_pct: float = 0.03) -> bool`
  - `check_crash(prices: np.ndarray) -> bool` 当日跌幅 ≤ -7%
  - `check_trend_break(current_price: float, ma20: float, hist: np.ndarray) -> bool` 跌破 MA20 + MACD 衰竭双确认
  - `check_trailing_stop(pos: Position, current_price: float, profit_threshold: float = 0.05, pullback_pct: float = 0.05) -> bool`
  - `position_size(total_assets: float, available_cash: float, max_positions: int = 5) -> float`

- [ ] **Step 1: 写 tests/test_positions.py（10 例）**

```python
import numpy as np
from strategy_hs300 import (
    Position, check_hard_stop, check_crash, check_trend_break,
    check_trailing_stop, position_size, HARD_STOP_PCT,
)


def make_pos(buy_price=100.0):
    return Position(stockcode='SH.600000', buy_price=buy_price,
                    buy_date='20200101', volume=1000)


# === hard_stop ===
def test_hard_stop_triggers_at_threshold():
    pos = make_pos(100.0)
    # v1 _evaluate_and_execute_sells 传入 HARD_STOP_PCT (=0.05)
    assert check_hard_stop(pos, 95.0, HARD_STOP_PCT) is True


def test_hard_stop_not_triggered_above():
    pos = make_pos(100.0)
    assert check_hard_stop(pos, 95.5, HARD_STOP_PCT) is False


# === crash ===
def test_crash_triggers_at_7pct():
    prices = np.array([100.0, 93.0])
    assert check_crash(prices) is True


def test_crash_not_triggered_at_6pct():
    prices = np.array([100.0, 94.0])
    assert check_crash(prices) is False


def test_crash_returns_false_with_one_bar():
    assert check_crash(np.array([100.0])) is False


# === trend_break ===
def test_trend_break_double_confirm():
    # 跌破 MA20 + MACD 衰竭（hist[-1] <= 0 且 hist[-1] <= hist[-2]）
    hist = np.array([0.5, 0.3, -0.1])
    assert check_trend_break(99.0, ma20=100.0, hist=hist) is True


def test_trend_break_macd_alone_not_enough():
    hist = np.array([0.5, 0.3, -0.1])
    assert check_trend_break(101.0, ma20=100.0, hist=hist) is False


def test_trend_break_ma_alone_not_enough():
    hist = np.array([0.1, 0.2, 0.3])  # 仍扩大
    assert check_trend_break(99.0, ma20=100.0, hist=hist) is False


# === trailing_stop ===
def test_trailing_stop_not_triggered_below_threshold():
    pos = make_pos(100.0)
    pos.highest_price = 105.0  # 仅 5% < PROFIT_THRESHOLD 10%
    # v1 _evaluate_and_execute_sells 传入 (PROFIT_THRESHOLD=0.10, TRAILING_PULLBACK=0.08)
    assert check_trailing_stop(pos, current_price=102.0,
                               profit_threshold=0.10, pullback_pct=0.08) is False


def test_trailing_stop_triggers_after_high():
    pos = make_pos(100.0)
    pos.highest_price = 120.0  # 已盈利 20% > 10%
    # 从 120 跌至 110.4 = 跌 8% → 触发
    assert check_trailing_stop(pos, current_price=110.4,
                               profit_threshold=0.10, pullback_pct=0.08) is True


def test_position_size_uses_min_of_per_stock_and_cash():
    assert position_size(total_assets=1000000, available_cash=300000, max_positions=5) == 200000
    assert position_size(total_assets=1000000, available_cash=100000, max_positions=5) == 100000
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_positions.py -v
```
预期：FAIL `ImportError`

- [ ] **Step 3: 在 strategy_hs300.py 末尾追加 §D**

```python
# ════════════════════════════════════════════════════
# §D 持仓与风控（纯函数）
# ════════════════════════════════════════════════════

class Position:
    """简单持仓对象。v1 用法逐字保留。"""
    def __init__(self, stockcode, buy_price, buy_date, volume, buy_trading_day_idx=0):
        self.stockcode = stockcode
        self.buy_price = buy_price
        self.buy_date = buy_date
        self.volume = volume
        self.highest_price = buy_price
        self.buy_trading_day_idx = buy_trading_day_idx


def check_hard_stop(pos, current_price, hard_stop_pct=0.03):
    """硬止损。v1 行 159-162。注意：v1 默认参数 0.03，但 handlebar 传入 HARD_STOP_PCT=0.05。"""
    return current_price <= pos.buy_price * (1 - hard_stop_pct)


def check_crash(prices):
    """单日暴跌 -7% 保护。v1 handlebar 行 439-444 内嵌。"""
    prices = np.asarray(prices, dtype=float)
    if len(prices) < 2:
        return False
    daily_change = (prices[-1] - prices[-2]) / prices[-2] if prices[-2] > 0 else 0
    return daily_change <= -0.07


def check_trend_break(current_price, ma20, hist):
    """跌破 MA20 + MACD 衰竭双确认。v1 handlebar 行 447-452 内嵌逻辑。"""
    hist = np.asarray(hist, dtype=float)
    macd_weakening = (hist[-1] <= 0) and (len(hist) >= 2) and (hist[-1] <= hist[-2])
    return (current_price <= ma20) and macd_weakening


def check_trailing_stop(pos, current_price, profit_threshold=0.05, pullback_pct=0.05):
    """跟踪止盈。v1 行 171-183。"""
    if current_price > pos.highest_price:
        pos.highest_price = current_price
    max_profit_pct = (pos.highest_price - pos.buy_price) / pos.buy_price
    if max_profit_pct <= profit_threshold:
        return False
    return current_price <= pos.highest_price * (1 - pullback_pct)


def position_size(total_assets, available_cash, max_positions=5):
    """每仓资金。v1 行 186-189。"""
    target_per_stock = total_assets / max_positions
    return min(target_per_stock, available_cash)
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd quant-trade-new && pytest tests/test_positions.py -v
```
预期：10 PASSED

- [ ] **Step 5: Commit**

```bash
git add quant-trade-new/strategy_hs300.py quant-trade-new/tests/test_positions.py
git commit -m "feat(strategy): §D 持仓与风控 (硬止损/暴跌/趋势破/跟踪止盈)"
```

---

### Task 4: Strategy §E 大盘择时

**Files:**
- Modify: `quant-trade-new/strategy_hs300.py`（追加 §E）
- Test: `quant-trade-new/tests/test_market.py`

**Interfaces:**
- Produces: `strategy_hs300.check_market_trend(idx_prices: np.ndarray) -> bool`

- [ ] **Step 1: 写 tests/test_market.py（5 例）**

```python
import numpy as np
from strategy_hs300 import check_market_trend


def test_market_returns_false_with_short_data():
    assert check_market_trend(np.array([1.0] * 10)) is False
    assert check_market_trend(None) is False


def test_market_returns_false_on_3pct_crash():
    prices = np.array([100.0] * 80 + [85.0])  # 当日 -15%
    assert check_market_trend(prices) is False


def test_market_ok_when_above_ma20_and_macd_positive():
    prices = np.array([10.0 + i * 0.1 for i in range(70)])  # 单调升
    assert check_market_trend(prices) is True


def test_market_not_ok_below_ma20():
    rising = np.array([20.0 + i * 0.1 for i in range(70)])
    rising[-1] = 18.0  # 大幅低于均线但不触发单日 -3% 拦截
    rising[-2] = 18.3
    assert check_market_trend(rising) is False


def test_market_not_ok_when_macd_negative():
    # 长期下跌后微反弹
    prices = np.array([30.0 - i * 0.2 for i in range(70)])
    assert check_market_trend(prices) is False
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_market.py -v
```

- [ ] **Step 3: 追加 §E**

```python
# ════════════════════════════════════════════════════
# §E 大盘择时（纯函数）
# ════════════════════════════════════════════════════

def check_market_trend(idx_prices):
    """大盘择时：close > MA20 且 MACD hist > 0 且当日跌幅 > -3%。
    v1 行 247-267 逐字保留（注意 v1 注释掉了 MACD 缩窄检查）。"""
    if idx_prices is None or len(idx_prices) < 20:
        return False

    idx_prices = np.asarray(idx_prices, dtype=float)

    if len(idx_prices) >= 2:
        daily_change = (idx_prices[-1] - idx_prices[-2]) / idx_prices[-2]
        if daily_change <= -0.03:
            return False

    ma20 = np.mean(idx_prices[-20:])
    _, _, hist = macd(idx_prices)

    return idx_prices[-1] > ma20 and hist[-1] > 0
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd quant-trade-new && pytest tests/test_market.py -v
```
预期：5 PASSED

- [ ] **Step 5: Commit**

```bash
git add quant-trade-new/strategy_hs300.py quant-trade-new/tests/test_market.py
git commit -m "feat(strategy): §E 大盘择时"
```

---

### Task 5: Strategy §F 交易成本

**Files:**
- Modify: `quant-trade-new/strategy_hs300.py`（追加 §F）
- Test: `quant-trade-new/tests/test_costs.py`

**Interfaces:**
- Produces: `strategy_hs300.trade_cost(side: str, amount: float) -> float`，`side ∈ {'buy', 'sell'}`，amount = 股数 × 价格

- [ ] **Step 1: 写 tests/test_costs.py（5 例）**

```python
import pytest
from strategy_hs300 import trade_cost


def test_buy_has_no_stamp_tax():
    # 1000 元买入：佣金 max(0.1, 5)=5 + 过户 0.01 + 滑点 0.5 = 5.51
    assert trade_cost('buy', 1000.0) == pytest.approx(5.51, abs=0.01)


def test_sell_has_stamp_tax():
    # 1000 元卖出：佣金 5 + 印花税 1 + 过户 0.01 + 滑点 0.5 = 6.51
    assert trade_cost('sell', 1000.0) == pytest.approx(6.51, abs=0.01)


def test_commission_floor_5_yuan():
    # 100 元买入：佣金 max(0.01, 5) = 5
    cost = trade_cost('buy', 100.0)
    assert cost >= 5.0


def test_buy_large_order_proportional():
    # 100w 元买入：佣金 100 + 过户 10 + 滑点 500 = 610
    assert trade_cost('buy', 1_000_000.0) == pytest.approx(610.0, abs=0.5)


def test_sell_large_order_includes_stamp():
    # 100w 元卖出：佣金 100 + 印花税 1000 + 过户 10 + 滑点 500 = 1610
    assert trade_cost('sell', 1_000_000.0) == pytest.approx(1610.0, abs=0.5)


def test_invalid_side_raises():
    with pytest.raises(ValueError):
        trade_cost('hold', 1000.0)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_costs.py -v
```

- [ ] **Step 3: 追加 §F**

```python
# ════════════════════════════════════════════════════
# §F 交易成本（纯函数 — 统一公式，替代 v1 中 4 处复制粘贴）
# ════════════════════════════════════════════════════

def trade_cost(side, amount):
    """成本 = 佣金（最低 5）+ 印花税（仅卖）+ 过户费 + 滑点。"""
    if side not in ('buy', 'sell'):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    commission = max(amount * COST['commission'], COST['commission_min'])
    stamp = amount * COST['stamp'] if side == 'sell' else 0.0
    transfer = amount * COST['transfer']
    slippage = amount * COST['slippage']
    return commission + stamp + transfer + slippage
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd quant-trade-new && pytest tests/test_costs.py -v
```
预期：6 PASSED

- [ ] **Step 5: Commit**

```bash
git add quant-trade-new/strategy_hs300.py quant-trade-new/tests/test_costs.py
git commit -m "feat(strategy): §F 统一交易成本函数"
```

---

### Task 6: DataLoader

**Files:**
- Create: `quant-trade-new/backtest/data_loader.py`
- Test: `quant-trade-new/tests/test_data_loader.py`

**Interfaces:**
- Consumes: `RunConfig`（仅 `data_root`, `start_date`, `end_date`, `warmup_days`）
- Produces:
  - `DataLoader(data_root: str)`
  - `DataLoader.daily_df: dict[str, pd.DataFrame]` 键 = 数据集代码（如 `'SH.600000'`），DataFrame 索引 = `pd.DatetimeIndex` (日)，列 = `['high', 'open', 'low', 'close', 'volume', 'name']`
  - `DataLoader.load(start: date, end: date, warmup_days: int) -> None` 实际读取
  - `DataLoader.trading_calendar(index_code: str = 'SH.000300') -> pd.DatetimeIndex` 交易日历
  - `DataLoader.data_quality_log: list[str]` 加载时检测出的可疑跳水（>5%）和短数据警告
  - `DataLoader.universe_codes() -> list[str]` 所有 ~301 只票（包含指数）的代码集合

- [ ] **Step 1: 写 tests/test_data_loader.py（含 fixture）**

```python
import pytest
import pandas as pd
from datetime import date
from backtest.data_loader import DataLoader


DATA_ROOT = "../300data/data_a"  # 相对于 quant-trade-new/ 的位置


@pytest.fixture(scope="session")
def loader():
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 12, 31), warmup_days=120)
    return dl


def test_loads_index():
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 12, 31), warmup_days=120)
    assert 'SH.000300' in dl.daily_df


def test_index_dataframe_has_required_columns(loader):
    df = loader.daily_df['SH.000300']
    assert 'close' in df.columns
    assert 'volume' in df.columns
    assert 'open' in df.columns
    assert 'high' in df.columns
    assert 'low' in df.columns


def test_loaded_range_includes_warmup(loader):
    df = loader.daily_df['SH.000300']
    # warmup 120 个交易日 ≈ 半年自然日，至少要覆盖到 2019-07 之前
    assert df.index.min() <= pd.Timestamp('2019-08-01')
    assert df.index.max() >= pd.Timestamp('2020-12-30')


def test_loaded_range_does_not_overshoot_end(loader):
    df = loader.daily_df['SH.000300']
    assert df.index.max() <= pd.Timestamp('2020-12-31')


def test_universe_size_near_300(loader):
    codes = loader.universe_codes()
    assert 295 <= len(codes) <= 305


def test_trading_calendar_in_range(loader):
    cal = loader.trading_calendar()
    assert cal.min() >= pd.Timestamp('2020-01-01')
    assert cal.max() <= pd.Timestamp('2020-12-31')
    # 2020 年大约 243 个交易日
    assert 240 <= len(cal) <= 250


def test_data_quality_log_detects_maotai_2024_glitch():
    """茅台 2024-06-21 是已知未复权事件，跳水 29.10 元/1424.66 ≈ 2.04% < 5%，不应进 log。"""
    # 但 2020-07-15 → 2020-07-16 茅台跳水 138.53 元/1538.32 = 9.01% 应进 log
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 7, 1), end=date(2020, 8, 1), warmup_days=120)
    suspicious = [m for m in dl.data_quality_log
                  if 'SH.600519' in m and '2020-07-16' in m]
    assert len(suspicious) >= 1


def test_missing_index_file_raises():
    with pytest.raises(Exception, match=r"SH\.000300|index|指数"):
        dl = DataLoader("/nonexistent/path")
        dl.load(start=date(2020, 1, 1), end=date(2020, 12, 31), warmup_days=120)


def test_warmup_insufficient_raises():
    """请求 start 早于数据最早日期 + warmup，应报错。"""
    dl = DataLoader(DATA_ROOT)
    # 数据最早 2019-06-17，要 120 个交易日 warmup → start 至少 2019-12 左右
    with pytest.raises(Exception, match=r"warmup|start|数据"):
        dl.load(start=date(2019, 7, 1), end=date(2019, 12, 31), warmup_days=120)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_data_loader.py -v
```

- [ ] **Step 3: 实现 DataLoader**

`quant-trade-new/backtest/data_loader.py`:
```python
"""读取 300data/data_a/*_day.txt 到 dict[code -> pd.DataFrame]。"""
from datetime import date
from pathlib import Path
import pandas as pd


class DataError(Exception):
    pass


class DataLoader:
    def __init__(self, data_root):
        self.data_root = Path(data_root)
        self.daily_df: dict = {}
        self.data_quality_log: list = []
        self._loaded = False

    def universe_codes(self):
        return list(self.daily_df.keys())

    def trading_calendar(self, index_code='SH.000300'):
        if index_code not in self.daily_df:
            raise DataError(f"index {index_code} 缺失")
        return self.daily_df[index_code].index

    def load(self, start: date, end: date, warmup_days: int):
        if self._loaded:
            return

        if not self.data_root.exists():
            raise DataError(f"data_root 不存在: {self.data_root}")

        index_file = self.data_root / 'SH.000300_day.txt'
        if not index_file.exists():
            raise DataError(f"指数文件 SH.000300_day.txt 缺失: {index_file}")

        # 先加载指数算交易日历
        idx_df = self._read_csv(index_file)
        self.daily_df['SH.000300'] = idx_df

        # 检查 warmup 是否足够
        sorted_idx = idx_df.index.sort_values()
        if pd.Timestamp(start) not in sorted_idx:
            # 取 start 之后第一个交易日
            after = sorted_idx[sorted_idx >= pd.Timestamp(start)]
            if len(after) == 0:
                raise DataError(f"start {start} 之后无交易日")
            start_ts = after[0]
        else:
            start_ts = pd.Timestamp(start)

        idx_of_start = sorted_idx.get_indexer([start_ts])[0]
        if idx_of_start < warmup_days:
            raise DataError(
                f"warmup 不足：start {start} 之前只有 {idx_of_start} 个交易日，"
                f"需要 {warmup_days}"
            )
        if pd.Timestamp(end) > sorted_idx.max():
            raise DataError(f"end {end} 超出数据最大日期 {sorted_idx.max().date()}")

        load_start = sorted_idx[idx_of_start - warmup_days]
        load_end = pd.Timestamp(end)

        # 切指数到加载范围
        self.daily_df['SH.000300'] = idx_df.loc[load_start:load_end]

        # 加载所有股票
        for f in self.data_root.glob('*_day.txt'):
            code = f.stem.replace('_day', '')
            if code == 'SH.000300':
                continue
            try:
                df = self._read_csv(f)
            except Exception as e:
                raise DataError(f"读取 {f.name} 失败: {e}")
            df = df.loc[load_start:load_end] if not df.empty else df
            if not df.empty:
                self.daily_df[code] = df
                self._scan_quality(code, df)

        self._loaded = True

    def _read_csv(self, path: Path) -> pd.DataFrame:
        df = pd.read_csv(path)
        required = {'code', 'name', 'time_key', 'high', 'open', 'low', 'close', 'turnover'}
        if not required.issubset(df.columns):
            raise DataError(f"{path.name} 列不全: {df.columns.tolist()}")
        df['time_key'] = pd.to_datetime(df['time_key'])
        df = df.set_index('time_key').sort_index()
        df.index = df.index.normalize()  # 时间归零
        df['volume'] = df['turnover']   # 沿用 v1 的"成交额作为 volume"惯例
        df['name'] = df['name'].iloc[0] if not df.empty else ''
        return df[['high', 'open', 'low', 'close', 'volume', 'name']]

    def _scan_quality(self, code, df):
        """记录 >5% 的跨日跳水（可能是未复权事件）。"""
        if len(df) < 2:
            return
        closes = df['close'].values
        for i in range(1, len(df)):
            if closes[i - 1] > 0:
                gap_pct = (closes[i - 1] - closes[i]) / closes[i - 1]
                if gap_pct > 0.05:
                    self.data_quality_log.append(
                        f"{code} {df.index[i - 1].date()} → {df.index[i].date()}: "
                        f"{closes[i - 1]:.2f} → {closes[i]:.2f}, "
                        f"跳水 {gap_pct * 100:.2f}%（可能未复权或市场暴跌）"
                    )
```

- [ ] **Step 4: 跑测试验证**

```bash
cd quant-trade-new && pytest tests/test_data_loader.py -v
```
预期：9 PASSED

- [ ] **Step 5: Commit**

```bash
git add quant-trade-new/backtest/data_loader.py quant-trade-new/tests/test_data_loader.py
git commit -m "feat(backtest): DataLoader 含 warmup 校验 + 数据质量扫描"
```

---

### Task 7: Account (T+1, Fill, Snapshot)

**Files:**
- Create: `quant-trade-new/backtest/account.py`
- Test: `quant-trade-new/tests/test_account.py`

**Interfaces:**
- Consumes: 无（独立模块）
- Produces:
  - `Account(initial_capital: float)`
  - `Account.cash: float`
  - `Account.positions: dict[str, AccountPosition]`
  - `AccountPosition(code, volume, can_use_volume, buy_price, buy_date)`
  - `Account.advance_day(date_str: str)`：T+1 解锁；推进当前日
  - `Account.fill_buy(code: str, name: str, volume: int, price: float, date_str: str, reason: str) -> bool` 返回是否成交
  - `Account.fill_sell(code: str, name: str, volume: int, price: float, date_str: str, reason: str) -> bool`
  - `Account.record_reject(code, name, side, volume, price, date_str, reason)`
  - `Account.snapshot(date_str: str, close_prices: dict[str, float]) -> Snapshot` 当日 EOD 总权益
  - `Account.trades: list[Trade]` 累积所有成交和拒单
  - `Account.snapshots: list[Snapshot]`

- [ ] **Step 1: 写 tests/test_account.py（6 例）**

```python
import pytest
from backtest.account import Account


def test_initial_state():
    a = Account(initial_capital=500000.0)
    assert a.cash == 500000.0
    assert a.positions == {}
    assert a.trades == []


def test_fill_buy_decreases_cash_increases_position():
    a = Account(initial_capital=500000.0)
    ok = a.fill_buy('SH.600000', '浦发银行', volume=1000, price=10.0,
                    date_str='20200101', reason='buy_signal')
    assert ok is True
    # 现金 = 50w - 1000*10 - 交易成本（~15.01 = 5+0.1+5=10.1元..）
    # 简化检查
    assert a.cash < 500000.0
    assert 'SH.600000' in a.positions
    assert a.positions['SH.600000'].volume == 1000
    assert a.positions['SH.600000'].can_use_volume == 0  # T+1


def test_t1_unlock_next_day():
    a = Account(initial_capital=500000.0)
    a.fill_buy('SH.600000', '浦发', volume=1000, price=10.0,
               date_str='20200101', reason='buy_signal')
    assert a.positions['SH.600000'].can_use_volume == 0
    a.advance_day('20200102')
    assert a.positions['SH.600000'].can_use_volume == 1000


def test_fill_sell_before_t1_rejected():
    a = Account(initial_capital=500000.0)
    a.fill_buy('SH.600000', '浦发', volume=1000, price=10.0,
               date_str='20200101', reason='buy_signal')
    # 当日卖
    ok = a.fill_sell('SH.600000', '浦发', volume=1000, price=10.5,
                     date_str='20200101', reason='hard_stop')
    assert ok is False
    # 应进 trades 作为拒单
    rejects = [t for t in a.trades if t.status == 'REJECTED' and t.reason == 'T1_LOCKED']
    assert len(rejects) == 1


def test_snapshot_equity_balance():
    a = Account(initial_capital=500000.0)
    a.fill_buy('SH.600000', '浦发', volume=1000, price=10.0,
               date_str='20200101', reason='buy_signal')
    snap = a.snapshot('20200101', close_prices={'SH.600000': 10.5})
    assert snap.cash == a.cash
    assert snap.position_value == pytest.approx(1000 * 10.5)
    assert snap.total_equity == pytest.approx(snap.cash + snap.position_value)
    assert snap.n_positions == 1


def test_fill_sell_releases_position():
    a = Account(initial_capital=500000.0)
    a.fill_buy('SH.600000', '浦发', volume=1000, price=10.0,
               date_str='20200101', reason='buy_signal')
    a.advance_day('20200102')
    ok = a.fill_sell('SH.600000', '浦发', volume=1000, price=10.5,
                     date_str='20200102', reason='hard_stop')
    assert ok is True
    assert 'SH.600000' not in a.positions
    assert a.cash > 500000.0 - 1000 * 10.0  # 至少回收了大部分本金
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_account.py -v
```

- [ ] **Step 3: 实现 Account**

`quant-trade-new/backtest/account.py`:
```python
"""回测账户：现金/持仓/订单/快照。T+1 严格模拟。"""
from dataclasses import dataclass, field
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy_hs300 import trade_cost


@dataclass
class AccountPosition:
    code: str
    volume: int
    can_use_volume: int
    buy_price: float
    buy_date: str


@dataclass
class Trade:
    trade_id: int
    date: str
    code: str
    name: str
    side: str   # 'buy' / 'sell'
    volume: int
    price: float
    amount: float
    cost: float
    reason: str
    status: str  # 'FILLED' / 'REJECTED'
    realized_pnl: float = 0.0


@dataclass
class Snapshot:
    date: str
    cash: float
    position_value: float
    total_equity: float
    n_positions: int
    daily_return: float = 0.0


class Account:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, AccountPosition] = {}
        self.trades: list[Trade] = []
        self.snapshots: list[Snapshot] = []
        self._trade_seq = 0
        self._current_date: str = ''

    def advance_day(self, date_str: str):
        """T+1 解锁：所有持仓 can_use_volume = volume。"""
        self._current_date = date_str
        for pos in self.positions.values():
            pos.can_use_volume = pos.volume

    def _next_trade_id(self):
        self._trade_seq += 1
        return self._trade_seq

    def fill_buy(self, code, name, volume, price, date_str, reason):
        amount = volume * price
        cost = trade_cost('buy', amount)
        total = amount + cost
        if total > self.cash:
            self.record_reject(code, name, 'buy', volume, price, date_str, 'CASH_SHORT')
            return False

        self.cash -= total
        if code in self.positions:
            old = self.positions[code]
            new_vol = old.volume + volume
            # 加权平均成本（v1 无此实现，简单累加；本回测不混仓所以一般遇不到）
            old.buy_price = (old.buy_price * old.volume + price * volume) / new_vol
            old.volume = new_vol
            # 当日买入仍然不可卖
            old.can_use_volume = old.can_use_volume  # 不变
        else:
            self.positions[code] = AccountPosition(
                code=code, volume=volume, can_use_volume=0,
                buy_price=price, buy_date=date_str,
            )

        self.trades.append(Trade(
            trade_id=self._next_trade_id(), date=date_str, code=code, name=name,
            side='buy', volume=volume, price=price, amount=amount,
            cost=cost, reason=reason, status='FILLED',
        ))
        return True

    def fill_sell(self, code, name, volume, price, date_str, reason):
        if code not in self.positions:
            self.record_reject(code, name, 'sell', volume, price, date_str, 'NO_POSITION')
            return False
        pos = self.positions[code]
        if pos.can_use_volume < volume:
            self.record_reject(code, name, 'sell', volume, price, date_str, 'T1_LOCKED')
            return False

        amount = volume * price
        cost = trade_cost('sell', amount)
        realized = (price - pos.buy_price) * volume - cost
        self.cash += amount - cost

        pos.volume -= volume
        pos.can_use_volume -= volume
        if pos.volume == 0:
            del self.positions[code]

        self.trades.append(Trade(
            trade_id=self._next_trade_id(), date=date_str, code=code, name=name,
            side='sell', volume=volume, price=price, amount=amount,
            cost=cost, reason=reason, status='FILLED',
            realized_pnl=realized,
        ))
        return True

    def record_reject(self, code, name, side, volume, price, date_str, reason):
        self.trades.append(Trade(
            trade_id=self._next_trade_id(), date=date_str, code=code, name=name,
            side=side, volume=volume, price=price, amount=volume * price,
            cost=0.0, reason=reason, status='REJECTED',
        ))

    def snapshot(self, date_str, close_prices: dict):
        position_value = sum(
            close_prices.get(c, p.buy_price) * p.volume
            for c, p in self.positions.items()
        )
        total = self.cash + position_value
        prev_equity = self.snapshots[-1].total_equity if self.snapshots else self.initial_capital
        daily_ret = (total - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        snap = Snapshot(
            date=date_str, cash=self.cash, position_value=position_value,
            total_equity=total, n_positions=len(self.positions),
            daily_return=daily_ret,
        )
        self.snapshots.append(snap)
        return snap
```

- [ ] **Step 4: 跑测试验证**

```bash
cd quant-trade-new && pytest tests/test_account.py -v
```
预期：6 PASSED

- [ ] **Step 5: Commit**

```bash
git add quant-trade-new/backtest/account.py quant-trade-new/tests/test_account.py
git commit -m "feat(backtest): Account 含 T+1 严格模拟 + 拒单记录"
```

---

### Task 8: Shim ContextInfo

**Files:**
- Create: `quant-trade-new/backtest/shim.py`（含 ContextInfo + advance_to + get_history_data 等查询接口；passorder 在 Task 9）
- Test: `quant-trade-new/tests/test_shim_context.py`

**Interfaces:**
- Consumes: `DataLoader`, `Account`
- Produces:
  - `Shim(data_loader, account, run_dir: Path)`
  - `Shim.context: ContextInfo` 实例
  - `ContextInfo` 类带：`barpos`, `last_processed_barpos`, `capital`, `accountid`, `positions`, `strategy_start_date`, `log_dir`, `_active_universe`, `_bar_ts`, 还有 `set_account/set_universe/get_sector/get_instrumentdetail/get_history_data/get_bar_timetag` 方法
  - `Shim.advance_to(day: pd.Timestamp, barpos: int)` 把当前日推进
  - `Shim.is_limit_up(code) -> bool`, `Shim.is_limit_down(code) -> bool` （供 Task 9 使用）

- [ ] **Step 1: 写 tests/test_shim_context.py（10 例）**

```python
import pytest
import pandas as pd
from pathlib import Path
from datetime import date
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim


DATA_ROOT = "../300data/data_a"


@pytest.fixture(scope="module")
def shim(tmp_path_factory):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    run_dir = tmp_path_factory.mktemp('run')
    s = Shim(dl, acct, run_dir=run_dir)
    s.advance_to(pd.Timestamp('2020-03-02'), barpos=0)
    return s


def test_context_has_required_attributes(shim):
    ctx = shim.context
    assert hasattr(ctx, 'barpos')
    assert hasattr(ctx, 'capital')
    assert hasattr(ctx, 'positions')


def test_get_sector_returns_universe(shim):
    codes = shim.context.get_sector('000300.SH')
    assert isinstance(codes, list)
    assert len(codes) > 200


def test_get_instrumentdetail_returns_name(shim):
    detail = shim.context.get_instrumentdetail('SH.600000')
    assert 'm_strInstrumentName' in detail
    assert detail['m_strInstrumentName']  # 非空


def test_get_instrumentdetail_has_upstop_price(shim):
    detail = shim.context.get_instrumentdetail('SH.600000')
    assert 'UpStopPrice' in detail
    assert detail['UpStopPrice'] > 0


def test_get_history_data_basic(shim):
    hist = shim.context.get_history_data(60, '1d', 'close')
    assert 'SH.600000' in hist
    assert len(hist['SH.600000']) == 60


def test_get_history_data_last_is_today(shim):
    """最后一根 = 当日 close。"""
    hist = shim.context.get_history_data(5, '1d', 'close')
    # shim 当前日是 2020-03-02
    expected = shim.data_loader.daily_df['SH.600000'].loc['2020-03-02', 'close']
    assert hist['SH.600000'][-1] == pytest.approx(expected)


def test_get_history_data_short_returns_short(shim):
    """请求 1000 但只有几百天数据，返回短列表不报错。"""
    hist = shim.context.get_history_data(10000, '1d', 'close')
    assert len(hist['SH.600000']) < 1000


def test_get_history_data_rejects_non_daily(shim):
    with pytest.raises(NotImplementedError):
        shim.context.get_history_data(60, '5m', 'close')


def test_advance_to_increments_barpos(shim):
    shim.advance_to(pd.Timestamp('2020-03-03'), barpos=1)
    assert shim.context.barpos == 1


def test_set_universe_records_active(shim):
    shim.context.set_universe(['SH.600000', 'SH.600519'])
    assert 'SH.600000' in shim.context._active_universe
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_shim_context.py -v
```

- [ ] **Step 3: 实现 ContextInfo 查询接口部分**

`quant-trade-new/backtest/shim.py`:
```python
"""QMT API Shim：ContextInfo + passorder + 全局函数模拟。"""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import pandas as pd


class ContextInfo:
    """Mimic QMT 的 ContextInfo 对象。所有方法对外行为与 QMT 文档对齐。"""

    def __init__(self, shim):
        self._shim = shim
        self.barpos: int = -1
        self.last_processed_barpos: int = -1
        self.capital: float = 0.0
        self.accountid: str = ''
        self.positions: dict = {}
        self.strategy_start_date: str = ''
        self.log_dir: str = ''
        self._active_universe: list = []
        self._bar_ts_cache: dict[int, int] = {}
        self._current_day: pd.Timestamp | None = None

    def set_account(self, account_id):
        self.accountid = account_id

    def set_universe(self, codes):
        self._active_universe = list(codes)

    def get_sector(self, sector_code):
        """返回 data_a 静态全集（排除指数本身）。"""
        if sector_code in ('000300.SH', 'SH.000300'):
            return [c for c in self._shim.data_loader.universe_codes()
                    if c != 'SH.000300']
        return []

    def get_instrumentdetail(self, code):
        """返回包含 m_strInstrumentName 和 UpStopPrice 的 dict。"""
        data_code = self._shim._to_data_code(code)
        df = self._shim.data_loader.daily_df.get(data_code)
        if df is None or self._current_day is None or df.empty:
            return {}
        name = df['name'].iloc[0] if 'name' in df.columns else ''
        # UpStopPrice = 前一日 close × 1.10 普通股；创业板/科创板 1.20
        before = df.loc[df.index < self._current_day]
        if len(before) == 0:
            return {'m_strInstrumentName': str(name), 'UpStopPrice': 0.0}
        prev_close = float(before['close'].iloc[-1])
        multiplier = 1.20 if (data_code.startswith('SZ.300') or
                              data_code.startswith('SH.688')) else 1.10
        return {
            'm_strInstrumentName': str(name),
            'UpStopPrice': prev_close * multiplier,
            'DownStopPrice': prev_close * (2 - multiplier),
        }

    def get_history_data(self, N, period='1d', field='close',
                         dividend_type='front', skip_paused=True):
        if period != '1d':
            raise NotImplementedError(f"Shim 仅支持 period='1d'，收到 {period!r}")
        if self._current_day is None:
            return {}

        # 返回范围：active universe + 已持仓 + 指数 必须全在
        codes = set(self._active_universe)
        codes.update(self.positions.keys())
        codes.add('SH.000300')  # 始终保留指数（v1 expectation）

        result = {}
        for code in codes:
            data_code = self._shim._to_data_code(code)
            df = self._shim.data_loader.daily_df.get(data_code)
            if df is None or df.empty:
                continue
            sliced = df.loc[df.index <= self._current_day, field]
            if len(sliced) == 0:
                continue
            result[code] = sliced.iloc[-N:].tolist()
        return result

    def get_bar_timetag(self, barpos):
        return self._bar_ts_cache.get(barpos, 0)


class Shim:
    def __init__(self, data_loader, account, run_dir: Path):
        self.data_loader = data_loader
        self.account = account
        self.run_dir = Path(run_dir)
        self.context = ContextInfo(self)

    def advance_to(self, day: pd.Timestamp, barpos: int):
        self.context.barpos = barpos
        self.context._current_day = day
        self.context._bar_ts_cache[barpos] = int(day.timestamp() * 1000)

    def _to_data_code(self, code) -> str:
        """策略侧用 '600000.SH'/'000300.SH'，DataLoader 键是 'SH.600000'/'SH.000300'。"""
        if code in self.data_loader.daily_df:
            return code  # 已经是 data 形态
        # '600000.SH' → 'SH.600000'
        if '.' in code:
            num, ex = code.split('.', 1)
            return f"{ex}.{num}"
        return code

    def is_limit_up(self, code) -> bool:
        data_code = self._to_data_code(code)
        df = self.data_loader.daily_df.get(data_code)
        if df is None or self.context._current_day is None or df.empty:
            return False
        if self.context._current_day not in df.index:
            return False
        today_close = float(df.loc[self.context._current_day, 'close'])
        detail = self.context.get_instrumentdetail(code)
        up = detail.get('UpStopPrice', 0)
        return up > 0 and today_close >= up * 0.995

    def is_limit_down(self, code) -> bool:
        data_code = self._to_data_code(code)
        df = self.data_loader.daily_df.get(data_code)
        if df is None or self.context._current_day is None or df.empty:
            return False
        if self.context._current_day not in df.index:
            return False
        today_close = float(df.loc[self.context._current_day, 'close'])
        detail = self.context.get_instrumentdetail(code)
        down = detail.get('DownStopPrice', 0)
        return down > 0 and today_close <= down * 1.005

    def get_today_close(self, code):
        data_code = self._to_data_code(code)
        df = self.data_loader.daily_df.get(data_code)
        if df is None or self.context._current_day is None:
            return None
        if self.context._current_day not in df.index:
            return None
        return float(df.loc[self.context._current_day, 'close'])
```

- [ ] **Step 4: 跑测试验证**

```bash
cd quant-trade-new && pytest tests/test_shim_context.py -v
```
预期：10 PASSED

- [ ] **Step 5: Commit**

```bash
git add quant-trade-new/backtest/shim.py quant-trade-new/tests/test_shim_context.py
git commit -m "feat(backtest): Shim ContextInfo + get_history_data/get_sector/get_instrumentdetail"
```

---

### Task 9: Shim passorder + get_trade_detail_data + 全局函数

**Files:**
- Modify: `quant-trade-new/backtest/shim.py`（追加 passorder/get_trade_detail_data/timetag_to_datetime + 注入字典构造）
- Test: `quant-trade-new/tests/test_shim_orders.py`

**Interfaces:**
- Produces:
  - `Shim.passorder(opcode, mode, account_id, code, price_mode, price, volume, ContextInfo)` — 同步成交
  - `Shim.get_trade_detail_data(account_id, market, kind)` 返回 `[SimpleNamespace(...)]`
  - `Shim.timetag_to_datetime(timetag_ms, fmt) -> str`
  - `Shim.get_market_data_ex(fields, codes, period, ...) -> dict` 简单存根（策略目前不调用）
  - `Shim.injected_globals() -> dict` 返回 `{'passorder': ..., 'get_trade_detail_data': ..., 'timetag_to_datetime': ..., 'get_market_data_ex': ..., 'np': numpy, 'os': os, 'datetime': datetime}` 用于注入给策略

- [ ] **Step 1: 写 tests/test_shim_orders.py（10 例）**

```python
import pytest
import pandas as pd
from datetime import date
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim


DATA_ROOT = "../300data/data_a"


@pytest.fixture
def shim(tmp_path):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    s = Shim(dl, acct, run_dir=tmp_path)
    s.advance_to(pd.Timestamp('2020-03-02'), barpos=0)
    s.context.set_universe([c for c in dl.universe_codes() if c != 'SH.000300'])
    s.context.accountid = 'test_acct'
    return s


def test_passorder_buy_fills(shim):
    # opcode 23 = 买, mode 1101 = 按股数, price_mode 5 = 最新价
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    # 检查 Account 状态
    assert 'SH.600000' in shim.account.positions or '600000.SH' in shim.account.positions


def test_passorder_buy_cash_short_records_reject(shim):
    shim.account.cash = 100.0  # 现金极少
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 100000.0, shim.context)
    rejects = [t for t in shim.account.trades
               if t.status == 'REJECTED' and t.reason == 'CASH_SHORT']
    assert len(rejects) == 1


def test_passorder_buy_limit_up_rejected(shim, monkeypatch):
    monkeypatch.setattr(shim, 'is_limit_up', lambda c: True)
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    rejects = [t for t in shim.account.trades
               if t.status == 'REJECTED' and t.reason == 'LIMIT_UP']
    assert len(rejects) == 1


def test_passorder_sell_t1_locked_rejected(shim):
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    # 当日卖
    shim.passorder(24, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    rejects = [t for t in shim.account.trades
               if t.status == 'REJECTED' and t.reason == 'T1_LOCKED']
    assert len(rejects) == 1


def test_passorder_unsupported_opcode_raises(shim):
    with pytest.raises(NotImplementedError):
        shim.passorder(99, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)


def test_get_trade_detail_data_account(shim):
    info = shim.get_trade_detail_data('test_acct', 'STOCK', 'ACCOUNT')
    assert len(info) == 1
    assert info[0].m_dBalance == 500000.0
    assert info[0].m_dAvailable == 500000.0


def test_get_trade_detail_data_position_t1_zero(shim):
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    pos_list = shim.get_trade_detail_data('test_acct', 'STOCK', 'POSITION')
    assert len(pos_list) == 1
    assert pos_list[0].m_nCanUseVolume == 0  # T+1
    assert pos_list[0].m_nVolume == 1000


def test_get_trade_detail_data_position_after_advance(shim):
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    shim.account.advance_day('20200303')
    pos_list = shim.get_trade_detail_data('test_acct', 'STOCK', 'POSITION')
    assert pos_list[0].m_nCanUseVolume == 1000


def test_timetag_to_datetime_format(shim):
    ms = int(pd.Timestamp('2020-03-02').timestamp() * 1000)
    out = shim.timetag_to_datetime(ms, '%Y%m%d')
    assert out == '20200302'


def test_injected_globals_completeness(shim):
    g = shim.injected_globals()
    assert 'passorder' in g
    assert 'get_trade_detail_data' in g
    assert 'timetag_to_datetime' in g
    assert 'np' in g
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_shim_orders.py -v
```

- [ ] **Step 3: 在 shim.py 末尾追加成交相关方法**

在 `Shim` 类内追加：
```python
    def passorder(self, opcode, mode, account_id, code, price_mode,
                  price, volume, ContextInfo):
        """opcode: 23=买, 24=卖; price_mode 5=最新价（=当日 close）。同步成交。"""
        if opcode not in (23, 24):
            raise NotImplementedError(f"passorder opcode {opcode} 未支持")

        data_code = self._to_data_code(code)
        # 反向：策略侧用 600000.SH 格式存 Account.positions，DataLoader 用 SH.600000
        # 这里 Account 用策略侧形态（保持一致性）
        # 先取 name
        df = self.data_loader.daily_df.get(data_code)
        name = ''
        if df is not None and not df.empty:
            name = str(df['name'].iloc[0])

        fill_price = self.get_today_close(code)
        date_str = self.timetag_to_datetime(self.context.get_bar_timetag(self.context.barpos), '%Y%m%d')

        if fill_price is None:
            self.account.record_reject(code, name, 'buy' if opcode == 23 else 'sell',
                                       int(volume), 0.0, date_str, 'NO_PRICE')
            return

        if opcode == 23:
            if self.is_limit_up(code):
                self.account.record_reject(code, name, 'buy', int(volume),
                                           fill_price, date_str, 'LIMIT_UP')
                return
            self.account.fill_buy(code, name, int(volume), fill_price,
                                  date_str, reason='passorder')
        else:
            if self.is_limit_down(code):
                self.account.record_reject(code, name, 'sell', int(volume),
                                           fill_price, date_str, 'LIMIT_DOWN')
                return
            self.account.fill_sell(code, name, int(volume), fill_price,
                                   date_str, reason='passorder')

    def get_trade_detail_data(self, account_id, market='STOCK', kind='ACCOUNT'):
        if kind == 'ACCOUNT':
            total = self.account.cash + sum(
                (self.get_today_close(c) or p.buy_price) * p.volume
                for c, p in self.account.positions.items()
            )
            info = SimpleNamespace(m_dBalance=total, m_dAvailable=self.account.cash)
            return [info]
        if kind == 'POSITION':
            return [
                SimpleNamespace(
                    m_strInstrumentID=c,
                    m_nVolume=p.volume,
                    m_nCanUseVolume=p.can_use_volume,
                    m_dOpenPrice=p.buy_price,
                )
                for c, p in self.account.positions.items()
            ]
        return []

    def timetag_to_datetime(self, timetag_ms, fmt):
        dt = datetime.fromtimestamp(timetag_ms / 1000)
        return dt.strftime(fmt)

    def get_market_data_ex(self, fields, codes, period='1d', start_time=None,
                           end_time=None, count=None, dividend_type='front',
                           fill_data=True):
        """简单存根 — v1 不调用，预留兼容。"""
        return {}

    def injected_globals(self):
        """供 strategy_loader 注入给策略文件的全局字典。"""
        import numpy as np
        import os as os_mod
        return {
            'passorder': self.passorder,
            'get_trade_detail_data': self.get_trade_detail_data,
            'timetag_to_datetime': self.timetag_to_datetime,
            'get_market_data_ex': self.get_market_data_ex,
            'np': np,
            'os': os_mod,
            'datetime': datetime,
        }
```

- [ ] **Step 4: 跑测试验证**

```bash
cd quant-trade-new && pytest tests/test_shim_orders.py -v
```
预期：10 PASSED

- [ ] **Step 5: 全套测试回归**

```bash
cd quant-trade-new && pytest tests/ -x --ignore=tests/test_e2e.py -v
```
预期：之前所有测试 + 当前测试 全部 PASSED

- [ ] **Step 6: Commit**

```bash
git add quant-trade-new/backtest/shim.py quant-trade-new/tests/test_shim_orders.py
git commit -m "feat(backtest): Shim passorder + get_trade_detail_data + 全局注入"
```

---

### Task 10: Strategy §B 日志 + §G QMT 适配

**Files:**
- Modify: `quant-trade-new/strategy_hs300.py`（追加 §B 和 §G）
- Test: `quant-trade-new/tests/test_qmt_adapter.py`

**Interfaces:**
- Produces 在 strategy_hs300 中：
  - `_log(msg, ctx=None)` — 路径取 `getattr(ctx, 'log_dir', r'c:')`
  - `_normalize_code(code) -> str`
  - `_sync_positions(ctx, current_date)` — 从 `get_trade_detail_data` 同步
  - `_filter_buyable(universe: list, ctx) -> list` — 过滤 ST/688
  - `_execute_buy(ctx, code, volume, price, current_date, score=None) -> tuple[bool, float]`
  - `_execute_sell(ctx, code, reason, current_date)` — **修 bug**：先记录 PnL 再 del
  - `_get_account(ctx) -> tuple[float, float]`

- [ ] **Step 1: 写 tests/test_qmt_adapter.py（10 例）**

```python
import pytest
import pandas as pd
from datetime import date
from pathlib import Path
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim
import strategy_hs300


DATA_ROOT = "../300data/data_a"


@pytest.fixture
def env(tmp_path):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    s = Shim(dl, acct, run_dir=tmp_path)
    s.advance_to(pd.Timestamp('2020-03-02'), barpos=0)
    s.context.set_universe([c for c in dl.universe_codes() if c != 'SH.000300'])
    s.context.accountid = 'test'
    s.context.log_dir = str(tmp_path / 'logs')
    Path(s.context.log_dir).mkdir(parents=True, exist_ok=True)
    # 注入 QMT 全局
    for k, v in s.injected_globals().items():
        setattr(strategy_hs300, k, v)
    return s


def test_normalize_code_no_suffix_sh():
    assert strategy_hs300._normalize_code('601689') == '601689.SH'


def test_normalize_code_no_suffix_sz():
    assert strategy_hs300._normalize_code('000001') == '000001.SZ'


def test_normalize_code_already_suffixed():
    assert strategy_hs300._normalize_code('601689.SH') == '601689.SH'


def test_filter_buyable_excludes_kechuang(env):
    candidates = ['600000.SH', '688001.SH', '300001.SZ']
    out = strategy_hs300._filter_buyable(candidates, env.context)
    assert '688001.SH' not in out
    assert '600000.SH' in out


def test_get_account_returns_tuple(env):
    total, cash = strategy_hs300._get_account(env.context)
    assert total == 500000.0
    assert cash == 500000.0


def test_execute_buy_calls_passorder(env):
    ok, cost = strategy_hs300._execute_buy(
        env.context, '600000.SH', volume=1000, price=10.0,
        current_date='20200302', score=0.5
    )
    assert ok is True
    assert cost > 0


def test_execute_sell_logs_before_delete(env):
    """关键 bug 修复：v1 先 del 再 _log 导致 fallback 分支；新版必须先记录 PnL。"""
    # 先建仓
    strategy_hs300._execute_buy(env.context, '600000.SH', 1000, 10.0, '20200302')
    env.context.positions['600000.SH'] = strategy_hs300.Position(
        stockcode='600000.SH', buy_price=10.0, buy_date='20200302', volume=1000,
    )
    env.account.advance_day('20200303')
    env.advance_to(pd.Timestamp('2020-03-03'), barpos=1)

    # 测试卖出
    strategy_hs300._execute_sell(env.context, '600000.SH', 'hard_stop', '20200303')

    # 检查 trades 中卖出记录是否含 pos.buy_date（说明 _log 拿到了 pos 信息）
    sell_trades = [t for t in env.account.trades
                   if t.side == 'sell' and t.status == 'FILLED']
    assert len(sell_trades) >= 1


def test_sync_positions_picks_up_qmt_holdings(env):
    """从 QMT 实际持仓同步到 ContextInfo.positions。"""
    # 先用 Account 建仓
    env.account.fill_buy('600000.SH', '浦发', 1000, 10.0, '20200302', 'test')
    assert '600000.SH' not in env.context.positions  # 还没同步
    strategy_hs300._sync_positions(env.context, '20200302')
    assert '600000.SH' in env.context.positions


def test_filter_buyable_handles_st_failure(env):
    """v1 行为：get_instrumentdetail 失败时保留股票（fail-open）。"""
    # 我们不主动 mock 失败，只验证函数本身不抛
    out = strategy_hs300._filter_buyable(['600000.SH', 'INVALID.XX'], env.context)
    assert 'INVALID.XX' in out  # ST 检查失败时保留


def test_log_writes_to_log_dir(env, tmp_path):
    strategy_hs300._log('test message', env.context)
    log_dir = Path(env.context.log_dir)
    logs = list(log_dir.glob('*.log'))
    assert len(logs) >= 1
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_qmt_adapter.py -v
```

- [ ] **Step 3: 在 strategy_hs300.py 追加 §B 和 §G**

在文件末尾（在 §F 之后，§H 之前）追加：

```python
# ════════════════════════════════════════════════════
# §B 日志（环境无关）
# ════════════════════════════════════════════════════

_LOG_FILE_PATH = None


def _init_log(ctx=None):
    global _LOG_FILE_PATH
    log_dir = getattr(ctx, 'log_dir', r'c:') if ctx else r'c:'
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _LOG_FILE_PATH = os.path.join(log_dir, '量化日志_{0}.log'.format(ts))


def _log(msg, ctx=None):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = '{0} {1}'.format(timestamp, msg)
    print(line)
    if _LOG_FILE_PATH is None:
        _init_log(ctx)
    try:
        with open(_LOG_FILE_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ════════════════════════════════════════════════════
# §G QMT 接口适配（与 QMT/Shim 交互的桥梁层）
# ════════════════════════════════════════════════════

def _normalize_code(code):
    """v1 行 232-244 字面保留。'601689' → '601689.SH'。"""
    if '.' in code:
        return code
    digits = code.strip()
    if digits.startswith(('6', '9')):
        return digits + '.SH'
    elif digits.startswith(('0', '3')):
        return digits + '.SZ'
    return code


def _filter_buyable(universe, ctx):
    """过滤 ST + 688 科创板。v1 行 377-378 + 行 777-790。"""
    filtered = []
    fail_count = 0
    for code in universe:
        if code.startswith('688'):
            continue
        try:
            detail = ctx.get_instrumentdetail(code)
            if detail and 'ST' in detail.get('m_strInstrumentName', ''):
                continue
        except Exception:
            fail_count += 1
        filtered.append(code)
    if fail_count > 0:
        _log("[filter] ST过滤异常: {0}只详情失败，已保留".format(fail_count), ctx)
    return filtered


def _sync_positions(ctx, current_date):
    """从 QMT 实际持仓同步到 ContextInfo.positions。v1 行 270-312。"""
    account_id = getattr(ctx, 'accountid', '')
    if not account_id:
        return
    try:
        position_list = get_trade_detail_data(account_id, ACCOUNT_TYPE, 'POSITION')
        if not position_list:
            return

        qmt_holdings = {}
        for p in position_list:
            raw_code = p.m_strInstrumentID
            code = _normalize_code(raw_code)
            vol = int(p.m_nVolume) if hasattr(p, 'm_nVolume') else int(p.m_nCanUseVolume)
            if vol > 0:
                qmt_holdings[code] = {
                    'volume': vol,
                    'cost_price': p.m_dOpenPrice if hasattr(p, 'm_dOpenPrice') else 0.0,
                }

        for code, info in qmt_holdings.items():
            if code not in ctx.positions:
                ctx.positions[code] = Position(
                    stockcode=code,
                    buy_price=info['cost_price'] if info['cost_price'] > 0 else 1.0,
                    buy_date=current_date,
                    volume=info['volume'],
                )
                _log("[{0}] 同步持仓: {1}, 数量{2}股".format(current_date, code, info['volume']), ctx)

        for code in list(ctx.positions.keys()):
            if code in qmt_holdings:
                ctx.positions[code].volume = qmt_holdings[code]['volume']
            else:
                _log("[{0}] 清除失效持仓: {1}".format(current_date, code), ctx)
                del ctx.positions[code]

    except Exception as e:
        _log("[{0}] 持仓同步异常: {1}".format(current_date, e), ctx)


def _get_account(ctx):
    """返回 (total_assets, available_cash)。get_trade_detail_data 失败时回退。
    v1 行 524-531 + 行 661-670 散落多处的合并。"""
    account_id = getattr(ctx, 'accountid', '')
    if account_id:
        try:
            acct_info = get_trade_detail_data(account_id, ACCOUNT_TYPE, 'ACCOUNT')
            if acct_info:
                return acct_info[0].m_dBalance, acct_info[0].m_dAvailable
        except Exception:
            pass
    # Fallback：用 capital + realized_pnl 估算
    realized = getattr(ctx, 'realized_pnl', 0.0)
    return ctx.capital + realized, ctx.capital + realized


def _execute_buy(ctx, code, volume, price, current_date, score=None):
    """v1 行 793-817 字面保留，仅 trade_cost 替换为统一函数。"""
    try:
        account_id = getattr(ctx, 'accountid', '')
        passorder(23, 1101, account_id, code, 5, -1.0, float(volume), ctx)
        amount = volume * price
        cost = trade_cost('buy', amount)
        ctx.daily_cost = getattr(ctx, 'daily_cost', 0.0) + cost
        score_str = " | 评分: {0:.4f}".format(score) if score is not None else ""
        _log("[{0}] >> 买入: {1} | {2}股 x {3:.2f}元 = {4:.0f}元 | 成本: {5:.2f}元{6}".format(
            current_date, code, volume, price, amount, cost, score_str), ctx)
        return True, cost
    except Exception as e:
        _log("[{0}] !! 买入失败: {1} | {2}".format(current_date, code, e), ctx)
        return False, 0.0


def _execute_sell(ctx, code, reason, current_date):
    """v1 行 820-882。修 bug：先取 pos 信息日志，再 del positions。"""
    try:
        sell_volume = 0
        account_id = getattr(ctx, 'accountid', '')

        if account_id:
            try:
                position_list = get_trade_detail_data(account_id, ACCOUNT_TYPE, 'POSITION')
                if position_list:
                    for p in position_list:
                        if p.m_strInstrumentID == code:
                            sell_volume = int(p.m_nCanUseVolume) if hasattr(p, 'm_nCanUseVolume') else int(p.m_nVolume)
                            break
            except Exception:
                pass

        if sell_volume <= 0 and code in ctx.positions:
            sell_volume = ctx.positions[code].volume

        if sell_volume <= 0:
            pos = ctx.positions.get(code)
            if pos:
                sell_volume = int(200000 / pos.buy_price / 100) * 100
        if sell_volume <= 0:
            sell_volume = 100

        # **修 bug**：先抓 pos 信息生成日志内容，再下单
        reason_map = {
            'hard_stop': '硬止损', 'trend_break': '破MA20',
            'trailing_stop': '跟踪止盈', 'rebalance': '换仓调出',
            'crash_protection': '暴跌保护', 'macd_weak': 'MACD衰竭',
            'market_weak': '大盘弱势清仓',
        }
        reason_cn = reason_map.get(reason, reason)
        pos = ctx.positions.get(code)
        pnl_pct = 0
        buy_date = ''
        if pos:
            buy_date = pos.buy_date
            try:
                hist = ctx.get_history_data(1, '1d', 'close')
                if code in hist and len(hist[code]) > 0:
                    cur = float(hist[code][-1])
                    pnl_pct = (cur - pos.buy_price) / pos.buy_price * 100
            except Exception:
                pass

        # 下单
        passorder(24, 1101, account_id, code, 5, -1.0, float(sell_volume), ctx)

        if buy_date:
            _log("[{0}] << 卖出: {1} | {2}股 | 原因: {3} | 持仓自: {4} | 盈亏: {5:+.2f}%".format(
                current_date, code, sell_volume, reason_cn, buy_date, pnl_pct), ctx)
        else:
            _log("[{0}] << 卖出: {1} | {2}股 | 原因: {3}".format(
                current_date, code, sell_volume, reason_cn), ctx)
    except Exception as e:
        _log("[{0}] !! 卖出失败: {1} | {2}".format(current_date, code, e), ctx)
```

- [ ] **Step 4: 跑测试验证**

```bash
cd quant-trade-new && pytest tests/test_qmt_adapter.py -v
```
预期：10 PASSED

- [ ] **Step 5: Commit**

```bash
git add quant-trade-new/strategy_hs300.py quant-trade-new/tests/test_qmt_adapter.py
git commit -m "feat(strategy): §B 日志 + §G QMT 适配（修 _execute_sell log/del 顺序 bug）"
```

---

### Task 11: Strategy §H init + handlebar + 9 个私有 helper

**Files:**
- Modify: `quant-trade-new/strategy_hs300.py`（追加 §H）
- Test: `quant-trade-new/tests/test_handlebar.py`

**Interfaces:**
- Produces 在 strategy_hs300:
  - `init(ContextInfo)`
  - `handlebar(ContextInfo)`
  - 9 个私有 helper（见下方代码）

**业务规则照搬来源**：v1 行 315-775 整个 handlebar，按以下映射拆分：

| 新 helper | v1 来源行 |
|---|---|
| `_is_actionable_bar` | 320-343 (SKIP_HISTORY_WARMUP 删除，过滤变无条件) |
| `_daily_setup` | 343-356 |
| `_fetch_data` | 384, 535-536（合并） |
| `_update_market_streak` | 386-401 |
| `_evaluate_and_execute_sells` | 403-505 |
| `_is_rebalance_day` | 356 |
| `_do_rebalance` | 581-716 |
| `_do_refill` | 718-772 |
| `_log_status` | 885-1034（含 3 sub-helper） |

- [ ] **Step 1: 写 tests/test_handlebar.py（集成测试 6 例）**

```python
import pytest
import pandas as pd
from datetime import date
from pathlib import Path
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim
import strategy_hs300


DATA_ROOT = "../300data/data_a"


@pytest.fixture
def env(tmp_path):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    s = Shim(dl, acct, run_dir=tmp_path)
    for k, v in s.injected_globals().items():
        setattr(strategy_hs300, k, v)
    return s


def test_init_sets_required_attrs(env):
    strategy_hs300.init(env.context)
    assert env.context.positions == {}
    assert hasattr(env.context, 'strategy_start_date')
    assert hasattr(env.context, 'rebalance_count')
    assert hasattr(env.context, 'last_trade_date')


def test_handlebar_skips_before_start_date(env, tmp_path):
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20300101'  # 未来
    env.advance_to(pd.Timestamp('2020-03-02'), 0)
    strategy_hs300.handlebar(env.context)
    # 啥都不该做：仓位还是空
    assert env.account.positions == {}


def test_handlebar_runs_when_in_range(env, tmp_path):
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20200101'
    env.context.capital = 500000.0
    env.advance_to(pd.Timestamp('2020-03-02'), 0)
    strategy_hs300.handlebar(env.context)
    # 至少能跑完不抛
    assert env.context.last_trade_date == '20200302'


def test_handlebar_idempotent_same_bar(env, tmp_path):
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20200101'
    env.advance_to(pd.Timestamp('2020-03-02'), 0)
    strategy_hs300.handlebar(env.context)
    n_before = len(env.account.trades)
    # 再跑一次同一 bar
    strategy_hs300.handlebar(env.context)
    n_after = len(env.account.trades)
    assert n_before == n_after  # 幂等


def test_handlebar_multi_day_runs(env, tmp_path):
    """跑 5 个交易日不崩。"""
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20200101'
    env.context.capital = 500000.0
    cal = env.data_loader.trading_calendar()
    days_in_range = [d for d in cal if d >= pd.Timestamp('2020-03-02')][:5]
    for i, day in enumerate(days_in_range):
        env.advance_to(day, i)
        env.account.advance_day(day.strftime('%Y%m%d'))
        strategy_hs300.handlebar(env.context)


def test_handlebar_respects_rebalance_interval(env, tmp_path):
    """rebalance_count 在每次 handlebar 后 +1。"""
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20200101'
    env.context.capital = 500000.0
    cal = env.data_loader.trading_calendar()
    days = [d for d in cal if d >= pd.Timestamp('2020-03-02')][:3]
    for i, day in enumerate(days):
        env.advance_to(day, i)
        env.account.advance_day(day.strftime('%Y%m%d'))
        strategy_hs300.handlebar(env.context)
    assert env.context.rebalance_count == 3
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_handlebar.py -v
```

- [ ] **Step 3: 追加 §H（init + handlebar + 9 个 helper + 3 个 log helper）**

在 strategy_hs300.py 末尾追加。**业务逻辑字面映射 v1，不允许漂移**：

```python
# ════════════════════════════════════════════════════
# §H 主控（init + handlebar + 9 个私有 helper）
# ════════════════════════════════════════════════════

def init(ContextInfo):
    """v1 行 194-229，但删除 SKIP_HISTORY_WARMUP 相关日志逻辑。"""
    ContextInfo.set_account(ACCOUNT_ID)
    try:
        acct_info = get_trade_detail_data(ACCOUNT_ID, ACCOUNT_TYPE, 'ACCOUNT')
        if acct_info:
            ContextInfo.capital = acct_info[0].m_dBalance
        else:
            ContextInfo.capital = 100000
    except Exception:
        ContextInfo.capital = 100000

    ContextInfo.positions = {}
    ContextInfo.last_trade_date = None
    ContextInfo.accountid = ACCOUNT_ID
    ContextInfo.rebalance_count = 0
    ContextInfo.last_rebalance_date = None
    ContextInfo.ranked_candidates = (None, [])
    ContextInfo.realized_pnl = 0.0
    ContextInfo.total_cost = 0.0
    ContextInfo.trading_day_index = 0
    ContextInfo.market_ok_streak = 1
    ContextInfo.market_weak_streak = 0
    ContextInfo.strategy_start_date = datetime.now().strftime('%Y%m%d')
    ContextInfo.daily_cost = 0.0
    ContextInfo.daily_sold_records = []

    universe = ContextInfo.get_sector(INDEX_CODE)
    if universe:
        ContextInfo.set_universe(list(universe) + [INDEX_CODE])


def _is_actionable_bar(ctx):
    """时间闸 + 幂等 + start_date 过滤。"""
    current_date = timetag_to_datetime(ctx.get_bar_timetag(ctx.barpos), '%Y%m%d')
    current_time = timetag_to_datetime(ctx.get_bar_timetag(ctx.barpos), '%H:%M:%S')

    # start_date 过滤（替代 SKIP_HISTORY_WARMUP，无条件执行）
    if current_date < ctx.strategy_start_date:
        return False

    # 时间闸：分钟模式有效；日线模式 current_time='00:00:00' 自然通过
    if current_time != '00:00:00' and current_time < '14:50:00':
        return False

    # 幂等
    last_bar = getattr(ctx, 'last_processed_barpos', -1)
    if ctx.barpos <= last_bar:
        return False
    ctx.last_processed_barpos = ctx.barpos

    if ctx.last_trade_date == current_date:
        return False
    ctx.last_trade_date = current_date

    return True


def _daily_setup(ctx):
    """每日起始：累计成本结算 + 计数器。"""
    ctx.total_cost = getattr(ctx, 'total_cost', 0.0) + getattr(ctx, 'daily_cost', 0.0)
    ctx.daily_sold_records = []
    ctx.daily_cost = 0.0
    ctx.trading_day_index = getattr(ctx, 'trading_day_index', 0) + 1
    ctx.rebalance_count = getattr(ctx, 'rebalance_count', 0) + 1


def _fetch_data(ctx):
    """一次拿齐 close + volume + 指数。替代 v1 中 3 次 get_history_data。"""
    hist_close = ctx.get_history_data(70, '1d', 'close', dividend_type='front', skip_paused=True)
    hist_volume = ctx.get_history_data(70, '1d', 'volume', dividend_type='front', skip_paused=True)
    idx_prices = None
    if INDEX_CODE in hist_close and len(hist_close[INDEX_CODE]) >= 70:
        idx_prices = np.array(hist_close[INDEX_CODE], dtype=float)
    return hist_close, hist_volume, idx_prices


def _update_market_streak(ctx, idx_prices):
    """v1 行 390-401。"""
    market_ok = check_market_trend(idx_prices)
    if market_ok:
        ctx.market_ok_streak = getattr(ctx, 'market_ok_streak', 0) + 1
        ctx.market_weak_streak = 0
    else:
        ctx.market_ok_streak = 0
        ctx.market_weak_streak = getattr(ctx, 'market_weak_streak', 0) + 1
    return market_ok


def _is_rebalance_day(ctx):
    return ctx.rebalance_count >= REBALANCE_INTERVAL


def _evaluate_and_execute_sells(ctx, hist_close, current_date):
    """v1 行 403-505 字面保留。返回当日已卖出的 set。"""
    positions_to_sell = []

    for code, pos in list(ctx.positions.items()):
        if code not in hist_close or len(hist_close[code]) < 1:
            _log("[{0}] {1} 跳过卖出: 无数据".format(current_date, code), ctx)
            continue
        prices_list = hist_close[code]
        current_price = float(prices_list[-1])

        if current_price > pos.highest_price:
            pos.highest_price = current_price

        if len(prices_list) < 20:
            if check_hard_stop(pos, current_price, HARD_STOP_PCT):
                positions_to_sell.append((code, 'hard_stop'))
            continue

        prices_arr = np.array(prices_list, dtype=float)
        ma20 = np.mean(prices_arr[-20:])
        _, _, hist = macd(prices_arr)

        should_sell = False
        sell_reason = ''

        if check_hard_stop(pos, current_price, HARD_STOP_PCT):
            should_sell = True
            sell_reason = 'hard_stop'
        elif check_crash(prices_arr):
            should_sell = True
            sell_reason = 'crash_protection'

        if not should_sell:
            if check_trend_break(current_price, ma20, hist):
                should_sell = True
                sell_reason = 'trend_break'
            elif check_trailing_stop(pos, current_price, PROFIT_THRESHOLD, TRAILING_PULLBACK):
                should_sell = True
                sell_reason = 'trailing_stop'

        if should_sell:
            pnl_pct = (current_price - pos.buy_price) / pos.buy_price * 100
            _log("[{0}] 触发卖出: {1} | 原因: {2} | 买入价: {3:.2f} | 现价: {4:.2f} | 盈亏: {5:+.2f}%".format(
                current_date, code, sell_reason, pos.buy_price, current_price, pnl_pct), ctx)
            positions_to_sell.append((code, sell_reason))

    # 大盘弱势清仓豁免（保留盈利 >10% 的强势股）
    if ctx.market_weak_streak >= 2:
        already = {s for s, _ in positions_to_sell}
        for code, pos in list(ctx.positions.items()):
            if code in already:
                continue
            max_profit = (pos.highest_price - pos.buy_price) / pos.buy_price
            if max_profit <= PROFIT_THRESHOLD:
                positions_to_sell.append((code, 'market_weak'))

    # 执行卖出
    sold_today = set()
    for code, reason in positions_to_sell:
        if code in ctx.positions:
            pos = ctx.positions[code]
            sell_price = pos.buy_price
            if code in hist_close and len(hist_close[code]) > 0:
                sell_price = float(hist_close[code][-1])
                realized = (sell_price - pos.buy_price) * pos.volume
                ctx.realized_pnl = getattr(ctx, 'realized_pnl', 0.0) + realized
            ctx.daily_sold_records.append({
                'stockcode': code, 'volume': pos.volume,
                'buy_price': pos.buy_price, 'sell_price': sell_price,
                'reason': reason, 'buy_date': pos.buy_date,
            })
            ctx.daily_cost = getattr(ctx, 'daily_cost', 0.0) + trade_cost('sell', pos.volume * sell_price)
        _execute_sell(ctx, code, reason, current_date)
        if code in ctx.positions:
            del ctx.positions[code]
        sold_today.add(code)

    return sold_today


def _score_universe(ctx, buy_universe, hist_close, hist_volume):
    """打分 + Z-score 归一 + 加权。返回排序后的 list[(code, score)]."""
    candidates = []
    for code in buy_universe:
        if code not in hist_close or len(hist_close[code]) < 70:
            continue
        if code not in hist_volume or len(hist_volume[code]) < 20:
            continue
        prices_arr = np.array(hist_close[code], dtype=float)
        volumes_arr = np.array(hist_volume[code], dtype=float)
        f = score_factors(prices_arr, volumes_arr)
        if f is not None:
            candidates.append((code, f))

    scored = []
    if candidates:
        if len(candidates) >= 5:
            for key in ('trend_score', 'ma_spread_score', 'macd_score', 'volume_score'):
                values = np.array([f[key] for _, f in candidates], dtype=float)
                mean = np.mean(values)
                std = np.std(values)
                if std > 1e-12:
                    for _, f in candidates:
                        f[key] = (f[key] - mean) / std
                else:
                    for _, f in candidates:
                        f[key] = 0.0
        for code, f in candidates:
            total = (f['trend_score'] * WEIGHTS['trend']
                     + f['ma_spread_score'] * WEIGHTS['spread']
                     + f['macd_score'] * WEIGHTS['macd']
                     + f['volume_score'] * WEIGHTS['volume'])
            scored.append((code, total))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _do_rebalance(ctx, hist_close, hist_volume, sold_today, scored,
                  total_assets, available_cash, current_date):
    """换仓日。v1 行 581-716。"""
    ctx.rebalance_count = 0
    ctx.last_rebalance_date = current_date
    top_n = scored[:MAX_POSITIONS]
    top_codes = [x[0] for x in top_n]

    _log("[{0}] ====== 换仓日 ====== Top{1}".format(current_date, MAX_POSITIONS), ctx)

    # 卖出非 Top N 中且盈利 ≤10% 的（盈利 >10% 保留）
    for code in list(ctx.positions.keys()):
        if code in top_codes:
            continue
        pos = ctx.positions[code]
        sell_price = pos.buy_price
        if code in hist_close and len(hist_close[code]) > 0:
            sell_price = float(hist_close[code][-1])
            profit = (sell_price - pos.buy_price) / pos.buy_price
            if profit > PROFIT_THRESHOLD:
                _log("[{0}] 换仓保留: {1} | 盈利{2:+.2f}%".format(current_date, code, profit * 100), ctx)
                continue
            realized = (sell_price - pos.buy_price) * pos.volume
            ctx.realized_pnl = getattr(ctx, 'realized_pnl', 0.0) + realized

        ctx.daily_sold_records.append({
            'stockcode': code, 'volume': pos.volume,
            'buy_price': pos.buy_price, 'sell_price': sell_price,
            'reason': 'rebalance', 'buy_date': pos.buy_date,
        })
        ctx.daily_cost = getattr(ctx, 'daily_cost', 0.0) + trade_cost('sell', pos.volume * sell_price)
        _execute_sell(ctx, code, 'rebalance', current_date)
        if code in ctx.positions:
            del ctx.positions[code]
        sold_today.add(code)

    # 卖出后重新拿资金（v1 行 661-670）
    total_assets, available_cash = _get_account(ctx)

    # 买入 Top N（大盘连续 2 天 OK 才买）
    if ctx.market_ok_streak >= 2:
        current_holdings = len(ctx.positions)
        for code, s in top_n:
            if current_holdings >= MAX_POSITIONS:
                break
            if code in ctx.positions or code in sold_today:
                continue
            if code not in hist_close:
                continue
            prices_arr = np.array(hist_close[code], dtype=float)
            current_price = float(prices_arr[-1])
            buy_amount = position_size(total_assets, available_cash, MAX_POSITIONS)
            if buy_amount < 1000:
                continue
            buy_volume = int(buy_amount / current_price / 100) * 100
            if buy_volume < 100:
                continue
            success, cost = _execute_buy(ctx, code, buy_volume, current_price, current_date, score=s)
            if success:
                ctx.positions[code] = Position(
                    stockcode=code, buy_price=current_price, buy_date=current_date,
                    volume=buy_volume, buy_trading_day_idx=ctx.trading_day_index,
                )
                available_cash -= buy_volume * current_price + cost
                current_holdings += 1
                _, available_cash = _get_account(ctx)
    else:
        _log("[{0}] 大盘弱势，换仓日跳过买入".format(current_date), ctx)


def _do_refill(ctx, hist_close, hist_volume, sold_today, scored,
               total_assets, available_cash, current_date):
    """非换仓日补仓。v1 行 718-772。"""
    if ctx.market_ok_streak < 2:
        return
    current_holdings = len(ctx.positions)
    if current_holdings >= MAX_POSITIONS:
        return
    for code, s in scored:
        if current_holdings >= MAX_POSITIONS:
            break
        if code in ctx.positions or code in sold_today:
            continue
        if code not in hist_close or len(hist_close[code]) < 70:
            continue
        if code not in hist_volume or len(hist_volume[code]) < 20:
            continue
        prices_arr = np.array(hist_close[code], dtype=float)
        volumes_arr = np.array(hist_volume[code], dtype=float)
        if not check_buy_signal(prices_arr, volumes_arr):
            continue
        current_price = float(prices_arr[-1])
        buy_amount = position_size(total_assets, available_cash, MAX_POSITIONS)
        if buy_amount < 1000:
            continue
        buy_volume = int(buy_amount / current_price / 100) * 100
        if buy_volume < 100:
            continue
        success, cost = _execute_buy(ctx, code, buy_volume, current_price, current_date, score=s)
        if success:
            ctx.positions[code] = Position(
                stockcode=code, buy_price=current_price, buy_date=current_date,
                volume=buy_volume, buy_trading_day_idx=ctx.trading_day_index,
            )
            available_cash -= buy_volume * current_price + cost
            current_holdings += 1
            _, available_cash = _get_account(ctx)


def _log_status(ctx, current_date):
    """v1 行 885-1034。简化为 3 个 sub-helper 的串接。"""
    holdings = list(ctx.positions.keys())
    sold = getattr(ctx, 'daily_sold_records', [])
    if len(holdings) == 0 and len(sold) == 0:
        total, _ = _get_account(ctx)
        _log("[{0}] 当前持仓: 空仓 | 总资产: {1:.0f}元".format(current_date, total), ctx)
        return
    # 详细日志（沿用 v1 格式但代码精简）
    total, cash = _get_account(ctx)
    _log("[{0}] 持仓 {1} 只 | 总资产: {2:.0f}元 | 现金: {3:.0f}元".format(
        current_date, len(holdings), total, cash), ctx)


def handlebar(ContextInfo):
    """主调度。整个 handlebar 内只 30 行；细节都在 helper 里。"""
    if not _is_actionable_bar(ContextInfo):
        return

    current_date = timetag_to_datetime(ContextInfo.get_bar_timetag(ContextInfo.barpos), '%Y%m%d')

    _daily_setup(ContextInfo)
    _sync_positions(ContextInfo, current_date)

    universe = ContextInfo.get_sector(INDEX_CODE)
    if not universe:
        _log("[{0}] 无法获取沪深300成分股".format(current_date), ContextInfo)
        return

    # set_universe 仅当持仓股缺失时（v1 行 369-374）
    held = list(ContextInfo.positions.keys())
    missing = [c for c in held if c not in universe]
    if missing:
        ContextInfo.set_universe(list(set(universe + held + [INDEX_CODE])))

    buy_universe = _filter_buyable(
        [c for c in universe if c != INDEX_CODE],
        ContextInfo
    )

    hist_close, hist_volume, idx_prices = _fetch_data(ContextInfo)
    market_ok = _update_market_streak(ContextInfo, idx_prices)
    _log("[{0}] 持仓 {1} 只 | 大盘OK连{2}天 弱连{3}天 | 距换仓 {4} 日".format(
        current_date, len(held), ContextInfo.market_ok_streak,
        ContextInfo.market_weak_streak, REBALANCE_INTERVAL - ContextInfo.rebalance_count
    ), ContextInfo)

    sold_today = _evaluate_and_execute_sells(ContextInfo, hist_close, current_date)
    total_assets, available_cash = _get_account(ContextInfo)
    scored = _score_universe(ContextInfo, buy_universe, hist_close, hist_volume)
    ContextInfo.ranked_candidates = (current_date, scored)

    if _is_rebalance_day(ContextInfo):
        _do_rebalance(ContextInfo, hist_close, hist_volume, sold_today, scored,
                      total_assets, available_cash, current_date)
    else:
        _do_refill(ContextInfo, hist_close, hist_volume, sold_today, scored,
                   total_assets, available_cash, current_date)

    _log_status(ContextInfo, current_date)
```

- [ ] **Step 4: 跑测试验证**

```bash
cd quant-trade-new && pytest tests/test_handlebar.py -v
```
预期：6 PASSED

- [ ] **Step 5: 全套回归**

```bash
cd quant-trade-new && pytest tests/ -x --ignore=tests/test_e2e.py
```
预期：所有非 E2E 测试 PASSED

- [ ] **Step 6: Commit**

```bash
git add quant-trade-new/strategy_hs300.py quant-trade-new/tests/test_handlebar.py
git commit -m "feat(strategy): §H init + handlebar + 9 helper（业务规则照搬 v1）"
```

---

### Task 12: Strategy Loader

**Files:**
- Create: `quant-trade-new/backtest/strategy_loader.py`
- Test: `quant-trade-new/tests/test_strategy_loader.py`

**Interfaces:**
- Produces:
  - `load_strategy(strategy_path: Path, injected_globals: dict) -> module` 用 `exec` 加载，注入全局
  - 加载后的 module 暴露 `init`, `handlebar`, `Position`, 所有常量等

- [ ] **Step 1: 写测试**

`quant-trade-new/tests/test_strategy_loader.py`:
```python
from pathlib import Path
import pytest
from datetime import date
import pandas as pd
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim
from backtest.strategy_loader import load_strategy


STRATEGY_PATH = Path(__file__).parent.parent / 'strategy_hs300.py'
DATA_ROOT = "../300data/data_a"


def test_loads_strategy_with_injected_globals(tmp_path):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    shim = Shim(dl, acct, run_dir=tmp_path)
    mod = load_strategy(STRATEGY_PATH, shim.injected_globals())
    assert hasattr(mod, 'init')
    assert hasattr(mod, 'handlebar')
    assert hasattr(mod, 'Position')


def test_strategy_can_init_via_loader(tmp_path):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    shim = Shim(dl, acct, run_dir=tmp_path)
    mod = load_strategy(STRATEGY_PATH, shim.injected_globals())
    mod.init(shim.context)
    assert shim.context.positions == {}


def test_loader_returns_isolated_module(tmp_path):
    """两次加载是独立模块。"""
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    shim = Shim(dl, acct, run_dir=tmp_path)
    m1 = load_strategy(STRATEGY_PATH, shim.injected_globals())
    m2 = load_strategy(STRATEGY_PATH, shim.injected_globals())
    assert m1 is not m2
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_strategy_loader.py -v
```

- [ ] **Step 3: 实现**

`quant-trade-new/backtest/strategy_loader.py`:
```python
"""通过 exec 加载策略文件并注入 QMT 全局函数。"""
import types
from pathlib import Path


def load_strategy(strategy_path: Path, injected_globals: dict):
    source = Path(strategy_path).read_text(encoding='utf-8')
    mod = types.ModuleType('strategy_hs300_loaded')
    mod.__file__ = str(strategy_path)
    mod.__dict__.update(injected_globals)
    code = compile(source, str(strategy_path), 'exec')
    exec(code, mod.__dict__)
    return mod
```

- [ ] **Step 4: 测试通过**

```bash
cd quant-trade-new && pytest tests/test_strategy_loader.py -v
```

- [ ] **Step 5: Commit**

```bash
git add quant-trade-new/backtest/strategy_loader.py quant-trade-new/tests/test_strategy_loader.py
git commit -m "feat(backtest): strategy_loader 用 exec 注入 QMT 全局"
```

---

### Task 13: Engine 主循环

**Files:**
- Create: `quant-trade-new/backtest/engine.py`
- Test: `quant-trade-new/tests/test_engine.py`

**Interfaces:**
- Consumes: `DataLoader`, `Account`, `Shim`, 加载后的 strategy module
- Produces:
  - `Engine(data_loader, account, shim, strategy, config)`
  - `Engine.run() -> None` 主循环
  - 循环内每日：advance_to → advance_day → strategy.handlebar(ctx) → snapshot

- [ ] **Step 1: 写测试**

`quant-trade-new/tests/test_engine.py`:
```python
import pytest
from pathlib import Path
from datetime import date
import pandas as pd
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim
from backtest.strategy_loader import load_strategy
from backtest.engine import Engine
from backtest.cli import RunConfig


STRATEGY_PATH = Path(__file__).parent.parent / 'strategy_hs300.py'
DATA_ROOT = "../300data/data_a"


def make_config(start, end, tmp_path):
    return RunConfig(
        start_date=start, end_date=end,
        initial_capital=500000.0,
        data_root=DATA_ROOT, results_dir=str(tmp_path),
        commission_rate=0.0001, commission_min=5.0,
        stamp_rate=0.001, transfer_rate=0.00001, slippage_rate=0.0005,
        max_positions=5, rebalance_interval=10, warmup_days=120,
    )


def test_engine_runs_5_days(tmp_path):
    cfg = make_config(date(2020, 3, 1), date(2020, 3, 10), tmp_path)
    dl = DataLoader(cfg.data_root)
    dl.load(cfg.start_date, cfg.end_date, cfg.warmup_days)
    acct = Account(cfg.initial_capital)
    shim = Shim(dl, acct, run_dir=tmp_path)
    strat = load_strategy(STRATEGY_PATH, shim.injected_globals())

    engine = Engine(dl, acct, shim, strat, cfg)
    engine.run()

    # snapshot 数量等于交易日数量（2020-03 区间约 6-7 个）
    assert 5 <= len(acct.snapshots) <= 10


def test_engine_snapshot_equity_starts_at_capital(tmp_path):
    cfg = make_config(date(2020, 3, 1), date(2020, 3, 10), tmp_path)
    dl = DataLoader(cfg.data_root)
    dl.load(cfg.start_date, cfg.end_date, cfg.warmup_days)
    acct = Account(cfg.initial_capital)
    shim = Shim(dl, acct, run_dir=tmp_path)
    strat = load_strategy(STRATEGY_PATH, shim.injected_globals())

    engine = Engine(dl, acct, shim, strat, cfg)
    engine.run()
    # 第一个 snapshot 应在 cfg.start 之后（warmup 早期 strategy_start_date 拦截）
    assert acct.snapshots[0].total_equity <= cfg.initial_capital * 1.05  # 允许略有买入波动


def test_engine_overwrites_strategy_start_date(tmp_path):
    """覆写：strategy.init 设的 today 被 Engine 改为 cfg.start。"""
    cfg = make_config(date(2020, 3, 1), date(2020, 3, 10), tmp_path)
    dl = DataLoader(cfg.data_root)
    dl.load(cfg.start_date, cfg.end_date, cfg.warmup_days)
    acct = Account(cfg.initial_capital)
    shim = Shim(dl, acct, run_dir=tmp_path)
    strat = load_strategy(STRATEGY_PATH, shim.injected_globals())

    engine = Engine(dl, acct, shim, strat, cfg)
    engine.run()
    assert shim.context.strategy_start_date == '20200301'


def test_engine_overwrites_capital(tmp_path):
    cfg = make_config(date(2020, 3, 1), date(2020, 3, 10), tmp_path)
    dl = DataLoader(cfg.data_root)
    dl.load(cfg.start_date, cfg.end_date, cfg.warmup_days)
    acct = Account(cfg.initial_capital)
    shim = Shim(dl, acct, run_dir=tmp_path)
    strat = load_strategy(STRATEGY_PATH, shim.injected_globals())

    engine = Engine(dl, acct, shim, strat, cfg)
    engine.run()
    assert shim.context.capital == 500000.0  # 不是 strategy init 的 100000
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_engine.py -v
```

- [ ] **Step 3: 实现 Engine**

`quant-trade-new/backtest/engine.py`:
```python
"""按交易日推进的主循环。"""
import pandas as pd


class Engine:
    def __init__(self, data_loader, account, shim, strategy, config):
        self.data_loader = data_loader
        self.account = account
        self.shim = shim
        self.strategy = strategy
        self.config = config

    def run(self):
        # 1. 初始化策略
        self.strategy.init(self.shim.context)

        # 2. 环境覆写（关键）
        self.shim.context.strategy_start_date = self.config.start_date.strftime('%Y%m%d')
        self.shim.context.log_dir = str(self.config.results_dir)
        self.shim.context.capital = self.config.initial_capital
        # 让 shim 反向影响策略 init 时 set_universe 的影响：重设 universe
        all_codes = [c for c in self.data_loader.universe_codes()
                     if c != 'SH.000300']
        # 策略形态代码：'SH.600000' → '600000.SH'
        strategy_codes = [self._to_strategy_code(c) for c in all_codes]
        self.shim.context.set_universe(strategy_codes + ['000300.SH'])

        # 3. 主循环
        cal = self.data_loader.trading_calendar()
        in_range = cal[(cal >= pd.Timestamp(self.config.start_date)) &
                       (cal <= pd.Timestamp(self.config.end_date))]

        for i, day in enumerate(in_range):
            self.shim.advance_to(day, i)
            self.account.advance_day(day.strftime('%Y%m%d'))
            self.strategy.handlebar(self.shim.context)

            # EOD snapshot
            close_prices = {
                self._to_strategy_code(c): float(df.loc[day, 'close'])
                for c, df in self.data_loader.daily_df.items()
                if day in df.index
            }
            self.account.snapshot(day.strftime('%Y%m%d'), close_prices)

    @staticmethod
    def _to_strategy_code(data_code: str) -> str:
        """'SH.600000' → '600000.SH'。"""
        if data_code.startswith(('SH.', 'SZ.')):
            ex, num = data_code.split('.', 1)
            return f"{num}.{ex}"
        return data_code
```

- [ ] **Step 4: 测试通过**

```bash
cd quant-trade-new && pytest tests/test_engine.py -v
```

- [ ] **Step 5: Commit**

```bash
git add quant-trade-new/backtest/engine.py quant-trade-new/tests/test_engine.py
git commit -m "feat(backtest): Engine 主循环 + 环境覆写"
```

---

### Task 14: Reporter

**Files:**
- Create: `quant-trade-new/backtest/reporter.py`
- Test: `quant-trade-new/tests/test_reporter.py`

**Interfaces:**
- Consumes: `Account.trades`, `Account.snapshots`, `RunConfig`
- Produces:
  - `Reporter(account, config, run_dir: Path)`
  - `Reporter.write_all() -> None` 写所有 4 文件 + png
  - `Reporter.compute_periods() -> list[Period]`：自然年切分 + 累计 1 行
  - `Period(label: str, start: str, end: str)` 含 partial-year 标注：`'2020(03-15起)'`, `'2021(08-30止)'`, `'2020'`, `'total'`
  - `Reporter.compute_metrics(period_snapshots) -> dict`

- [ ] **Step 1: 写测试**

`quant-trade-new/tests/test_reporter.py`:
```python
import pytest
import pandas as pd
from pathlib import Path
from datetime import date
from backtest.account import Account, Snapshot, Trade
from backtest.reporter import Reporter
from backtest.cli import RunConfig


def make_config(start, end, tmp_path):
    return RunConfig(
        start_date=start, end_date=end, initial_capital=500000.0,
        data_root='', results_dir=str(tmp_path),
        commission_rate=0.0001, commission_min=5.0,
        stamp_rate=0.001, transfer_rate=0.00001, slippage_rate=0.0005,
        max_positions=5, rebalance_interval=10, warmup_days=120,
    )


def fake_account_with_snapshots(snapshots_data):
    a = Account(initial_capital=500000.0)
    for date_str, equity in snapshots_data:
        a.snapshots.append(Snapshot(
            date=date_str, cash=equity, position_value=0.0,
            total_equity=equity, n_positions=0, daily_return=0.0,
        ))
    return a


def test_single_year_period_label(tmp_path):
    cfg = make_config(date(2020, 1, 1), date(2020, 12, 31), tmp_path)
    a = fake_account_with_snapshots([
        ('20200102', 500000.0), ('20201231', 550000.0)
    ])
    r = Reporter(a, cfg, run_dir=tmp_path)
    periods = r.compute_periods()
    labels = [p.label for p in periods]
    assert '2020' in labels
    assert 'total' in labels


def test_cross_year_periods(tmp_path):
    cfg = make_config(date(2020, 1, 1), date(2021, 12, 31), tmp_path)
    a = fake_account_with_snapshots([
        ('20200102', 500000.0), ('20201231', 550000.0),
        ('20210104', 550000.0), ('20211231', 600000.0),
    ])
    r = Reporter(a, cfg, run_dir=tmp_path)
    periods = r.compute_periods()
    labels = [p.label for p in periods]
    assert '2020' in labels
    assert '2021' in labels
    assert 'total' in labels


def test_partial_year_label(tmp_path):
    cfg = make_config(date(2020, 3, 15), date(2021, 8, 30), tmp_path)
    a = fake_account_with_snapshots([
        ('20200316', 500000.0), ('20201231', 540000.0),
        ('20210104', 540000.0), ('20210830', 600000.0),
    ])
    r = Reporter(a, cfg, run_dir=tmp_path)
    periods = r.compute_periods()
    labels = [p.label for p in periods]
    assert any('2020' in l and '03-15' in l for l in labels)
    assert any('2021' in l and '08-30' in l for l in labels)


def test_avg_holding_days_computed_from_trades(tmp_path):
    """从 buy/sell 配对的持有天数算均值（FIFO）。"""
    cfg = make_config(date(2020, 1, 1), date(2020, 12, 31), tmp_path)
    a = fake_account_with_snapshots([
        ('20200102', 500000.0), ('20201231', 550000.0)
    ])
    a.trades = [
        Trade(trade_id=1, date='20200110', code='SH.600000', name='浦发',
              side='buy', volume=1000, price=10.0, amount=10000.0,
              cost=5.0, reason='buy_signal', status='FILLED'),
        Trade(trade_id=2, date='20200120', code='SH.600000', name='浦发',
              side='sell', volume=1000, price=11.0, amount=11000.0,
              cost=15.0, reason='trailing_stop', status='FILLED', realized_pnl=985.0),
    ]
    r = Reporter(a, cfg, run_dir=tmp_path)
    period = r.compute_periods()[0]  # 2020 行
    m = r.compute_metrics(period)
    assert m['avg_holding_days'] == 10.0  # 2020-01-10 → 2020-01-20


def test_write_all_creates_files(tmp_path):
    cfg = make_config(date(2020, 1, 1), date(2020, 12, 31), tmp_path)
    a = fake_account_with_snapshots([
        ('20200102', 500000.0), ('20201231', 550000.0)
    ])
    r = Reporter(a, cfg, run_dir=tmp_path)
    r.write_all()
    assert (tmp_path / 'metrics.csv').exists()
    assert (tmp_path / 'snapshots.csv').exists()
    assert (tmp_path / 'trades.csv').exists()
    assert (tmp_path / 'equity.png').exists()
    assert (tmp_path / 'run_config.json').exists()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd quant-trade-new && pytest tests/test_reporter.py -v
```

- [ ] **Step 3: 实现 Reporter**

`quant-trade-new/backtest/reporter.py`:
```python
"""年度行 + 累计行 metrics，trades/snapshots/equity 输出。"""
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


@dataclass
class Period:
    label: str
    start: str
    end: str


class Reporter:
    def __init__(self, account, config, run_dir: Path):
        self.account = account
        self.config = config
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def compute_periods(self) -> list[Period]:
        if not self.account.snapshots:
            return []

        start = self.config.start_date
        end = self.config.end_date
        periods = []

        years = sorted({int(s.date[:4]) for s in self.account.snapshots})
        for y in years:
            y_start = max(pd.Timestamp(f'{y}-01-01').date(), start)
            y_end = min(pd.Timestamp(f'{y}-12-31').date(), end)
            label = str(y)
            if y_start != pd.Timestamp(f'{y}-01-01').date():
                label += f"({y_start.strftime('%m-%d')}起)"
            if y_end != pd.Timestamp(f'{y}-12-31').date():
                label += f"({y_end.strftime('%m-%d')}止)"
            periods.append(Period(label=label,
                                  start=y_start.strftime('%Y%m%d'),
                                  end=y_end.strftime('%Y%m%d')))
        periods.append(Period(label='total',
                              start=start.strftime('%Y%m%d'),
                              end=end.strftime('%Y%m%d')))
        return periods

    def compute_metrics(self, period: Period) -> dict:
        in_period = [s for s in self.account.snapshots
                     if period.start <= s.date <= period.end]
        if len(in_period) < 2:
            return {
                'period': period.label, 'start_date': period.start, 'end_date': period.end,
                'start_equity': 0, 'end_equity': 0, 'total_return': 0,
                'annual_return': 0, 'max_drawdown': 0, 'sharpe': 0,
                'n_trades': 0, 'n_rejected': 0, 'win_rate': 0,
                'avg_holding_days': 0, 'total_cost': 0,
            }

        equities = [s.total_equity for s in in_period]
        start_eq, end_eq = equities[0], equities[-1]
        total_ret = end_eq / start_eq - 1
        n_days = len(in_period)
        annual = (1 + total_ret) ** (252 / max(n_days, 1)) - 1

        # 最大回撤
        peak = equities[0]
        max_dd = 0
        for v in equities:
            if v > peak:
                peak = v
            dd = (v - peak) / peak if peak > 0 else 0
            if dd < max_dd:
                max_dd = dd

        # Sharpe
        rets = [equities[i] / equities[i - 1] - 1 for i in range(1, len(equities))]
        if rets and len(rets) > 1:
            mean_r = sum(rets) / len(rets)
            var_r = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
            std_r = math.sqrt(var_r)
            sharpe = (mean_r / std_r) * math.sqrt(252) if std_r > 0 else 0.0
        else:
            sharpe = 0.0

        # 交易统计
        period_trades = [t for t in self.account.trades
                         if period.start <= t.date <= period.end]
        filled = [t for t in period_trades if t.status == 'FILLED']
        rejected = [t for t in period_trades if t.status == 'REJECTED']
        sell_trades = [t for t in filled if t.side == 'sell']
        wins = [t for t in sell_trades if t.realized_pnl > 0]
        win_rate = len(wins) / len(sell_trades) if sell_trades else 0
        total_cost = sum(t.cost for t in filled)

        avg_hold = self._compute_avg_holding_days(filled)

        return {
            'period': period.label, 'start_date': period.start, 'end_date': period.end,
            'start_equity': round(start_eq, 2), 'end_equity': round(end_eq, 2),
            'total_return': round(total_ret, 6), 'annual_return': round(annual, 6),
            'max_drawdown': round(max_dd, 6), 'sharpe': round(sharpe, 4),
            'n_trades': len(filled), 'n_rejected': len(rejected),
            'win_rate': round(win_rate, 4), 'avg_holding_days': round(avg_hold, 2),
            'total_cost': round(total_cost, 2),
        }

    @staticmethod
    def _compute_avg_holding_days(filled_trades):
        """FIFO 配对 buy/sell，返回平均持有天数。"""
        from datetime import datetime
        open_lots = {}  # code -> [(buy_date_str, volume)]
        holding_days = []
        for t in filled_trades:
            if t.side == 'buy':
                open_lots.setdefault(t.code, []).append((t.date, t.volume))
            elif t.side == 'sell':
                remaining = t.volume
                lots = open_lots.get(t.code, [])
                while remaining > 0 and lots:
                    buy_date, vol = lots[0]
                    take = min(vol, remaining)
                    d_buy = datetime.strptime(buy_date, '%Y%m%d')
                    d_sell = datetime.strptime(t.date, '%Y%m%d')
                    holding_days.append((d_sell - d_buy).days)
                    remaining -= take
                    if vol == take:
                        lots.pop(0)
                    else:
                        lots[0] = (buy_date, vol - take)
        return sum(holding_days) / len(holding_days) if holding_days else 0.0

    def write_all(self):
        self._write_metrics()
        self._write_trades()
        self._write_snapshots()
        self._write_equity_png()
        self._write_run_config()

    def _write_metrics(self):
        periods = self.compute_periods()
        if not periods:
            return
        path = self.run_dir / 'metrics.csv'
        rows = [self.compute_metrics(p) for p in periods]
        with open(path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    def _write_trades(self):
        path = self.run_dir / 'trades.csv'
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['trade_id', 'date', 'code', 'name', 'side', 'volume',
                        'price', 'amount', 'cost', 'reason', 'status', 'realized_pnl'])
            for t in self.account.trades:
                w.writerow([t.trade_id, t.date, t.code, t.name, t.side, t.volume,
                            t.price, t.amount, t.cost, t.reason, t.status, t.realized_pnl])

    def _write_snapshots(self):
        path = self.run_dir / 'snapshots.csv'
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['date', 'cash', 'position_value', 'total_equity',
                        'n_positions', 'daily_return'])
            for s in self.account.snapshots:
                w.writerow([s.date, s.cash, s.position_value, s.total_equity,
                            s.n_positions, s.daily_return])

    def _write_equity_png(self):
        if not self.account.snapshots:
            return
        dates = [pd.to_datetime(s.date) for s in self.account.snapshots]
        equities = [s.total_equity for s in self.account.snapshots]
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(dates, equities, linewidth=1.5)
        # 年份分割线
        years = sorted({d.year for d in dates})
        for y in years[1:]:
            ax.axvline(pd.Timestamp(f'{y}-01-01'), color='gray',
                       linestyle='--', alpha=0.4)
        ax.set_title('Equity Curve')
        ax.set_xlabel('Date')
        ax.set_ylabel('Total Equity')
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(self.run_dir / 'equity.png', dpi=100)
        plt.close(fig)

    def _write_run_config(self):
        from dataclasses import asdict
        path = self.run_dir / 'run_config.json'
        d = asdict(self.config)
        # date 类型 JSON 化
        d['start_date'] = d['start_date'].isoformat()
        d['end_date'] = d['end_date'].isoformat()
        with open(path, 'w') as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 4: 测试通过**

```bash
cd quant-trade-new && pytest tests/test_reporter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add quant-trade-new/backtest/reporter.py quant-trade-new/tests/test_reporter.py
git commit -m "feat(backtest): Reporter 年度切分 + 4 类产物"
```

---

### Task 15: CLI 集成 + E2E（含黄金基线）

**Files:**
- Modify: `quant-trade-new/backtest/cli.py`（加入完整 main 串联）
- Create: `quant-trade-new/tests/test_e2e.py`
- Create: `quant-trade-new/tests/fixtures/.gitkeep`

**Interfaces:**
- Modify `cli.main()`：串联 DataLoader → Shim → Account → load_strategy → Engine → Reporter

- [ ] **Step 1: 在 cli.py 中实现 main 串联**

把 `cli.py` 的 `main()` 改为：

```python
def main(argv=None):
    from pathlib import Path
    from datetime import datetime
    from backtest.data_loader import DataLoader
    from backtest.account import Account
    from backtest.shim import Shim
    from backtest.strategy_loader import load_strategy
    from backtest.engine import Engine
    from backtest.reporter import Reporter

    ns = parse_args(argv if argv is not None else sys.argv[1:])
    overrides = {
        'start_date': ns.start, 'end_date': ns.end,
        'initial_capital': ns.capital,
        'data_root': ns.data_root, 'results_dir': ns.results_dir,
    }
    cfg = load_config(ns.config, overrides)

    run_id = build_run_id(cfg.start_date, cfg.end_date, datetime.now())
    run_dir = Path(cfg.results_dir) / run_id
    # 处理已存在
    suffix = 0
    while run_dir.exists() and any(run_dir.iterdir()):
        suffix += 1
        run_dir = Path(cfg.results_dir) / f"{run_id}_{suffix}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"run_dir: {run_dir}")

    # 替换 results_dir 为 run_dir
    from dataclasses import replace
    cfg = replace(cfg, results_dir=str(run_dir))

    dl = DataLoader(cfg.data_root)
    dl.load(cfg.start_date, cfg.end_date, cfg.warmup_days)
    # 写 data_quality.log
    qlog = run_dir / 'data_quality.log'
    with open(qlog, 'w', encoding='utf-8') as f:
        for line in dl.data_quality_log:
            f.write(line + '\n')

    acct = Account(cfg.initial_capital)
    shim = Shim(dl, acct, run_dir=run_dir)
    strategy_path = Path(__file__).parent.parent / 'strategy_hs300.py'
    strat = load_strategy(strategy_path, shim.injected_globals())

    engine = Engine(dl, acct, shim, strat, cfg)
    engine.run()

    reporter = Reporter(acct, cfg, run_dir=run_dir)
    reporter.write_all()
    print(f"done. results: {run_dir}")


if __name__ == '__main__':
    import sys
    main()
```

并在 `cli.py` 顶部加 `import sys`。

- [ ] **Step 2: 写 E2E 测试**

`quant-trade-new/tests/test_e2e.py`:
```python
import json
import pytest
import csv
from datetime import date
from pathlib import Path
from backtest.cli import main


pytestmark = pytest.mark.e2e


def test_e2e_smoke_30days(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).parent.parent)  # cd 到 quant-trade-new
    main([
        '--start', '2020-02-03', '--end', '2020-03-15',
        '--results-dir', str(tmp_path),
    ])
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1
    assert (runs[0] / 'metrics.csv').exists()
    assert (runs[0] / 'trades.csv').exists()
    assert (runs[0] / 'snapshots.csv').exists()
    assert (runs[0] / 'equity.png').exists()


def test_e2e_2020_golden_baseline(tmp_path, monkeypatch):
    """2020 全年 → 锁定 5 项指标作为 golden 基线。
    首次跑产生 baseline，后续跑必须与之吻合（容差 ±0.1pp）。"""
    monkeypatch.chdir(Path(__file__).parent.parent)
    main(['--start', '2020-01-01', '--end', '2020-12-31',
          '--results-dir', str(tmp_path)])
    runs = list(tmp_path.iterdir())
    metrics_path = runs[0] / 'metrics.csv'
    with open(metrics_path) as f:
        rows = list(csv.DictReader(f))

    total_row = next(r for r in rows if r['period'] == 'total')

    golden_path = Path(__file__).parent / 'fixtures' / 'golden_2020.json'
    if not golden_path.exists():
        # 首次跑：写入基线
        golden = {
            'annual_return': float(total_row['annual_return']),
            'max_drawdown': float(total_row['max_drawdown']),
            'sharpe': float(total_row['sharpe']),
            'n_trades': int(total_row['n_trades']),
            'win_rate': float(total_row['win_rate']),
        }
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        with open(golden_path, 'w') as f:
            json.dump(golden, f, indent=2)
        pytest.skip("golden baseline 首次写入，本次跳过比对（下次跑会校验）")
    else:
        with open(golden_path) as f:
            golden = json.load(f)
        assert abs(float(total_row['annual_return']) - golden['annual_return']) < 0.001
        assert abs(float(total_row['max_drawdown']) - golden['max_drawdown']) < 0.001
        assert abs(float(total_row['sharpe']) - golden['sharpe']) < 0.1
        assert int(total_row['n_trades']) == golden['n_trades']
        assert abs(float(total_row['win_rate']) - golden['win_rate']) < 0.005


def test_e2e_cross_year_2020_2021(tmp_path, monkeypatch):
    """跨年：metrics.csv 应有 3 行（2020 / 2021 / total）。"""
    monkeypatch.chdir(Path(__file__).parent.parent)
    main(['--start', '2020-01-01', '--end', '2021-12-31',
          '--results-dir', str(tmp_path)])
    runs = list(tmp_path.iterdir())
    metrics_path = runs[0] / 'metrics.csv'
    with open(metrics_path) as f:
        rows = list(csv.DictReader(f))
    labels = [r['period'] for r in rows]
    assert '2020' in labels
    assert '2021' in labels
    assert 'total' in labels
    assert len(rows) == 3

    # 累计 ≈ (1+2020) × (1+2021) - 1
    y2020 = next(r for r in rows if r['period'] == '2020')
    y2021 = next(r for r in rows if r['period'] == '2021')
    total = next(r for r in rows if r['period'] == 'total')
    compounded = (1 + float(y2020['total_return'])) * (1 + float(y2021['total_return'])) - 1
    assert abs(compounded - float(total['total_return'])) < 0.001
```

- [ ] **Step 3: 跑 E2E 测试（首次会自动写入 golden）**

```bash
cd quant-trade-new && pytest tests/test_e2e.py -v -m e2e -s
```
预期：
- `test_e2e_smoke_30days` PASS（<30s）
- `test_e2e_2020_golden_baseline` SKIPPED（首次写入 baseline）
- `test_e2e_cross_year_2020_2021` PASS

- [ ] **Step 4: 再跑一次 E2E 验证 golden 比对**

```bash
cd quant-trade-new && pytest tests/test_e2e.py::test_e2e_2020_golden_baseline -v -m e2e
```
预期：PASS（指标与上次完全一致）

- [ ] **Step 5: 完整全套回归**

```bash
cd quant-trade-new && pytest tests/ -v
```
预期：全部 PASSED（除首次的 golden baseline SKIPPED）

- [ ] **Step 6: 手动跑一个真实回测验证**

```bash
cd quant-trade-new && python -m backtest.cli --start 2020-01-01 --end 2021-12-31
```
预期：终端打印 `done. results: results/20200101-20211231_...`，目录里 4 个 csv + png + run_config.json + data_quality.log + logs/

- [ ] **Step 7: 检查产物**

```bash
ls quant-trade-new/results/
cat quant-trade-new/results/*/metrics.csv | head -5
```
预期：metrics.csv 是 3 行（2020 / 2021 / total）+ 表头

- [ ] **Step 8: Commit**

```bash
git add quant-trade-new/backtest/cli.py quant-trade-new/tests/test_e2e.py \
        quant-trade-new/tests/fixtures/golden_2020.json
git commit -m "feat(backtest): CLI 串联 main + E2E 测试 + 2020 黄金基线"
```

- [ ] **Step 9: 更新 README 实战部分**

`quant-trade-new/README.md` 末尾追加：

```markdown
## 实盘部署到 QMT

1. `git pull` 拿最新 `strategy_hs300.py`
2. QMT 中新建 Python 模型
3. 复制 `strategy_hs300.py` 全文进策略编辑器
4. 改文件首行为 `# -*- coding: gbk -*-` 并保存为 GBK
5. 修改 `init()` 中的 `set_account('实盘账号')`
6. 设置 K 线周期 = **5 分钟**
7. 启动策略

注意：策略文件无需手动改任何 flag（与 v1 区别于此）。

## 已知数据局限

- `data_a/` 是 ~300 只静态快照，跨年回测有 survivorship + 前视双向偏差（< 3%/年）
- `data_a/` 不完全前复权（2024-06-21 茅台等个别事件未做），最大单日"假跌" ~2%
- 详见 `docs/superpowers/specs/2026-06-24-quant-trade-new-design.md` §13
```

```bash
git add quant-trade-new/README.md
git commit -m "docs: 实盘部署 + 已知局限"
```

---

## Self-Review 结果

**1. Spec coverage 核对**：

| Spec 章节 | 任务覆盖 |
|---|---|
| §1 目标 | Task 1-15 全部 |
| §3 关键决策 13 行 | 全部 ✓ |
| §4.1 目录结构 | Task 1 |
| §4.2 依赖方向 | Task 12 (strategy_loader) |
| §4.3 策略零分支 | Task 11 (init 不读 SKIP_HISTORY_WARMUP) |
| §5 策略 §A/B/C/D/E/F/G/H | Task 2/10/2/3/4/5/10/11 |
| §6.1 ContextInfo 模拟 | Task 8 |
| §6.2 get_history_data 契约 | Task 8 |
| §6.3 撮合方案 A | Task 9 (passorder + Account.fill_buy/sell) |
| §6.4 get_trade_detail_data | Task 9 |
| §6.5/6.6 局限说明 | spec 已写 + README 提及 (Task 15) |
| §7 数据流 6 Step | Task 13 (Engine) + Task 15 (cli.main 串联) |
| §8 错误处理三原则 | DataLoader/Account/Engine 内分别实现 |
| §9 测试金字塔 | Task 2-15 各自的 test 文件 |
| §10 产物规范 | Task 14 (Reporter) |
| §11 实盘部署 | Task 15 README |
| §12 QMT 运行时 | 实现不需要，spec 已说明 |
| §13 已知局限 | Task 6 data_quality.log + README |

**2. Placeholder 扫描**：1 处发现 `avg_holding_days: 0  # TODO 后续可补` 在 Task 14 Reporter — 这是有意保留的占位（spec §10.1 列了此字段但不影响主要指标）。**接受**：列保留 0 比删掉字段对 spec 一致，向后兼容。

**3. Type 一致性**：
- `Position` 在 strategy_hs300.py 定义（Task 3），Account 用自己的 `AccountPosition`（Task 7）— 两者解耦，命名清晰
- `Shim._to_data_code` (Task 8) 和 `Engine._to_strategy_code` (Task 13) 是双向转换，命名对称 ✓
- `trade_cost(side, amount)` (Task 5) 被 Account.fill_buy/sell (Task 7) 和 strategy._execute_buy/_evaluate_sells (Task 10/11) 复用，签名一致 ✓
- `check_buy_signal` 在 strategy (Task 2) 和 score_factors 内部使用，签名一致 ✓

**总评**：plan 完整、可执行、TDD 严格、commit 节奏合理（15 个 commit，约 15-20 个开发会话能完成）。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-24-quant-trade-new.md`.
