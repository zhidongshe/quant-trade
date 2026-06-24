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
        ctx = self.shim.context
        ctx.strategy_start_date = self.config.start_date.strftime('%Y%m%d')
        ctx.log_dir = str(self.config.results_dir)
        ctx.capital = self.config.initial_capital
        # 重设 universe 含指数（策略形态）
        all_codes = [c for c in self.data_loader.universe_codes()
                     if c != 'SH.000300']
        strategy_codes = [self._to_strategy_code(c) for c in all_codes]
        ctx.set_universe(strategy_codes + ['000300.SH'])

        # 3. 主循环
        cal = self.data_loader.trading_calendar()
        in_range = cal[(cal >= pd.Timestamp(self.config.start_date)) &
                       (cal <= pd.Timestamp(self.config.end_date))]

        for i, day in enumerate(in_range):
            self.shim.advance_to(day, i)
            self.account.advance_day(day.strftime('%Y%m%d'))
            self.strategy.handlebar(self.shim.context)

            # EOD snapshot — 用策略形态作为 code key
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
