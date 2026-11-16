# 同源窗口关联与完整版本裁决 — 测试记录

本批（gb-0027）为“不同编号窗口可能同源”补充可撤销同源关联。验证环境为 Python 3.11 + 实装依赖（FastAPI 0.115.6 / SQLAlchemy 2.0.36 / NumPy 2.2.1 / scikit-learn 1.6.1），数据库使用 SQLite 单文件以在本机复现；生产仍为 PostgreSQL 16，行锁语义相同。

## 运行方式

```sh
cd backend
rm -f /tmp/links.db /tmp/conc.db /tmp/http.db /tmp/legacy.db /tmp/wk.db
PYTHONPATH=$PWD python3 ../test-artifacts/gb-0027/scripts/test_links.py
PYTHONPATH=$PWD python3 ../test-artifacts/gb-0027/scripts/test_concurrency.py
PYTHONPATH=$PWD python3 ../test-artifacts/gb-0027/scripts/test_http.py
PYTHONPATH=$PWD python3 ../test-artifacts/gb-0027/scripts/test_upgrade.py
PYTHONPATH=$PWD python3 ../test-artifacts/gb-0027/scripts/test_worker.py
cd ../frontend && npm ci && npm run build
```

前端 `tsc --noEmit && vite build` 通过（1621 modules，dist/index.js 226.61 kB）。

## 覆盖

| 脚本 | 场景 | 结果 |
|---|---|---|
| test_links.py | 跨拆分关联阻止新研究（409）；获批下载暂停（403）；原结果/`fit_hash` 不变 | 通过 |
| test_links.py | 撤销关联后仅恢复无冲突研究；版本 0→1→2 | 通过 |
| test_links.py | 链式合并 T05–C02–S01（间接相连为一组，跨 train/cal/test） | 通过 |
| test_links.py | 拆链：删除间接边仍跨拆分→保持阻止；删除剩余边→恢复 | 通过 |
| test_links.py | 冻结集合间的链经过非冻结中间窗口仍判定冲突（历史运行） | 通过 |
| test_links.py | 旧档 `link_version=NULL` 读取时置 v0 并按当前完整版本补裁决 | 通过 |
| test_links.py | 自关联 422 / 重复关联 409 / 异研究窗口 404 / 重复撤销 404 | 通过 |
| test_links.py | `input_hash`、`fit_hash` 不随关联版本变化 | 通过 |
| test_concurrency.py | 关联变更提交后创建读取完整新版本并被阻止 | 通过 |
| test_concurrency.py | 旧版本冻结的计算在写回时按新版本裁决，不能恢复失效资格 | 通过 |
| test_concurrency.py | 并发关联变更版本单调且互不覆盖，最新 Revision 完整快照等于有效边集 | 通过 |
| test_http.py | 真实 HTTP：角色鉴权（viewer 403）、409 文案含冲突链、结果页报告字段、导出 403/200、撤销列表、未知研究 404 | 通过 |
| test_upgrade.py | 手工创建无新表/列的旧 schema，`upgrade_schema()` 幂等补列建表；旧运行导出→冲突→撤销恢复，结果 JSON 不变 | 通过 |
| test_worker.py | 执行真实 worker 循环体一次：完成写回按完整版本裁决；事后关联冲突不改变结果 JSON（逐字节比较） | 通过 |

seed 在全新库仍生成 3 用户 / 1350 窗口 / 12 特征 / 1 完成研究 / 1 已批准建议；`SL-01`、`SL-02` 可拟合，`SL-03` 仍秩亏拒绝。

## 已知差异与边界

- 行锁为 `SELECT ... FOR UPDATE`（写者）与 `FOR SHARE`（裁决者）。SQLite 忽略该子句，故并发测试在 SQLite 上验证的是服务层代码路径与版本单调性；PostgreSQL 上锁会真正阻塞，语义要求一致。
- 汇总重算为“关联增删时遍历全部历史运行”，单研究最多 2000 窗口、运行数很小，未做增量图缓存。
- 同源关联仅限同一研究内；跨研究不建边（当前来源为三份独立预置研究）。
- 冲突不改 `status`，仅以 `conflict_blocked` 表达资格失效，避免旧运行被误标为失败。
