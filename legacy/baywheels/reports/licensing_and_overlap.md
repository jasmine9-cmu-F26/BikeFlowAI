# License 与外部数据 overlap 核验

审计日期：2026-10-30。机器可读的 URL、网络检查时间、页面 hash、trip ZIP hash、实际日期和天气 non-null 统计见 [external_sources.json](external_sources.json)。
本文区分仓库授权、官方原始数据条款和外部数据可用性；没有给社区 archive 新增 license。

## Community archive

Source: [terinjokes/baywheels-history](https://github.com/terinjokes/baywheels-history)。
当前 HEAD 的完整文件树没有 LICENSE；README.org 仅介绍数据和采样频率，没有复用/再分发声明。
对完整本地历史的 LICENSE / LICENCE / COPYING / NOTICE 文件名检查也没有发现匹配。
`system_information.json` 给出运营方和 timezone，但当前版本没有 license 字段。

结论：**没有找到明确的 repo reuse / redistribution license**。公开可 clone 不能代替授权。
不能自行把他人的 archive 或数据改标 MIT、CC0 或 CC BY，也不能因为本次 audit 就宣称已取得社区 archive 的再分发许可。
若要再托管完整历史，仍需确认 archive 作者授权，以及官方数据条款对该方式的适用范围。

## Official Bay Wheels / Lyft 数据

[官方 System Data 页面](https://lyftbikes.com/system-data) 将 trip data 链接到
[Lyft Data License Agreement，2022-01-11](https://baywheels-assets.s3.amazonaws.com/data-license-agreement.html)。

协议第 1 条允许在其条件下访问、复制、分析、修改并在产品或服务中使用数据；第 2(b) 条限制作为独立数据集托管、发布、分发、转售，另有非商业分析、报告、研究的例外。
第 2(c–e) 条还涉及授权接口、访问限制和 extraction 方式。不能只摘第 1 条就声称 unrestricted open data。
当前官方页还提供实时 GBFS 链接，但**没有因此证明这份社区历史 archive 的采集及再分发方式已获授权**。

项目实践：保留来源链接、下载/提取代码及汇总 audit；raw trip ZIP/CSV、历史 JSON 与 Parquet 留本地。
本报告记录已发现的条款，不把“没有 repo license”和“官方数据完全不可分析”混为一谈。

## Trip overlap：实际读取了文件

从[官方 S3 列表](https://s3.amazonaws.com/baywheels-data/index.html)核实并下载了 202208 到 202307 的 12 个 ZIP（合计 98,052,445 bytes），本地位置 `data/raw/trips/`，已被 Git ignore。
逐行读取实际 CSV，而非只检查链接存在：共 **2,514,078 trips**；`started_at` 的本地日期处于 archive calendar date 范围内的有 **2,360,811** 条。
文件从 2022-08-01 到 2023-07-31，覆盖 archive 的 2022-08-07 到 2023-07-19。

这个日期级计数包含 archive 开始当天更早、结束当天更晚的 trips，**不是**按精确 UTC instants 得到的可 replay requests 数量。
CSV 的 naive 时间没有在此步骤被静默设定为 UTC；proposal 使用 Pacific 时间，仍需验证文件约定，并处理 DST fold / nonexistent times。
Trip ID 示例包括 `BK-A3` 等 short names，archive status 多为 UUID，所以不能直接用 CSV station ID join status.station_id。
需要用当时的 station_information short_name 等字段建立有时效的对应关系，检查非唯一、缺失和站点迁移，再计算 OD overlap 和 ride-time 样本数。
**行级精确时间 overlap、trip→archive→current station ID mapping、ride-time 可用性仍为 pending**。

## Weather overlap：检查响应内容

[Open-Meteo Previous Runs 官方文档](https://open-meteo.com/en/docs/previous-runs-api)说明：多数模型从 January 2024 起归档；GFS 2m temperature 有 March 2021 起的较长历史。
因此，2022–2023 archive 不能直接假设有完整 weather feature set。

对 SF 一个代表坐标 37.7749, -122.4194，实际请求整个 archive 日期范围、`gfs_seamless`、`previous_day1`：

| Variable | Hourly values | Non-null | Non-null rate |
|---|---:|---:|---:|
| temperature_2m_previous_day1 | 8,328 | 8,328 | 100% |
| precipitation_previous_day1 | 8,328 | 0 | 0% |
| wind_speed_10m_previous_day1 | 8,328 | 0 | 0% |

API 返回成功不代表数据存在。此结果只验证一个点、一个模型、三个变量；不推广成所有区域/模型都无降水或风速历史。
`previous_day1` 是 valid time 前约 24h 的预测，可作为保守候选，但尚未构建按 request time 的特征 join 或核实每个值的实际发布可见时间。
不要用 realized future weather / reanalysis 冒充当时可用预报。可先在团队批准后去掉不可用变量，或另找有发布时间证据的数据源，再重新 audit。

[Open-Meteo license 页面](https://open-meteo.com/en/licence)将 API 数据列为 CC BY 4.0，要求适当 attribution、license link 和修改说明；代码 license 是不同问题。
数据 license 也不等于托管 API 使用条款；若集成服务，需要再检查对应使用条件。

## 可以提交什么

可整理到团队项目的产物是 audit 代码、synthetic fixtures、汇总统计、来源记录和带 provisional 状态的 manifests。
本次没有 commit 或 push，没有向任何人发邮件或请求授权，也没有把 raw 文件上传到外部服务。
