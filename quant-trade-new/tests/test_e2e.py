"""End-to-end tests for the full backtest pipeline.

Run with:  pytest tests/test_e2e.py -v -m e2e -s
These tests are slow; skip during unit-test runs:
  pytest tests/ --ignore=tests/test_e2e.py
"""
import json
import pytest
import csv
from pathlib import Path
from backtest.cli import main


pytestmark = pytest.mark.e2e


def test_e2e_smoke_30days(tmp_path, monkeypatch):
    """30 天冒烟跑 — 仅验证 5 产物文件存在，跑时 <30s"""
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
    assert (runs[0] / 'run_config.json').exists()


def test_e2e_2020_golden_baseline(tmp_path, monkeypatch):
    """2020 全年 → 锁定 5 项指标作为 golden 基线，后续 ±0.1pp 容差对比。
    首次跑时自动写 fixture，并 pytest.skip。"""
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
    """跨年：metrics.csv 应有 3 行（2020 / 2021 / total）"""
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
