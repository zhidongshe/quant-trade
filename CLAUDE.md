# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a quantitative trading strategy for CSI 300 (沪深300) components, designed to run on the 迅投QMT (XtQuant) trading platform. The strategy uses a multi-factor trend-following approach with strict risk controls.

## Repository Structure

There are **two versions** of the strategy:

1. **Modular version** (`strategy/`)
   - `strategy/hs300_trend_strategy.py` — Main strategy entry point (`init` / `handlebar`)
   - `strategy/indicators.py` — Technical indicators: `sma`, `macd`, `check_buy_signal`
   - `strategy/portfolio.py` — `Position` dataclass, stop-loss/take-profit logic, position sizing
   - Used for local development, testing, and as the readable reference implementation

2. **Single-file production version** (`hs300_trend_strategy_single_file.py`)
   - This is the actual file copied into QMT for backtesting and live trading
   - Contains additional features not in the modular version:
     - `score_stock()` — weighted scoring for candidate ranking
     - `REBALANCE_INTERVAL = 10` — periodic rebalancing (every ~2 weeks)
     - `_sync_positions()` — syncs `ContextInfo.positions` with QMT actual holdings
     - File logging with timestamps to `c:\量化日志_{timestamp}.log`
     - `_normalize_stock_code()` — handles QMT code format differences
     - `_fetch_market()` / `_series_from_market()` — wrappers for `get_market_data_ex`
   - When editing strategy logic, update **both** versions or decide which is the source of truth

## Running Tests

```bash
cd /Users/shezhidong/Documents/代码库/quant-trade
pytest tests/ -v
```

Run a single test file:
```bash
pytest tests/test_indicators.py -v
pytest tests/test_portfolio.py -v
pytest tests/test_handlebar_integration.py -v
```

Run a single test:
```bash
pytest tests/test_portfolio.py::test_hard_stop_loss_triggered -v
```

The integration tests (`test_handlebar_integration.py`) import from the **single-file version** and include a `MockContextInfo` class to simulate QMT behavior.

## Key Architecture Decisions

### QMT `set_universe` Data Gotcha

QMT's `get_history_data` only returns data for stocks in the current universe. The strategy must merge held stocks with the CSI 300 universe before calling `set_universe`, otherwise sold stocks will have no price data for stop-loss checks. The single-file version calls `set_universe` only when there are "missing" held stocks, to avoid a QMT bug where daily `set_universe` causes empty data on the next bar.

### Stop-Loss / Exit Logic

Three independent exit conditions are checked in order:
1. **Hard stop**: price ≤ buy_price × (1 − 3%)
2. **Trend break**: price ≤ 20-day MA
3. **Trailing stop**: after profit exceeds 5%, sell if price falls 5% from the highest price reached

When history data has fewer than 20 bars, only the hard stop is checked.

### Entry Logic (4-Factor Confirmation)

`check_buy_signal(prices, volumes)` requires ALL of:
- Close > MA60
- MA5 > MA20
- MACD histogram > 0
- Today's volume > 20-day average volume

The single-file version adds `score_stock()` which returns a weighted score for ranking candidates when rebalancing.

### Position Sizing

`calculate_buy_amount(total_capital, available_cash, max_positions=5)` caps each position at 20% of total capital, rounds down to the nearest 100 RMB (A-share lot size), and never exceeds available cash. Actual share volume is then computed as `int(buy_amount / price / 100) * 100`.

## QMT Deployment Notes

When loading into QMT:
- Change file encoding to **GBK** and add `# -*- coding: gbk -*-` as the first line
- Update `ContextInfo.set_account('你的资金账号')` with the real account number
- Update `sys.path.insert` to the actual path on the QMT machine
- The strategy depends on QMT runtime functions: `passorder`, `get_trade_detail_data`, `get_history_data`, `get_market_data_ex`, `timetag_to_datetime`, `get_sector`, `get_instrumentdetail`

## Dependencies

- `numpy` — required for indicator calculations
- `pytest` — required for running tests
- No `requirements.txt` or `pyproject.toml` is present; install dependencies manually
