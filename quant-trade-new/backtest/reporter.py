"""年度行 + 累计行 metrics，trades/snapshots/equity/run_config 输出。"""
import csv
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


@dataclass
class Period:
    label: str
    start: str  # YYYYMMDD
    end: str    # YYYYMMDD


class Reporter:
    def __init__(self, account: 'Account', config: 'RunConfig', run_dir: Path):
        self.account = account
        self.config = config
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def compute_periods(self) -> list:
        """自然年切分 + 累计 1 行。"""
        if not self.account.snapshots:
            return []

        cfg_start = self.config.start_date
        cfg_end = self.config.end_date

        years = sorted({int(s.date[:4]) for s in self.account.snapshots})
        periods = []
        for y in years:
            y_start = max(date(y, 1, 1), cfg_start)
            y_end = min(date(y, 12, 31), cfg_end)
            label = str(y)
            if y_start != date(y, 1, 1):
                label += f"({y_start.strftime('%m-%d')}起)"
            if y_end != date(y, 12, 31):
                label += f"({y_end.strftime('%m-%d')}止)"
            periods.append(Period(
                label=label,
                start=y_start.strftime('%Y%m%d'),
                end=y_end.strftime('%Y%m%d'),
            ))
        periods.append(Period(
            label='total',
            start=cfg_start.strftime('%Y%m%d'),
            end=cfg_end.strftime('%Y%m%d'),
        ))
        return periods

    def compute_metrics(self, period: Period,
                        start_equity_override: float | None = None) -> dict:
        """14 列指标字典。

        start_equity_override: 当提供时，用于 total_return / annual_return 计算的起始
        净值（用于跨年链式收益率计算，确保各年复合 = 总收益）。不影响 max_drawdown /
        sharpe 的计算基础（这两者仍以 period 内第一个快照为锚）。

        注意：当 start_equity_override 不为 None 时：
        - `start_equity` 字段 = override 值（前年末权益），用于年度连贯的复合公式
        - 但 `max_drawdown` 和 `sharpe` 仍以 period 内第一个 snapshot 为锚点
          （回撤定义为"period 内"最大点对点回撤）
        """
        in_period = [s for s in self.account.snapshots
                     if period.start <= s.date <= period.end]

        if len(in_period) < 2:
            return {
                'period': period.label,
                'start_date': period.start,
                'end_date': period.end,
                'start_equity': 0,
                'end_equity': 0,
                'total_return': 0,
                'annual_return': 0,
                'max_drawdown': 0,
                'sharpe': 0,
                'n_trades': 0,
                'n_rejected': 0,
                'win_rate': 0,
                'avg_holding_days': 0,
                'total_cost': 0,
            }

        equities = [s.total_equity for s in in_period]
        # start_equity_override 允许调用方传入上一期末净值，使各年 total_return
        # 首尾相衔，保证 (1+y1)*(1+y2)-1 == total['total_return']
        start_eq = start_equity_override if start_equity_override is not None else equities[0]
        end_eq = equities[-1]
        total_ret = end_eq / start_eq - 1
        n_days = len(in_period)
        annual = (1 + total_ret) ** (252 / max(n_days, 1)) - 1

        # 最大回撤
        peak = equities[0]
        max_dd = 0.0
        for v in equities:
            if v > peak:
                peak = v
            dd = (v - peak) / peak if peak > 0 else 0.0
            if dd < max_dd:
                max_dd = dd

        # Sharpe（日度）
        rets = [equities[i] / equities[i - 1] - 1 for i in range(1, len(equities))]
        if len(rets) > 1:
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
        win_rate = len(wins) / len(sell_trades) if sell_trades else 0.0
        total_cost = sum(t.cost for t in filled)
        avg_hold = self._compute_avg_holding_days(filled)

        return {
            'period': period.label,
            'start_date': period.start,
            'end_date': period.end,
            'start_equity': round(start_eq, 2),
            'end_equity': round(end_eq, 2),
            'total_return': round(total_ret, 6),
            'annual_return': round(annual, 6),
            'max_drawdown': round(max_dd, 6),
            'sharpe': round(sharpe, 4),
            'n_trades': len(filled),
            'n_rejected': len(rejected),
            'win_rate': round(win_rate, 4),
            'avg_holding_days': round(avg_hold, 2),
            'total_cost': round(total_cost, 2),
        }

    @staticmethod
    def _compute_avg_holding_days(filled_trades) -> float:
        """FIFO 配对 buy/sell，返回平均持有天数。"""
        open_lots: dict = {}  # code -> [(buy_date_str, volume)]
        holding_days: list = []
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

    # ------------------------------------------------------------------
    # write_all and helpers
    # ------------------------------------------------------------------

    def write_all(self) -> None:
        """写全部 5 类产物。"""
        self._write_metrics()
        self._write_trades()
        self._write_snapshots()
        self._write_equity_png()
        self._write_run_config()

    def _write_metrics(self):
        periods = self.compute_periods()
        if not periods:
            return

        # 按年链式传递 prev_end_equity，确保 (1+y1)*(1+y2)-1 == total['total_return']。
        # 'total' 行始终用全程第一个快照作为起点（不传 override）。
        rows = []
        prev_end_equity: float | None = None
        for p in periods:
            if p.label == 'total':
                row = self.compute_metrics(p)
            else:
                row = self.compute_metrics(p, start_equity_override=prev_end_equity)
                prev_end_equity = row['end_equity']
            rows.append(row)

        path = self.run_dir / 'metrics.csv'
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    def _write_trades(self):
        path = self.run_dir / 'trades.csv'
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['trade_id', 'date', 'code', 'name', 'side', 'volume',
                        'price', 'amount', 'cost', 'reason', 'status', 'realized_pnl'])
            for t in self.account.trades:
                w.writerow([t.trade_id, t.date, t.code, t.name, t.side,
                            t.volume, t.price, t.amount, t.cost,
                            t.reason, t.status, t.realized_pnl])

    def _write_snapshots(self):
        path = self.run_dir / 'snapshots.csv'
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['date', 'cash', 'position_value', 'total_equity',
                        'n_positions', 'daily_return'])
            for s in self.account.snapshots:
                w.writerow([s.date, s.cash, s.position_value, s.total_equity,
                            s.n_positions, s.daily_return])

    def _write_equity_png(self):
        if not self.account.snapshots:
            return
        dates = [datetime.strptime(s.date, '%Y%m%d') for s in self.account.snapshots]
        equities = [s.total_equity for s in self.account.snapshots]

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(dates, equities, linewidth=1.5)

        # 跨年纵向虚线
        years = sorted({d.year for d in dates})
        for y in years[1:]:
            ax.axvline(datetime(y, 1, 1), color='gray', linestyle='--', alpha=0.4)

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
        # date → ISO string
        if isinstance(d.get('start_date'), date):
            d['start_date'] = d['start_date'].isoformat()
        if isinstance(d.get('end_date'), date):
            d['end_date'] = d['end_date'].isoformat()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
