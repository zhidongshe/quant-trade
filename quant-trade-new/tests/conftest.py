import sys
from pathlib import Path

# 让 tests 能 import backtest.* 和 strategy_hs300
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
