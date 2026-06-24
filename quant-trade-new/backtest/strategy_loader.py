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
