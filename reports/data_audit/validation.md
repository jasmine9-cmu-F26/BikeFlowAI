# Audit validation

验证日期：2026-10-30。源 archive HEAD：`b409260cc6a4a38b5d9c5336e32f132d1d8b71ac`。

- 全部 40,965 commits 完成提取；仅初始 commit 无 feed 文件，已在 extraction_errors.csv 中记录。
- 完整提取器再次运行成功，复用了已有 atomic parts；没有把无效 commit 转为空站。
- 5 个 unittest 通过，覆盖 nearest 匹配的平局和 ±210 秒边界、长 gap、slot 去重、禁止使用 split 外 observation、独立 calibration 和 60 min purge。
- Synthetic Git 集成测试覆盖 metadata-only commit、重复 feed timestamp、同 commit metadata join、中断后复用已有 parts，以及完整 extractor→audit→Parquet/CSV/report 流程。
- 三个实际历史位置的样本与 `git show` 原始 status/information 一致，逐字段核对 timestamp、available/disabled counts、installed/renting/returning、capacity、lat/lon：
  - Commit 100: `192595874bbb717bc1c4b7346abe8658d7c63c49`
  - Commit 20000: `94ba32d9bf344a429ec08fe90079bbf67c4f9a8a`
  - Latest: `b409260cc6a4a38b5d9c5336e32f132d1d8b71ac`
- 完整 Parquet metadata row count：20,781,391。原始提取 20,783,395 行，重复 station_id+feed timestamp 去掉 2,004 行。
- 所有 12 个月 trip CSV 都被实际逐行读取；原始 ZIP 留在 ignored data/raw，天气探测统计实际 non-null values。
- `git check-ignore` 确认 venv、raw trip ZIP 和合并 Parquet 不会作为新文件加入 Git。
- 原仓库已有 tracked JSON 保持原样；没有训练模型、git commit 或 push。

这些检查验证提取和 audit 的时间/数据处理行为，不证明修订后的模型可达到预测质量目标。
90% station gate 已失败，因此 selected stations 为空、split 和 ID map 仍带 provisional/未核验状态；没有伪造最终冻结数据集。
