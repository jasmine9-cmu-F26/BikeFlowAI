# Bay Wheels Data Audit

审计日期：2026-10-30（America/Los_Angeles）。结论：**FALLBACK，原 proposal 的 7-minute / 90% coverage 条件不成立。**
这是完整本地 Git 历史的实际审计；没有训练模型。数据可用于历史状态研究，但当前不能宣称已足够支撑 proposal 原样的训练、校准、测试和 replay。

## Repo 与可追溯性

- Source: https://github.com/terinjokes/baywheels-history
- Frozen source HEAD: `b409260cc6a4a38b5d9c5336e32f132d1d8b71ac`；完整非 shallow 历史，线性提交。
- Commits: **40,965**；earliest `2022-08-07T22:05:59Z`；latest `2023-07-19T19:07:00Z`。
- Commit interval median / p90: **10.417 / 16.533 min**。
- Available files: `.github/workflows/scrape.yml`, `README.org`, `station_information.json`, `station_status.json`, `system_alerts.json`, `system_information.json`, `update.sh`。
- 未在当前树及 `git log --all` 的 LICENSE / LICENCE / COPYING / NOTICE 文件名检查中发现许可证。README 也未声明复用许可；这不等于已证明底层数据无任何许可。
- 完整数值、依赖版本、提取器 hash、Parquet SHA-256: `audit_summary.json`。

## Date range 与 snapshots

- 使用 **station_status.last_updated**（UTC Unix seconds）作为 snapshot 时间，保留 commit 时间和 hash。
- Date range: **2022-08-07T22:09:32Z → 2023-07-19T19:06:56Z**。
- Unique feed timestamps: **40,960**；raw station rows: **20,783,395**；按 station_id + timestamp 去重后 **20,781,391**。
- 无效/缺少文件的 commits: 1，详见 `extraction_errors.csv`，没有把它们当成空站。
- Feed interval median / p90: **10.417 / 16.533 min**。
- 这是 2022–2023 的历史数据，不覆盖 2026 年；历史回放和当前服务需分别验证。

## Coverage 与验收

固定 UTC epoch 对齐的 7-minute 网格；每个 slot 只有在 ±210 秒内存在观察才算 covered，多条观察只计一次。
分母为整个审计/分割期间应有 slots，**不缩成单个站点自己的存活期**。Presence、valid 和 fresh 三种覆盖率分别列出。
Valid 是结构完整性检查：已安装、已知 renting/returning flags、非负 bike/dock counts 且同 commit metadata 可 join；fresh 进一步要求 last_reported age 在 0–300 秒。
Valid 不是最终训练准入；未报告/陈旧观察不能作为可靠标签，建模前还需确定严格的 base/target freshness 和 causal metadata 规则。

- Stations examined: **548**。
- Whole-feed 7-minute coverage: **57.56%**。
- Stations ≥90% archive presence coverage: **0**；≥90% training valid coverage: **0**。
- Selected stations: **0**。`selected_stations.csv` 只有通过门槛的站；失败时保留空表，避免把候选误称已冻结。
- 全部滑动 10-week windows 的最佳 whole-feed coverage 也只有 **65.29%**，起于 `2023-03-29T18:24:00Z`。这是单站覆盖的上界；不能靠挑 20 个站或 10 周达到 90%。此计算仅诊断，不据此挑 test。
- `candidate_stations.csv` 是按 training coverage 排名的 SF 候选，仅供调整设计后的复审；没有以 test 结果选站。

## Chronological splits / calibration

只用完整 Monday-to-Monday UTC weeks，按 60/15/10/15 的累计比例向下取整为整周；后面每个 split 开头排除 60 分钟，边界不能被 label 跨越。
这些是 **audit proposal**，因为 coverage 未过，尚未冻结为可训练数据集。

| Split | Start UTC | End UTC (exclusive) | Weeks after purge |
|---|---|---|---:|
| train | 2022-08-08T00:00:00Z | 2023-02-27T00:00:00Z | 29.000 |
| tune | 2023-02-27T01:00:00Z | 2023-04-17T00:00:00Z | 6.994 |
| calibration | 2023-04-17T01:00:00Z | 2023-05-22T00:00:00Z | 4.994 |
| test | 2023-05-22T01:00:00Z | 2023-07-17T00:00:00Z | 7.994 |

时长足以容纳 8 weeks train 和 2 later weeks test，并留独立 tuning / calibration；缺少的是足够密集的观察。Split 保持真实日历时间，不把缺失周压缩掉。

## Missingness / long gaps

- Whole-feed missing slots: **42.44%**。
- Feed gaps >14 / >30 / >60 min: **6,661 / 1,226 / 76**。
- Longest feed gap: **159.17 min**。
- `gap_summary.csv` 逐站报告相邻观察间隔及站点上线前/下线后的边界缺失；gap 次数不能等同缺失 slot 数。

## Label retention k=1…8

基准为每个 station 的有效 **实际 snapshot 时刻 t**；target=t+7k，nearest observation 在 ±3.5 min 内才有 label，平局取较早。
没有对齐后 forward-fill 或将 missing 记为 0。同一未来 snapshot 可以被多个 targets 使用，故样本并不独立；这里是可观测率，不是训练质量证明。
每个 split 分开匹配；target 和匹配 observation 都必须在本 split 内。Fresh retention 要求 target last_reported ≤5 min，分母仍为结构完整的 base rows，并未要求 base fresh；未通过 station gate，以下为全站诊断结果。

| k | Minutes | Eligible base rows | Valid label retention | Fresh label retention |
|---:|---:|---:|---:|---:|
| 1 | 7 | 20,614,127 | 51.82% | 50.70% |
| 2 | 14 | 20,613,612 | 56.58% | 55.29% |
| 3 | 21 | 20,613,097 | 62.77% | 61.39% |
| 4 | 28 | 20,612,582 | 66.62% | 65.13% |
| 5 | 35 | 20,612,582 | 57.99% | 56.70% |
| 6 | 42 | 20,612,067 | 60.00% | 58.67% |
| 7 | 49 | 20,611,552 | 69.62% | 68.09% |
| 8 | 56 | 20,611,552 | 59.46% | 58.13% |

`label_retention.csv` 另含各 split、training top20 exploratory 和 selected groups；空 selected group 的 rate 留空。
高 label retention 并不能代替 ≥90% fixed-grid coverage 验收。

## Class balance / status flags

- 在 20,614,642 个 valid observed station rows 中：bike unavailable **4.10%**；dock unavailable **4.28%**。
- Bike unavailable = bikes<1 或 renting=false；dock unavailable = docks<1 或 returning=false。缺失观察不进入分母。
- `class_balance.csv` 是观察行的事件率；`label_retention.csv` 同时给各 k 的 matched target 事件计数。不能当作均匀时间事件率。
- 这些是结构完整观察的诊断统计，包含部分陈旧状态；最终训练标签需要再排除陈旧/不报告行，不能把它们当成确认 empty/full。

质量计数（可能重叠，分母 20,781,391 observed rows）：

- unmatched_metadata: 3 (0.00%).
- missing_counts: 0 (0.00%).
- unknown_flags: 0 (0.00%).
- uninstalled: 166,747 (0.80%).
- not_renting: 429,036 (2.06%).
- not_returning: 429,035 (2.06%).
- stale_over_300s: 630,799 (3.04%).
- missing_last_reported: 0 (0.00%).
- future_last_reported: 0 (0.00%).
- capacity_count_mismatch: 3,853,084 (18.54%).
- information_after_status: 6,304,843 (30.34%).

## Station changes / IDs

`station_changes.csv` 有 **1,664** 条相邻可观察 metadata 字段变化，含 capacity、lat/lon、legacy/external/information IDs、name 和 region。
`station_id_map.csv` 是历史有效区间，非当前站 ID 的臆测；`current_gbfs_id` 留空。legacy ID 共用/更名不自动等于同一物理站。
没有下一 metadata 版本时 end 留空，只表示未观测到后继版本，不代表持续有效至今；站点缺报期间也不能凭区间补出状态。
同 commit metadata 可能比 status feed 新几秒，其次数已列出；本审计只用于 coverage，做模型特征时必须再使用 ≤request time 的 metadata as-of join。
Station selection 要求 training 内 capacity 和坐标不变；没有用 held-out metadata 来筛站。
capacity 与 available/disabled 四项之和不相等只是诊断信号，须检查 feed 语义及 metadata 时序，不能据此自动修正库存或用 capacity-bikes 替代实际 docks。

## Timezone

Git commit 的 offset 转为 UTC；feed last_updated / last_reported 是 Unix seconds。`system_information.json` 给出 America/Los_Angeles。
Trip CSV 的 naive 时间应按 Pacific 本地时间处理，并单独处理 DST ambiguous/nonexistent 时间，不能固定减 8 小时，也不能静默猜 fold。
已逐行读取 trip CSV 检查日期，但尚未完成时间本地化与 station-state join；Pacific 是 proposal 约定，仍需对文件约定验证。

## Weather / trips / licensing

参见 `external_sources.json` 和 `licensing_and_overlap.md`（独立网络检查，含 URL 和检查时间）。
官方 Previous Runs 文档说多数模型从 January 2024 开始，GFS 2m temperature 从 March 2021 是例外；不能假定 2022–2023 的完整温度/降水/风速特征都覆盖。
Trip 文件和日期覆盖不等于 station ID overlap；需要分别检查。
本次 external check 已读取 12 个月、2,514,078 条 trips 验证日期，精确 UTC overlap / station ID join 仍 pending。
Archive 没有已发现的 repo license；Lyft 官方 license 有独立条款，不应自动当作社区 archive 的 redistribution 授权，也不应给原 archive 加 MIT/CC license。

## Decision 与下一步

**FALLBACK for the original proposal gate.** 20 stations × ≥90% of 7-minute slots 不成立；缩小同一个 archive 的站点/时段也不能补足上界。
可保留这些历史数据用于实验，但需要团队/课程认可新的采样与 missingness 方案后重新 audit，例如更粗粒度时间轴，或更密集且覆盖足够周数的新 archive。
独立 calibrate/test 时长可满足，实际可训练性仍取决于修订后的 gate、每 split/horizon 稀有事件数、trip ID mapping 及 weather availability。
代码、汇总报告、manifest 可以整理到项目 repo；raw JSON、trip CSV、Parquet 留本地，不复制整个社区 archive 历史到项目 repo。
