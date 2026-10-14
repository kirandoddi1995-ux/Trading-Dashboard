# Evidence Assistant provider decision

Prepared for the 2026-10-14 handoff. Primary-source retrieval date: **2026-10-13**. These are public documentation checks, not a backend, hardware or account verification. No PC hardware was inspected; no credentials were read; no model was downloaded, account created or backend commissioned.

Decision: ship deterministic evidence retrieval first. External LLMs are unnecessary. The default service has no inference charge or account requirement; optional local inference would still consume electricity and existing hardware. “Zero cost” here means zero authorised provider spend, not free hardware or energy.

## UI contract available now

```python
from research_assistant import assistant_status, answer

status = assistant_status()
result = answer(question, usecase)
```

| Main UI label | Canonical use case | Bounded output |
| --- | --- | --- |
| Explain evidence | signals | Explain input, label and execution evidence requirements; no signal generation or trading authority |
| Backtest summary | backtests | Quote admitted reports and limitations; no recalculated returns or invented win rates |
| Capture health | health_record_qa | Capture/storage operations, receipts, replay and provenance QA; no medical advice |
| Report draft | report_drafts | Fixed report heading, evidence quotations and limitations for human review |

Both label forms work. The public functions are deterministic even if a separate service instance has an injected provider. They import no application/capture backend and load no stored records. Freeform questions are untrusted: a bounded word recognizer determines scope; neither question text nor secrets are echoed, persisted, or sent to a provider. This is evidence QA, not unrestricted chat or a semantic question-answering model. A matched keyword does not establish that the question is fully answered.

`assistant_status()` exposes `status`, `mode`, `backend_enabled=False`, `llm_enabled=False`, `provider_commissioned=False`, supported UI/canonical use cases, and the exact catalogue IDs/hashes/kinds. It reports hardware as `NOT_INSPECTED`. `answer()` supplies `answer`, `quotes`, `citations`, `draft`, `audit`, `code` and invariant authority flags. Every quote carries `record_id`, `sha256`, `kind`, and `source_reference`; every citation carries the exact record ID and hash. The hash binds canonical UTF-8 JSON for the whole record, including provenance, classification and exact text. It is not a signature or proof of source rights.

Default real-market status is `INSUFFICIENT_EVIDENCE`. `verified_sessions` and `verified_executable_labels` are `None`, not measured zero. Licensed labels remain `BLOCKED`. The fixed catalogue contains application-authored code guidance and a `SYNTHETIC_REFERENCE` to the existing generated-fixture plumbing entry point. No synthetic score or imaginary report is supplied. No output grants order, training, fill or promotion authority.

UI integration belongs to Main. Render `quote` and `source_reference` as escaped/plain text, label synthetic and application guidance visibly, and do not execute record content, interpolate it as HTML, or automatically navigate its source string. The source string is a provenance label, not a verified URL. Numerical facts may appear only within exact validated quotations. Display insufficiency and blocked-label status alongside report drafts. Unsupported/oversized requests return fixed `BLOCKED` codes; no exception details are exposed.

## Optional swappable protocol, still OFF

`EvidenceService(records, admitted=..., provider=None, commission=None)` accepts only explicitly supplied in-memory public records. Admissions must be independently obtained ID-to-hash mappings. Every requested `RecordRef` must match that mapping, the exact record and the use case. No scan, loader, query expansion, download, embeddings, training or record mutation exists. Private/confidential classifications are rejected even for local inference. A caller can misclassify or falsely admit a record; this module does not certify its truth, licensing, point-in-time availability or authenticity. The existing `research_lab_grounding` in public main was inspected and its selector-only principle retained; it was not changed or invoked as a model backend.

The ordinary `EvidenceService.answer` is always deterministic. The separate async `answer_with_provider` accepts a `SelectorProvider.select(prompt, timeout_seconds, max_response_bytes, cancel)` implementation only with explicit `Commission` attestations for confirmation, hardware, licence, local-only operation, read-only operation, no credentials/accounts, no network/downloads and zero provider cost. No implementation is supplied. Commission flags are a trusted caller's attestation, not an OS sandbox or automatic discovery mechanism.

The selector sees only bounded recognized use case plus public evidence; it never receives the raw question. Evidence text is JSON-delimited untrusted data. Responses can select only exact retrieved ID/hash references bound to `prompt_sha256`, never author prose, facts, numbers, tool calls or replacement quotations. Duplicate JSON keys, nonfinite JSON constants, unknown fields, stale prompt/hash bindings, unknown/repeated IDs and malformed/oversized responses are rejected. Validation reconstructs full quotes from original admitted records. Stored injection text can remain visible as a source quote; it is never executed or promoted to an instruction or verified truth.

Caps: at most 24 supplied/requested records, 4,096 canonical UTF-8 bytes per record, 32,768 aggregate data/prompt bytes, 2,048 question bytes, 4,096 response bytes; default one provider request per service instance, configurable only up to four; default two-second timeout, ceiling five seconds; provider budget exactly zero. Failed attempts consume quota, with no retries. Retain the instance for quota continuity; a future adapter must add global/persistent request and resource caps before commissioning. No arbitrary provider configuration, endpoint, account or secret is accepted by these public UI functions.

Timeout, cancellation, disabled/invalid commission, exhausted quota or rejected selector output yield deterministic evidence with a stable code. Caller task cancellation propagates and cancels/drains child tasks. The async protocol requires cooperative yielding and cancellation. A blocking or cancellation-suppressing injected implementation cannot be forcibly stopped by this module; an actual future adapter needs an independently reviewed process boundary, enforced deadline/resource limits, no egress and no writable/private file access. That commissioning remains unperformed and unauthorised by this delivery.

Audit output has an explicit metadata allowlist: prompt/response SHA-256, bounded use case, mode, code, and content policy. No freeform question, evidence, model response, exception, secret or path is logged. The hashes cover the actual serialized prompt and bounded response; response hash is `None` if no bounded response was received on an attempted call. On a non-attempt/fallback it hashes the deterministic selector envelope. Nothing is persisted. Hashes support binding/reproducibility, not cryptographic anonymity; sensitive low-entropy strings can be guessed, so do not export audit hashes beyond the reviewed boundary.

`evaluate_faithfulness` checks exact quotation/provenance/citation binding, fixed answer/draft content and invariant authority/count fields against explicitly provided records and references. Its `PASS` is structural faithfulness, not semantic truth or evidence completeness; empty evidence can pass binding while remaining insufficient. Independent admission is the caller's responsibility. Adversarial tests exercise secret redaction, forged numbers/refs, injection, quotas, cancellation and offline operation; the fake providers are test fixtures only.

## Public candidate research (retrieved 2026-10-13)

| Candidate | Primary evidence | Decision |
| --- | --- | --- |
| Deterministic Python catalogue | Local source inspection of `research_lab_grounding.py`, `research_lab.readiness` and `plumbing_demo` in the supplied public main clone | Ship now; no model needed |
| Qwen3-0.6B weights | Official [model card](https://huggingface.co/Qwen/Qwen3-0.6B) declares Apache-2.0, model size/context and local runtime support; official [licence text](https://huggingface.co/Qwen/Qwen3-0.6B/blob/main/LICENSE) | Small local selector candidate only, subject to exact artifact/version licence and quality evaluation; not downloaded or selected as a commissioned backend |
| Ollama runtime | Official [MIT licence](https://github.com/ollama/ollama/blob/main/LICENSE), [Windows requirements](https://docs.ollama.com/windows), [hardware support](https://docs.ollama.com/gpu), and [FAQ](https://docs.ollama.com/faq) | Future option only; runtime licence does not license every model |
| llama.cpp runtime | Official [repository](https://github.com/ggml-org/llama.cpp) documents local inference and CPU/GPU paths under MIT | Future process-isolated option; no binary installed and no adapter created |
| Gemini unpaid services | Official [terms](https://ai.google.dev/gemini-api/terms?hl=en) explain unpaid-service content use and possible human review, and instruct users not to submit sensitive/confidential/personal information; [pricing](https://ai.google.dev/gemini-api/docs/pricing) distinguishes free limits from paid services | Reject for this delivery: external/account/key use and confidentiality constraints are incompatible; free tiers are not unlimited or unconditional |
| Groq free plan | Official [billing FAQ](https://console.groq.com/docs/billing-faqs), [rate limits](https://console.groq.com/docs/rate-limits), [quickstart](https://console.groq.com/docs/quickstart), [data policy](https://console.groq.com/docs/your-data) and [agreement](https://console.groq.com/docs/legal/services-agreement) | Reject for this delivery: API key/account and external transfer required; no-training language does not mean no possible operational retention |

Ollama's FAQ documents local-only cloud disabling (`OLLAMA_NO_CLOUD=1` or `disable_ollama_cloud`), loopback binding and memory growth with context/concurrency. It also describes automatic desktop updates and model pulls; therefore local-only configuration alone does not prove zero network egress. An offline future deployment needs reviewed network blocking, no updater/pulls/search/cloud routes, no server content logs and preapproved artifacts. No such configuration was changed. [Ollama FAQ](https://docs.ollama.com/faq).

No hardware fit has been established. A future reviewer must obtain authorised CPU/OS/RAM/disk/GPU/driver facts and measure model weights plus context cache/runtime headroom and latency at the intended caps. Parameter count and quantization do not establish a minimum RAM figure or acceptable performance; no invented PC specification or guaranteed throughput is claimed. [Ollama hardware support](https://docs.ollama.com/gpu), [Qwen model card](https://huggingface.co/Qwen/Qwen3-0.6B).

Provider/model licences and hosted terms are version-sensitive. These links record a documentation review on 2026-10-13; they do not certify terms on 2026-10-14 or grant production rights. There is no account setup, actual model call or hardware benchmark in this change.

## Local verification (2026-10-14)

The owned suite passes **55 deterministic offline tests**. Both owned Python files pass strict mypy and Ruff. Validation commands were `python -B -m pytest -q -p no:cacheprovider tests/test_research_assistant.py`, `python -m mypy --strict --no-incremental --cache-dir=NUL research_assistant.py tests/test_research_assistant.py`, and `python -m ruff check --no-cache research_assistant.py tests/test_research_assistant.py`. No dependency installation or application/health/package/progress/capture change was required. The separate read-only workbench review and its purge finding are recorded in the backfill-rights note.
