# Research Lab: methods, integrations and honest delivery boundary

Reviewed public baseline: `0223f0033672e072e522017f2cdfe7cab0478e18`.
Research accessed 13 October 2026. No private market data, credentials or hosted
resources were read. This package does not complete or commission the whole ML
programme. It adds an authenticated, read-only application view and tested
diagnostic/LLM boundaries over the merged foundation.

## What is delivered, and what is not

Research → NIFTY Research Lab shows the evidence requirements, engine chain,
monitoring limitations and grounded explanation. Its explicit button executes the
existing synthetic version-aware replay using whole IST sessions. The generated
fixture has one session: ML remains INSUFFICIENT_DATA rather than counting six
correlated rows as six independent days. No real-data loader, private report
upload, external LLM call, automatic fitting or schedule is connected.

The diagnostic module implements equal-session Brier/log loss and fixed reliability
bins; paired session-loss bootstrap intervals; Holm correction with all attempted
trials counted; and fixed-bin Jensen–Shannon drift. These are descriptive library
tools, not a new safety gate. They do not authenticate their caller's data, prove
that probabilities were OOS, select significance thresholds or establish a model
edge. Wrong absolute certainty has infinite log loss, represented explicitly
without emitting non-standard JSON Infinity. Nothing clips it into a finite score.

The LLM contract is implemented and adversarially tested. An explicitly commissioned
local adapter can select IDs from a fixed, hashed catalogue of application-authored
facts. Output cannot add prose, numbers, tools, URLs or a trade recommendation.
The app currently uses the deterministic summary, labelled **LLM disabled**.
This is not described as a running language model. There is no supplied backend,
model download or new account. A future local adapter needs hardware, licence,
latency/timeout and resource-limit evaluation and separate commissioning. A paid
API is outside the zero-running-cost constraint. Existing generic AI Copilot is
not used as research authority or called by this lab.

## Research decisions and their basis

1. **A frozen study, not a search for the best backtest.** Retain failed,
   insufficient and unresolved trials before execution in the existing durable
   registry. Record every attempted hypothesis/feature/threshold, not just model
   names. [PBO](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) explains
   selection across backtests; [DSR](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
   addresses selection and non-normal returns. Neither statistic is calculated
   here: real returns, a complete strategy population and defensible sampling
   assumptions are absent. Holm is available for valid, frozen raw tests;
   counting failed/unreported attempts conservatively does not rescue invalid
   p-values. [R's official multiple-comparison reference](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html)
   supports Holm under dependence and explicitly accounts for a comparison count
   larger than the reported p-value list. No model/strategy is selected here.

2. **Session-level chronological evaluation.** Reuse the existing purged
   walk-forward engine with actual feature/label intervals, label availability,
   whole IST session groups and a frozen pre-test gap. A post-test embargo is
   vacuous when training is strictly prior-only; do not claim CPCV was implemented.
   [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
   provides ordering/gaps but row gaps alone do not resolve overlapping financial
   labels. [scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html)
   supports fitting every transform on training data only. Keep historical 2025
   and 2026 sealed; prospective versioned captures are a separate explicit scope.

3. **Simple models before complexity.** Frozen ridge and no-trade/zero, mean,
   chance and simple-rule baselines come before trees or neural models. A few
   highly correlated capture days cannot justify model complexity or model
   selection. Feature additions are separate registered trials. Direction labels,
   executable net-return labels and option-premium outcomes must remain distinct.
   No paper claims that ridge will produce a profitable NIFTY edge; this is a
   conservative engineering choice given the current data.

4. **Calibration is its own OOS experiment.** Use proper scores and reliability
   diagrams, including loss to a frozen base-rate baseline, not accuracy alone.
   [scikit-learn calibration](https://scikit-learn.org/stable/modules/calibration.html)
   and [Guo et al.](https://proceedings.mlr.press/v70/guo17a.html) motivate separate
   calibration evaluation. Guo's neural/image/text findings are not evidence
   that temperature scaling works for this intraday market. Future sigmoid or
   isotonic fitting must use separate chronological calibration sessions, not
   OOS test labels. This package fits no calibrator and grants no win probability.

5. **Uncertainty follows the sampling unit.** Paired loss intervals resample
   sessions rather than five-minute rows. IID-session resampling is labelled an
   approximation; dependence between days can require a preregistered moving
   block bootstrap. The present interval is not a hypothesis test, a financial
   confidence guarantee or a universal sample-adequacy rule. Power/precision,
   regime coverage and stability must determine frozen study requirements before
   evaluation; do not lower existing production count/evidence requirements.

6. **Execution evidence before profitability.** Reuse dated side-aware quote,
   contract, tick, lot, spread/depth and exact-decimal tariff scenarios. Require
   actual NSE contract masters and dated fee/margin evidence. Unknown fills,
   partial fills and stop/target first touches stay unknown. Index candles cannot
   manufacture an option premium or an executable futures fill.
   [LEAN reality models](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts)
   distinguish fills, fees, slippage, margin and capacity; adapting a generic
   model to India needs source-specific evidence. Full queue/partial-fill and
   intrabar execution remain engineering work. Brokerage ₹20/order is still an
   assumption until contract-note verification, not silently a dated official fee.

7. **Volatility/regimes are conditional future studies.**
   [QuantLib](https://www.quantlib.org/) is a useful open-source reference, not a
   substitute for premium quotes, curves and contract conventions. Start with
   realized-volatility/seasonality diagnostics and market surface sanity checks,
   then separately preregister whether GARCH, a surface model or regime model
   adds OOS value. [Rough volatility research](https://arxiv.org/abs/1410.3394)
   is important theoretical/empirical work, not validation for deploying a rough
   model on this tiny NIFTY capture. Do not infer Greeks from missing premiums.
   Smoothed regime states use future information: any future regime feature must
   be filtered causally and refitted only inside its training fold.

8. **Drift monitoring is not autonomous retraining.** Track schema, missingness,
   revisions, input distributions, prediction distributions and delayed outcome
   scores separately. Fixed-bin JS is descriptive; bins must be frozen from
   training and retained. [River ADWIN](https://riverml.xyz/latest/api/drift/ADWIN/)
   is a candidate online detector, not installed or wired here. Reference windows,
   false-alarm policy and seasonality need preregistration; a small-sample drift
   flag must not cause retuning, promotion or an invented performance claim.

9. **LLM explains evidence; code owns measurements.**
   [ALCE](https://arxiv.org/abs/2305.14627) evaluates citation completeness and
   correctness and shows that citations alone do not assure support. Consequently
   this package uses a narrow fact-selection interface and code-authored final
   text, not unrestricted RAG or a numerical forecaster. No secrets or capture
   payloads enter prompts. This restricted boundary is intentionally less flexible
   than an open chat assistant; prompt injection cannot add a new fact. It does
   not claim to prove the truth of every retrieved document or solve arbitrary
   natural-language financial reasoning.

10. **India-specific references and legal review stay explicit.**
    [NSE contracts](https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications)
    and [market timing](https://www.nseindia.com/resources/exchange-communication-holidays)
    must be interpreted segment-by-segment and with original dated circulars.
    [Upstox CAS announcement](https://upstox.com/developer/api-documentation/announcements/closing-auction-session/)
    does not authorize extending an index-only recorder. Live 09:15–15:30 is
    unchanged. Lot/expiry/roll/tax changes require dated contracts; current rates
    are not back-applied to development history. Owner must resolve the actual
    F&O close circular before instrument-specific scheduling changes.

    [NSE usage policy](https://www.nseindia.com/static/market-data/nse-data-policy)
    and [access disclaimer](https://www.nseindia.com/static/nse-disclaimer) mean
    publicly downloadable data is not automatically licensed for the intended
    speculative/ML use or redistribution. No historical download was made.
    [SEBI's retail-algo circular](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html)
    and [2026 RA master-circular page](https://www.sebi.gov.in/legal/master-circulars/feb-2026/master-circular-for-research-analysts_99571.html)
    are relevant review entry points. Ask an Indian professional about private
    personal use versus sharing security-specific recommendations, personalised
    advice, remuneration/marketing, research-analyst/adviser obligations and any
    future broker integration. No-orders software is not assumed exempt merely
    because it calls itself decision support. These are open questions, not legal
    advice. No claim that this brief exhausts later amendments or approvals.

## T: ranked integrations and agent roles

The plugin directory read on this run confirms GitHub, Supabase, Google Drive and
OpenAI Developers are already installed/enabled. No additional paid service or
connection is necessary for this package; no permissions were changed.

1. **GitHub + an independent code-review/test agent.** Highest benefit: exact-SHA
   PR review, CI failure diagnosis and package verification. Keep publishing under
   the owner's reviewed PR workflow. A reviewer should not approve its own code.
2. **Supabase, project-scoped/read-only for diagnostics.** Useful for capacity,
   schema and permission inventories. The connector can expose write tools, so
   installation is not a read-only permission guarantee; owner should constrain
   access at connection/role level. No autonomous migration/deletion authority.
3. **Google Drive.** Existing archive/custody inspection, quota and exact byte
   readback are more useful than another archive provider. Do not broaden Drive
   scopes or assume one client's folder rights apply to another client.
4. **A quant-methods/leakage-review agent, using native web research and local
   Python.** Its job is to challenge sampling, labels, costs and selection bias,
   not generate more parameter combinations. No third-party 'trading agent' or
   large generic skill pack is recommended without source/security review.
5. **OpenAI Developers / official documentation.** Already installed; useful for
   the later local/external adapter design. Installation does not provide free
   runtime inference. [Official plugin concepts](https://developers.openai.com/plugins/concepts/plugins)
   distinguish skills from connected tools. No API account/key is needed now.

The skills.sh directory was inspected for discovery, but no unvetted community
skill is recommended or installed. Roles 1/4 are engineering review roles, not
autonomous trading agents. QuantLib/scikit-learn/River are research libraries,
not plugins; pin/review them only when a separately admitted study needs them.

## Next build order

Keep capture independent. Complete real custody/restore and capacity alert drills
in parallel with a licensed prospective label/admission adapter. Finish every
writer/cold-reader path and native parity, then shadow dedup and source-specific
retention with a physical steady-state capacity proof. Only then commission any
deletion. For research: freeze futures paper baseline → admitted executable labels
and costs → chronological model/calibration evaluation → independent prospective
paper validation → explicit governance review. Real private-data automation and
optional local LLM integration follow, not precede, those boundaries.

No low-cost/free tool, attractive paper or additional agent creates missing market
evidence. 'No tradable edge found' and 'insufficient evidence' remain valid results.

## Frozen source identity

Real captured recipes bind the exact producer source hashes. A later public-main
change does not make old capture sources interchangeable with the new release.
Any future private-data reader must use the matching frozen producer source
capsule and verify that identity before replay. This package's demonstration is
generated under its own reviewed source identity; it does not admit or replay
today's real captures. The installed capture folder remains untouched.
