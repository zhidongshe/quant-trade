"""QMT API Shim：ContextInfo + 查询方法模拟。passorder/成交在 Task 9 实现。"""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import pandas as pd


class ContextInfo:
    """模拟 QMT 的 ContextInfo 对象。所有方法行为与 QMT 文档对齐。"""

    def __init__(self, shim: "Shim"):
        self._shim = shim
        self.barpos: int = -1
        self.last_processed_barpos: int = -1
        self.capital: float = 0.0
        self.accountid: str = ''
        self.positions: dict = {}
        self.strategy_start_date: str = ''
        self.log_dir: str = ''
        self._active_universe: list = []
        self._bar_ts_cache: dict = {}
        self._current_day: pd.Timestamp | None = None
        self.do_back_test: bool = True  # 本地 Shim 回测 == QMT 回测语义

    # ------------------------------------------------------------------
    # 配置方法
    # ------------------------------------------------------------------
    def set_account(self, account_id: str) -> None:
        """no-op：回测中账号由 Account 对象管理，这里仅存储 id。"""
        self.accountid = account_id

    def set_universe(self, codes: list) -> None:
        """记录策略当前 universe（策略侧代码，如 '600000.SH'）。"""
        self._active_universe = list(codes)

    # ------------------------------------------------------------------
    # 查询方法
    # ------------------------------------------------------------------
    def get_sector(self, sector_code: str) -> list:
        """返回 HS300 全集（策略侧代码形态）。

        策略调用 get_sector('000300.SH') 期望得到 '600000.SH' 格式。
        DataLoader.universe_codes() 返回 'SH.600000' 格式，所以需要转换。
        """
        if sector_code in ('000300.SH', 'SH.000300'):
            return [
                self._shim._to_strategy_code(c)
                for c in self._shim.data_loader.universe_codes()
                if c not in ('SH.000300', '000300.SH')
            ]
        return []

    def get_instrumentdetail(self, code: str) -> dict:
        """返回含 m_strInstrumentName / UpStopPrice / DownStopPrice 的 dict。

        UpStopPrice = 前一日 close × 1.10（普通股）或 × 1.20（创业板/科创板）。
        code 可接受数据形态（SH.600000）或策略形态（600000.SH）。
        """
        data_code = self._shim._to_data_code(code)
        df = self._shim.data_loader.daily_df.get(data_code)
        if df is None or self._current_day is None or df.empty:
            return {}

        name = str(df['name'].iloc[0]) if 'name' in df.columns else ''

        # 前一日 close
        before = df.loc[df.index < self._current_day]
        if len(before) == 0:
            return {
                'm_strInstrumentName': name,
                'UpStopPrice': 0.0,
                'DownStopPrice': 0.0,
            }

        prev_close = float(before['close'].iloc[-1])
        # 创业板 SZ.300xxx 或科创板 SH.688xxx 涨跌停 ±20%
        if data_code.startswith('SZ.300') or data_code.startswith('SH.688'):
            multiplier = 1.20
        else:
            multiplier = 1.10

        return {
            'm_strInstrumentName': name,
            'UpStopPrice': round(prev_close * multiplier, 2),
            'DownStopPrice': round(prev_close * (2 - multiplier), 2),
        }

    def get_history_data(
        self,
        N: int,
        period: str = '1d',
        field: str = 'close',
        dividend_type: str = 'front',
        skip_paused: bool = True,
    ) -> dict:
        """返回 {code: [N 个值]} 其中最后一根 = 当日（含）。

        - 只支持 period='1d'；其他 raise NotImplementedError。
        - 数据短于 N 天时返回短列表，不报错（QMT 行为）。
        - 结果 key 全部使用策略形态（如 '600000.SH'、'000300.SH'）
          与 set_universe 输入一致，确保 `if '000300.SH' in hist_prices` 能命中。
        """
        if period != '1d':
            raise NotImplementedError(
                f"Shim 仅支持 period='1d'，收到 {period!r}"
            )
        if self._current_day is None:
            return {}

        # 收集需要返回的代码集合（key 形态全部用策略形态）
        # 规则：active_universe 中的代码保留其形态；持仓同理；指数用策略形态 key
        code_map: dict[str, str] = {}  # result_key -> data_code

        # active_universe 中的代码（策略侧形态，如 '600000.SH'）
        for c in self._active_universe:
            data_c = self._shim._to_data_code(c)
            code_map[c] = data_c  # key 保持策略传入的形态

        # 持仓（可能是策略形态，也可能是数据形态）
        for c in self.positions.keys():
            if c not in code_map:
                data_c = self._shim._to_data_code(c)
                code_map[c] = data_c

        # 指数：以策略形态 key 包含（策略用 '000300.SH' 来取大盘序列）
        code_map['000300.SH'] = 'SH.000300'  # 策略形态 key → data 形态文件名

        result: dict[str, list] = {}
        for result_key, data_code in code_map.items():
            df = self._shim.data_loader.daily_df.get(data_code)
            if df is None or df.empty:
                continue
            if field not in df.columns:
                continue
            sliced = df.loc[df.index <= self._current_day, field]
            if len(sliced) == 0:
                continue
            result[result_key] = sliced.iloc[-N:].tolist()

        return result

    def get_bar_timetag(self, barpos: int) -> int:
        """返回 barpos 对应的毫秒时间戳（由 advance_to 缓存）。"""
        return self._bar_ts_cache.get(barpos, 0)


class Shim:
    """连接 DataLoader / Account 与 ContextInfo 的胶水层。

    提供 advance_to、代码形态转换、以及 Task 9 需要的辅助查询。
    """

    def __init__(self, data_loader, account, run_dir: Path):
        self.data_loader = data_loader
        self.account = account
        self.run_dir = Path(run_dir)
        self.context = ContextInfo(self)

    # ------------------------------------------------------------------
    # 时间推进
    # ------------------------------------------------------------------
    def advance_to(self, day: pd.Timestamp, barpos: int) -> None:
        """推进当前交易日并更新 barpos 缓存。

        使用 Python stdlib datetime 创建本地午夜时间戳，保证与
        timetag_to_datetime 里的 datetime.fromtimestamp() 时区一致。
        pd.Timestamp.timestamp() 把 naive 当 UTC，而 fromtimestamp() 用本地时区，
        两者在非 UTC 机器上会偏移；此处统一用 Python datetime（本地时区）。
        """
        from datetime import datetime as _dt
        self.context.barpos = barpos
        self.context._current_day = day
        # 本地午夜 → POSIX → fromtimestamp 解码回本地午夜
        local_midnight = _dt(day.year, day.month, day.day, 0, 0, 0)
        self.context._bar_ts_cache[barpos] = int(local_midnight.timestamp() * 1000)

    # ------------------------------------------------------------------
    # 代码形态转换
    # ------------------------------------------------------------------
    @staticmethod
    def _to_data_code(code: str) -> str:
        """策略形态 → 数据形态。

        '600000.SH' → 'SH.600000'
        'SH.600000' → 'SH.600000'（已是数据形态，直接返回）
        """
        if '.' not in code:
            return code
        left, right = code.split('.', 1)
        # 数据形态：左侧是交易所标识（2 位字母）；策略形态：左侧是数字代码
        if left.isdigit() or (len(left) > 2 and left[0].isdigit()):
            # 策略形态：'600000.SH' → 'SH.600000'
            return f"{right}.{left}"
        # 已经是数据形态 'SH.600000'
        return code

    @staticmethod
    def _to_strategy_code(data_code: str) -> str:
        """数据形态 → 策略形态。

        'SH.600000' → '600000.SH'
        '600000.SH' → '600000.SH'（已是策略形态）
        """
        if '.' not in data_code:
            return data_code
        left, right = data_code.split('.', 1)
        # 数据形态：左侧是交易所标识（2 位字母）
        if not (left.isdigit() or (len(left) > 2 and left[0].isdigit())):
            return f"{right}.{left}"
        return data_code

    # ------------------------------------------------------------------
    # 辅助查询（供 Task 9 使用）
    # ------------------------------------------------------------------
    def get_today_close(self, code: str) -> float | None:
        """返回当前交易日的收盘价；不在数据中返回 None。"""
        data_code = self._to_data_code(code)
        df = self.data_loader.daily_df.get(data_code)
        if df is None or self.context._current_day is None:
            return None
        if self.context._current_day not in df.index:
            return None
        return float(df.loc[self.context._current_day, 'close'])

    def is_limit_up(self, code: str) -> bool:
        """当日收盘价 ≥ 涨停价 × 0.995（容忍 0.5% 浮点误差）。"""
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

    def is_limit_down(self, code: str) -> bool:
        """当日收盘价 ≤ 跌停价 × 1.005（容忍 0.5% 浮点误差）。"""
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

    # ------------------------------------------------------------------
    # Task 9: 成交接口 + 全局注入
    # ------------------------------------------------------------------
    def passorder(self, opcode, mode, account_id, code, price_mode,
                  price, volume, ContextInfo):
        """opcode: 23=买, 24=卖；其他 raise NotImplementedError。同步成交（方案 A）。"""
        if opcode not in (23, 24):
            raise NotImplementedError(f"passorder opcode {opcode} 未支持")

        data_code = self._to_data_code(code)
        df = self.data_loader.daily_df.get(data_code)
        name = ''
        if df is not None and not df.empty and 'name' in df.columns:
            name = str(df['name'].iloc[0])

        fill_price = self.get_today_close(code)
        date_str = self.timetag_to_datetime(
            self.context.get_bar_timetag(self.context.barpos), '%Y%m%d'
        )
        side = 'buy' if opcode == 23 else 'sell'

        if fill_price is None:
            self.account.record_reject(code, name, side, int(volume), 0.0, date_str, 'NO_PRICE')
            return

        if opcode == 23:
            if self.is_limit_up(code):
                self.account.record_reject(
                    code, name, 'buy', int(volume), fill_price, date_str, 'LIMIT_UP'
                )
                return
            self.account.fill_buy(code, name, int(volume), fill_price, date_str, reason='passorder')
        else:
            if self.is_limit_down(code):
                self.account.record_reject(
                    code, name, 'sell', int(volume), fill_price, date_str, 'LIMIT_DOWN'
                )
                return
            self.account.fill_sell(code, name, int(volume), fill_price, date_str, reason='passorder')

    def get_trade_detail_data(self, account_id, market='STOCK', kind='ACCOUNT'):
        """模拟 QMT get_trade_detail_data，返回 SimpleNamespace 列表。"""
        if kind == 'ACCOUNT':
            total = self.account.cash + sum(
                (self.get_today_close(c) or p.buy_price) * p.volume
                for c, p in self.account.positions.items()
            )
            return [SimpleNamespace(m_dBalance=total, m_dAvailable=self.account.cash)]

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

    def timetag_to_datetime(self, timetag_ms: int, fmt: str) -> str:
        """毫秒时间戳 → 格式化日期字符串。"""
        return datetime.fromtimestamp(timetag_ms / 1000).strftime(fmt)

    def get_market_data_ex(self, fields, codes, period='1d', start_time=None,
                           end_time=None, count=None, dividend_type='front',
                           fill_data=True):
        """简单存根 — v1 不调用，预留兼容。"""
        return {}

    def injected_globals(self) -> dict:
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
