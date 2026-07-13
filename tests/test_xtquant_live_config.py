from xtquant_live.config import LiveConfig, load_live_config
from xtquant_live.state_paths import build_log_file_path, build_state_file_path


def test_load_live_config_prefers_env_values(monkeypatch, tmp_path):
    monkeypatch.setenv('HS300_ACCOUNT_ID', 'acct-001')
    monkeypatch.setenv('HS300_QMT_PATH', r'D:\QMT\userdata_mini')
    monkeypatch.setenv('HS300_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('HS300_LOG_DIR', str(tmp_path / 'logs'))
    monkeypatch.setenv('HS300_SCHEDULE_TIME', '14:52')

    cfg = load_live_config()

    assert cfg.account_id == 'acct-001'
    assert cfg.qmt_path == r'D:\QMT\userdata_mini'
    assert cfg.state_dir == str(tmp_path / 'state')
    assert cfg.log_dir == str(tmp_path / 'logs')
    assert cfg.schedule_time == '14:52'


def test_state_and_log_paths_use_config_dirs(tmp_path):
    cfg = LiveConfig(
        account_id='8890358835',
        qmt_path=r'C:\QMT\userdata_mini',
        state_dir=str(tmp_path / 'state'),
        log_dir=str(tmp_path / 'logs'),
        schedule_time='14:55',
    )

    state_path = build_state_file_path(cfg)
    log_path = build_log_file_path(cfg, '20260713_145500')

    assert state_path.endswith('hs300_xtquant_8890358835_state.json')
    assert str(tmp_path / 'state') in state_path
    assert log_path.endswith('量化日志_xtquant_20260713_145500.log')
    assert str(tmp_path / 'logs') in log_path


def test_invalid_schedule_time_falls_back_to_default(monkeypatch):
    monkeypatch.setenv('HS300_SCHEDULE_TIME', 'bad-time')

    cfg = load_live_config()

    assert cfg.schedule_time == '14:55'
