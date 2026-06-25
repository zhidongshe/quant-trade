# 沪深300 v1 离线回测系统 - 实施进度

Plan: docs/superpowers/plans/2026-06-21-hs300-backtest-v1.md
Spec: docs/superpowers/specs/2026-06-21-hs300-backtest-v1-design.md
Branch: feature/backtest-v1

Task 1: complete (commits 9e980e5..4bd038b, review clean, 3 Minor findings — brief-originated, defer)
Task 2: complete (commits 4bd038b..1e63341, review clean — 3 Minor defensive findings: missing-dir guard, load_daily idempotency, pytest cwd assumption)
Task 3: complete (commits 1e63341..4411551, review clean — 2 Minor cosmetic findings)
Task 4: complete (commits 4411551..fcbf6a6, review clean — 2 Minor: 1 extra test for auto-hook coverage, 1 redundant double-call)
Task 5: complete (commits fcbf6a6..46398c2 incl fix, re-review clean — commit msg says '深拷贝' but is technically shallow copy; harmless because Position fields are all primitives)
Task 6: complete (commits 46398c2..da54edb, review clean — Important about 'unfilled' resolved with inline comment fix; Minor SELL KeyError gap will be replaced by Task 7's reject branches)
Task 7: complete (commits da54edb..1071876, review clean — unfilled 死代码已清理 + zero-volume guard 已加)
Task 8: complete (commits 1071876..ec5a163, review clean — 3 Minor: market_ok_streak default 0 vs v1 init's 1 [v1 init() will overwrite], unguarded KeyError on uncached barpos, persisted_state currently unused in v1)
Task 9: complete (commits ec5a163..b02fe45, review clean — partial day bar 正确避免未来泄露; 49 行 fixture 含 9:35-15:00 共 49 根 bar)
Task 10: complete (commits b02fe45..d310941, review clean — no issues)
Task 11: complete (commits d310941..c69b8e8, review clean — dual encoding gbk→utf-8 fallback 在本地适配上合理)
Task 12: complete (commits c69b8e8..1cf5ac9, review clean — no issues)
Task 13: complete (commits 1cf5ac9..b372c78, review clean — no issues)
Task 14: complete (commits b372c78..f900eb7, review clean — no issues)
Task 15: complete (commits f900eb7..9638b7a, review clean — no issues)
Task 16: complete (commits 9638b7a..b3a63b6, review clean — main() 串联 + Oct 2025 冒烟跑成功，4 个产物文件已生成)
Task 17: complete (commits b3a63b6..def27be incl format-fix, smoke produces trades > 0; fix uncovered shim QMT-format mismatch with v1 — major bug avoided thanks to smoke test)
Task 18: complete (full 2019-09~2025-12 跑通, total return +132.24%, 1037 trades; 2 sanity flags: 2020 max_dd -71.58%, 2025 +106%; 1 day position_count=6 违反 MAX_POSITIONS)

---

# quant-trade-new (QMT 实盘/回测两用) - 实施进度

Plan: docs/superpowers/plans/2026-06-24-quant-trade-new.md
Spec: docs/superpowers/specs/2026-06-24-quant-trade-new-design.md
Branch: feature/backtest-v1
Plan commit: e28385d (with pre-flight fix 94d20d0)

Pre-flight: 3 conflicts resolved
- A. helpers 9→10 (添加 _score_universe) — spec 已更新
- B. avg_holding_days 实施 FIFO 配对算法 — plan Task 14 已更新
- C. _log_status 简化为概要日志 — spec 已更新
Task 1: complete (commits 11543ac..198a360 incl fix wave, re-review clean — 4 spec drifts fixed: default.yaml null/test fix/dead fixture/main argv)
Task 2: complete (commits a17e07c, review clean — 14 tests pass; controller's '15 vs 14' concern was false alarm — brief actually had 14 tests + 1 fixture)
Task 3: complete (commits e62f8cb..bb5cc3e incl bool() consistency fix, re-review clean — all 6 v1 rules verbatim, 11 tests)
Task 4: complete (commits 7c77039..ab0bc46 incl v1-verbatim fix, re-review clean — 5 tests, MACD-narrowing comment block preserved)
Task 5: complete (commits 29462d6, review clean — 6 tests, 4-component cost formula correct, single source of truth for fees)
Task 6: complete (commits fb31b6a..8fa93e3 incl empty-filter fix, re-review clean — universe 273 for 2020 range, data quality scan working)
Task 7: complete (commits c1c2336..a10058f incl first-snapshot daily_return fix + regression test, re-review clean — 7 tests, 57/57 full suite; deferred Minor: unused 'field' import, dead _current_date)
Task 8: complete (commits 9e479f1..f58b985 incl index-key fix, re-review clean — 15 tests + regression, full suite 72/72; index now returned as strategy-form '000300.SH')
Task 9: complete (commit 321b682, review clean — 10 tests + full suite 82/82; timezone using local TZ is design choice for QMT compatibility)
Task 10: complete (commit 599aa84, review clean — 10 tests + 92/92 full suite; _execute_sell log/del bug fixed, trade_cost unified, utf-8 encoding)
Task 11: complete (commit edc20e6, review clean — handlebar 35 lines, 10 helpers; cross-task Shim.advance_to timezone fix included, all 25 Task 8+9 tests still pass; full suite 98/98)
Task 12: complete (commit 41a5916, review clean — 3 tests + 101/101 full suite, exec injection clean, isolated modules)
Task 13: complete (commit 4998493, review clean — 4 tests + 105/105 full suite; init→overwrite order correct, daily 4-step loop verified)
Task 14: complete (commit 1ea536d, review clean — 5 tests + 110/110 full suite; Period labels correct, FIFO avg_holding_days verified, 5 artifacts generated)
Task 15: complete (commits 5e0cbca + 1fe40b3 incl docstring clarification, review clean — 3 E2E + 113/113 full suite; 2020 baseline locked (-37%/-44.85%/sharpe -1.188/245 trades); deferred Minor: type hint, test independence assertion)
Review fix wave: commit 8396fbd — 6 Important + 4 Minor applied (realized_pnl phantom-gain fix, ACCOUNT_ID dev-guard, test assertion tightened, LIMIT_UP regression test, log path fix, dead-code removal, unused import, type hints); 111/111 unit + 3/3 E2E pass; golden baseline unchanged (annual_return -0.369779, max_drawdown -0.448539, sharpe -1.188, n_trades 245, win_rate 0.2917)
