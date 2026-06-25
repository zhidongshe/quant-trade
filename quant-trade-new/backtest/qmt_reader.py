"""读取 QMT 导出的 .DAT 二进制日线数据文件。

格式（小端序 Little-Endian）：
- 8 字节文件头（跳过）
- N × 64 字节记录
  每记录（共 64 字节）：
    偏移  0– 3  int32   时间戳（Unix epoch 秒，CST 午夜 = 前一日 16:00 UTC）
    偏移  4– 7  int32   开盘价 × 1000
    偏移  8–11  int32   最高价 × 1000
    偏移 12–15  int32   最低价 × 1000
    偏移 16–19  int32   收盘价 × 1000
    偏移 20–23  int32   保留（通常为 0）
    偏移 24–27  int32   成交笔数
    偏移 28–31  int32   标记（2 = 普通记录）
    偏移 32–39  uint64  成交量（股）
    偏移 40–43  int32   标志位
    偏移 44–47  float32 恒为 1.0（sentinel）
    偏移 48–51  float32 未确定
    偏移 52–55  int32   昨日收盘价 × 1000
    偏移 56–59  int32   保留（通常为 0）
    偏移 60–63  int32   终止标记（恒为 32766）

个股与指数均使用 ×1000 的价格缩放。
"""

import struct
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd

# CST = UTC+8
CST = timezone(timedelta(hours=8))

# 个股与指数价格缩放因子均 ×1000
# 验证：601899 2020-01-02 close=4750 → 4.75 CNY
#        000300 2020-01-02 close=4152241 → 4152.241 ≈ 4152.24
PRICE_SCALE = 1000.0


def _ts_to_datetime(ts: int) -> pd.Timestamp:
    """Unix epoch 秒 → CST 午夜 pd.Timestamp。"""
    utc_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    cst_dt = utc_dt + timedelta(hours=8)
    return pd.Timestamp(cst_dt.strftime('%Y-%m-%d'))


def _read_dat_file(filepath: Path, price_scale: float) -> pd.DataFrame | None:
    """读取单个 .DAT 文件，返回 DataFrame（index=日期, columns=high/open/low/close/volume/name）。

    返回 None 表示文件为空或无法解析。
    """
    data = filepath.read_bytes()
    if len(data) < 8:
        return None

    record_count = (len(data) - 8) // 64
    if record_count == 0:
        return None

    dates = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    for i in range(record_count):
        off = 8 + i * 64
        # 偏移 0–31: 8 个 int32（时间戳 + OHLC + 保留 + 成交笔数 + 标记）
        vals = struct.unpack_from('<8i', data, off)
        ts = vals[0]
        o = vals[1] / price_scale
        h = vals[2] / price_scale
        l = vals[3] / price_scale
        c = vals[4] / price_scale
        # 偏移 32–39: volume 为 uint64
        v_lo, v_hi = struct.unpack_from('<2I', data, off + 32)
        v = v_lo | (v_hi << 32)

        dates.append(_ts_to_datetime(ts))
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(v)

    # name 从文件名推导
    code_name = filepath.stem  # e.g. "600000"

    df = pd.DataFrame({
        'high': highs,
        'open': opens,
        'low': lows,
        'close': closes,
        'volume': volumes,
        'name': code_name,
    }, index=dates)
    df.index.name = 'time_key'
    return df


class QMTDataLoader:
    """从 qmt300/SH/ 和 qmt300/SZ/ 目录加载 .DAT 数据。"""

    def __init__(self, data_root: str):
        self.data_root = Path(data_root)
        self.daily_df: dict[str, pd.DataFrame] = {}
        self.data_quality_log: list[str] = []
        self._loaded = False
        self._cal_start: pd.Timestamp | None = None
        self._cal_end: pd.Timestamp | None = None

    def universe_codes(self) -> list[str]:
        return list(self.daily_df.keys())

    def trading_calendar(self, index_code: str = '000300.SH') -> pd.DatetimeIndex:
        """返回交易日历。

        index_code 接受 '000300.SH'（策略形态），内部转为 'SH.000300'（数据形态）。
        """
        data_key = 'SH.000300'
        if data_key not in self.daily_df:
            raise FileNotFoundError(f"指数文件 {data_key} 缺失，请确认 {self.data_root}/SH/000300.DAT 存在")
        idx = self.daily_df[data_key].index
        if self._cal_start is not None and self._cal_end is not None:
            idx = idx[(idx >= self._cal_start) & (idx <= self._cal_end)]
        return idx

    def load(self, start, end, warmup_days: int) -> None:
        """加载 SH/ 和 SZ/ 目录下所有 .DAT 文件。"""
        if self._loaded:
            return

        sh_dir = self.data_root / 'SH'
        sz_dir = self.data_root / 'SZ'

        if not sh_dir.exists():
            raise FileNotFoundError(f"QMT 数据目录不存在: {sh_dir}")

        # 先加载指数（SH/000300.DAT）
        index_path = sh_dir / '000300.DAT'
        if not index_path.exists():
            raise FileNotFoundError(f"指数文件缺失: {index_path}")

        idx_df = _read_dat_file(index_path, PRICE_SCALE)
        if idx_df is None or idx_df.empty:
            raise FileNotFoundError(f"指数文件为空: {index_path}")

        sorted_idx = idx_df.index.sort_values()

        # 计算 warmup 窗口
        start_ts = pd.Timestamp(start)
        after_start = sorted_idx[sorted_idx >= start_ts]
        if len(after_start) == 0:
            raise ValueError(f"start {start} 之后无交易日，数据不足")

        effective_start_ts = after_start[0]
        pos = sorted_idx.get_indexer([effective_start_ts])[0]
        if pos < warmup_days:
            raise ValueError(
                f"warmup 数据不足：start {start} 之前只有 {pos} 个交易日，"
                f"需要 {warmup_days}；请将 start 推迟或减少 warmup_days"
            )

        load_start = sorted_idx[pos - warmup_days]
        load_end = pd.Timestamp(end)

        self._cal_start = effective_start_ts
        self._cal_end = load_end

        # 切指数
        self.daily_df['SH.000300'] = idx_df.loc[load_start:load_end]

        # 加载 SH 和 SZ 所有股票
        for exchange_dir, exchange_prefix in [(sh_dir, 'SH'), (sz_dir, 'SZ')]:
            if not exchange_dir.exists():
                continue
            for f in sorted(exchange_dir.glob('*.DAT')):
                code = f.stem
                if code == '000300':
                    continue  # 指数已加载

                data_code = f'{exchange_prefix}.{code}'
                try:
                    df = _read_dat_file(f, PRICE_SCALE)
                except Exception as e:
                    raise ValueError(f"读取 {f.name} 失败: {e}")

                if df is None or df.empty:
                    continue

                df = df.loc[load_start:load_end]
                if df.empty:
                    continue

                self.daily_df[data_code] = df
                self._scan_quality(data_code, df)

        self._loaded = True

    def _scan_quality(self, code: str, df: pd.DataFrame) -> None:
        """记录 >5% 的跨日收盘价跳水（可能未复权或极端行情）。"""
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
