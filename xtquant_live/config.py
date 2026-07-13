from dataclasses import dataclass
import os
import re


@dataclass(frozen=True)
class LiveConfig:
    account_id: str
    qmt_path: str
    state_dir: str
    log_dir: str
    schedule_time: str


def resolve_runtime_value(raw: str | None, default: str) -> str:
    value = (raw or '').strip()
    return value or default


def validate_schedule_time(value: str) -> str:
    if not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ValueError(f'invalid schedule time: {value}')
    return value


def load_live_config(env: dict | None = None, config_path: str | None = None) -> LiveConfig:
    env_map = env or os.environ
    schedule_time = validate_schedule_time(
        resolve_runtime_value(env_map.get('HS300_SCHEDULE_TIME'), '14:55')
    )
    return LiveConfig(
        account_id=resolve_runtime_value(env_map.get('HS300_ACCOUNT_ID'), '8890358835'),
        qmt_path=resolve_runtime_value(env_map.get('HS300_QMT_PATH'), r'C:\国金证券QMT交易端\userdata_mini'),
        state_dir=resolve_runtime_value(env_map.get('HS300_STATE_DIR'), 'c:\\'),
        log_dir=resolve_runtime_value(env_map.get('HS300_LOG_DIR'), 'c:\\'),
        schedule_time=schedule_time,
    )
