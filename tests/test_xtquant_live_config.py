from xtquant_live.config import load_live_config


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
