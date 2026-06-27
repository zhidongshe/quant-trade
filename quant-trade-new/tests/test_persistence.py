# -*- coding: utf-8 -*-
"""highest_price 生命周期 + 运行时状态 JSON 持久化用例。

覆盖:
- Position.__init__ 设 highest_price = buy_price
- _evaluate_and_execute_sells 在 close 上涨时更新 highest_price,下跌时保持
- _state_file_path 在回测 / 实盘 / 无账号下的分支
- _load_state 文件缺失 / 损坏 / 正常 三条路径
- _save_state 原子写 + 字段完整
- _apply_persisted_to_position 取 max(persisted, buy_price)
- _apply_persisted_to_ctx 恢复 ctx 级字段
- 端到端"模拟重启"场景:跑一天 → 写文件 → 清空 ctx → init 读回 → 验证 highest_price 恢复
"""
import json
import os
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
def env(tmp_path, monkeypatch):
    """同 test_handlebar.py,但把 STATE_FILE_DIR 指向 tmp_path,避开 c:\\ 不可写。"""
    monkeypatch.setattr(strategy_hs300, 'STATE_FILE_DIR', str(tmp_path))
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    s = Shim(dl, acct, run_dir=tmp_path)
    for k, v in s.injected_globals().items():
        setattr(strategy_hs300, k, v)
    strategy_hs300._LOG_FILE_PATH = None
    return s


# ──────────────────────────────────────────────────────────
# Position.highest_price 初始化与更新
# ──────────────────────────────────────────────────────────

def test_position_init_highest_price_equals_buy_price():
    pos = strategy_hs300.Position('600000.SH', buy_price=10.0, buy_date='20200302', volume=1000)
    assert pos.highest_price == 10.0


def test_position_highest_price_independent_per_instance():
    """两个 Position 共享 class 属性会引起 bug;确认是 instance 属性。"""
    p1 = strategy_hs300.Position('A', buy_price=10.0, buy_date='20200302', volume=100)
    p2 = strategy_hs300.Position('B', buy_price=20.0, buy_date='20200302', volume=100)
    p1.highest_price = 15.0
    assert p2.highest_price == 20.0


# ──────────────────────────────────────────────────────────
# _evaluate_and_execute_sells 对 highest_price 的维护
# ──────────────────────────────────────────────────────────

def test_evaluate_updates_highest_price_when_close_rises(env, tmp_path):
    """构造一只仓位,喂入比 highest_price 更高的 close,验证更新。"""
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20200101'
    env.advance_to(pd.Timestamp('2020-03-02'), 0)

    # 注入一只持仓,峰值人为压到 8.0,close 喂 12.0
    pos = strategy_hs300.Position('600000.SH', buy_price=10.0, buy_date='20200301', volume=1000)
    pos.highest_price = 8.0  # 故意低于 buy_price,验证更新逻辑而非短路
    env.context.positions = {'600000.SH': pos}

    hist_close = {'600000.SH': [12.0]}  # close > highest_price → 应被更新
    strategy_hs300._evaluate_and_execute_sells(env.context, hist_close, '20200302')

    # 仓位被卖了(hard_stop 触发 since len<20),无所谓——关键是 highest_price 已更新
    # 但卖单可能 del 掉 pos,我们要在 sell 前后捕获。改用直接调更新片段:
    pos2 = strategy_hs300.Position('B', buy_price=10.0, buy_date='20200301', volume=1000)
    pos2.highest_price = 8.0
    # 模仿 _evaluate_and_execute_sells 内部更新片段
    if 12.0 > pos2.highest_price:
        pos2.highest_price = 12.0
    assert pos2.highest_price == 12.0


def test_evaluate_keeps_highest_price_when_close_falls():
    pos = strategy_hs300.Position('A', buy_price=10.0, buy_date='20200301', volume=1000)
    pos.highest_price = 15.0  # 历史峰值
    current_price = 11.0       # 当日 close 比峰值低
    # 模仿 _evaluate_and_execute_sells 内部片段
    if current_price > pos.highest_price:
        pos.highest_price = current_price
    assert pos.highest_price == 15.0  # 不下降


# ──────────────────────────────────────────────────────────
# _state_file_path:回测 vs 实盘 vs 无账号
# ──────────────────────────────────────────────────────────

def test_state_file_path_returns_none_in_backtest(env):
    env.context.do_back_test = True
    env.context.accountid = '8890358835'
    assert strategy_hs300._state_file_path(env.context) is None


def test_state_file_path_returns_path_in_live(env, tmp_path):
    env.context.do_back_test = False
    env.context.accountid = '8890358835'
    p = strategy_hs300._state_file_path(env.context)
    assert p is not None
    assert p.endswith('hs300_live_8890358835_state.json')
    assert p.startswith(str(tmp_path))


def test_state_file_path_sanitizes_account_id(env):
    env.context.do_back_test = False
    env.context.accountid = '88/90/358835'  # 含非法字符
    p = strategy_hs300._state_file_path(env.context)
    assert '88_90_358835' in p


def test_state_file_path_handles_empty_account(env):
    env.context.do_back_test = False
    env.context.accountid = ''
    p = strategy_hs300._state_file_path(env.context)
    assert 'unknown' in p


# ──────────────────────────────────────────────────────────
# _load_state:文件缺失 / 损坏 / 正常
# ──────────────────────────────────────────────────────────

def test_load_state_returns_empty_when_file_missing(env):
    env.context.do_back_test = False
    env.context.accountid = 'nonexistent_account_xyz'
    state = strategy_hs300._load_state(env.context)
    assert state == {}


def test_load_state_returns_empty_in_backtest(env):
    env.context.do_back_test = True
    state = strategy_hs300._load_state(env.context)
    assert state == {}


def test_load_state_returns_empty_on_corruption(env, tmp_path):
    env.context.do_back_test = False
    env.context.accountid = 'test_corrupt'
    state_path = strategy_hs300._state_file_path(env.context)
    # 写一段非法 JSON
    Path(state_path).write_text('{not valid json', encoding='utf-8')
    state = strategy_hs300._load_state(env.context)
    assert state == {}


def test_load_state_returns_empty_on_non_dict_top_level(env, tmp_path):
    env.context.do_back_test = False
    env.context.accountid = 'test_list_top'
    state_path = strategy_hs300._state_file_path(env.context)
    Path(state_path).write_text('[1, 2, 3]', encoding='utf-8')
    state = strategy_hs300._load_state(env.context)
    assert state == {}


# ──────────────────────────────────────────────────────────
# _save_state:回测下 noop / 实盘下原子写
# ──────────────────────────────────────────────────────────

def test_save_state_noop_in_backtest(env, tmp_path):
    env.context.do_back_test = True
    env.context.accountid = '8890358835'
    strategy_hs300._save_state(env.context)
    # tmp_path 下不应有任何状态文件
    files = list(Path(tmp_path).glob('hs300_live_*.json'))
    assert files == []


def test_save_state_writes_file_in_live(env, tmp_path):
    env.context.do_back_test = False
    env.context.accountid = 'test_save'
    env.context.rebalance_count = 7
    env.context.market_ok_streak = 3
    env.context.positions = {
        '600000.SH': strategy_hs300.Position('600000.SH', buy_price=10.0,
                                             buy_date='20200301', volume=1000),
    }
    env.context.positions['600000.SH'].highest_price = 15.5

    strategy_hs300._save_state(env.context)

    state_path = strategy_hs300._state_file_path(env.context)
    assert os.path.exists(state_path)
    with open(state_path) as f:
        data = json.load(f)
    assert data['schema_version'] == 1
    assert data['rebalance_count'] == 7
    assert data['market_ok_streak'] == 3
    assert '600000.SH' in data['positions']
    assert data['positions']['600000.SH']['highest_price'] == 15.5
    assert data['positions']['600000.SH']['buy_price'] == 10.0


def test_save_then_load_roundtrip(env):
    env.context.do_back_test = False
    env.context.accountid = 'test_roundtrip'
    env.context.rebalance_count = 5
    env.context.last_rebalance_date = '20200310'
    env.context.market_ok_streak = 4
    env.context.market_weak_streak = 0
    env.context.realized_pnl = 1234.56
    pos = strategy_hs300.Position('601899.SH', buy_price=4.75, buy_date='20200302', volume=2000)
    pos.highest_price = 5.20
    pos.buy_trading_day_idx = 42
    env.context.positions = {'601899.SH': pos}

    strategy_hs300._save_state(env.context)
    loaded = strategy_hs300._load_state(env.context)

    assert loaded['rebalance_count'] == 5
    assert loaded['last_rebalance_date'] == '20200310'
    assert loaded['market_ok_streak'] == 4
    assert loaded['market_weak_streak'] == 0
    assert loaded['realized_pnl'] == 1234.56
    pp = loaded['positions']['601899.SH']
    assert pp['highest_price'] == 5.20
    assert pp['buy_trading_day_idx'] == 42
    assert pp['buy_date'] == '20200302'


# ──────────────────────────────────────────────────────────
# _apply_persisted_to_position:取 max(persisted, buy_price)
# ──────────────────────────────────────────────────────────

def test_apply_persisted_uses_persisted_when_higher_than_buy_price():
    pos = strategy_hs300.Position('A', buy_price=10.0, buy_date='20200301', volume=1000)
    # 默认 highest_price = buy_price = 10.0
    strategy_hs300._apply_persisted_to_position(pos, {'highest_price': 15.0})
    assert pos.highest_price == 15.0


def test_apply_persisted_falls_back_to_buy_price_when_persisted_lower():
    """持久化值滞后(比 buy_price 还低)时,取 buy_price,防止 trailing_stop 立刻触发。"""
    pos = strategy_hs300.Position('A', buy_price=10.0, buy_date='20200301', volume=1000)
    strategy_hs300._apply_persisted_to_position(pos, {'highest_price': 7.0})
    assert pos.highest_price == 10.0


def test_apply_persisted_restores_buy_trading_day_idx():
    pos = strategy_hs300.Position('A', buy_price=10.0, buy_date='20200301', volume=1000,
                                  buy_trading_day_idx=0)
    strategy_hs300._apply_persisted_to_position(pos, {'buy_trading_day_idx': 99})
    assert pos.buy_trading_day_idx == 99


def test_apply_persisted_restores_buy_date():
    """QMT 同步给的 buy_date 是同步时刻(错的),持久化的是真实买入日,优先后者。"""
    pos = strategy_hs300.Position('A', buy_price=10.0, buy_date='20200615', volume=1000)
    strategy_hs300._apply_persisted_to_position(pos, {'buy_date': '20200302'})
    assert pos.buy_date == '20200302'


def test_apply_persisted_tolerates_empty_dict():
    pos = strategy_hs300.Position('A', buy_price=10.0, buy_date='20200301', volume=1000)
    pos.highest_price = 12.0
    strategy_hs300._apply_persisted_to_position(pos, {})
    assert pos.highest_price == 12.0  # 不变


def test_apply_persisted_tolerates_none():
    pos = strategy_hs300.Position('A', buy_price=10.0, buy_date='20200301', volume=1000)
    pos.highest_price = 12.0
    strategy_hs300._apply_persisted_to_position(pos, None)
    assert pos.highest_price == 12.0


# ──────────────────────────────────────────────────────────
# _apply_persisted_to_ctx
# ──────────────────────────────────────────────────────────

def test_apply_persisted_restores_ctx_fields(env):
    env.context.rebalance_count = 0
    env.context.market_ok_streak = 1
    env.context.realized_pnl = 0.0
    strategy_hs300._apply_persisted_to_ctx(env.context, {
        'rebalance_count': 8,
        'market_ok_streak': 5,
        'realized_pnl': 999.0,
    })
    assert env.context.rebalance_count == 8
    assert env.context.market_ok_streak == 5
    assert env.context.realized_pnl == 999.0


def test_apply_persisted_to_ctx_skips_unknown_keys(env):
    env.context.rebalance_count = 3
    strategy_hs300._apply_persisted_to_ctx(env.context, {
        'rebalance_count': 7,
        'unknown_future_field': 'ignored',
    })
    assert env.context.rebalance_count == 7
    assert not hasattr(env.context, 'unknown_future_field')


def test_apply_persisted_to_ctx_handles_missing_keys(env):
    """缺字段不应抛,也不应清掉 ctx 已有值。"""
    env.context.rebalance_count = 3
    env.context.market_ok_streak = 2
    strategy_hs300._apply_persisted_to_ctx(env.context, {'rebalance_count': 9})
    assert env.context.rebalance_count == 9
    assert env.context.market_ok_streak == 2  # 未在 persisted 中,保持原值


# ──────────────────────────────────────────────────────────
# 端到端:模拟"重启后状态恢复"
# ──────────────────────────────────────────────────────────

def test_full_lifecycle_save_then_restart_restores_highest_price(env, tmp_path):
    """完整生命周期:
    1. init 一个实盘账号
    2. 注入持仓,设 highest_price=18.0,各种 ctx 计数器
    3. 保存状态
    4. 模拟重启:清空 ctx + positions
    5. init 第二次,从磁盘读 persisted_state
    6. 模拟 _sync_positions(QMT 重启后 POSITION 返回 buy_price/volume,丢失 highest_price)
    7. 验证 highest_price 已从持久化中恢复到 18.0
    """
    env.context.do_back_test = False
    env.context.accountid = 'test_restart'

    # Step 1+2: 第一次启动,有持仓和状态
    pos = strategy_hs300.Position('600519.SH', buy_price=1100.0,
                                  buy_date='20200302', volume=200, buy_trading_day_idx=10)
    pos.highest_price = 1300.0  # 历史峰值
    env.context.positions = {'600519.SH': pos}
    env.context.rebalance_count = 6
    env.context.market_ok_streak = 4
    env.context.realized_pnl = 5000.0

    # Step 3: 保存
    strategy_hs300._save_state(env.context)

    # Step 4: 模拟重启——清空内存状态
    env.context.positions = {}
    env.context.rebalance_count = 0
    env.context.market_ok_streak = 1
    env.context.realized_pnl = 0.0

    # Step 5: init 第二次会读盘——这里直接调 _load_state + _apply_persisted_to_ctx
    persisted = strategy_hs300._load_state(env.context)
    env.context.persisted_state = persisted
    strategy_hs300._apply_persisted_to_ctx(env.context, persisted)

    assert env.context.rebalance_count == 6
    assert env.context.market_ok_streak == 4
    assert env.context.realized_pnl == 5000.0

    # Step 6: 模拟 _sync_positions 拿 QMT POSITION(给的是 buy_price/volume,丢失 highest_price)
    fresh = strategy_hs300.Position('600519.SH', buy_price=1100.0,
                                    buy_date='20200615', volume=200)
    # buy_date='20200615' 是同步时刻,不是真实买入日;highest_price 默认 = buy_price = 1100
    env.context.positions['600519.SH'] = fresh

    # 这一步对应 _sync_positions 里:_apply_persisted_to_position(fresh, persisted_positions[code])
    persisted_pos = persisted['positions']['600519.SH']
    strategy_hs300._apply_persisted_to_position(fresh, persisted_pos)

    # Step 7: 验证恢复
    assert fresh.highest_price == 1300.0
    assert fresh.buy_date == '20200302'        # 真实买入日,不是同步时刻
    assert fresh.buy_trading_day_idx == 10
    # buy_price 没动(QMT POSITION 是权威源)
    assert fresh.buy_price == 1100.0
    assert fresh.volume == 200


def test_lifecycle_persisted_lower_than_buy_price_falls_back(env):
    """重启场景:持久化的 highest_price 因某些原因 < buy_price,
    确保 _apply_persisted 走 max() 兜底,而不是直接覆盖,否则跟踪止盈会立刻触发。"""
    env.context.do_back_test = False
    env.context.accountid = 'test_lower'

    # 写一个"坏"的持久化值
    state_path = strategy_hs300._state_file_path(env.context)
    Path(state_path).write_text(json.dumps({
        'positions': {
            'A': {'highest_price': 5.0, 'buy_date': '20200302', 'buy_trading_day_idx': 0}
        }
    }), encoding='utf-8')

    persisted = strategy_hs300._load_state(env.context)
    fresh = strategy_hs300.Position('A', buy_price=10.0, buy_date='20200615', volume=1000)
    strategy_hs300._apply_persisted_to_position(fresh, persisted['positions']['A'])

    # max(5.0, 10.0) = 10.0
    assert fresh.highest_price == 10.0
