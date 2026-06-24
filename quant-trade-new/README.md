# quant-trade-new

沪深 300 多头趋势策略，QMT 实盘 + 本地日线回测两用。

## 安装
```bash
cd quant-trade-new
pip install -e .[test]
```

## 跑回测
```bash
python -m backtest.cli --start 2020-01-01 --end 2021-12-31
```

## 跑测试
```bash
pytest tests/ -x
```

## 部署到 QMT
见 `docs/superpowers/specs/2026-06-24-quant-trade-new-design.md` §11
