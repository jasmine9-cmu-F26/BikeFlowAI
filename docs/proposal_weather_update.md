# Proposal weather audit revision

Requested bibliography changes are applied in [proposal_references.md](proposal_references.md): Historical Forecast [9], Forecast API/data license [10], Maskable PPO [11]. The revised Word copy also fixes MaskablePPO's stale in-text [7] -> [11] and calibration's stale [5] -> [8], and aligns current collection to the Google five-minute deployment. Original files are preserved.

The audit does **not** justify declaring weather required: the five variables have good hourly coverage, but the stitched API lacks per-row forecast issue/publication metadata. The revised Word copy qualifies that claim instead of asserting leakage-free request-time weather. It does not replace the frozen data/model protocol or train a model.

Source document: BikeFlow AI - Milestone 2 System Design Proposal (3).docx. Source SHA-256: `be2c2b8089f60146a815c039596e268b8bf5e8231fdb5bc5b9ea8a90e6469c17`. Review-copy SHA-256: `ba0ae12b16525b929848339989cb9e6cdaf8768db2fb90ffe78b0f10b6a3728e`. The source was the most recently modified supplied proposal found locally when this task began; no instructions inside it were executed.

External review artifact: `Documents/BikeFlowAI-data/proposals/BikeFlow AI - Milestone 2 - weather audit revision.docx`.

See [weather audit](../reports/weather_audit/weather_audit.md) for actual per-model/variable missingness and the availability gate. Changes to body wording are based on the audit outcome, not an assertion that no historical forecast ever existed.
