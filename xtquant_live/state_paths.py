import os

from xtquant_live.config import LiveConfig


def _safe_account_id(account_id: str) -> str:
    return ''.join(ch if ch.isalnum() or ch in ('_', '-') else '_' for ch in account_id)


def build_state_file_path(config: LiveConfig) -> str:
    return os.path.join(config.state_dir, f'hs300_xtquant_{_safe_account_id(config.account_id)}_state.json')


def build_log_file_path(config: LiveConfig, now_text: str) -> str:
    return os.path.join(config.log_dir, f'量化日志_xtquant_{now_text}.log')
