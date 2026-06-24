"""读取 300data/data_a/*_day.txt 到 dict[code -> pd.DataFrame]。"""
from datetime import date
from pathlib import Path
import pandas as pd


class DataError(Exception):
    pass


class DataLoader:
    def __init__(self, data_root: str):
        self.data_root = Path(data_root)
        self.daily_df: dict = {}
        self.data_quality_log: list = []
        self._loaded = False
        self._cal_start: pd.Timestamp | None = None
        self._cal_end: pd.Timestamp | None = None

    def universe_codes(self) -> list:
        return list(self.daily_df.keys())

    def trading_calendar(self, index_code: str = 'SH.000300') -> pd.DatetimeIndex:
        if index_code not in self.daily_df:
            raise DataError(f"index {index_code} 缺失，请先调用 load()")
        idx = self.daily_df[index_code].index
        if self._cal_start is not None and self._cal_end is not None:
            # 返回 [start, end] 范围内的交易日（不含 warmup 预热窗口）
            idx = idx[(idx >= self._cal_start) & (idx <= self._cal_end)]
        return idx

    def load(self, start: date, end: date, warmup_days: int) -> None:
        if self._loaded:
            return

        if not self.data_root.exists():
            raise DataError(f"SH.000300 data_root 不存在: {self.data_root}")

        index_file = self.data_root / 'SH.000300_day.txt'
        if not index_file.exists():
            raise DataError(
                f"指数文件 SH.000300 缺失，路径不存在: {index_file}"
            )

        # 先加载指数，建交易日历
        idx_df = self._read_csv(index_file)
        sorted_idx = idx_df.index.sort_values()

        # 计算 warmup 窗口起始
        start_ts = pd.Timestamp(start)
        after_start = sorted_idx[sorted_idx >= start_ts]
        if len(after_start) == 0:
            raise DataError(f"start {start} 之后无交易日，数据不足")

        effective_start_ts = after_start[0]
        pos = sorted_idx.get_indexer([effective_start_ts])[0]
        if pos < warmup_days:
            raise DataError(
                f"warmup 数据不足：start {start} 之前只有 {pos} 个交易日，"
                f"需要 {warmup_days}；请将 start 推迟或减少 warmup_days"
            )

        load_start = sorted_idx[pos - warmup_days]
        load_end = pd.Timestamp(end)

        # 记录 [start, end] 边界供 trading_calendar() 过滤
        self._cal_start = effective_start_ts
        self._cal_end = load_end

        # 切指数到加载范围（含 warmup）
        self.daily_df['SH.000300'] = idx_df.loc[load_start:load_end]

        # 加载所有股票文件
        for f in sorted(self.data_root.glob('*_day.txt')):
            code = f.stem.replace('_day', '')
            if code == 'SH.000300':
                continue
            try:
                df = self._read_csv(f)
            except Exception as e:
                raise DataError(f"读取 {f.name} 失败: {e}")
            df = df.loc[load_start:load_end] if not df.empty else df
            # 静态 universe：所有 ~301 只股票均记录，即使该区间无数据（如新股）
            self.daily_df[code] = df
            if not df.empty:
                self._scan_quality(code, df)

        self._loaded = True

    def _read_csv(self, path: Path) -> pd.DataFrame:
        df = pd.read_csv(path, encoding='utf-8')
        required = {'code', 'name', 'time_key', 'high', 'open', 'low', 'close', 'turnover'}
        missing = required - set(df.columns)
        if missing:
            raise DataError(f"{path.name} 缺少列: {missing}，实际列: {df.columns.tolist()}")
        df['time_key'] = pd.to_datetime(df['time_key'])
        df = df.set_index('time_key').sort_index()
        df.index = df.index.normalize()  # 时间部分归零
        df = df.rename(columns={'turnover': 'volume'})
        # name 存为单一字符串（取第一行，整列填充相同值）
        df['name'] = df['name'].iloc[0] if not df.empty else ''
        return df[['high', 'open', 'low', 'close', 'volume', 'name']]

    def _scan_quality(self, code: str, df: pd.DataFrame) -> None:
        """记录 >5% 的跨日收盘价跳水（可能是未复权事件或极端行情）。"""
        if len(df) < 2:
            return
        closes = df['close'].values
        dates = df.index
        for i in range(1, len(closes)):
            prev = closes[i - 1]
            curr = closes[i]
            if prev > 0:
                gap_pct = (prev - curr) / prev
                if gap_pct > 0.05:
                    self.data_quality_log.append(
                        f"{code} {dates[i - 1].date()} → {dates[i].date()}: "
                        f"{prev:.2f} → {curr:.2f}, "
                        f"跳水 {gap_pct * 100:.2f}%（可能未复权或市场暴跌）"
                    )
