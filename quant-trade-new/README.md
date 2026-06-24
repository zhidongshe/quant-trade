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

## 实盘部署到 QMT

1. `git pull` 拿最新 `strategy_hs300.py`
2. QMT 中新建 Python 模型
3. 复制 `strategy_hs300.py` 全文进策略编辑器
4. 改文件首行为 `# -*- coding: gbk -*-` 并保存为 GBK
5. 修改 `init()` 中的 `set_account('实盘账号')`
6. 设置 K 线周期 = **5 分钟**
7. 启动策略

注意：策略文件无需手动改任何 flag（与 v1 区别于此）。

## 已知数据局限

- `data_a/` 是 ~300 只静态快照，跨年回测有 survivorship + 前视双向偏差（< 3%/年）
- `data_a/` 不完全前复权（2024-06-21 茅台等个别事件未做），最大单日"假跌" ~2%
- 详见 `docs/superpowers/specs/2026-06-24-quant-trade-new-design.md` §13
