# Decision backlog and development replay commissioning

No policy thresholds change. No new remote evidence events or collectors are added.
Order placement stays absent/disabled. No model approval power is added.

## Evidence delivery diagnostics

Each equity governance evaluation now logs `EQUITY_GOVERNANCE_BACKLOG`:
instrument, correlation ID, evaluation timestamp, sampled pending count and age,
recorded failures, configured limits, current finding codes and resulting state.
`backlog_finding_present` distinguishes an actual OUTBOX_BACKLOG finding from
a retained READ_ONLY state due to hysteresis or a different safety finding.
Missing telemetry remains null. Logs exclude evidence payloads and exception text.
The same measurement appears under `governance_backlog` in the existing scan timing
JSON, with scan ID and candidate. No second outbox read is made for this diagnostic.

For supervised market-hours scans, retain the timing JSON and compare evaluation
times with sender logs and refreshed queue counts. Measure peak backlog, time
above 100, and drain duration. A post-scan zero does not establish the peak or
exact drain time. Keep 100 pending / 900-second age safeguards. Do not auto-rerun
rejected trades or bypass fresh quote/governance checks after delivery drains.

## Development-only diagnostics

Run against the EXISTING 2022-2024 replay report, not bar files or a mixed-period
report. This tool rejects 2025/2026 sessions and episodes. Substitute your actual
private development-report path; do not commit the input or output.

```powershell
.venv\Scripts\python.exe directional_replay_diagnostics.py --report "C:\Users\banga\Documents\TradingResearch\development-replay.json"
```

Output covers return dispersion, MAE/MFE, exit reasons, accepted sessions with no
episodes, yearly summaries, and deterministic session-clustered 95% percentile
intervals for the episode-weighted mean. CLI output includes the input report's
SHA-256 and diagnostics version, but not its private path. Sessions must be
chronological and every episode must exit after entry; even excluded sessions
outside development are rejected. Zero-episode sessions participate in
sampling; draws containing no episodes are explicitly counted as undefined.
There is no confidence interval when none can be estimated.

Intervals preserve within-session dependence, not dependence across consecutive
days. They do not correct strategy search/multiple testing, certify an edge, model
charges, or imply executable option returns. Synthetic underlying research is
not fill/outcome evidence. Freeze a development rule and its data/implementation
hashes before any validation access; 2026 remains untouched until that process
authorizes holdout use. No rule is frozen or selected by this release.
